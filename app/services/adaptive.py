from types import SimpleNamespace

from app.models import QuestionAttempt, Question, Topic, LearningMaterial
from app.services.topic_mastery import (
    MASTERED_THRESHOLD, MIN_PROMOTION_SAMPLES, distinct_first_answers,
    get_material_topic_performance, get_topic_performance, mastery_priority,
)


def calculate_next_difficulty(correct_rate: float | None, current_difficulty: int):
    if correct_rate is not None:
        if correct_rate >= 0.8:
            current_difficulty += 1
        elif correct_rate < 0.5:
            current_difficulty -= 1
    return max(1, min(5, current_difficulty))


def explain_difficulty(correct_rate, sample_count, current_difficulty):
    """Same rule and explanation for preview, topic generation and evaluation."""
    current = max(1, min(5, current_difficulty))
    if correct_rate is None:
        return current, f"该知识点暂无答题记录，先从难度 {current}/5 开始。"
    prefix = f"最近 {sample_count} 道不同题目首次正确率 {correct_rate:.0%}。"
    if correct_rate >= 0.8 and sample_count < MIN_PROMOTION_SAMPLES:
        return current, prefix + f"升档至少需要 {MIN_PROMOTION_SAMPLES} 道不同题目的首次作答，当前保持难度 {current}/5。"
    difficulty = calculate_next_difficulty(correct_rate, current)
    if difficulty > current:
        reason = "达到 80% 且样本足够，提高一档"
    elif difficulty < current:
        reason = "低于 50%，降低一档以巩固基础"
    elif correct_rate >= 0.8:
        reason = "已在最高难度，保持"
    elif correct_rate < 0.5:
        reason = "已在最低难度，保持"
    else:
        reason = "处于 50%～80% 区间，保持"
    return difficulty, prefix + reason + f"（{difficulty}/5）。复习可改善掌握度，升档仍需不同题目的首次作答验证。"


def _recent_answers(user_id, db, limit=5, topic_id=None):
    query = (db.query(QuestionAttempt, Question).join(Question)
             .join(LearningMaterial, LearningMaterial.id == Question.material_id)
             .filter(QuestionAttempt.user_id == user_id, LearningMaterial.user_id == user_id))
    if topic_id is not None:
        query = query.join(Topic, (Topic.id == Question.topic_id) & (Topic.material_id == Question.material_id)).filter(Topic.id == topic_id)
    return distinct_first_answers(query.all())[:limit]


def get_recent_correct_rate(user_id: int, db, limit: int = 5):
    recent = _recent_answers(user_id, db, limit)
    return sum(a.is_correct for a, _ in recent) / len(recent) if recent else None


def get_next_difficulty(user_id: int, current_difficulty: int, db):
    recent = _recent_answers(user_id, db)
    rate = sum(a.is_correct for a, _ in recent) / len(recent) if recent else None
    return explain_difficulty(rate, len(recent), current_difficulty)[0]


def get_topic_recent_correct_rate(user_id: int, topic_id: int, db, limit: int = 5):
    recent = _recent_answers(user_id, db, limit, topic_id)
    return sum(a.is_correct for a, _ in recent) / len(recent) if recent else None


def get_next_topic_difficulty(user_id: int, topic_id: int, current_difficulty: int, db):
    performance = get_topic_performance(user_id, topic_id, db)
    return explain_difficulty(
        performance["recent_correct_rate"] if performance else None,
        performance["recent_attempt_count"] if performance else 0, current_difficulty,
    )[0]


def get_weak_topics(user_id: int, material_id: int, db, threshold: int = MASTERED_THRESHOLD):
    # Preserve the old (mastery attributes, topic) shape without reading stale
    # snapshots or inserting/updating ORM records during a recommendation read.
    rows = get_material_topic_performance(user_id, material_id, db)
    rows = sorted((r for r in rows if r["mastery_score"] is not None and r["mastery_score"] < threshold),
                  key=lambda r: mastery_priority(r["mastery_score"], r["attempt_count"], r["topic"].id))
    return [(SimpleNamespace(**{k:v for k,v in r.items() if k not in ("topic","attempts")},
                             correct_rate=r["historical_correct_rate"]), r["topic"]) for r in rows]


def get_weakest_topic(user_id: int, material_id: int, db, threshold: int = MASTERED_THRESHOLD):
    weak = get_weak_topics(user_id, material_id, db, threshold)
    if not weak:
        return None
    mastery, topic = weak[0]
    return {"topic_id":topic.id, "topic_name":topic.name, "mastery_score":mastery.mastery_score,
            "correct_rate":mastery.correct_rate, "attempt_count":mastery.attempt_count,
            "mastery_model":mastery.mastery_model, "mastery_reason":mastery.mastery_reason}


