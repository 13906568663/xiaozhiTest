"""Knowledge 域 Pydantic Schema — 知识库、文档、检索相关 DTO。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import ChunkMethod, DocumentStatus
from app.schemas.common import TimestampsMixin


# ---------------------------------------------------------------------------
# KnowledgeBase schemas
# ---------------------------------------------------------------------------


class EmbeddingConfig(BaseModel):
    """向量模型连接配置，存储于 KnowledgeBase.embedding_config。"""

    model_config = ConfigDict(extra="allow")

    provider_ref: str | None = Field(
        default=None, description="引用全局 Provider 的 code，优先复用其 host / key 配置"
    )
    api_host: str | None = Field(
        default=None, description="Embedding 服务地址，为空时使用全局 openai_base_url"
    )
    api_key: str | None = Field(
        default=None, description="API 密钥明文，优先级高于 api_key_env"
    )
    api_key_env: str | None = Field(default=None, description="API 密钥的环境变量名")
    api_path: str = Field(default="/embeddings", description="Embedding API 路径")
    max_batch_size: int | None = Field(
        default=None,
        ge=1,
        le=512,
        description="单次请求中 input 数组的最大条数；DashScope 等限制为 10，留空时对 DashScope 域名自动用 10，否则默认 256",
    )

    @field_validator(
        "provider_ref", "api_host", "api_key", "api_key_env", mode="before"
    )
    @classmethod
    def normalize_optional_strings(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("api_path", mode="before")
    @classmethod
    def normalize_api_path(cls, value: object) -> str:
        normalized = str(value or "/embeddings").strip()
        if not normalized:
            return "/embeddings"
        if not normalized.startswith("/"):
            return f"/{normalized}"
        return normalized


class KnowledgeBaseBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str = Field(description="唯一编码，节点引用标识")
    name: str = Field(description="知识库显示名称")
    description: str | None = Field(default=None, description="知识库用途说明")
    status: str = Field(default="active", description="active / inactive")
    embedding_model: str = Field(
        default="text-embedding-3-small", description="向量模型名称"
    )
    embedding_dimensions: int = Field(default=1536, ge=1, description="向量维度")
    embedding_config: dict[str, Any] = Field(
        default_factory=dict, description="Embedding API 连接配置"
    )
    chunk_method: ChunkMethod = Field(
        default=ChunkMethod.FIXED,
        description="分块策略：fixed 固定字数 / semantic 语义切割",
    )
    chunk_size: int = Field(default=512, ge=64, description="分块大小（字符数）")
    chunk_overlap: int = Field(default=64, ge=0, description="分块重叠字符数")


class KnowledgeBaseCreate(KnowledgeBaseBase):
    pass


class KnowledgeBaseUpdate(KnowledgeBaseBase):
    pass


class KnowledgeBaseRead(TimestampsMixin, KnowledgeBaseBase):
    document_count: int = Field(default=0, description="文档总数")


class KnowledgeBaseDeleteResponse(BaseModel):
    deleted: bool = Field(description="是否删除成功")
    knowledge_base_id: str = Field(description="被删除的知识库 ID")


# ---------------------------------------------------------------------------
# Document schemas
# ---------------------------------------------------------------------------


class DocumentTextCreate(BaseModel):
    """手动输入文本创建文档。"""

    title: str = Field(description="文档标题")
    content: str = Field(description="文档文本内容")
    source_type: str = Field(default="text", description="text / markdown")


class DocumentRead(TimestampsMixin):
    """文档读取响应。"""

    knowledge_base_id: str = Field(description="所属知识库 ID")
    title: str
    source_type: str
    file_name: str | None = None
    file_size: int | None = None
    status: DocumentStatus
    chunk_count: int = 0
    error_message: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class DocumentDeleteResponse(BaseModel):
    deleted: bool
    document_id: str


# ---------------------------------------------------------------------------
# Search schemas
# ---------------------------------------------------------------------------


class KnowledgeSearchRequest(BaseModel):
    """知识库检索请求。"""

    query: str = Field(description="检索文本")
    top_k: int = Field(default=5, ge=1, le=50, description="返回最相似的 chunk 数量")
    score_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="最低相似度阈值（0-1），低于此值的结果不返回",
    )


class ChunkSearchResult(BaseModel):
    """单条检索结果。"""

    chunk_id: str = Field(description="分块 ID")
    document_id: str = Field(description="所属文档 ID")
    document_title: str = Field(description="所属文档标题")
    chunk_index: int = Field(description="分块序号")
    content: str = Field(description="分块文本")
    score: float = Field(description="相似度得分（0-1，越高越相似）")


class KnowledgeSearchResponse(BaseModel):
    """知识库检索响应。"""

    query: str
    results: list[ChunkSearchResult] = Field(default_factory=list)
    total: int = Field(default=0, description="返回的结果数量")
