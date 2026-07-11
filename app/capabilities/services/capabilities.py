"""能力注册表 CRUD 服务。

包含针对历史数据库表结构的兼容逻辑：
- capability_registry 旧版本可能有 scope NOT NULL 列，新版本已去掉该约束。
  创建能力时若因 scope 触发 NOT NULL 约束错误，自动回退到反射表结构的原始 INSERT，
  并填充 scope='GLOBAL' 以兼容旧表，无需修改数据库 schema。
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.capabilities.schemas import (
    CapabilityCreate,
    CapabilityDeleteResponse,
    CapabilityRead,
    CapabilityUpdate,
)
from app.capabilities.services.model_providers import ModelProviderService
from app.db.base import generate_uuid
from app.db.models import CapabilityRegistry
from app.domain.enums import CapabilityType


class CapabilityService:
    def __init__(self) -> None:
        self.model_provider_service = ModelProviderService()

    @staticmethod
    def _is_legacy_scope_not_null_violation(exc: IntegrityError) -> bool:
        """判断 IntegrityError 是否由旧版 scope 列的 NOT NULL 约束引起。

        旧版本数据库表包含 scope NOT NULL 列，新版 ORM 模型已移除该字段。
        通过消息内容判断，而非捕获具体数据库驱动异常，以保持跨驱动兼容性。
        """
        message = str(exc).lower()
        return (
            "scope" in message
            and "capability_registry" in message
            and ('column "scope"' in message or "capability_registry.scope" in message)
            and ("not null" in message or "null value in column" in message)
        )

    @staticmethod
    def _capability_read_from_record(record: Any) -> CapabilityRead:
        """从原始数据库行映射构建 CapabilityRead，处理旧版 scope 字段和大写枚举值。"""
        payload = dict(record)
        # 旧版 type 存储为大写（如 "MODEL"），需归一化为小写以匹配枚举定义
        if isinstance(payload.get("type"), str):
            payload["type"] = payload["type"].lower()
        payload.pop("scope", None)
        return CapabilityRead.model_validate(payload)

    async def _insert_with_legacy_scope(
        self,
        session: AsyncSession,
        capability_payload: dict[str, Any],
    ) -> CapabilityRead:
        connection = await session.connection()

        def _reflect_table(sync_connection: sa.Connection) -> sa.Table:
            metadata = sa.MetaData()
            return sa.Table(
                "capability_registry", metadata, autoload_with=sync_connection
            )

        table = await connection.run_sync(_reflect_table)
        insert_payload = dict(capability_payload)
        if isinstance(insert_payload.get("type"), CapabilityType):
            insert_payload["type"] = insert_payload["type"].name
        if "scope" in table.c:
            insert_payload["scope"] = "GLOBAL"

        result = await session.execute(
            sa.insert(table).values(insert_payload).returning(*table.c),
        )
        row = result.mappings().one()
        await session.commit()
        return self._capability_read_from_record(row)

    def _normalize_config(
        self, capability_type: CapabilityType, config_json: dict[str, Any]
    ) -> dict[str, Any]:
        normalized = dict(config_json or {})
        if capability_type == CapabilityType.MODEL:
            return self.model_provider_service.normalize_config(normalized)
        if capability_type == CapabilityType.MCP:
            normalized.pop("tool_name", None)
            url = str(normalized.get("url") or "").strip()
            if not url:
                raise ValueError("MCP capability requires config_json.url.")

            client_type = (
                str(normalized.get("client_type") or "http_stateless").strip().lower()
            )
            if client_type not in {"http_stateless", "http_stateful"}:
                raise ValueError(
                    "MCP capability config_json.client_type must be http_stateless/http_stateful.",
                )
            normalized["client_type"] = client_type

            transport = (
                str(normalized.get("transport") or "streamable_http").strip().lower()
            )
            if transport not in {"streamable_http", "sse"}:
                raise ValueError(
                    "MCP capability config_json.transport must be streamable_http/sse.",
                )
            normalized["transport"] = transport

            headers = normalized.get("headers")
            if headers is not None and not isinstance(headers, dict):
                raise ValueError(
                    "MCP capability config_json.headers must be an object."
                )

            timeout_seconds = normalized.get("timeout_seconds")
            if timeout_seconds is not None:
                try:
                    timeout_value = int(timeout_seconds)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        "MCP capability config_json.timeout_seconds must be a positive integer.",
                    ) from exc
                if timeout_value <= 0:
                    raise ValueError(
                        "MCP capability config_json.timeout_seconds must be a positive integer.",
                    )
                normalized["timeout_seconds"] = timeout_value
            return normalized

        if capability_type == CapabilityType.VIRTUAL_MCP:
            mounted_tools = normalized.get("mounted_tools")
            if mounted_tools is not None and not isinstance(mounted_tools, list):
                raise ValueError(
                    "Virtual MCP config_json.mounted_tools must be an array."
                )
            headers = normalized.get("headers")
            if headers is not None and not isinstance(headers, dict):
                raise ValueError(
                    "Virtual MCP config_json.headers must be an object."
                )
            return normalized

        if capability_type != CapabilityType.FUNCTION:
            return normalized

        url = str(normalized.get("url") or "").strip()
        if not url:
            raise ValueError("Function capability requires config_json.url.")

        method = str(normalized.get("method") or "POST").strip().upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError(
                "Function capability config_json.method must be GET/POST/PUT/PATCH/DELETE."
            )
        normalized["method"] = method

        headers = normalized.get("headers")
        if headers is not None and not isinstance(headers, dict):
            raise ValueError(
                "Function capability config_json.headers must be an object."
            )

        input_schema = normalized.get("input_schema")
        if input_schema is not None and not isinstance(input_schema, dict):
            raise ValueError(
                "Function capability config_json.input_schema must be an object."
            )

        output_schema = normalized.get("output_schema")
        if output_schema is not None and not isinstance(output_schema, dict):
            raise ValueError(
                "Function capability config_json.output_schema must be an object."
            )

        timeout_seconds = normalized.get("timeout_seconds")
        if timeout_seconds is not None:
            try:
                timeout_value = int(timeout_seconds)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "Function capability config_json.timeout_seconds must be a positive integer."
                ) from exc
            if timeout_value <= 0:
                raise ValueError(
                    "Function capability config_json.timeout_seconds must be a positive integer."
                )
            normalized["timeout_seconds"] = timeout_value

        return normalized

    async def create(
        self, session: AsyncSession, payload: CapabilityCreate
    ) -> CapabilityRead:
        capability_payload = payload.model_dump()
        capability_payload["config_json"] = self._normalize_config(
            payload.type, payload.config_json
        )
        capability_payload.setdefault("id", generate_uuid())
        capability = CapabilityRegistry(**capability_payload)
        session.add(capability)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            if not self._is_legacy_scope_not_null_violation(exc):
                raise
            return await self._insert_with_legacy_scope(session, capability_payload)

        await session.refresh(capability)
        return CapabilityRead.model_validate(capability)

    async def list(
        self, session: AsyncSession, capability_type: CapabilityType | None = None
    ) -> list[CapabilityRead]:
        stmt = sa.select(CapabilityRegistry).order_by(
            CapabilityRegistry.created_at.desc()
        )
        if capability_type is not None:
            stmt = stmt.where(CapabilityRegistry.type == capability_type)

        rows = (await session.scalars(stmt)).all()
        return [CapabilityRead.model_validate(item) for item in rows]

    async def get(self, session: AsyncSession, capability_id: str) -> CapabilityRead:
        capability = await session.get(CapabilityRegistry, capability_id)
        if capability is None:
            raise LookupError(f"Capability '{capability_id}' not found.")
        return CapabilityRead.model_validate(capability)

    async def update(
        self, session: AsyncSession, capability_id: str, payload: CapabilityUpdate
    ) -> CapabilityRead:
        capability = await session.get(CapabilityRegistry, capability_id)
        if capability is None:
            raise LookupError(f"Capability '{capability_id}' not found.")

        update_payload = payload.model_dump()
        update_payload["config_json"] = self._normalize_config(
            payload.type, payload.config_json
        )
        for key, value in update_payload.items():
            setattr(capability, key, value)

        await session.commit()
        await session.refresh(capability)
        return CapabilityRead.model_validate(capability)

    async def delete(
        self, session: AsyncSession, capability_id: str
    ) -> CapabilityDeleteResponse:
        capability = await session.get(CapabilityRegistry, capability_id)
        if capability is None:
            raise LookupError(f"Capability '{capability_id}' not found.")

        await session.delete(capability)
        await session.commit()
        return CapabilityDeleteResponse(deleted=True, capability_id=capability_id)
