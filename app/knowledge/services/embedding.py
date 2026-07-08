"""Embedding 服务——调用 OpenAI 兼容 /embeddings 端点进行批量向量化。

与 http_invoker.py 保持一致，使用 urllib + asyncio.to_thread 避免引入新的 HTTP 客户端。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.request
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_DEFAULT_EMBED_BATCH_SIZE = 256
# DashScope 兼容 OpenAI 的 /embeddings 接口通常限制单次最多 10 条 input
_DASHSCOPE_DEFAULT_BATCH_SIZE = 10


def _resolve_api_key(embedding_config: dict[str, Any]) -> str | None:
    """按优先级解析 API Key：config.api_key > config.api_key_env > 全局配置。"""
    if key := embedding_config.get("api_key"):
        return key
    if env_name := embedding_config.get("api_key_env"):
        return os.environ.get(env_name)
    return get_settings().openai_api_key


def _resolve_api_host(embedding_config: dict[str, Any]) -> str:
    if host := embedding_config.get("api_host"):
        return host.rstrip("/")
    settings = get_settings()
    if settings.openai_base_url:
        return settings.openai_base_url.rstrip("/")
    return "https://api.openai.com/v1"


def _resolve_max_batch_size(embedding_config: dict[str, Any]) -> int:
    """单次 /embeddings 请求的 input 条数上限（不同厂商差异大）。"""
    raw = embedding_config.get("max_batch_size")
    if raw is not None:
        try:
            n = int(raw)
            if 1 <= n <= 512:
                return n
        except (TypeError, ValueError):
            pass
    host = _resolve_api_host(embedding_config).lower()
    if "dashscope" in host:
        return _DASHSCOPE_DEFAULT_BATCH_SIZE
    return _DEFAULT_EMBED_BATCH_SIZE


def _call_embeddings_api(
    texts: list[str],
    model: str,
    embedding_config: dict[str, Any],
) -> list[list[float]]:
    """同步调用 /embeddings 端点，返回向量列表。"""
    api_host = _resolve_api_host(embedding_config)
    api_path = embedding_config.get("api_path", "/embeddings")
    api_key = _resolve_api_key(embedding_config)
    url = f"{api_host}{api_path}"
    logger.info(
        "Embedding request: url=%s, model=%s, config_keys=%s",
        url,
        model,
        list(embedding_config.keys()),
    )

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        # 默认 'Authorization: Bearer xxx'，允许 embedding_config 指定网关风格的自定义头
        # （例如 'Authorization-Gateway' + 空 scheme 直接透传 token）。
        raw_header_name = embedding_config.get("auth_header_name")
        header_name = (
            str(raw_header_name).strip() if raw_header_name else ""
        ) or "Authorization"
        raw_scheme = embedding_config.get("auth_header_scheme")
        header_scheme = str(raw_scheme) if raw_scheme is not None else "Bearer "
        headers[header_name] = f"{header_scheme}{api_key}"

    payload = json.dumps({"input": texts, "model": model}, ensure_ascii=False).encode(
        "utf-8"
    )

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        logger.error("Embedding API error %s %s: %s", exc.code, url, err_body)
        raise RuntimeError(
            f"Embedding API 请求失败 (HTTP {exc.code}): {err_body[:500]}"
        ) from exc
    except urllib.error.URLError as exc:
        logger.error("Embedding API unreachable %s: %s", url, exc.reason)
        raise RuntimeError(f"无法连接 Embedding API ({url}): {exc.reason}") from exc

    vectors = _extract_vectors(body)
    if not vectors:
        logger.error(
            "Embedding API returned empty vectors, url=%s, body=%s",
            url,
            json.dumps(body, ensure_ascii=False)[:1000],
        )
        raise RuntimeError(
            f"Embedding API 返回空向量，请检查模型和输入是否正确。"
            f" 请求地址: {url}, 响应: {json.dumps(body, ensure_ascii=False)[:500]}"
        )
    return vectors


def _extract_vectors(body: dict[str, Any]) -> list[list[float]]:
    """从不同格式的 API 响应中提取向量列表。

    支持的格式:
      - OpenAI 标准: {"data": [{"embedding": [...], "index": 0}, ...]}
      - 简化单条:    {"embedding": [0.1, 0.2, ...]}
      - 简化批量:    {"embeddings": [[0.1, ...], [0.2, ...]]}
    """
    # OpenAI 标准格式
    if data_items := body.get("data"):
        if isinstance(data_items, list) and data_items:
            data_items.sort(key=lambda x: x.get("index", 0))
            return [item["embedding"] for item in data_items if item.get("embedding")]

    # 简化批量格式: {"embeddings": [[...], [...]]}
    if embeddings := body.get("embeddings"):
        if isinstance(embeddings, list) and embeddings:
            if isinstance(embeddings[0], list):
                return embeddings

    # 简化单条格式: {"embedding": [0.1, 0.2, ...]}
    if embedding := body.get("embedding"):
        if isinstance(embedding, list) and embedding:
            if isinstance(embedding[0], (int, float)):
                return [embedding]
            if isinstance(embedding[0], list):
                return embedding

    return []


async def batch_embed(
    texts: list[str],
    model: str,
    embedding_config: dict[str, Any],
) -> list[list[float]]:
    """批量向量化，按 embedding_config.max_batch_size 或宿主默认值分批调用。"""
    if not texts:
        return []

    batch_size = _resolve_max_batch_size(embedding_config)
    all_vectors: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        vectors = await asyncio.to_thread(
            _call_embeddings_api, batch, model, embedding_config
        )
        all_vectors.extend(vectors)

    if len(all_vectors) != len(texts):
        raise RuntimeError(
            f"Embedding API 返回向量数 {len(all_vectors)} 与输入条数 {len(texts)} 不一致"
        )

    return all_vectors


async def embed_single(
    text: str,
    model: str,
    embedding_config: dict[str, Any],
) -> list[float]:
    """向量化单条文本。"""
    results = await batch_embed([text], model, embedding_config)
    return results[0]