def generate_question_for_weakest_topic(
    user_id: int,
    material_id: int,
    db,
    current_difficulty: int = 2
):
    from app.services.question_generator import (
        generate_question_from_material,
        save_generated_question
    )

    recommendation = get_learning_recommendation(
        user_id=user_id,
        material_id=material_id,
        db=db,
        default_difficulty=current_difficulty,
    )

    if recommendation["topic"] is None:
        return None

    topic = recommendation["topic"]
    weakest_topic = {"topic_id": topic["id"], "topic_name": topic["name"],
                     "mastery_score": recommendation["mastery_score"],
                     "correct_rate": recommendation["recent_correct_rate"],
                     "attempt_count": recommendation["attempt_count"]}

    question_data = generate_question_from_material(
        material_id=material_id,
        user_id=user_id,
        topic=weakest_topic["topic_name"],
        db=db,
        current_difficulty=recommendation["recommended_difficulty"],
        topic_id=weakest_topic["topic_id"],
        adapt_difficulty=False,
    )

    # The requested level is authoritative even if the provider returns another.
    question_data.difficulty = recommendation["recommended_difficulty"]

    question = save_generated_question(
        material_id=material_id,
        question_data=question_data,
        db=db,
        topic_id=weakest_topic["topic_id"],
        is_adaptive=True
    )

    return {
        "topic": weakest_topic,
        "question": question
    }


def get_pending_adaptive_question(user_id: int, material_id: int, db):
    return (db.query(Question).join(Topic, Topic.id == Question.topic_id)
            .outerjoin(QuestionAttempt, (QuestionAttempt.question_id == Question.id)
                       & (QuestionAttempt.user_id == user_id))
            .filter(Question.material_id == material_id, Topic.material_id == material_id,
                    Question.is_adaptive.is_(True), QuestionAttempt.id.is_(None))
            .order_by(Question.id.desc()).first())


def get_learning_recommendation(user_id: int, material_id: int, db, default_difficulty: int = 2):
    """Read-only live assessment, shared with map, weak topics and coach."""
    default_difficulty = max(1, min(5, default_difficulty))
    performance = get_material_topic_performance(user_id, material_id, db)
    result = {"material_id":material_id, "topic":None, "mastery_score":None,
              "recent_correct_rate":None, "recent_attempt_count":0, "attempt_count":0,
              "current_difficulty":default_difficulty, "recommended_difficulty":default_difficulty,
              "has_history":False, "pending_question_id":None,
              "reason":"资料还没有知识点，请先在资料库整理知识点。"}
    if not performance:
        return result
    pending = get_pending_adaptive_question(user_id, material_id, db)
    selected = next((r for r in performance if pending and r["topic"].id == pending.topic_id), None)
    selected = selected or min(performance, key=lambda r: mastery_priority(
        r["mastery_score"], r["attempt_count"], r["topic"].id))
    topic, attempts = selected["topic"], selected["attempts"]
    current = max(1, min(5, attempts[0][1].difficulty if attempts else default_difficulty))
    difficulty, difficulty_reason = explain_difficulty(selected["recent_correct_rate"], selected["recent_attempt_count"], current)
    score = selected["mastery_score"]
    if score is None:
        topic_reason = "优先探索尚未评估的知识点，不将缺少记录视为薄弱。"
    elif score < MASTERED_THRESHOLD:
        topic_reason = f"优先巩固已练习知识点中掌握度较低的一项（{score}/100，低于阈值 80）。"
    else:
        topic_reason = "当前知识点均已达到 80 分掌握度，继续巩固。"
    if pending:
        difficulty = max(1, min(5, pending.difficulty))
        topic_reason = "已有一道未完成的自适应题目，优先继续原知识点。"
        difficulty_reason = f"沿用待答题难度 {difficulty}/5，完成后再按最新表现调整。"
    rate, historical = selected["recent_correct_rate"], selected["historical_correct_rate"]
    if rate is None:
        recent_reason = "暂无首次作答，尚不能判断近期趋势。"
    else:
        trend = "高于" if rate > historical else "低于" if rate < historical else "等于"
        recent_reason = (f"最近 {selected['recent_attempt_count']} 道首次正确率 {rate:.0%}，{trend}历史 {historical:.0%}；"
                         "最近证据占掌握度 30%，与历史窗口可能重叠，不增加不同题目数。")
    result.update({k:v for k,v in selected.items() if k not in ("topic","attempts")})
    result.update(topic={"id":topic.id, "name":topic.name},
                  current_difficulty=current, recommended_difficulty=difficulty,
                  has_history=bool(attempts), pending_question_id=pending.id if pending else None,
                  reason=topic_reason + difficulty_reason,
                  decision_reasons={"topic":topic_reason, "mastery":selected["mastery_reason"],
                                    "difficulty":difficulty_reason, "recent_performance":recent_reason})
    return result
