"""Offline prequential comparison. No DB sessions, model calls or policy changes.

All predictions for a timestamp are frozen before any outcome at that timestamp
is applied. Future outcomes enter only the separate evaluation pass.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import itertools
import json
from pathlib import Path
from statistics import mean
from types import SimpleNamespace as Item

from app.services.adaptive import calculate_next_difficulty, explain_difficulty
from app.services.topic_mastery import assess_topic, mastery_priority, MODEL_VERSION

VERSION = "adaptive_eval_v1"
ALGORITHMS = ("raw_accuracy_v1", "recent5_accuracy_v1", MODEL_VERSION)
SOURCES = {"synthetic", "real_history"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


def time_value(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be an ISO8601 string with timezone")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp requires timezone")
    return result.astimezone(timezone.utc)


def check_id(value):
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValueError("IDs must be nonempty strings of at most 128 characters")
    return value


def validate_dataset(data):
    if data.get("schema_version") != 1 or data.get("source", {}).get("kind") not in SOURCES:
        raise ValueError("schema_version=1 and explicit synthetic/real_history source required")
    topics, event_ids, questions = {}, set(), {}
    for topic in data["topics"]:
        key = tuple(check_id(topic[k]) for k in ("learner_id", "material_id", "topic_id"))
        if key in topics:
            raise ValueError("duplicate topic")
        topics[key] = time_value(topic["available_at"])
    events = []
    for raw in data["events"]:
        e = dict(raw)
        for key in ("id", "learner_id", "material_id", "topic_id", "question_id"):
            check_id(e[key])
        if e["id"] in event_ids:
            raise ValueError("duplicate event ID")
        event_ids.add(e["id"])
        if e["kind"] not in {"first", "review"} or type(e["correct"]) is not bool:
            raise ValueError("invalid event kind or boolean correct")
        if type(e["difficulty"]) is not int or not 1 <= e["difficulty"] <= 5:
            raise ValueError("difficulty must be integer 1..5")
        if type(e.get("order", 0)) is not int:
            raise ValueError("event order must be integer")
        e["_time"] = time_value(e["timestamp"])
        key = (e["learner_id"], e["material_id"], e["topic_id"])
        if key not in topics or topics[key] > e["_time"]:
            raise ValueError("event has no available topic")
        question_key = (e["learner_id"], e["question_id"])
        identity = (e["material_id"], e["topic_id"], e["difficulty"])
        if question_key in questions and questions[question_key] != identity:
            raise ValueError("question changed material/topic/difficulty")
        questions[question_key] = identity
        events.append(e)
    return topics, sorted(events, key=lambda e: (e["_time"], e.get("order", 0), e["id"]))


def assess(history, reviews, algorithm):
    """Use the actual production S2 calculator; baselines use first answers only."""
    if algorithm == MODEL_VERSION:
        pairs = [(Item(id=i, question_id=e["question_id"], is_correct=e["correct"],
                       created_at=e["_time"]),
                  Item(id=e["question_id"], difficulty=e["difficulty"]))
                 for i, e in enumerate(history)]
        rs = [Item(id=i, question_id=e["question_id"], is_correct=e["correct"],
                   created_at=e["_time"]) for i, e in enumerate(reviews)]
        score = assess_topic(pairs, rs)["mastery_score"]
    else:
        rows = history[-5:] if algorithm == ALGORITHMS[1] else history
        score = 100 * mean(e["correct"] for e in rows) if rows else None
    recent = history[-5:]
    rate = mean(e["correct"] for e in recent) if recent else None
    current = history[-1]["difficulty"] if history else 2
    if algorithm == MODEL_VERSION:
        difficulty = explain_difficulty(rate, len(recent), current)[0]
    else:
        rows = history if algorithm == ALGORITHMS[0] else recent
        rate = mean(e["correct"] for e in rows) if rows else None
        difficulty = calculate_next_difficulty(rate, current)
    return {"score": score, "count": len(history), "current_difficulty": current,
            "difficulty": difficulty}


def measured(value, n, learners, minimum, min_learners):
    enough = n >= minimum and learners >= min_learners
    return {"value": round(value, 6) if enough and value is not None else None,
            "n": n, "learners": learners, "status": "descriptive" if enough else "not_evaluable",
            "reason": None if enough else f"requires n>={minimum} and learners>={min_learners}"}


def _auc(rows):
    positives = sum(r[1] for r in rows)
    negatives = len(rows) - positives
    if not positives or not negatives:
        return None
    rank_sum, offset = 0.0, 0
    for _, group in itertools.groupby(sorted(rows, key=lambda r: r[0]), key=lambda r: r[0]):
        group = list(group)
        average_rank = (offset + 1 + offset + len(group)) / 2
        rank_sum += average_rank * sum(r[1] for r in group)
        offset += len(group)
    return (rank_sum - positives * (positives + 1) / 2) / (positives * negatives)


def replay(data, *, min_predictions=20, min_learners=2, min_history=3,
           horizon=10, min_future_per_topic=2):
    for value in (min_predictions, min_learners, min_history, horizon, min_future_per_topic):
        if type(value) is not int or value < 1:
            raise ValueError("evaluation limits must be positive integers")
    topics, events = validate_dataset(data)
    history, reviews, seen = defaultdict(list), defaultdict(list), set()
    traces, ignored, snapshots = [], Counter(), defaultdict(list)
    catalog = defaultdict(list)
    for (learner, material, topic), available in topics.items():
        catalog[learner, material].append((topic, available))
    for timestamp, group in itertools.groupby(events, key=lambda e: e["_time"]):
        batch = list(group)
        accepted, batch_seen = [], set()
        for event in batch:
            qkey = (event["learner_id"], event["question_id"])
            if event["kind"] == "first":
                if qkey in seen or qkey in batch_seen:
                    ignored["duplicate_first"] += 1
                else:
                    accepted.append(event)
                    batch_seen.add(qkey)
        # No answers/reviews from batch have been added at this point.
        for event in accepted:
            learner, material, topic = (event[k] for k in ("learner_id", "material_id", "topic_id"))
            trace = {k: event[k] for k in ("id", "learner_id", "material_id", "topic_id",
                                         "question_id", "timestamp", "difficulty", "correct")}
            trace["algorithms"] = {}
            for algorithm in ALGORITHMS:
                states = {}
                for candidate, available in catalog[learner, material]:
                    if available <= timestamp:
                        key = learner, material, candidate
                        states[candidate] = assess(history[key], reviews[key], algorithm)
                ranking = sorted(states, key=lambda t: mastery_priority(
                    states[t]["score"], states[t]["count"], t))
                selected = ranking[0]
                trace["algorithms"][algorithm] = {
                    **states[topic], "ranking": ranking,
                    "ranking_scores": {t: states[t]["score"] for t in ranking},
                    "selected_topic": selected, "selected_difficulty": states[selected]["difficulty"]}
            traces.append(trace)
        # Apply all first answers, then eligible reviews; visible only next timestamp.
        for event in accepted:
            key = tuple(event[k] for k in ("learner_id", "material_id", "topic_id"))
            history[key].append(event)
            seen.add((event["learner_id"], event["question_id"]))
        for event in batch:
            if event["kind"] == "review":
                if (event["learner_id"], event["question_id"]) not in seen:
                    ignored["orphan_or_early_review"] += 1
                else:
                    key = tuple(event[k] for k in ("learner_id", "material_id", "topic_id"))
                    reviews[key].append(event)
        changed_keys = {tuple(event[k] for k in ("learner_id", "material_id", "topic_id")) for event in accepted}
        for key in sorted(changed_keys):
            snapshots[key].append({"count": len(history[key]),
                "recent_rate": mean(e["correct"] for e in history[key][-5:]),
                "scores": {a: assess(history[key], reviews[key], a)["score"] for a in ALGORITHMS}})
    metrics = _evaluate(traces, snapshots, min_predictions, min_learners,
                        min_history, horizon, min_future_per_topic)
    summary = {"evaluation_version": VERSION, "production_model": MODEL_VERSION,
        "dataset_sha256": digest(data), "source": data["source"],
        "implementation_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in (
            ("replay", Path(__file__)),
            ("mastery", Path(__file__).resolve().parents[1]/"app/services/topic_mastery.py"),
            ("adaptive", Path(__file__).resolve().parents[1]/"app/services/adaptive.py"))},
        "config": {"min_predictions": min_predictions, "min_learners": min_learners,
                   "min_history": min_history, "ranking_horizon": horizon,
                   "min_future_per_topic": min_future_per_topic,
                   "same_timestamp": "all decisions before all outcomes"},
        "samples": {"input_events": len(events), "first_answers": len(traces),
                    "review_events": sum(e["kind"] == "review" for e in events),
                    "learners": len({e["learner_id"] for e in events}),
                    "observed_topics": len({(e["learner_id"], e["material_id"], e["topic_id"]) for e in traces}),
                    "catalog_topics": len(topics), "ignored": dict(ignored)},
        "algorithms": metrics,
        "limitations": ["Fixed logged actions: counterfactual learning gains are not identifiable.",
            "rules_v2 score/100 is an uncalibrated score proxy, not an estimated ability probability.",
            "Overlapping checkpoints and answers within a learner are correlated.",
            "Future failure rates are observed proxies affected by item difficulty and selection.",
            "No historical pending-question/recommendation logs; evaluate fresh decisions only.",
            "Synthetic results validate rules only; real_history is observational, not a randomized trial."]}
    return summary, traces


def _evaluate(traces, snapshots, minimum, min_learners, min_history, horizon, future_min):
    groups = defaultdict(list)
    for t in traces:
        groups[t["learner_id"], t["material_id"]].append(t)
    output = {}
    for algorithm in ALGORITHMS:
        eligible = [(t["algorithms"][algorithm]["score"] / 100, int(t["correct"]), t["learner_id"])
                    for t in traces if t["algorithms"][algorithm]["count"] >= min_history]
        learners = len({r[2] for r in eligible})
        brier = mean((s-y)**2 for s, y, _ in eligible) if eligible else None
        prediction = measured(brier, len(eligible), learners, minimum, min_learners)
        auc_value = _auc(eligible)
        auc = measured(auc_value, len(eligible), learners, minimum, min_learners)
        if auc_value is None:
            auc.update(value=None, status="not_evaluable", reason="requires both correct and incorrect outcomes")
        ranking_pairs, ranking_learners = [], set()
        for group in groups.values():
            for index, t in enumerate(group):
                # Outcomes strictly later than this checkpoint. Nothing feeds back into predictions.
                future = [r for r in group[index+1:] if time_value(r["timestamp"]) > time_value(t["timestamp"])][:horizon]
                outcomes = defaultdict(list)
                for r in future:
                    outcomes[r["topic_id"]].append(int(r["correct"]))
                scores = t["algorithms"][algorithm]["ranking_scores"]
                candidates = [k for k, v in outcomes.items() if len(v) >= future_min and scores.get(k) is not None]
                for left, right in itertools.combinations(candidates, 2):
                    # Lower mastery should precede lower future success; exclude tied outcomes.
                    actual = mean(outcomes[left]) - mean(outcomes[right])
                    if actual == 0:
                        continue
                    predicted = scores[left] - scores[right]
                    ranking_pairs.append(.5 if predicted == 0 else float(predicted * actual > 0))
                    ranking_learners.add(t["learner_id"])
        trend = []
        for key, rows in snapshots.items():
            # Non-overlapping five-answer blocks, exact counts only (same-time batches may skip a checkpoint).
            by_count = {r["count"]: r for r in rows}
            for count in range(10, max(by_count, default=0)+1, 5):
                previous, current = by_count.get(count-5), by_count.get(count)
                if previous and current:
                    change = current["recent_rate"] - previous["recent_rate"]
                    if abs(change) >= .2 - 1e-9:
                        delta = current["scores"][algorithm] - previous["scores"][algorithm]
                        trend.append({"learner": key[0], "direction": "improving" if change > 0 else "declining",
                                      "score_change": delta, "responded": delta * change > 0})
        small = [t["algorithms"][algorithm] for t in traces if 1 <= t["algorithms"][algorithm]["count"] < 3]
        early = sum(s["difficulty"] > s["current_difficulty"] for s in small)
        scores = [r["scores"][algorithm] for rows in snapshots.values() for r in rows if r["count"] <= 4]
        jumps = [abs(b["scores"][algorithm] - a["scores"][algorithm])
                 for rows in snapshots.values() for a, b in zip(rows, rows[1:])
                 if 1 <= a["count"] < b["count"] <= 4]
        output[algorithm] = {
            "score_proxy_brier": prediction, "score_auc": auc,
            "ranking_pairwise_concordance": measured(mean(ranking_pairs) if ranking_pairs else None,
                len(ranking_pairs), len(ranking_learners), minimum, min_learners),
            "trend_direction_response": measured(mean(r["responded"] for r in trend) if trend else None,
                len(trend), len({r["learner"] for r in trend}), minimum, min_learners),
            "trend_score_change": {d: {"n": len(rows := [r for r in trend if r["direction"] == d]),
                "mean": round(mean(r["score_change"] for r in rows), 6) if rows else None}
                for d in ("improving", "declining")},
            "small_sample": {"n": len(scores), "extreme_score_fraction": mean(s in (0, 100) for s in scores) if scores else None,
                "jump_pairs": len(jumps), "mean_absolute_score_jump": mean(jumps) if jumps else None,
                "promotion_decisions_n": len(small), "early_promotions": early,
                "early_promotion_fraction": early / len(small) if small else None},
            "difficulty": {"n": len(traces),
                "up": sum(t["algorithms"][algorithm]["difficulty"] > t["algorithms"][algorithm]["current_difficulty"] for t in traces),
                "down": sum(t["algorithms"][algorithm]["difficulty"] < t["algorithms"][algorithm]["current_difficulty"] for t in traces),
                "out_of_bounds": sum(not 1 <= t["algorithms"][algorithm]["difficulty"] <= 5 for t in traces)},
            "cold_start_decisions": sum(t["algorithms"][algorithm]["count"] == 0 for t in traces)}
    return output
