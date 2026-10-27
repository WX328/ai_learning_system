
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.core.dependencies import get_current_user
from app.core.resource_limits import model_request_guard
from app.models.learning_material import LearningMaterial
from app.services.adaptive import (
    generate_question_for_weakest_topic, get_learning_recommendation,
    get_pending_adaptive_question,
)

router = APIRouter(
    prefix="/adaptive",
    tags=["自适应学习"]
)


def require_owned_material(material_id: int, user_id: int, db):
    material = db.query(LearningMaterial).filter(
        LearningMaterial.id == material_id, LearningMaterial.user_id == user_id
    ).first()
    if material is None:
        raise HTTPException(404, "学习资料不存在或无权访问")
    return material


@router.get("/recommendation")
def recommendation(
    material_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_owned_material(material_id, current_user.id, db)
    return get_learning_recommendation(current_user.id, material_id, db)


@router.get("/next-question", dependencies=[Depends(model_request_guard)])
def get_next_question(
    material_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    require_owned_material(material_id, current_user.id, db)


    # ==============================
    # 1. 查找当前用户未完成的自适应题目
    # ==============================
    existing_question = get_pending_adaptive_question(current_user.id, material_id, db)

    # ==============================
    # 2. 如果已经有未完成的题目，直接返回
    # ==============================
    if existing_question is not None:

        preview = get_learning_recommendation(current_user.id, material_id, db)

        return {
            "topic": {
                **preview["topic"],
                "mastery_score": preview["mastery_score"],
                "correct_rate": preview["recent_correct_rate"],
                "attempt_count": preview["attempt_count"],
            },
            "question": {
                "id": existing_question.id,
                "material_id": existing_question.material_id,
                "topic_id": existing_question.topic_id,
                "question_type": existing_question.question_type,
                "question": existing_question.question,
                "option_a": existing_question.option_a,
                "option_b": existing_question.option_b,
                "option_c": existing_question.option_c,
                "option_d": existing_question.option_d,
                "difficulty": existing_question.difficulty
            }
        }

    # ==============================
    # 3. 没有未完成题目 → 生成新题
    # ==============================
    try:
        result = generate_question_for_weakest_topic(
            user_id=current_user.id,
            material_id=material_id,
            db=db
        )

    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )

    # ==============================
    # 4. 没有薄弱知识点
    # ==============================
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="当前资料没有知识点，请先整理知识点"
        )

    topic = result["topic"]
    question = result["question"]

    # ==============================
    # 5. 返回新生成的题目
    # ==============================
    return {
        "topic": {
            "id": topic["topic_id"],
            "name": topic["topic_name"],
            "mastery_score": topic["mastery_score"],
            "correct_rate": topic["correct_rate"],
            "attempt_count": topic["attempt_count"]
        },
        "question": {
            "id": question.id,
            "material_id": question.material_id,
            "topic_id": question.topic_id,
            "question_type": question.question_type,
            "question": question.question,
            "option_a": question.option_a,
            "option_b": question.option_b,
            "option_c": question.option_c,
            "option_d": question.option_d,
            "difficulty": question.difficulty
        }
    }
