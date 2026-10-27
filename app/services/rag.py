import logging
import re
from time import perf_counter

from app.core.settings import deepseek_client
from app.models import LearningChunk, LearningMaterial, Topic
from app.services.embedding import EmbeddingError
from app.services.retriever import (
    RetrievalResults, search_similar_chunks, retrieval_method, retrieval_rrf_k, topic_context_chunks,
)
from app.services.reranker import RerankError, rerank_chunks, rerank_enabled

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = "你是一个专业、耐心的AI学习助手。"


def _topic_question(query: str, topic: Topic) -> str:
    return (
        f"当前选中的知识点是「{topic.name}」。围绕该知识点回答用户原问题。\n"
        "用户说‘这个知识点’、‘不懂’或‘不知道’时，指的是当前选中的知识点，请从基础解释。\n"
        "可以用符合资料概念的生活类比或简短示例帮助理解，并说明这是用于解释的示例，"
        "不要声称示例来自原文，也不要把资料没有覆盖的技术细节说成原文结论。\n"
        "若问题明显超出当前知识点及所给资料范围，请说明缺少哪方面依据并建议切换知识点。\n"
        f"用户原问题：{query}"
    )


def _build_prompt(context: str, query: str) -> str:
    return f"""你是一个智能学习助手。

请根据下面提供的学习资料回答用户的问题。

学习资料：
{context}

用户问题：
{query}

要求：
1. 优先根据学习资料回答。
2. 不要编造资料中的事实或结论；可以用明确标注为示例的类比辅助解释。
3. 如果学习资料无法回答问题，请明确告诉用户。
4. 回答要清晰、易懂。"""


def _call_llm(context: str, query: str) -> str:
    response = deepseek_client("rag").chat.completions.create(
        model="deepseek-chat",
        max_tokens=2048,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_prompt(context, query)},
        ],
    )
    return response.choices[0].message.content


def _source_rows(results: list[dict]) -> list[dict]:
    sources = []
    for rank, result in enumerate(results, start=1):
        chunk = result["chunk"]
        excerpt = re.sub(r"\s+", " ", result.get("content", chunk.content) or "").strip()
        sources.append({
            "rank": rank,
            "chunk_id": chunk.id,
            "chunk_index": chunk.chunk_index,
            "topic_id": getattr(chunk, "topic_id", None),
            "excerpt": excerpt[:240] + ("…" if len(excerpt) > 240 else ""),
            "similarity": (
                round(float(result["similarity"]), 6)
                if result.get("similarity") is not None else None
            ),
            "bm25_score": (
                round(float(result["bm25_score"]), 6)
                if result.get("bm25_score") is not None else None
            ),
            "rrf_score": (
                round(float(result["rrf_score"]), 6)
                if result.get("rrf_score") is not None else None
            ),
            "retrieval_methods": result.get("retrieval_methods", ["vector"]),
            "rerank_score": (
                round(float(result["rerank_score"]), 6)
                if result.get("rerank_score") is not None else None
            ),
        })
    return sources


def _retrieval_meta(
    *,
    candidate_count: int,
    source_count: int,
    rerank_requested: bool,
    rerank_applied: bool,
    rerank_fallback: bool,
    retrieval_latency_ms: float,
    rerank_latency_ms: float,
    started_at: float,
    retrieval_details: dict | None = None,
) -> dict:
    return {
        "candidate_count": candidate_count,
        "source_count": source_count,
        "rerank_requested": rerank_requested,
        "rerank_applied": rerank_applied,
        "rerank_fallback": rerank_fallback,
        "retrieval_latency_ms": round(retrieval_latency_ms, 2),
        "rerank_latency_ms": round(rerank_latency_ms, 2),
        "total_latency_ms": round((perf_counter() - started_at) * 1000, 2),
        **(retrieval_details or {}),
    }


