"""Administrative metadata only; never return learning contents or credentials."""
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select, union
from sqlalchemy.orm import Session, aliased

from app.core.dependencies import get_current_admin
from app.database import get_db
from app.models import (AdminAuditLog, CoachSession, LearningMaterial, LearningRecord,
                        QAHistory, Question, QuestionAttempt, ReviewAttempt, Topic, User)
from app.schemas.admin import AdminUserResponse, UserStatusRequest
from app.services.admin import set_user_status


def private_response(response: Response):
    response.headers["Cache-Control"] = "no-store, private"


router = APIRouter(prefix="/admin", tags=["管理员"],
    dependencies=[Depends(get_current_admin), Depends(private_response)])


def safe_user(user):
    return AdminUserResponse.model_validate(user).model_dump(mode="json")


@router.get("/users")
def users(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
          search: str = Query("", max_length=50), role: Literal["user", "admin"] | None = None,
          is_active: bool | None = None, db: Session = Depends(get_db)):
    query = db.query(User)
    if search.strip():
        query = query.filter(User.username.contains(search.strip(), autoescape=True))
    if role is not None:
        query = query.filter(User.role == role)
    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    total = query.count()
    rows = query.order_by(User.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"items":[safe_user(user) for user in rows], "total":total, "page":page, "page_size":page_size}


@router.get("/users/{user_id}")
def user_detail(user_id: int, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "用户不存在")
    material_ids = select(LearningMaterial.id).where(LearningMaterial.user_id == user_id)
    def count(model, *conditions):
        return db.query(func.count()).select_from(model).filter(*conditions).scalar()
    attempts = db.query(QuestionAttempt).join(Question).filter(QuestionAttempt.user_id == user_id,
                                                              Question.material_id.in_(material_ids))
    total = attempts.count()
    correct = attempts.filter(QuestionAttempt.is_correct.is_(True)).count()
    return {**safe_user(user), "statistics":{
        "material_count":count(LearningMaterial, LearningMaterial.user_id == user_id),
        "topic_count":count(Topic, Topic.material_id.in_(material_ids)),
        "question_count":count(Question, Question.material_id.in_(material_ids)),
        "answer_count":total, "correct_rate":round(correct / total * 100) if total else None,
        "review_count":count(ReviewAttempt, ReviewAttempt.user_id == user_id),
        "qa_count":count(QAHistory, QAHistory.user_id == user_id),
        "coach_session_count":count(CoachSession, CoachSession.user_id == user_id)}}


@router.patch("/users/{user_id}/status", response_model=AdminUserResponse)
def user_status(user_id: int, request: UserStatusRequest,
                current_admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    return set_user_status(db, current_admin.id, current_admin.auth_version, user_id, request.is_active)


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    def count(model, *conditions):
        return db.query(func.count()).select_from(model).filter(*conditions).scalar()
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    activity = union(*(select(model.user_id).where(model.created_at >= cutoff)
                       for model in (QuestionAttempt, ReviewAttempt, QAHistory, LearningRecord))).subquery()
    return {"total_users":count(User), "enabled_users":count(User, User.is_active.is_(True)),
            "disabled_users":count(User, User.is_active.is_(False)),
            "admin_users":count(User, User.role == "admin"),
            "active_users_30d":db.query(func.count()).select_from(activity).scalar(),
            "material_count":count(LearningMaterial), "question_count":count(Question),
            "answer_count":count(QuestionAttempt)}


@router.get("/audit-logs")
def audit_logs(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
               db: Session = Depends(get_db)):
    actor, target = aliased(User), aliased(User)
    query = db.query(AdminAuditLog, actor.username, target.username).outerjoin(
        actor, actor.id == AdminAuditLog.actor_user_id).outerjoin(target, target.id == AdminAuditLog.target_user_id)
    total = query.count()
    rows = query.order_by(AdminAuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"total":total, "page":page, "page_size":page_size, "items":[{
        "id":log.id, "actor_user_id":log.actor_user_id, "actor_username":actor_name,
        "target_user_id":log.target_user_id, "target_username":target_name,
        "action":log.action, "result":log.result, "before_active":log.before_active,
        "after_active":log.after_active, "created_at":log.created_at.replace(tzinfo=timezone.utc).isoformat()
    } for log, actor_name, target_name in rows]}
