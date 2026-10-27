"""Actual-answer capture layered on S3 decisions; one atomic authoritative log."""
from copy import deepcopy
import csv
import hashlib
import hmac
import json
from pathlib import Path
import secrets

from evaluation.experiment_bank import validate_actual_bank, public_question
from evaluation.learning_experiment import (make_plan, next_item, record_decision,
    validate_records, analyze, write_analysis, write_records)
from evaluation.adaptive_replay import digest, time_value

SESSION_SCHEMA = "actual_answers_v1"


def create_study(root, bank, participants, *, source, seed=20261023, learning_steps=4, fixed_difficulty=2):
    if source not in {"demo_experiment", "real_experiment"}:
        raise ValueError("choose demo_experiment or real_experiment explicitly")
    plan = make_plan(bank, participants, source=source, seed=seed,
                     learning_steps=learning_steps, fixed_difficulty=fixed_difficulty)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    (root / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    state = {"schema_version": SESSION_SCHEMA, "plan_sha256": digest(plan), "observations": []}
    (root / "observations.json").write_text(json.dumps(state, indent=2)+"\n", encoding="utf-8")
    return plan


def records_from_observations(plan, state):
    if set(state) != {"schema_version", "plan_sha256", "observations"} or state["schema_version"] != SESSION_SCHEMA or state["plan_sha256"] != digest(plan):
        raise ValueError("observations do not match frozen study plan")
    items = {i["item_id"]: i for i in plan["bank"]["items"]}
    records = []
    for observation in state["observations"]:
        if set(observation) != {"record", "answer"}:
            raise ValueError("invalid observation")
        row, answer = observation["record"], observation["answer"]
        if answer not in {"A", "B", "C", "D"}:
            raise ValueError("invalid observed answer")
        if row["correct"] != str(int(answer == items[row["item_id"]]["answer"])):
            raise ValueError("observed answer disagrees with automatic grading")
        records.append(row)
    validate_records(plan, records)
    return records


def load_study(root):
    root = Path(root)
    plan = json.loads((root / "plan.json").read_text(encoding="utf-8"))
    validate_actual_bank(plan["bank"], require_approved=plan["source"] == "real_experiment")
    state = json.loads((root / "observations.json").read_text(encoding="utf-8"))
    return plan, state, records_from_observations(plan, state)


def show_next(root, participant):
    plan, _, records = load_study(root)
    decision = next_item(plan, records, participant)
    result = {"source": plan["source"], "decision": decision}
    if decision["status"] == "ready":
        result["question"] = public_question(plan["bank"], decision["item_id"])
    return result


def submit_answer(root, decision, answer, *, timestamp=None, duration_seconds=None):
    root = Path(root)
    lock = root / "observations.lock"
    try:
        handle = lock.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise ValueError("study writer is busy; inspect an abandoned lock before removing it") from exc
    temporary = root / "observations.json.tmp"
    temporary_created = False
    try:
        with handle:
            plan, state, records = load_study(root)
            if answer not in {"A", "B", "C", "D"}:
                raise ValueError("answer must be A, B, C or D")
            item = next((i for i in plan["bank"]["items"] if i["item_id"] == decision.get("item_id")), None)
            if item is None:
                raise ValueError("unknown question")
            updated = record_decision(plan, records, decision, answer == item["answer"],
                timestamp=timestamp, duration_seconds=duration_seconds)
            state["observations"].append({"record": updated[-1], "answer": answer})
            # Only one authoritative file changes. S3 CSV is a derived snapshot.
            with temporary.open("x", encoding="utf-8") as stream:
                temporary_created = True
                json.dump(state, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                import os
                os.fsync(stream.fileno())
            temporary.replace(root / "observations.json")
            response = {"saved": True, "phase": decision["phase"], "source": plan["source"]}
            if decision["phase"] == "learning":
                response.update(correct=answer == item["answer"], correct_answer=item["answer"], explanation=item["explanation"])
            return response
    finally:
        if temporary_created and temporary.exists():
            temporary.unlink()
        lock.unlink()


def progress(root):
    plan, _, records = load_study(root)
    result = []
    for assignment in plan["assignments"]:
        code = assignment["participant_id"]
        counts = {phase: sum(r["participant_id"] == code and r["phase"] == phase for r in records)
                  for phase in ("pre", "learning", "post")}
        total = plan["learning_steps"] + sum(i["pool"] in {"A", "B"} for i in plan["bank"]["items"])
        result.append({**assignment, "counts": counts, "answered": sum(counts.values()), "total": total,
                       "status": next_item(plan, records, code)["status"]})
    return {"source": plan["source"], "participants": result}


def export_study(root, output, *, minimum_per_arm=5):
    """Private S3 projection plus a separate pseudonymous shareable report."""
    plan, state, records = load_study(root)
    report = analyze(plan, records, minimum_per_arm=minimum_per_arm)
    report["grading"] = "Observed A-D choice automatically compared with frozen reviewed item key"
    report["limitations"] = [s for s in report["limitations"] if not s.startswith("Correctness is facilitator-recorded")]
    report["limitations"].append("Automatic grading cannot verify the correctness of an item key or equivalent test forms; human review remains necessary.")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    private = output / "private-s3"
    private.mkdir()
    (private / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    write_records(private / "records.csv", records)
    write_analysis(report, private / "analysis")
    key = secrets.token_bytes(32)
    def pseudonym(code):
        return "P-" + hmac.new(key, code.encode(), hashlib.sha256).hexdigest()[:24]
    public = output / "shareable"
    safe = deepcopy(report)
    for p in safe["participants"]:
        p["participant_id"] = pseudonym(p["participant_id"])
    safe["limitations"] += ["Pseudonymized export, not anonymous. No real identities should be stored in research codes.",
        "Demo data are software verification only; real_experiment is researcher declared, not proof of human participation."]
    write_analysis(safe, public)
    first = {}
    fields = ("participant_id", "phase", "correct", "actual_difficulty", "requested_difficulty", "elapsed_seconds", "duration_seconds")
    with (public / "events.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for r in records:
            code, when = r["participant_id"], time_value(r["timestamp"])
            first.setdefault(code, when)
            writer.writerow({**{k: r[k] for k in fields if k in r}, "participant_id": pseudonym(code),
                             "elapsed_seconds": (when-first[code]).total_seconds()})
    manifest = {"source": plan["source"], "protocol": plan["protocol"], "model": plan["production_model"],
        "bank_id": plan["bank"]["bank_id"], "bank_version": plan["bank"]["version"], "bank_sha256": plan["bank_sha256"],
        "plan_sha256": digest(plan), "records_sha256": digest(records), "observations_sha256": digest(state),
        "events_sha256": hashlib.sha256((public / "events.csv").read_bytes()).hexdigest(),
        "privacy": "Fresh HMAC pseudonyms per export; relative times; no answer choice, question text, original code or identity map",
        "evidence": "demonstration_only" if plan["source"] == "demo_experiment" else "researcher_declared_real_experiment"}
    (public / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return {"source": plan["source"], "groups": report["groups"], "gain_difference": report["gain_difference"],
            "shareable": str(public), "private_s3": str(private)}
