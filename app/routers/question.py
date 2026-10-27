from app.services.answer_submission import record_answer
import logging
from threading import BoundedSemaphore

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    User,
    LearningMaterial,
    Question,
    QuestionAttempt
)

from app.core.dependencies import get_current_user

from app.models.topic import Topic

from app.schemas.question import (
    QuestionGenerateRequest,
    QuestionResponse,
    QuestionAnswerRequest,
    QuestionAnswerResponse,
    QuestionFeedbackResponse,
)

from app.services.question_generator import (
    generate_question_from_material,
    save_generated_question
)

from app.services.answer_feedback import generate_answer_feedback, local_answer_feedback
from app.core.resource_limits import model_request_guard


router = APIRouter(
    prefix="/questions",
    tags=["Questions"]
)
logger = logging.getLogger(__name__)
generation_slots = BoundedSemaphore(2)

@router.post(
    "/generate",
    response_model=list[QuestionResponse], dependencies=[Depends(model_request_guard)]
)
def generate_question_api(
    request:QuestionGenerateRequest,
    current_user:User = Depends(get_current_user),
    db:Session = Depends(get_db)
):
    material = db.query(LearningMaterial).filter(
        LearningMaterial.id == request.material_id,
        LearningMaterial.user_id == current_user.id
    ).first()

    if material is None:
        raise HTTPException(
            status_code=404,
            detail="学习资料不存在或无权访问"
        )

    if request.topic_id is None:
        raise HTTPException(status_code=400, detail="请先提取并选择知识点，再生成练习")
    if request.topic_id is not None:
        topic = db.query(Topic).filter(
            Topic.id == request.topic_id,
            Topic.material_id == request.material_id,
        ).first()
        if topic is None:
            raise HTTPException(status_code=404, detail="知识点不存在或不属于该学习资料")

    if not generation_slots.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="出题任务较多，请稍后再试")
    try:
        generated = [generate_question_from_material(
            material_id=request.material_id,
            user_id=current_user.id,
            topic=request.topic,
            db=db,
            current_difficulty=request.difficulty,
            topic_id=request.topic_id,
        ) for _ in range(request.count)]
        questions = [save_generated_question(
            material_id=request.material_id,
            question_data=data,
            db=db,
            topic_id=request.topic_id,
            commit=False,
        ) for data in generated]
        db.commit()
        for question in questions:
            db.refresh(question)
        return questions
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    finally:
        generation_slots.release()

@router.post(
    "/{question_id}/answer",
    response_model=QuestionAnswerResponse
)
def answer_question(
    question_id:int,
    request:QuestionAnswerRequest,
    current_user:User = Depends(get_current_user),
    db:Session = Depends(get_db)
):
    return record_answer(question_id, request.answer, current_user, db)



@router.post("/{question_id}/feedback", response_model=QuestionFeedbackResponse, dependencies=[Depends(model_request_guard)])
def answer_feedback(
    question_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(QuestionAttempt, Question).join(
        Question, Question.id == QuestionAttempt.question_id
    ).join(
        LearningMaterial, LearningMaterial.id == Question.material_id
    ).filter(
        Question.id == question_id,
        QuestionAttempt.user_id == current_user.id,
        LearningMaterial.user_id == current_user.id,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="答题记录不存在")
    attempt, question = row
    if attempt.ai_feedback:
        return {"feedback": attempt.ai_feedback, "source": "ai"}
    try:
        feedback = generate_answer_feedback(
            question=question.question,
            options={
                "A": question.option_a, "B": question.option_b,
                "C": question.option_c, "D": question.option_d,
            },
            user_answer=attempt.user_answer,
            correct_answer=question.answer,
            explanation=question.explanation,
        )
    except Exception as exc:
        logger.warning("Answer feedback unavailable: %s", type(exc).__name__)
        return {"feedback": local_answer_feedback(attempt.is_correct, question.explanation),
                "source": "local"}
    attempt.ai_feedback = feedback
    db.commit()
    return {"feedback": feedback, "source": "ai"}
