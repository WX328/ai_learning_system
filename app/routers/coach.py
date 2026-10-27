"""Authenticated, durable coach sessions with cross-process command leases."""
from copy import deepcopy
import json
import time
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models import User, Question, QuestionAttempt
from app.models.coach_session import CoachSession, CoachTurn
from app.schemas.coach import CoachCreate, CoachCommand
from app.schemas.question import QuestionResponse
from app.agents.tools import owned_material, profile
from app.agents.coach import run_coach
from app.services.answer_submission import record_answer
from app.services.answer_feedback import local_answer_feedback
from app.services.topic_mastery import mastery_priority

router = APIRouter(prefix="/coach/sessions", tags=["学习教练"])


def owned_session(db, user, session_id):
    session = db.query(CoachSession).filter_by(id=str(session_id), user_id=user.id).first()
    if session is None:
        raise HTTPException(404, "学习会话不存在")
    try:
        owned_material(db, user.id, session.material_id)
    except ValueError as exc:
        raise HTTPException(404, "学习资料不存在") from exc
    return session


def snapshot(db, session):
    state = deepcopy(session.state)
    # Stored plans survive; displayed assessments always use current evidence,
    # including old sessions and reviews performed outside this coach session.
    learning = profile(db, session.user_id, session.material_id)
    state["suggested_topics"] = suggested_topics(learning)
    qid = state.pop("pending_question_id", None)
    question = db.query(Question).filter_by(id=qid, material_id=session.material_id).first() if qid else None
    return {
        "id": session.id, "material_id": session.material_id, "goal": session.goal,
        "minutes": session.minutes, "status": session.status, "revision": session.revision,
        "busy": session.lease_until > time.time(), "state": state,
        "messages": session.messages,
        "question": QuestionResponse.model_validate(question, from_attributes=True).model_dump() if question else None,
    }


def suggested_topics(learning):
    return sorted(learning["topics"], key=lambda t: mastery_priority(
        t["mastery"], t["attempt_count"], t["id"]))[:3]


@router.get("")
def list_sessions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(CoachSession).filter_by(user_id=user.id).order_by(CoachSession.created_at.desc()).limit(30).all()
    return [{"id": s.id, "goal": s.goal, "status": s.status, "minutes": s.minutes,
             "material_id": s.material_id, "created_at": s.created_at.isoformat()} for s in rows]


