"""Deterministic SOFTWARE DEMONSTRATION. No human participants or model calls."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from evaluation.experiment_session import (create_study, show_next, submit_answer,
    progress, export_study, load_study)
from evaluation.learning_experiment import load_records, analyze
from scripts.create_review_bank import draft_bank


def verify(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    study = output / "study"
    codes = [f"DEMO-{i:02}" for i in range(1, 5)]
    create_study(study, draft_bank(), codes, source="demo_experiment", learning_steps=4)
    checks = {"pre_post_feedback_hidden": True, "learning_feedback_present": True}
    for code in codes:
        step = 0
        while (display := show_next(study, code))["decision"]["status"] == "ready":
            decision = display["decision"]
            if set(display["question"]) != {"item_id", "stem", "options"}:
                raise AssertionError("answer disclosed in participant display")
            step += 1
            response = submit_answer(study, decision, "ABCD"[(step-1) % 4], duration_seconds=1,
                timestamp=(datetime(2026, 1, 1, tzinfo=timezone.utc)+timedelta(seconds=step)).isoformat())
            if decision["phase"] == "learning":
                checks["learning_feedback_present"] &= "explanation" in response
            else:
                checks["pre_post_feedback_hidden"] &= set(response) == {"saved", "source", "phase"}
    plan, _, records = load_study(study)
    result = export_study(study, output / "export")
    projected = load_records(Path(result["private_s3"]) / "records.csv")
    checks["s3_roundtrip_identical"] = analyze(plan, projected) == analyze(plan, records)
    state = progress(study)
    checks["all_phases_complete"] = all(p["status"] == "complete" and p["answered"] == p["total"] == 12 for p in state["participants"])
    checks["both_arms_present"] = {p["arm"] for p in plan["assignments"]} == {"fixed", "adaptive"}
    if not all(checks.values()):
        raise AssertionError(checks)
    report = {"source": "demo_experiment", "purpose": "software_e2e_verification_only", "real_human_participants": 0,
        "scripted_research_codes": len(codes), "scripted_answers": len(records), "question_items": len(plan["bank"]["items"]),
        "model_calls": 0, "production_database_access": False, "checks": checks,
        "inference_status": result["gain_difference"]["status"],
        "limitations": "Scripted A/B/C/D input and artificial clock. Neither real experimental scores nor evidence of learning improvement."}
    (output / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.output_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
