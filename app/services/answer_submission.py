"""Shared transactional grading for regular practice and coach sessions."""
from fastapi import HTTPException
from sqlalchemy import exists, select, update
from app.models import Question, QuestionAttempt, LearningMaterial, LearningRecord, Topic, User
from app.services.achievement import check_achievements
from app.services.topic_mastery import update_topic_mastery
from app.services.xp import calculate_level
from app.services.answer_feedback import local_answer_feedback


def record_answer(question_id, answer, current_user, db, *, commit=True):
    question = db.query(Question).filter(
        Question.id ==question_id
    ).first()

    if question is None:
        raise HTTPException(
            status_code=404,
            detail="题目不存在"
        )

    existing_attempt = db.query(QuestionAttempt).filter(
        QuestionAttempt.user_id == current_user.id,
        QuestionAttempt.question_id == question_id
    ).first()

    if existing_attempt is not None:
        raise HTTPException(
            status_code=400,
            detail="你已经回答过这个问题了"
        )

    material = db.query(LearningMaterial).filter(
        LearningMaterial.id == question.material_id,
        LearningMaterial.user_id == current_user.id
    ).first()

    if material is None:
        raise HTTPException(
            status_code=403,
            detail="无权回答该题目"
        )

    # Preserve legacy NULL-topic questions; do not guess their attribution.
    # Reject a broken non-NULL association before awarding XP or writing attempts.
    if question.topic_id is not None and db.query(Topic.id).filter_by(
        id=question.topic_id, material_id=question.material_id
    ).first() is None:
        raise HTTPException(status_code=409, detail="题目知识点关联无效，请联系管理员")

    is_correct = (
        answer == question.answer
    )

    earned_xp = 20 if is_correct else 0

    # Acquire SQLite's write reservation before checking NOT EXISTS. Serializes
    # XP and achievement decisions across workers without deleting old records.
    expected_version = current_user.auth_version
    acquired = db.execute(update(User).where(
        User.id == current_user.id, User.is_active.is_(True),
        User.auth_version == current_user.auth_version,
        ~exists(select(QuestionAttempt.id).where(
            QuestionAttempt.user_id == current_user.id,
            QuestionAttempt.question_id == question.id)),
    ).values(total_xp=User.total_xp + earned_xp,
             correct_streak=User.correct_streak + 1 if is_correct else 0)
        .execution_options(synchronize_session=False)).rowcount
    if not acquired:
        db.rollback()
        db.refresh(current_user)
        if not current_user.is_active:
            raise HTTPException(401, "账号已停用")
        if current_user.auth_version != expected_version:
            raise HTTPException(401, "登录已失效")
        raise HTTPException(400, "你已经回答过这个问题了或登录已失效")
    db.refresh(current_user)

    attempt = QuestionAttempt(
        user_id=current_user.id,
        question_id=question.id,
        user_answer=answer,
        is_correct=is_correct,
        earned_xp=earned_xp
    )

    db.add(attempt)
    db.flush()

    answer_count = db.query(QuestionAttempt).filter(
        QuestionAttempt.user_id == current_user.id
    ).count()
    new_achievements = check_achievements(
        user_id=current_user.id,
        db=db,
        answer_count=answer_count,
        correct_streak=current_user.correct_streak
    )
    for achievement in new_achievements:
        current_user.total_xp += achievement.xp_reward
    current_user.level = calculate_level(current_user.total_xp)

    if question.topic_id is not None:
        update_topic_mastery(
            user_id=current_user.id,
            topic_id=question.topic_id,
            db=db,
            commit=False,
        )

    learning_record = LearningRecord(
        user_id=current_user.id,
        content_type="question",
        content_id=question.id,
        study_time=0,
        progress=100
    )

    db.add(learning_record)
    if commit:
        db.commit()
    else:
        db.flush()

    return {
        "question_id":question.id,
        "user_answer":answer,
        "correct_answer":question.answer,
        "is_correct":is_correct,
        "explanation":question.explanation,
        "earned_xp":earned_xp,
        "feedback":local_answer_feedback(is_correct, question.explanation),
        "feedback_source":"local",
    }