@router.post("")
def create_session(request: CoachCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sid = str(request.request_id)
    existing = db.get(CoachSession, sid)
    if existing:
        if (existing.user_id, existing.material_id, existing.goal, existing.minutes) != (
            user.id, request.material_id, request.goal, request.minutes,
        ):
            raise HTTPException(409, "请求编号已使用，请刷新后重试")
        return snapshot(db, owned_session(db, user, sid))
    try:
        learning = profile(db, user.id, request.material_id)
    except ValueError as exc:
        raise HTTPException(404, "学习资料不存在") from exc
    topics = suggested_topics(learning)
    intro = max(1, request.minutes // 4)
    review = max(1, request.minutes // 5)
    plan = [
        {"title": "围绕目标梳理知识", "minutes": intro},
        {"title": "讲解与自适应练习", "minutes": request.minutes - intro - review},
        {"title": "回顾错误与总结", "minutes": review},
    ]
    session = CoachSession(id=sid, user_id=user.id, material_id=request.material_id,
                           goal=request.goal, minutes=request.minutes, state={
        "plan": plan, "suggested_topics": topics, "target_questions": min(8, max(1, request.minutes // 5)),
        "completed": [], "pending_question_id": None, "current_topic": None,
        "sources": [], "tool_trace": [], "degraded": False,
    }, messages=[{"role": "assistant", "content":
        "学习计划已保存。点击“开始 / 继续辅导”，我会结合你的目标与资料安排本次学习。"}])
    db.add(session)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = owned_session(db, user, sid)
        if (existing.material_id, existing.goal, existing.minutes) != (
            request.material_id, request.goal, request.minutes,
        ):
            raise HTTPException(409, "请求编号已使用")
        return snapshot(db, existing)
    return snapshot(db, session)


@router.get("/{session_id}")
def get_session(session_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return snapshot(db, owned_session(db, user, session_id))


def answer_pending(db, session, state, user, answer):
    qid = state.get("pending_question_id")
    question = db.query(Question).filter_by(id=qid, material_id=session.material_id).first() if qid else None
    if question is None:
        raise HTTPException(409, "当前没有待答练习")
    attempt = db.query(QuestionAttempt).filter_by(user_id=user.id, question_id=qid).first()
    if attempt:
        result = {"question_id": qid, "user_answer": attempt.user_answer,
                  "correct_answer": question.answer, "is_correct": attempt.is_correct,
                  "explanation": question.explanation, "earned_xp": attempt.earned_xp,
                  "feedback": local_answer_feedback(attempt.is_correct, question.explanation),
                  "feedback_source": "local"}
    else:
        result = record_answer(qid, answer, user, db, commit=False)
    result["topic"] = state.get("current_topic")
    state["completed"].append(result)
    current_topics = {t["id"]: t for t in profile(db, user.id, session.material_id)["topics"]}
    state["suggested_topics"] = [
        current_topics.get(t["id"], t) for t in state["suggested_topics"]
    ]
    state["pending_question_id"] = None
    state["degraded"] = False
    session.status = "active"
    return result["feedback"] + " 你可以继续辅导，或结束本次学习。"


def finish_session(session, state):
    completed = state["completed"]
    correct = sum(r["is_correct"] for r in completed)
    weak = list(dict.fromkeys(r["topic"] for r in completed if not r["is_correct"] and r.get("topic")))
    text = f"本次目标：{session.goal}。已完成 {len(completed)} 道练习，答对 {correct} 道。"
    if weak:
        text += " 下次优先复习：" + "、".join(weak) + "。"
    elif completed:
        text += " 下次可换一个知识点，检查能否迁移运用。"
    else:
        text += " 本次尚无作答记录，暂不能据此判断掌握程度。"
    if state.get("pending_question_id"):
        text += " 未作答题目未计入成绩。"
    state["pending_question_id"] = None
    state["summary"] = text
    session.status = "completed"
    return text


@router.post("/{session_id}/turns")
def command(session_id: UUID, request: CoachCommand,
            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    session = owned_session(db, user, session_id)
    rid = str(request.request_id)
    payload = json.dumps(request.model_dump(mode="json", exclude={"request_id"}), sort_keys=True)
    receipt = db.get(CoachTurn, (session.id, rid))
    if receipt:
        if receipt.payload != payload:
            raise HTTPException(409, "同一请求编号不能提交不同内容")
        return snapshot(db, session)
    if session.status == "completed":
        raise HTTPException(409, "学习已结束，请创建新会话")
    if request.action == "message" and session.state.get("pending_question_id"):
        raise HTTPException(409, "请先提交当前练习，或结束本次学习")
    if request.action == "message" and session.revision >= 60:
        raise HTTPException(409, "本次对话已达上限，请结束后开始新会话")
    token = str(uuid4())
    acquired = db.query(CoachSession).filter(
        CoachSession.id == session.id, CoachSession.revision == request.revision,
        CoachSession.lease_until <= time.time(),
    ).update({"lease_token": token, "lease_until": time.time() + 600}, synchronize_session=False)
    db.commit()
    if not acquired:
        raise HTTPException(409, "会话正在处理或进度已更新，请刷新后重试")
    db.refresh(session)
    try:
        state = deepcopy(session.state)
        if request.action == "answer":
            state["sources"] = []
            content = answer_pending(db, session, state, user, request.answer)
            user_text = "提交答案：" + request.answer
        elif request.action == "finish":
            state["sources"] = []
            content = finish_session(session, state)
            user_text = "结束本次学习"
        else:
            content, state["degraded"] = run_coach(db, session, state, request.message)
            user_text = request.message
        # A worker whose lease expired must not commit any grading or generated questions.
        renewed = db.query(CoachSession).filter_by(id=session.id, lease_token=token).update(
            {"lease_token": None, "lease_until": 0.0}, synchronize_session=False)
        if not renewed:
            raise HTTPException(409, "本轮处理已失效，请刷新会话")
        session.state = state
        session.messages = (session.messages + [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": content, "sources": state.get("sources", [])},
        ])[-120:]
        session.revision += 1
        db.add(CoachTurn(session_id=session.id, request_id=rid, payload=payload))
        db.commit()
        db.refresh(session)
        return snapshot(db, session)
    except Exception:
        db.rollback()
        db.query(CoachSession).filter_by(id=str(session_id), lease_token=token).update(
            {"lease_token": None, "lease_until": 0.0}, synchronize_session=False)
        db.commit()
        raise
