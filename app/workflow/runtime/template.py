"""占位符 / 模板解析引擎。

支持 ${variable} 格式的占位符，从 context / payload / env / node 中解析替换，
支持点分路径（如 ${step1.output.id}）访问嵌套字段。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from app.workflow.schemas import TaskNodeDefinition

PLACEHOLDER_PATTERN = re.compile(r"\$\{([^{}]+)}")


def resolve_value_template(
    value: Any,
    *,
    context: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    node: TaskNodeDefinition | None = None,
) -> Any:
    """递归解析模板值中的占位符表达式。"""
    if isinstance(value, dict):
        return {
            key: resolve_value_template(
                item, context=context, payload=payload, node=node
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            resolve_value_template(item, context=context, payload=payload, node=node)
            for item in value
        ]
    if not isinstance(value, str):
        return value

    full_match = PLACEHOLDER_PATTERN.fullmatch(value)
    if full_match:
        return lookup_placeholder(
            full_match.group(1), context=context, payload=payload, node=node
        )

    def _replace(match: re.Match[str]) -> str:
        resolved = lookup_placeholder(
            match.group(1), context=context, payload=payload, node=node
        )
        if resolved is None:
            return ""
        # artifact ref / ref-list 必须走摘要，绝不能 json.dumps 后嵌入 prompt
        # —— 否则一条占位符就会把几百 KB 的大对象数据原样灌入 LLM 上下文，
        # 直接超过 max input tokens。
        summary = _summarize_artifact_for_prompt(resolved)
        if summary is not None:
            return summary
        if isinstance(resolved, (dict, list)):
            return _safe_inline_json(resolved)
        return str(resolved)

    return PLACEHOLDER_PATTERN.sub(_replace, value)


# 单次模板渲染中允许内嵌的最大 JSON 体积（字节）。超过即降级为摘要文本，
# 防止 prompt 渲染层把 context 里的大对象（如解析了 artifact 后的全量数据列表）
# 直接 dump 进 system / user message 把 LLM 上下文打爆。
MAX_INLINE_TEMPLATE_JSON_BYTES = 1500


def _safe_inline_json(value: dict | list) -> str:
    """把 dict / list 转为内嵌 JSON；超阈值时降级为摘要文本。"""
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return f"<unserializable {type(value).__name__}>"
    if len(text.encode("utf-8")) <= MAX_INLINE_TEMPLATE_JSON_BYTES:
        return text
    if isinstance(value, list):
        return (
            f"<large-list len={len(value)} approx_bytes={len(text)} "
            f"(已截断，请通过 artifact / 节点输出读取完整内容)>"
        )
    keys = list(value.keys())[:5]
    more = f", ...共 {len(value)} 个 key" if len(value) > 5 else ""
    return (
        f"<large-dict keys=[{', '.join(keys)}{more}] approx_bytes={len(text)} "
        f"(已截断，请通过 artifact / 节点输出读取完整内容)>"
    )


def _summarize_artifact_for_prompt(value: object) -> str | None:
    """artifact ref 渲染层桥接：避免 prompt/template 互相 import session_assets。

    返回 ``None`` 表示 value 不需要走摘要，调用方按常规渲染。
    """
    # 内联导入以避免顶层循环依赖（session_assets 反过来用 helpers）
    from app.workflow.services.session_assets import summarize_artifact_value
    return summarize_artifact_value(value)


def lookup_placeholder(
    expression: str,
    *,
    context: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    node: TaskNodeDefinition | None = None,
) -> Any:
    """按点分路径从 context/payload/env/node 中查找占位符值。"""
    sources: dict[str, Any] = {
        "context": context or {},
        "payload": payload or {},
        "env": os.environ,
        "node": {"code": node.code, "name": node.name} if node else {},
    }
    parts = [part for part in expression.split(".") if part]
    if not parts:
        return None

    current: Any = sources.get(parts[0])
    for part in parts[1:]:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
        if current is None:
            return None
    return current


def extract_json_path(payload: Any, path: str) -> Any:
    """解析受限的 JSONPath 路径，用于提取响应中的某段。

    支持的语法（最小集 + wildcard + 整数下标）：

      * ``$``              — 整个 payload
      * ``$.a.b.c``        — 点分路径下钻
      * ``$.a.b[*]``       — 当 ``b`` 是 list 时，对每个元素继续后续路径（list 投影）
      * ``$.a.b[0]`` / ``$.a.b[-1]`` — list 取下标；越界返回 ``None``
      * ``$.a.b.*``        — 当 ``b`` 是 dict 时，对所有 value 继续后续路径
        （等价于"展开 dict.values()"）；若 ``b`` 是 list 则等同 ``[*]``
      * ``$.a.b[*].NAME``  — 常用组合：list[dict] 提取某字段 → list[str]

    flatten 语义：任意 ``*`` / ``[*]`` 段产生的中间结果都是 list；继续往下走时，
    若子路径再产生 list，统一 extend 合并为一层（即结果不会出现 ``list[list[...]]``
    的嵌套）。这让 step1 ``$.data.sites[*].NAME`` 直接得到 ``list[str]``，让 step2
    ``$.data.*`` 直接把 ``{父节点: [子项]}`` flatten 成扁平 ``list[str]``。

    路径不匹配或类型不符时返回 ``None``（不抛错，由调用方决定 fallback）。
    无法识别的下标语法（如 ``[name]`` 这类 quoted key）会被忽略并整段截断，
    避免拼错的 path 把整个解析炸掉。
    """
    normalized = path.strip()
    if not normalized or normalized == "$":
        return payload
    if not normalized.startswith("$."):
        return None

    tokens = _tokenize_json_path(normalized[2:])
    if not tokens:
        return payload
    return _walk_json_path(payload, tokens)


def _tokenize_json_path(body: str) -> list[str]:
    """把 ``a.b[*].NAME`` / ``a.b[0]`` 这样的 path 体拆成 token 列表。

    Token 形状：普通段（``a`` / ``NAME``）、``[*]``、``[<int>]``、``*``。
    无法识别的 ``[...]`` 段（如 ``[name]``）会让整段后续 token 被丢弃，
    上层 walk 走到该位置时自然返回 ``None`` —— 这是显式 fail-loud 的妥协。
    """
    tokens: list[str] = []
    for segment in body.split("."):
        if not segment:
            continue
        buffer = segment
        while "[" in buffer:
            head, _, rest = buffer.partition("[")
            if head:
                tokens.append(head)
            close = rest.find("]")
            if close < 0:
                buffer = ""
                break
            inner = rest[:close]
            after = rest[close + 1:]
            if inner == "*":
                tokens.append("[*]")
                buffer = after
                continue
            try:
                _ = int(inner)
            except ValueError:
                # 不识别的下标语法（如 ``[name]``）：丢弃当前 segment 余下部分。
                buffer = ""
                break
            tokens.append(f"[{inner}]")
            buffer = after
        if buffer:
            tokens.append(buffer)
    return tokens


def _walk_json_path(current: Any, tokens: list[str]) -> Any:
    if not tokens:
        return current
    head, *tail = tokens

    if head == "[*]":
        if not isinstance(current, list):
            return None
        return _project_list(current, tail)

    if head.startswith("[") and head.endswith("]"):
        if not isinstance(current, list):
            return None
        try:
            index = int(head[1:-1])
        except ValueError:
            return None
        if not -len(current) <= index < len(current):
            return None
        return _walk_json_path(current[index], tail)

    if head == "*":
        if isinstance(current, dict):
            return _project_list(list(current.values()), tail)
        if isinstance(current, list):
            return _project_list(current, tail)
        return None

    if isinstance(current, dict):
        return _walk_json_path(current.get(head), tail)
    return None


def _project_list(items: list[Any], tail: list[str]) -> list[Any]:
    """对 list 中每个元素继续 walk tail，结果中的 list 会被自动 flatten extend。"""
    results: list[Any] = []
    for item in items:
        sub = _walk_json_path(item, tail)
        if sub is None:
            continue
        if isinstance(sub, list):
            results.extend(sub)
        else:
            results.append(sub)
    return results


def apply_response_pick(
    payload: Any,
    pick_config: dict[str, Any] | None,
) -> Any:
    """根据 ``pick_config`` 对 HTTP 响应做字段裁剪（原地修改）。

    用途：把大体积 JSON 响应里 LLM 用不到的字段提前剔除，显著降低后续灌入
    模型上下文的 token 数。

    ``pick_config`` 形如::

        {
            "$.data.joints": ["NAME"],
            "$.data.sites": ["NAME"],
            "$.data.strongholds": ["NAME"],
        }

    语义：
      * key 为 ``$.a.b.c`` 风格的 JSON 路径（与 :func:`extract_json_path` 一致），
        定位到要裁剪的"容器"。
      * value 为要 **保留** 的字段名列表。
      * 容器是 ``list[dict]`` 时：对每个元素只保留指定字段；非 dict 元素原样保留。
      * 容器是 ``dict`` 时：只保留指定字段。
      * 路径不存在、类型不匹配、字段列表为空时 **静默跳过**，不抛错（避免误配置
        阻断生产链路；裁剪是优化项而非约束项）。

    Args:
        payload: HTTP 响应解析后的 JSON 对象（dict / list）。
        pick_config: 字段裁剪配置，``None`` 或空 dict 表示不裁剪。

    Returns:
        与入参同一个对象（同时也已被原地修改）。返回值仅为方便链式调用。
    """
    if not isinstance(pick_config, dict) or not pick_config:
        return payload

    for path, fields in pick_config.items():
        if not isinstance(fields, list) or not fields:
            continue
        fields_set: set[str] = {
            str(f) for f in fields if isinstance(f, (str, int))
        }
        if not fields_set:
            continue
        target = extract_json_path(payload, str(path))
        if target is None:
            continue
        if isinstance(target, list):
            for index, item in enumerate(target):
                if isinstance(item, dict):
                    target[index] = {
                        key: value
                        for key, value in item.items()
                        if key in fields_set
                    }
        elif isinstance(target, dict):
            for key in list(target.keys()):
                if key not in fields_set:
                    target.pop(key)

    return payload
