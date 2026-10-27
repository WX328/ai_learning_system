"""Deterministic prescribed outcomes; NOT a learner or learning-effect simulator."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path


def make_fixture():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    topics, events = [], []
    for learner in range(1, 9):
        learner_id = f"sim-{learner:02}"
        sequences = {"improving": "00000111111111100000", "declining": "11111000000000011111",
                     "mixed": "10101" * 4}
        for topic, answers in sequences.items():
            topics.append({"learner_id": learner_id, "material_id": "sim-material", "topic_id": topic,
                           "available_at": start.isoformat()})
            for i, answer in enumerate(answers):
                order = i * 3 + list(sequences).index(topic)
                events.append({"id": f"{learner_id}-{topic}-{i:02}", "order": order,
                    "learner_id": learner_id, "material_id": "sim-material", "topic_id": topic,
                    "question_id": f"{learner_id}-{topic}-q{i:02}", "kind": "first",
                    "timestamp": (start + timedelta(days=learner, minutes=order)).isoformat(),
                    "difficulty": 1 + (learner-1) % 5, "correct": answer == "1"})
        # Repeated review is observed only after the first ten questions of this topic.
        for i in range(4):
            events.append({"id": f"{learner_id}-review-{i}", "order": 100+i,
                "learner_id": learner_id, "material_id": "sim-material", "topic_id": "improving",
                "question_id": f"{learner_id}-improving-q00", "kind": "review",
                "timestamp": (start+timedelta(days=learner, minutes=29, seconds=i+1)).isoformat(),
                "difficulty": 1 + (learner-1) % 5, "correct": True})
    return {"schema_version": 1, "source": {"kind": "synthetic",
        "description": "Eight scripted learners, improving/declining tracks with later reversal and mixed sequences; outcomes independent of recommendations",
        "generator": "generate_adaptive_fixture_v1; no randomness"}, "topics": topics, "events": events}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(make_fixture(), ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
