"""Shared, deterministic mastery baseline. Scores are rule indices, not probabilities.

Smoothing terms are regularizers, never counted as answered questions.
Reads recompute from evidence and never repair or trust the legacy cache.
"""
from datetime import datetime, timezone

from app.models import (LearningMaterial, TopicMastery, QuestionAttempt, Question,
                        ReviewAttempt, Topic)

MODEL_VERSION = "rules_v2"
MASTERED_THRESHOLD = 80
HISTORY_WEIGHT = 0.7
RECENT_WEIGHT = 0.3
REVIEW_WEIGHT = 0.3
RECENT_LIMIT = 5
MIN_PROMOTION_SAMPLES = 3


def _order(record):
    value = record.created_at
    value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return value, record.id


def distinct_first_answers(attempts):
    """Earliest answer per question, newest distinct question first."""
    first = {}
    for attempt, question in sorted(attempts, key=lambda pair: _order(pair[0])):
        first.setdefault(question.id, (attempt, question))
    return sorted(first.values(), key=lambda pair: _order(pair[0]), reverse=True)


def mastery_priority(score, count, topic_id):
    return (0 if score is not None and score < MASTERED_THRESHOLD else 1 if score is None else 2,
            score if score is not None else 0, count, topic_id)


def assess_topic(attempts, reviews=()):
    """Pure assessment from observed answers and bounded latest-review evidence.

    y = .7*first + .3*latest_review if reviewed, otherwise y = first.
    Success weight is .6+.2*d, failure weight is 1.6-.2*d for difficulty d.
    Component = (1+success)/(2+success+failure).
    Score = 100*(.7*all_questions + .3*last_five_first_questions).
    """
    attempts = distinct_first_answers(attempts)
    first_by_id = {q.id: a for a, q in attempts}
    latest = {}
    for review in sorted(reviews, key=_order):
        first = first_by_id.get(review.question_id)
        if first is not None and _order(review)[0] >= _order(first)[0]:
            latest[review.question_id] = review
    count = len(attempts)
    recent = attempts[:RECENT_LIMIT]
    historical_rate = sum(a.is_correct for a, _ in attempts) / count if count else None
    recent_rate = sum(a.is_correct for a, _ in recent) / len(recent) if recent else None
    difficulties = [max(1, min(5, q.difficulty)) for _, q in attempts]

    def component(rows):
        success = failure = 0.0
        for answer, question in rows:
            outcome = float(answer.is_correct)
            review = latest.get(question.id)
            if review is not None:
                outcome = (1 - REVIEW_WEIGHT) * outcome + REVIEW_WEIGHT * float(review.is_correct)
            difficulty = max(1, min(5, question.difficulty))
            success += outcome * (0.6 + 0.2 * difficulty)
            failure += (1 - outcome) * (1.6 - 0.2 * difficulty)
        return (1 + success) / (2 + success + failure)

    history_component = component(attempts) if count else None
    recent_component = component(recent) if count else None
    score = round(100 * (HISTORY_WEIGHT * history_component + RECENT_WEIGHT * recent_component)) if count else None
    status = "unseen" if score is None else "strong" if score >= MASTERED_THRESHOLD else "weak"
    result = {
        "mastery_model": MODEL_VERSION, "mastery_score": score, "mastery_status": status,
        "attempt_count": count, "historical_correct_rate": historical_rate,
        "recent_correct_rate": recent_rate, "recent_attempt_count": len(recent),
        "average_difficulty": round(sum(difficulties) / count, 2) if count else None,
        "sample_limited": count < RECENT_LIMIT,
        "reviewed_question_count": len(latest),
        "review_correct_count": sum(r.is_correct for r in latest.values()),
        "mastery_components": {
            "historical": round(history_component, 6) if count else None,
            "recent": round(recent_component, 6) if count else None,
            "historical_weight": HISTORY_WEIGHT, "recent_weight": RECENT_WEIGHT,
            "review_weight": REVIEW_WEIGHT, "smoothing_success": 1, "smoothing_failure": 1,
        },
    }
    if not count:
        reason = "该知识点暂无答题记录，掌握情况未知，不能据此判断薄弱。"
    else:
        state = "低于巩固阈值 80，仍需巩固" if status == "weak" else "达到规则阈值 80，可继续巩固或探索"
        reason = (f"规则掌握度 {score}/100，{state}。依据 {count} 道不同题目："
                  f"历史首次正确率 {historical_rate:.0%}，最近 {len(recent)} 道首次正确率 {recent_rate:.0%}，"
                  f"平均难度 {result['average_difficulty']:g}/5。历史证据占 70%，最近证据占 30%，"
                  "难题答对权重更高、答错惩罚更轻，并用平滑项抑制小样本极端分数。")
        if latest:
            reason += (f"已复习 {len(latest)} 道不同题目，其中最新复习答对 {result['review_correct_count']} 道；"
                       "复习最多占该题证据的 30%，不覆盖首次结果、不增加样本。")
        if result["sample_limited"]:
            reason += "不同题目少于 5 道，目前仅为初步评估。"
    result["mastery_reason"] = reason
    return result


def _get_performance(user_id, db, *, material_id=None, topic_id=None):
    topics_query = db.query(Topic).join(LearningMaterial).filter(LearningMaterial.user_id == user_id)
    if material_id is not None:
        topics_query = topics_query.filter(Topic.material_id == material_id)
    if topic_id is not None:
        topics_query = topics_query.filter(Topic.id == topic_id)
    topics = topics_query.order_by(Topic.id).all()
    if not topics:
        return []
    topic_ids = topics_query.with_entities(Topic.id)
    # Exclude malformed cross-material topic links and foreign user records.
    def scoped(query, model):
        return (query.join(Question, Question.id == model.question_id)
                .join(Topic, (Topic.id == Question.topic_id) & (Topic.material_id == Question.material_id))
                .filter(model.user_id == user_id, Topic.id.in_(topic_ids)))
    grouped = {topic.id: [] for topic in topics}
    for attempt, question in scoped(db.query(QuestionAttempt, Question), QuestionAttempt).all():
        grouped[question.topic_id].append((attempt, question))
    reviews = {topic.id: [] for topic in topics}
    for review, question in scoped(db.query(ReviewAttempt, Question), ReviewAttempt).all():
        reviews[question.topic_id].append(review)
    return [{"topic": topic, "attempts": distinct_first_answers(grouped[topic.id]),
             **assess_topic(grouped[topic.id], reviews[topic.id])} for topic in topics]


def get_material_topic_performance(user_id: int, material_id: int, db):
    return _get_performance(user_id, db, material_id=material_id)


def get_user_topic_performance(user_id: int, db):
    return _get_performance(user_id, db)


def get_topic_performance(user_id: int, topic_id: int, db):
    rows = _get_performance(user_id, db, topic_id=topic_id)
    return rows[0] if rows else None


def update_topic_mastery(user_id: int, topic_id: int, db, *, commit: bool = True):
    performance = get_topic_performance(user_id, topic_id, db)
    if performance is None or not performance["attempt_count"]:
        return None
    mastery = db.query(TopicMastery).filter_by(user_id=user_id, topic_id=topic_id).first()
    if mastery is None:
        mastery = TopicMastery(user_id=user_id, topic_id=topic_id)
        db.add(mastery)
    mastery.mastery_score = performance["mastery_score"]
    mastery.correct_rate = performance["historical_correct_rate"]
    mastery.attempt_count = performance["attempt_count"]
    mastery.updated_at = datetime.now(timezone.utc)
    if commit:
        db.commit()
    else:
        db.flush()
    db.refresh(mastery)
    return mastery
