"""Account-scoped data for the learning workspace; no model API calls."""
from datetime import timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models import (LearningMaterial, LearningChunk, LearningRecord, QAHistory,
                        Question, QuestionAttempt, ReviewAttempt, Topic, User)
from app.services.xp import XP_LEVELS, calculate_level
from app.services.topic_mastery import update_topic_mastery, get_user_topic_performance

router = APIRouter(prefix="/study", tags=["学习工作台"])


def stamp(value):
    return value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.isoformat()


def question_rows(db, user_id):
    return db.query(QuestionAttempt, Question, LearningMaterial).join(
        Question, Question.id == QuestionAttempt.question_id
    ).join(LearningMaterial, LearningMaterial.id == Question.material_id).filter(
        QuestionAttempt.user_id == user_id, LearningMaterial.user_id == user_id
    ).order_by(QuestionAttempt.id.desc()).all()


def reviews_for(db, user_id):
    return db.query(ReviewAttempt).join(Question, Question.id == ReviewAttempt.question_id).join(
        LearningMaterial, LearningMaterial.id == Question.material_id
    ).filter(ReviewAttempt.user_id == user_id, LearningMaterial.user_id == user_id).order_by(
        ReviewAttempt.id
    ).all()


def level_info(user):
    level = calculate_level(user.total_xp)
    next_xp = XP_LEVELS.get(level + 1)
    start = XP_LEVELS[level]
    return {"total_xp": user.total_xp, "level": level, "level_start_xp": start,
            "next_level_xp": next_xp, "xp_remaining": max(0, next_xp - user.total_xp) if next_xp else 0,
            "level_progress": round((user.total_xp - start) / (next_xp - start) * 100) if next_xp else 100}


