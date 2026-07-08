"""文本分块器——支持固定字数滑动窗口和语义切割两种模式。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ChunkData:
    index: int
    content: str
    metadata: dict = field(default_factory=dict)


def split_text(
    text: str,
    chunk_size: int = 512,
    chunk_overlap: int = 64,
    source_type: str = "text",
    chunk_method: str = "fixed",
) -> list[ChunkData]:
    """将文本分块。

    chunk_method:
      - fixed: 固定字数滑动窗口（Markdown 模式下按段落感知切分）。
      - semantic: 先按句拆分，再调用 _merge_by_boundary 基于语义相似度
        变化点合并/拆分，需要外部先调用 split_text_semantic 获取 embedding
        后使用。此入口仅做回退（无 embedding 时退化为 fixed）。
    """
    if not text or not text.strip():
        return []

    if chunk_method == "semantic":
        return _split_into_sentences(text, chunk_size, chunk_overlap)

    if source_type == "markdown":
        return _split_markdown(text, chunk_size, chunk_overlap)
    return _split_sliding_window(text, chunk_size, chunk_overlap)


async def split_text_semantic(
    text: str,
    chunk_size: int = 512,
    chunk_overlap: int = 64,
    *,
    embedding_model: str,
    embedding_config: dict,
) -> list[ChunkData]:
    """语义切割：按句拆分 → 逐句 embedding → 检测相似度下降点 → 合并为语义连贯的块。"""
    from app.knowledge.services.embedding import batch_embed

    sentences = _extract_sentences(text)
    if not sentences:
        return []

    max_sentence_chars = max(
        512, min(_MAX_SENTENCE_EMBED_CHARS, max(chunk_size * 12, 2048))
    )
    sentences = _split_oversized_segments(sentences, max_sentence_chars)
    if not sentences:
        return []

    if len(sentences) <= 2:
        return [ChunkData(index=0, content=text.strip())]

    sentence_texts = [s for s in sentences]
    embeddings = await batch_embed(sentence_texts, embedding_model, embedding_config)

    merged = _merge_by_semantic_boundary(
        sentences, embeddings, chunk_size, chunk_overlap
    )
    for i, ch in enumerate(merged):
        ch.index = i
    return merged


# ---------------------------------------------------------------------------
# 固定字数切割
# ---------------------------------------------------------------------------


def _split_sliding_window(
    text: str, chunk_size: int, chunk_overlap: int
) -> list[ChunkData]:
    chunks: list[ChunkData] = []
    start = 0
    idx = 0
    while start < len(text):
        end = start + chunk_size
        chunk_text = text[start:end].strip()
        if chunk_text:
            chunks.append(ChunkData(index=idx, content=chunk_text))
            idx += 1
        if end >= len(text):
            break
        start = end - chunk_overlap
    return chunks


_MD_HEADING_RE = re.compile(r"^#{1,6}\s", re.MULTILINE)


def _split_markdown(text: str, chunk_size: int, chunk_overlap: int) -> list[ChunkData]:
    sections = _MD_HEADING_RE.split(text)
    headings = _MD_HEADING_RE.findall(text)

    paragraphs: list[str] = []
    for i, section in enumerate(sections):
        if i == 0 and not section.strip():
            continue
        prefix = headings[i - 1] if i > 0 and i - 1 < len(headings) else ""
        full = (prefix + section).strip()
        if full:
            sub_paragraphs = re.split(r"\n\s*\n", full)
            paragraphs.extend(p.strip() for p in sub_paragraphs if p.strip())

    chunks: list[ChunkData] = []
    idx = 0
    current_chunk = ""

    for para in paragraphs:
        if len(para) > chunk_size:
            if current_chunk:
                chunks.append(ChunkData(index=idx, content=current_chunk))
                idx += 1
                current_chunk = ""
            sub_chunks = _split_sliding_window(para, chunk_size, chunk_overlap)
            for sc in sub_chunks:
                sc.index = idx
                chunks.append(sc)
                idx += 1
            continue

        if current_chunk and len(current_chunk) + len(para) + 2 > chunk_size:
            chunks.append(ChunkData(index=idx, content=current_chunk))
            idx += 1
            overlap_text = current_chunk[-chunk_overlap:] if chunk_overlap > 0 else ""
            current_chunk = (
                (overlap_text + "\n\n" + para).strip() if overlap_text else para
            )
        else:
            current_chunk = (
                (current_chunk + "\n\n" + para).strip() if current_chunk else para
            )

    if current_chunk:
        chunks.append(ChunkData(index=idx, content=current_chunk))

    return chunks


# ---------------------------------------------------------------------------
# 语义切割辅助
# ---------------------------------------------------------------------------

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？.!?\n])\s*")

# 语义分块会先对「句子」逐条向量化；单条过长易触发 Embedding API 长度限制（与固定分块不同）。
# 保守上限：多语言下字符数与 token 非线性，避免逼近常见 8k token 输入上限
_MAX_SENTENCE_EMBED_CHARS = 4000


def _split_oversized_segments(sentences: list[str], max_chars: int) -> list[str]:
    """将超长片段切成多段，避免单次 embedding 输入超限。"""
    out: list[str] = []
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if len(s) <= max_chars:
            out.append(s)
            continue
        start = 0
        while start < len(s):
            piece = s[start : start + max_chars].strip()
            if piece:
                out.append(piece)
            start += max_chars
    return out


def _extract_sentences(text: str) -> list[str]:
    """按句号/问号/叹号/换行拆分为句子列表，过滤空白。"""
    raw = _SENTENCE_SPLIT_RE.split(text)
    return [s.strip() for s in raw if s.strip()]


def _split_into_sentences(
    text: str, chunk_size: int, chunk_overlap: int
) -> list[ChunkData]:
    """语义模式的同步回退：按句拆分后按 chunk_size 合并，无 embedding 信息。"""
    sentences = _extract_sentences(text)
    if not sentences:
        return []

    chunks: list[ChunkData] = []
    idx = 0
    current = ""
    for sent in sentences:
        if current and len(current) + len(sent) + 1 > chunk_size:
            chunks.append(ChunkData(index=idx, content=current))
            idx += 1
            overlap_text = current[-chunk_overlap:] if chunk_overlap > 0 else ""
            current = (overlap_text + " " + sent).strip() if overlap_text else sent
        else:
            current = (current + " " + sent).strip() if current else sent

    if current:
        chunks.append(ChunkData(index=idx, content=current))
    return chunks


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _merge_by_semantic_boundary(
    sentences: list[str],
    embeddings: list[list[float]],
    chunk_size: int,
    chunk_overlap: int,
) -> list[ChunkData]:
    """根据相邻句子 embedding 的余弦相似度变化点来切分段落。

    当相邻句子的相似度低于阈值时，判定为语义断点，开始新的 chunk。
    同时保证单个 chunk 不超过 chunk_size。
    """
    if len(sentences) != len(embeddings):
        return _split_into_sentences("\n".join(sentences), chunk_size, chunk_overlap)

    similarities: list[float] = []
    for i in range(len(embeddings) - 1):
        similarities.append(_cosine_similarity(embeddings[i], embeddings[i + 1]))

    if not similarities:
        return [ChunkData(index=0, content=" ".join(sentences))]

    mean_sim = sum(similarities) / len(similarities)
    std_sim = (
        sum((s - mean_sim) ** 2 for s in similarities) / len(similarities)
    ) ** 0.5
    threshold = mean_sim - std_sim

    chunks: list[ChunkData] = []
    idx = 0
    current_sentences: list[str] = [sentences[0]]

    for i in range(1, len(sentences)):
        current_text = " ".join(current_sentences)
        new_text = current_text + " " + sentences[i]

        is_boundary = i - 1 < len(similarities) and similarities[i - 1] < threshold
        exceeds_size = len(new_text) > chunk_size

        if is_boundary or exceeds_size:
            chunk_content = " ".join(current_sentences).strip()
            if chunk_content:
                chunks.append(ChunkData(index=idx, content=chunk_content))
                idx += 1

            if chunk_overlap > 0:
                overlap = chunk_content[-chunk_overlap:]
                current_sentences = [overlap + " " + sentences[i]]
            else:
                current_sentences = [sentences[i]]
        else:
            current_sentences.append(sentences[i])

    remaining = " ".join(current_sentences).strip()
    if remaining:
        chunks.append(ChunkData(index=idx, content=remaining))

    return chunks
