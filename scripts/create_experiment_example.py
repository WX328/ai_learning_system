"""Create a SYNTHETIC manifest and an empty workflow example, not exam questions."""
import argparse
import hashlib
import json
from pathlib import Path

from evaluation.learning_experiment import make_plan, write_records, analyze, write_analysis


def example_bank():
    items = []
    for pool in ("A", "B", "learning"):
        for topic in ("demo-topic-1", "demo-topic-2"):
            for level in (range(1, 6) if pool == "learning" else (2, 3)):
                for repeat in range(6 if pool == "learning" else 1):
                    id = f"DEMO-{pool}-{topic}-{level}-{repeat}"
                    items.append({"item_id": id, "topic_id": topic, "difficulty": level,
                        "pool": pool, "content_hash": hashlib.sha256(id.encode()).hexdigest(), "family_id": id})
    return {"description": "SYNTHETIC metadata placeholders. No actual questions; replace with independently reviewed forms before real testing.", "items": items}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    bank = example_bank()
    participants = [f"DEMO-P{i:02}" for i in range(1, 9)]
    for name, data in (("bank.json", bank), ("participants.json", participants)):
        (args.output_dir/name).write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    plan = make_plan(bank, participants, source="synthetic_experiment")
    (args.output_dir/"plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    write_records(args.output_dir/"records.csv", [])
    write_analysis(analyze(plan, []), args.output_dir/"report")
    print("Synthetic workflow created with zero observations; no measured learning gains.")


if __name__ == "__main__":
    main()