@router.get("/summary")
def summary(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = question_rows(db, current_user.id)
    reviews = reviews_for(db, current_user.id)
    latest = {r.question_id: r for r in reviews}
    wrong = [q.id for a, q, _ in rows if not a.is_correct]
    correct = sum(a.is_correct for a, _, _ in rows)
    return {**level_info(current_user), "answered_count": len(rows), "correct_count": correct,
            "correct_rate": round(correct / len(rows) * 100) if rows else None,
            "review_count": len(reviews),
            "pending_mistakes": sum(not latest[q].is_correct if q in latest else True for q in wrong)}


@router.get("/mistakes")
def mistakes(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    reviews = reviews_for(db, current_user.id)
    latest = {r.question_id: r for r in reviews}
    counts = {}
    for review in reviews:
        counts[review.question_id] = counts.get(review.question_id, 0) + 1
    topics = dict(db.query(Topic.id, Topic.name).join(LearningMaterial).filter(
        LearningMaterial.user_id == current_user.id).all())
    result = []
    for attempt, question, material in question_rows(db, current_user.id):
        if attempt.is_correct:
            continue
        last = latest.get(question.id)
        result.append({"id": question.id, "material_id": material.id, "material_title": material.title,
                       "topic_name": topics.get(question.topic_id, "未关联知识点"),
                       "question": question.question, "difficulty": question.difficulty,
                       "options": {key: getattr(question, "option_" + key.lower()) for key in "ABCD"},
                       "user_answer": attempt.user_answer, "correct_answer": question.answer,
                       "explanation": question.explanation, "created_at": stamp(attempt.created_at),
                       "review_count": counts.get(question.id, 0),
                       "resolved": bool(last and last.is_correct),
                       "last_review_at": stamp(last.created_at) if last else None})
    return result


class ReviewRequest(BaseModel):
    answer: str = Field(pattern="^[ABCD]$")
    request_id: UUID


@router.post("/mistakes/{question_id}/review")
def review_question(question_id: int, request: ReviewRequest,
                    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    question = db.query(Question).join(LearningMaterial).filter(
        Question.id == question_id, LearningMaterial.user_id == current_user.id).first()
    wrong = db.query(QuestionAttempt).filter(QuestionAttempt.user_id == current_user.id,
        QuestionAttempt.question_id == question_id, QuestionAttempt.is_correct.is_(False)).first()
    if question is None or wrong is None:
        raise HTTPException(404, "错题不存在")
    request_id = str(request.request_id)
    previous = db.query(ReviewAttempt).filter_by(user_id=current_user.id, request_id=request_id).first()
    if previous is None:
        previous = ReviewAttempt(user_id=current_user.id, question_id=question_id,
            request_id=request_id, user_answer=request.answer, is_correct=request.answer == question.answer)
        db.add(previous)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            previous = db.query(ReviewAttempt).filter_by(user_id=current_user.id, request_id=request_id).first()
            if previous is None:
                raise
    if previous.question_id != question_id or previous.user_answer != request.answer:
        raise HTTPException(409, "这次提交已被使用，请重新开始复习")
    if question.topic_id is not None:
        update_topic_mastery(current_user.id, question.topic_id, db)
    return {"question_id": question_id, "is_correct": previous.is_correct,
            "user_answer": previous.user_answer, "correct_answer": question.answer,
            "explanation": question.explanation, "earned_xp": 0}


@router.get("/records")
def records(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = question_rows(db, current_user.id)
    question_lookup = {q.id: (q, m) for _, q, m in rows}
    result = [{"id": "answer-" + str(a.id), "type": "answer", "title": q.question,
               "material_id": m.id, "material_title": m.title, "created_at": stamp(a.created_at),
               "is_correct": a.is_correct, "earned_xp": a.earned_xp,
               "detail": f"你的答案：{a.user_answer}；正确答案：{q.answer}\n{q.explanation or ''}"}
              for a, q, m in rows]
    for r in reviews_for(db, current_user.id):
        if r.question_id not in question_lookup:
            continue
        q, m = question_lookup[r.question_id]
        result.append({"id": "review-" + str(r.id), "type": "review", "title": q.question,
                       "material_id": m.id, "material_title": m.title, "created_at": stamp(r.created_at),
                       "is_correct": r.is_correct, "earned_xp": 0,
                       "detail": f"你的答案：{r.user_answer}；正确答案：{q.answer}\n{q.explanation or ''}"})
    histories = db.query(QAHistory, LearningMaterial).join(LearningMaterial).filter(
        QAHistory.user_id == current_user.id, LearningMaterial.user_id == current_user.id).all()
    for history, material in histories:
        result.append({"id": "chat-" + str(history.id), "type": "chat", "title": history.question,
                       "material_id": material.id, "material_title": material.title,
                       "created_at": stamp(history.created_at), "detail": history.answer})
    for record in db.query(LearningRecord).filter(LearningRecord.user_id == current_user.id,
                                                 LearningRecord.content_type != "question").all():
        result.append({"id": "record-" + str(record.id), "type": "study", "title": "学习记录",
                       "material_id": None, "material_title": "", "created_at": stamp(record.created_at),
                       "detail": f"学习进度：{record.progress}%", "study_time": record.study_time})
    return sorted(result, key=lambda row: (row["created_at"], row["id"]), reverse=True)


@router.get("/map")
def knowledge_map(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    materials = db.query(LearningMaterial).filter(LearningMaterial.user_id == current_user.id).all()
    topics = db.query(Topic).join(LearningMaterial).filter(LearningMaterial.user_id == current_user.id).all()
    chunks = db.query(LearningChunk.material_id, LearningChunk.topic_id, LearningChunk.embedding.isnot(None),
                      LearningChunk.embedding != "").join(LearningMaterial).filter(
                          LearningMaterial.user_id == current_user.id).all()
    performance = {r["topic"].id:r for r in get_user_topic_performance(current_user.id, db)}
    output = []
    for material in materials:
        material_chunks = [c for c in chunks if c[0] == material.id]
        nodes = []
        for t in topics:
            if t.material_id != material.id:
                continue
            nodes.append({"id": t.id, "name": t.name, "description": t.description,
                          **{k:v for k,v in performance[t.id].items() if k not in ("topic","attempts")},
                          "chunk_count": sum(c[1] == t.id for c in material_chunks)})
        output.append({"id": material.id, "title": material.title, "topics": nodes,
                       "chunk_count": len(material_chunks),
                       "embedded_count": sum(bool(c[2] and c[3]) for c in material_chunks),
                       "linked_count": sum(c[1] in {t["id"] for t in nodes} for c in material_chunks)})
    return output
