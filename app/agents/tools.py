"""Allowlisted tools. User/material scope comes only from the server."""
from pydantic import BaseModel, ConfigDict, Field
from app.models import LearningMaterial, Topic, Question, QuestionAttempt
from app.services.topic_mastery import (get_material_topic_performance, mastery_priority,
                                       distinct_first_answers, MASTERED_THRESHOLD)
from app.schemas.question import QuestionResponse
from app.services.retriever import search_similar_chunks
from app.services.question_generator import generate_question_from_material, save_generated_question


class EmptyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchArgs(EmptyArgs):
    query: str = Field(min_length=1, max_length=500)


class PracticeArgs(EmptyArgs):
    topic_id: int = Field(gt=0, description="必须使用当前资料学习档案中的知识点 ID")
    topic: str = Field(min_length=1, max_length=200)
    difficulty: int = Field(default=2, ge=1, le=5)


SPECS = {
    "get_learning_profile": (EmptyArgs, "读取当前资料的练习统计和知识点掌握情况"),
    "get_weak_topics": (EmptyArgs, "读取待巩固与未练习知识点"),
    "search_material": (SearchArgs, "检索当前资料，返回带片段 ID 的证据"),
    "create_practice": (PracticeArgs, "生成一道练习并等待用户回答；先讲解，再从学习档案选择有效 topic_id；没有知识点时请用户先提取"),
    "get_recent_mistakes": (EmptyArgs, "读取当前资料中最近首次答错的题目和用户选择"),
}
TOOLS = [{"type": "function", "function": {
    "name": name, "description": description, "parameters": model.model_json_schema(),
}} for name, (model, description) in SPECS.items()]


def owned_material(db, user_id, material_id):
    material = db.query(LearningMaterial).filter_by(id=material_id, user_id=user_id).first()
    if material is None:
        raise ValueError("资料不存在或无权访问")
    return material


def profile(db, user_id, material_id):
    owned_material(db, user_id, material_id)
    rows = get_material_topic_performance(user_id, material_id, db)
    rows = sorted(rows, key=lambda r: mastery_priority(r["mastery_score"], r["attempt_count"], r["topic"].id))[:100]
    attempts = distinct_first_answers(db.query(QuestionAttempt, Question).join(Question).filter(
        Question.material_id == material_id, QuestionAttempt.user_id == user_id,
    ).all())[:20]
    return {
        "recent_count": len(attempts),
        "recent_correct": sum(a.is_correct for a, _ in attempts),
        "topics": [{"id": r["topic"].id, "name": r["topic"].name, "mastery": r["mastery_score"],
                    **{k:v for k,v in r.items() if k not in ("topic","attempts")}} for r in rows],
    }


def execute_tool(name, arguments, db, session, state):
    if name not in SPECS:
        raise ValueError("工具不存在")
    args = SPECS[name][0].model_validate(arguments)
    owned_material(db, session.user_id, session.material_id)
    if name == "get_learning_profile":
        return profile(db, session.user_id, session.material_id)
    if name == "get_weak_topics":
        topics = profile(db, session.user_id, session.material_id)["topics"]
        return sorted((t for t in topics if t["mastery"] is None or t["mastery"] < MASTERED_THRESHOLD),
                      key=lambda t: mastery_priority(t["mastery"], t["attempt_count"], t["id"]))[:10]
    if name == "get_recent_mistakes":
        rows = db.query(Question, QuestionAttempt).join(QuestionAttempt).filter(
            Question.material_id == session.material_id,
            QuestionAttempt.user_id == session.user_id, QuestionAttempt.is_correct.is_(False),
        ).order_by(QuestionAttempt.id.desc()).limit(5).all()
        return [{"question": q.question, "user_answer": a.user_answer} for q, a in rows]
    if name == "search_material":
        results = search_similar_chunks(args.query, session.material_id, db, top_k=3)
        sources = [{"id": r["chunk"].id, "text": r["chunk"].content[:1800],
                    "score": round(float(r["similarity"]), 3)} for r in results]
        state["sources"] = sources
        return {"sources": sources, "note": "未命中资料，请明确告知用户" if not sources else ""}
    if state.get("pending_question_id"):
        raise ValueError("请先完成当前练习")
    if len(state["completed"]) >= state["target_questions"]:
        raise ValueError("本次计划的练习已完成，请总结或讲解")
    if args.topic_id is not None:
        topic = db.query(Topic).filter_by(id=args.topic_id, material_id=session.material_id).first()
        if topic is None:
            raise ValueError("知识点不属于当前资料")
    from app.routers.question import generation_slots
    if not generation_slots.acquire(blocking=False):
        raise ValueError("出题服务繁忙，请稍后重试")
    try:
        data = generate_question_from_material(
            session.material_id, session.user_id, args.topic, db,
            current_difficulty=args.difficulty, topic_id=args.topic_id,
        )
        question = save_generated_question(session.material_id, data, db,
                                           topic_id=args.topic_id, is_adaptive=True, commit=False)
    finally:
        generation_slots.release()
    state["pending_question_id"] = question.id
    state["current_topic"] = args.topic
    session.status = "waiting_answer"
    return {"question": QuestionResponse.model_validate(question, from_attributes=True).model_dump()}