def rag_answer(query: str, material_id: int, db, top_k: int = 6, topic_id: int | None = None):
    started_at = perf_counter()
    use_rerank = rerank_enabled()
    method = retrieval_method()
    retrieval_started_at = perf_counter()
    answer_query = query
    search_query = query
    if topic_id is not None:
        topic = db.query(Topic).filter(Topic.id == topic_id, Topic.material_id == material_id).first()
        # A small topic already fits in the prompt. Asking for an example or
        # saying "I don't understand" must not discard its known source text.
        topic_sources = topic_context_chunks(material_id, topic_id, db, top_k=top_k + 1)
        if topic is not None:
            answer_query = _topic_question(query, topic)
        if len(topic_sources) <= top_k:
            results = topic_sources
            use_rerank = False
        else:
            # Large topics still benefit from ranking. Include the selected
            # topic in the search, since terse questions may omit its name.
            search_query = f"{topic.name}\n{query}"
            try:
                results = search_similar_chunks(
                    query=search_query, material_id=material_id, db=db,
                    top_k=max(10, top_k) if use_rerank else top_k,
                    similarity_threshold=0.35, topic_id=topic_id,
                    method=method, rrf_k=retrieval_rrf_k(),
                )
            except EmbeddingError:
                logger.warning("Topic retrieval unavailable; using known topic sources")
                results = []
            if not results:
                results = RetrievalResults(topic_sources[:top_k], metadata=topic_sources.metadata)
                use_rerank = False
    else:
        results = search_similar_chunks(
            query=query,
            material_id=material_id,
            db=db,
            top_k=max(10, top_k) if use_rerank else top_k,
            similarity_threshold=0.35,
            topic_id=topic_id,
            method=method,
            rrf_k=retrieval_rrf_k(),
        )
    retrieval_details = getattr(results, "metadata", {"retrieval_method": method})
    retrieval_latency_ms = (perf_counter() - retrieval_started_at) * 1000
    candidate_count = len(results)
    rerank_applied = False
    rerank_fallback = False
    rerank_latency_ms = 0.0

    if results:
        if use_rerank:
            rerank_started_at = perf_counter()
            try:
                results = rerank_chunks(search_query, results, top_n=min(3, top_k))
                rerank_applied = True
            except RerankError as exc:
                logger.warning("RAG rerank fallback: %s", exc)
                rerank_fallback = True
                results = results[:top_k]
            finally:
                rerank_latency_ms = (perf_counter() - rerank_started_at) * 1000

        sources = _source_rows(results)
        retrieval = _retrieval_meta(
            candidate_count=candidate_count,
            source_count=len(sources),
            rerank_requested=use_rerank,
            rerank_applied=rerank_applied,
            rerank_fallback=rerank_fallback,
            retrieval_latency_ms=retrieval_latency_ms,
            rerank_latency_ms=rerank_latency_ms,
            started_at=started_at,
            retrieval_details=retrieval_details,
        )
        context = "\n\n".join(result.get("content", result["chunk"].content) for result in results)
        try:
            answer = _call_llm(context, answer_query)
        except Exception as exc:
            logger.warning("RAG answer unavailable: %s", type(exc).__name__)
            return {
                "answer": "AI 服务暂时不可用，请稍后重试。",
                "status": "provider_error",
                "context_source": "retrieval",
                "sources": sources,
                "retrieval": retrieval,
            }
        return {
            "answer": answer,
            "status": "answered",
            "context_source": "retrieval",
            "sources": sources,
            "retrieval": retrieval,
        }

    retrieval = _retrieval_meta(
        candidate_count=0,
        source_count=0,
        rerank_requested=use_rerank,
        rerank_applied=False,
        rerank_fallback=False,
        retrieval_latency_ms=retrieval_latency_ms,
        rerank_latency_ms=0.0,
        started_at=started_at,
        retrieval_details=retrieval_details,
    )

    # 检索不到时的兜底：先判断资料是否已建立索引。
    if topic_id is not None:
        return {
            "answer": "在当前知识点范围内未找到足够相关的资料，请换个问法或切换到「整份资料」。",
            "status": "no_context",
            "context_source": None,
            "sources": [],
            "retrieval": retrieval,
        }
    material = db.query(LearningMaterial).filter(LearningMaterial.id == material_id).first()
    if material is None:
        return {"answer": "学习资料不存在或已被删除。", "status": "not_found", "context_source": None, "sources": [], "retrieval": retrieval}

    embedded_count = db.query(LearningChunk).filter(
        LearningChunk.material_id == material_id,
        LearningChunk.embedding.isnot(None),
        LearningChunk.embedding != "",
    ).count()

    if embedded_count == 0 and method != "bm25":
        return {
            "answer": "这份资料还没有建立向量索引，暂时无法检索回答。请先在「资料库」中点击该资料的「重建向量」，完成后再来提问。",
            "status": "not_indexed",
            "context_source": None,
            "sources": [],
            "retrieval": retrieval,
        }

    # 已建立索引但语义检索没命中：降级用资料正文开头作答，尽量给出有用回答。
    context = (material.content or "").strip()[:3000]
    if not context:
        return {"answer": "这份资料内容为空，无法回答。", "status": "empty_material", "context_source": None, "sources": [], "retrieval": retrieval}

    try:
        answer = _call_llm(context, query)
    except Exception as exc:
        logger.warning("RAG answer unavailable: %s", type(exc).__name__)
        return {
            "answer": "AI 服务暂时不可用，请稍后重试。",
            "status": "provider_error",
            "context_source": "document_fallback",
            "sources": [],
            "retrieval": retrieval,
        }
    return {"answer": answer, "status": "answered", "context_source": "document_fallback", "sources": [], "retrieval": retrieval}
