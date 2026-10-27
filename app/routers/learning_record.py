from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import LearningRecord, User, LearningMaterial, Question
from app.schemas.learning_record import LearningRecordCreate
from app.core.dependencies import get_current_user

router = APIRouter(
    prefix="/learning-records",
    tags=["学习记录"]
)

@router.post("")
def create_learning_record(
    record:LearningRecordCreate,
    current_user:User = Depends(get_current_user),
    db:Session = Depends(get_db)
):
    if record.content_id is not None:
        if record.content_type in {"material", "learning_material"}:
            owned = db.query(LearningMaterial.id).filter_by(id=record.content_id, user_id=current_user.id).first()
        elif record.content_type == "question":
            owned = db.query(Question.id).join(LearningMaterial).filter(
                Question.id == record.content_id, LearningMaterial.user_id == current_user.id).first()
        else:
            raise HTTPException(422, "不支持此学习内容类型")
        if owned is None:
            raise HTTPException(404, "学习内容不存在或无权访问")
    new_record = LearningRecord(
        user_id=current_user.id,
        content_type=record.content_type,
        content_id=record.content_id,
        study_time=record.study_time,
        progress=record.progress
    )

    db.add(new_record)
    db.commit()
    db.refresh(new_record)

    return{
        "id":new_record.id,
        "user_id":new_record.user_id,
        "content_type":new_record.content_type,
        "content_id":new_record.content_id,
        "study_time":new_record.study_time,
        "progress":new_record.progress,
        "created_at":new_record.created_at
    }

@router.get("")
def get_my_learning_records(
    current_user:User = Depends(get_current_user),
    db:Session = Depends(get_db)
):
    records = db.query(LearningRecord).filter(
        LearningRecord.user_id ==current_user.id
    ).all()

    return records
