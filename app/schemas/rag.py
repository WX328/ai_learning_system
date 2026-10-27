from typing import Literal

from pydantic import BaseModel, Field

class RAGAskRequest(BaseModel):
    query:str = Field(
        min_length=1,
        description="用户的问题"
    )

    material_id:int = Field(
        gt=0,
        description="学习资料ID"
    )

    topic_id:int | None = Field(
        default=None,
        gt=0,
        description="知识点ID，可选"
    )

class RAGAskResponse(BaseModel):
    history_id:int | None
    question:str
    answer:str
    status:Literal["answered", "provider_error", "not_found", "not_indexed", "empty_material", "no_context"]
    context_source:Literal["retrieval", "document_fallback"] | None
    sources:list["RAGSource"] = Field(default_factory=list)
    retrieval:"RAGRetrievalMeta | None" = None


class RAGSource(BaseModel):
    rank:int
    chunk_id:int
    chunk_index:int
    topic_id:int | None = None
    excerpt:str
    similarity:float | None = None
    bm25_score:float | None = None
    rrf_score:float | None = None
    retrieval_methods:list[Literal["vector", "bm25", "topic"]] = Field(default_factory=list)
    rerank_score:float | None = None


class RAGRetrievalMeta(BaseModel):
    retrieval_method:Literal["vector", "bm25", "hybrid", "topic"] = "vector"
    vector_candidate_count:int = 0
    bm25_candidate_count:int = 0
    db_latency_ms:float = 0.0
    embedding_latency_ms:float = 0.0
    vector_latency_ms:float = 0.0
    bm25_latency_ms:float = 0.0
    fusion_latency_ms:float = 0.0
    candidate_count:int
    source_count:int
    rerank_requested:bool
    rerank_applied:bool
    rerank_fallback:bool
    retrieval_latency_ms:float
    rerank_latency_ms:float
    total_latency_ms:float
