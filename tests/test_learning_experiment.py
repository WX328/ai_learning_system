"""Independent experiment workflow, allocation, leakage and missing data tests."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from evaluation.learning_experiment import (make_plan, next_item, record_decision,
    validate_bank, validate_records, analyze, load_records, write_records, write_analysis)


def bank():
    items = []
    for pool in ("A", "B", "learning"):
        for topic in ("topic-1", "topic-2"):
            for level in (range(1, 6) if pool == "learning" else (2, 3)):
                for repeat in range(3 if pool == "learning" else 1):
                    id = f"{pool}-{topic}-{level}-{repeat}"
                    items.append({"item_id": id, "topic_id": topic, "difficulty": level, "pool": pool,
                                  "content_hash": hashlib.sha256(id.encode()).hexdigest(), "family_id": id})
    return {"description": "Synthetic manifest only, not actual validated examination items", "items": items}


def plan(n=4):
    return make_plan(bank(), [f"P{i:02}" for i in range(n)], learning_steps=4, source="synthetic_experiment")


def complete_participant(p, records, code, *, pre_correct=True, learning_correct=True, post_correct=False):
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    while (decision := next_item(p, records, code))["status"] == "ready":
        correct = {"pre": pre_correct, "learning": learning_correct, "post": post_correct}[decision["phase"]]
        records = record_decision(p, records, decision, correct,
            timestamp=(timestamp+timedelta(minutes=decision["step"])).isoformat(), duration_seconds=30)
    return records


class LearningExperimentTest(unittest.TestCase):
    def test_assignment_is_repeatable_and_balanced_in_complete_blocks(self):
        p = plan(8)
        self.assertEqual(p, plan(8))
        for arm in ("fixed", "adaptive"):
            rows = [r for r in p["assignments"] if r["arm"] == arm]
            self.assertEqual(len(rows), 4)
            self.assertEqual(sum(r["pre_form"] == "A" for r in rows), 2)
        p = plan(2)
        self.assertEqual({r["arm"] for r in p["assignments"]}, {"fixed", "adaptive"})

    def test_reused_item_content_or_family_is_rejected(self):
        for key in ("item_id", "content_hash", "family_id"):
            bad = bank()
            bad["items"][-1][key] = bad["items"][0][key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_bank(bad)

    def test_unbalanced_forms_and_missing_levels_are_rejected(self):
        bad = bank()
        bad["items"].pop(0)
        with self.assertRaises(ValueError):
            validate_bank(bad)
        bad = bank()
        bad["items"] = [i for i in bad["items"] if not (i["pool"] == "learning" and i["difficulty"] == 5)]
        with self.assertRaises(ValueError):
            validate_bank(bad)

    def test_incomplete_records_never_invent_learning_gains(self):
        p = plan()
        report = analyze(p, [])
        self.assertEqual(sum(g["assigned"] for g in report["groups"].values()), 4)
        self.assertTrue(all(g["mean_gain"] is None for g in report["groups"].values()))
        self.assertIsNone(report["gain_difference"]["value"])
        self.assertIsNone(report["gain_difference"]["bootstrap_95_percentile"])

    def test_pretest_learning_posttest_are_sequential_and_disjoint(self):
        p = plan()
        code = p["assignments"][0]["participant_id"]
        records = complete_participant(p, [], code)
        phases = [r["phase"] for r in records]
        self.assertEqual(phases, ["pre"]*4+["learning"]*4+["post"]*4)
        self.assertEqual(len({r["item_id"] for r in records}), len(records))
        self.assertEqual(next_item(p, records, code)["status"], "complete")
        report = analyze(p, records)
        row = next(r for r in report["participants"] if r["participant_id"] == code)
        self.assertEqual(row["gain"], -1)
        self.assertIsNone(report["gain_difference"]["value"])

    def test_fixed_and_adaptive_modes_execute_their_respective_difficulty_policies(self):
        p = make_plan(bank(), [f"P{i}" for i in range(4)], learning_steps=6, source="synthetic_experiment")
        records = []
        for person in p["assignments"]:
            records = complete_participant(p, records, person["participant_id"], learning_correct=False)
        arms = {r["participant_id"]: r["arm"] for r in p["assignments"]}
        learning = [r for r in records if r["phase"] == "learning"]
        self.assertTrue(all(r["actual_difficulty"] == "2" for r in learning if arms[r["participant_id"]] == "fixed"))
        self.assertTrue(any(r["actual_difficulty"] == "1" for r in learning if arms[r["participant_id"]] == "adaptive"))

    def test_pretest_correctness_is_not_fed_into_learning(self):
        p = plan()
        code = p["assignments"][0]["participant_id"]
        left, right = [], []
        for i in range(4):
            for records, correct in ((left, True), (right, False)):
                d = next_item(p, records, code)
                updated = record_decision(p, records, d, correct,
                    timestamp=(datetime(2026, 1, 1, tzinfo=timezone.utc)+timedelta(minutes=i)).isoformat())
                records[:] = updated
        a, b = next_item(p, left, code), next_item(p, right, code)
        self.assertEqual(a["phase"], "learning")
        self.assertEqual((a["item_id"], a["requested_difficulty"]), (b["item_id"], b["requested_difficulty"]))

    def test_repeated_or_stale_decision_cannot_be_recorded(self):
        p = plan()
        code = p["assignments"][0]["participant_id"]
        decision = next_item(p, [], code)
        rows = record_decision(p, [], decision, True)
        with self.assertRaises(ValueError):
            record_decision(p, rows, decision, False)

    def test_record_tampering_wrong_phase_and_plan_changes_are_rejected(self):
        p = plan()
        code = p["assignments"][0]["participant_id"]
        rows = record_decision(p, [], next_item(p, [], code), True)
        for field, value in (("phase", "post"), ("correct", "yes"), ("item_id", "other"), ("actual_difficulty", "5")):
            changed = deepcopy(rows)
            changed[0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_records(p, changed)
        changed = deepcopy(p)
        changed["assignments"][0]["arm"] = "other"
        with self.assertRaises(ValueError):
            next_item(changed, [], code)

    def test_chronology_and_invalid_durations_are_rejected(self):
        p = plan()
        code = p["assignments"][0]["participant_id"]
        timestamp = "2026-01-01T00:00:00Z"
        rows = record_decision(p, [], next_item(p, [], code), True, timestamp=timestamp)
        with self.assertRaises(ValueError):
            record_decision(p, rows, next_item(p, rows, code), False, timestamp=timestamp)
        for value in (-1, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                record_decision(p, [], next_item(p, [], code), False, duration_seconds=value)

    def test_gain_estimate_and_participant_bootstrap_require_enough_complete_people(self):
        p = plan(4)
        rows = []
        for person in p["assignments"]:
            rows = complete_participant(p, rows, person["participant_id"], pre_correct=False,
                                        post_correct=person["arm"] == "adaptive")
        report = analyze(p, rows)
        self.assertIsNone(report["gain_difference"]["value"])
        exploratory = analyze(p, rows, minimum_per_arm=2)
        self.assertEqual(exploratory["gain_difference"]["value"], 1)
        self.assertEqual(exploratory["gain_difference"]["bootstrap_95_percentile"], [1, 1])
        self.assertEqual(exploratory["source"], "synthetic_experiment")
        self.assertEqual(exploratory, analyze(p, rows, minimum_per_arm=2))

    def test_csv_and_reports_roundtrip_with_no_production_tables(self):
        p = plan()
        code = p["assignments"][0]["participant_id"]
        records = complete_participant(p, [], code)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"records.csv"
            write_records(path, records)
            self.assertEqual(load_records(path), records)
            report = analyze(p, records)
            write_analysis(report, folder)
            self.assertIn("synthetic_experiment", (Path(folder)/"experiment.md").read_text(encoding="utf-8"))
            self.assertTrue((Path(folder)/"participants.csv").exists())

    def test_cli_plan_next_record_rejects_duplicate_and_releases_its_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/"bank.json").write_text(json.dumps(bank()), encoding="utf-8")
            (root/"people.json").write_text('["P1","P2"]', encoding="utf-8")

            def run(*args):
                return subprocess.run([sys.executable, "-m", "scripts.learning_experiment", *map(str, args)],
                                      capture_output=True, text=True, encoding="utf-8", errors="replace")

            result = run("plan", "--bank", root/"bank.json", "--participants", root/"people.json",
                "--source", "synthetic_experiment", "--learning-steps", 4, "--output-dir", root/"study")
            self.assertEqual(result.returncode, 0, result.stderr)
            common = ("--plan", root/"study/plan.json", "--records", root/"study/records.csv")
            result = run("next", *common, "--participant", "P1", "--output", root/"decision.json")
            self.assertEqual(result.returncode, 0, result.stderr)
            result = run("record", *common, "--decision", root/"decision.json", "--correct", 1)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = run("record", *common, "--decision", root/"decision.json", "--correct", 0)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(len(load_records(root/"study/records.csv")), 1)
            self.assertFalse((root/"study/records.csv.lock").exists())
            result = run("analyze", *common, "--output-dir", root/"report")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((root/"report/experiment.json").read_text())["gain_difference"]["status"], "not_evaluable")

    def test_cli_does_not_remove_another_writers_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            p = plan()
            (root/"plan.json").write_text(json.dumps(p), encoding="utf-8")
            write_records(root/"records.csv", [])
            lock = root/"records.csv.lock"
            lock.write_text("another writer", encoding="utf-8")
            result = subprocess.run([sys.executable, "-m", "scripts.learning_experiment", "record",
                "--plan", str(root/"plan.json"), "--records", str(root/"records.csv"),
                "--decision", str(root/"missing.json"), "--correct", "1"], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(lock.read_text(), "another writer")


if __name__ == "__main__":
    unittest.main()
