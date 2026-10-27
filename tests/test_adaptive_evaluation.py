"""Temporal leakage, metric denominators, privacy and export safety on disposable data."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from evaluation.adaptive_replay import ALGORITHMS, replay, validate_dataset, _auc
from scripts.evaluate_adaptive import write_report
from scripts.export_learning_history import export_history
from scripts.generate_adaptive_fixture import make_fixture

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def dataset(answers="10101", *, times=None):
    return {"schema_version": 1, "source": {"kind": "synthetic", "description": "test"},
        "topics": [{"learner_id": "L", "material_id": "M", "topic_id": "T", "available_at": START.isoformat()}],
        "events": [{"id": f"f-{i:03}", "order": i, "learner_id": "L", "material_id": "M", "topic_id": "T",
                    "question_id": f"q-{i}", "kind": "first", "timestamp": (START+timedelta(minutes=i+1)).isoformat() if times is None else times[i],
                    "difficulty": 2, "correct": value == "1"} for i, value in enumerate(answers)]}


class AdaptiveReplayTest(unittest.TestCase):
    def test_empty_dataset_has_unknown_metrics_not_zero(self):
        report, traces = replay(dataset(""))
        self.assertEqual(traces, [])
        for metrics in report["algorithms"].values():
            self.assertIsNone(metrics["score_proxy_brier"]["value"])
            self.assertIsNone(metrics["ranking_pairwise_concordance"]["value"])

    def test_prediction_is_frozen_before_current_answer(self):
        a = dataset("11110")
        b = deepcopy(a)
        b["events"][-1]["correct"] = True
        _, left = replay(a)
        _, right = replay(b)
        self.assertEqual([r["algorithms"] for r in left], [r["algorithms"] for r in right])

    def test_appending_future_answers_and_reviews_cannot_change_prefix(self):
        short = dataset("010")
        long = dataset("010111")
        review = {**long["events"][0], "id": "review", "kind": "review", "correct": True,
                  "timestamp": (START+timedelta(days=1)).isoformat()}
        long["events"].append(review)
        _, before = replay(short)
        _, after = replay(long)
        self.assertEqual(before, after[:len(before)])

    def test_same_timestamp_answers_do_not_see_each_other(self):
        same = (START+timedelta(minutes=1)).isoformat()
        _, traces = replay(dataset("10", times=[same, same]))
        for trace in traces:
            for state in trace["algorithms"].values():
                self.assertIsNone(state["score"])
                self.assertEqual(state["count"], 0)

    def test_same_timestamp_review_is_not_available_to_decision(self):
        data = dataset("00")
        data["events"].append({**data["events"][0], "id": "review", "kind": "review", "correct": True,
            "timestamp": data["events"][1]["timestamp"]})
        _, traces = replay(data)
        self.assertEqual(traces[1]["algorithms"]["rules_v2"]["score"], 31)

    def test_future_topic_cannot_enter_current_ranking(self):
        data = dataset("11")
        data["topics"].append({**data["topics"][0], "topic_id": "future", "available_at": (START+timedelta(days=1)).isoformat()})
        _, traces = replay(data)
        self.assertTrue(all(a["ranking"] == ["T"] for t in traces for a in t["algorithms"].values()))

    def test_duplicate_first_keeps_earliest_and_sample_count(self):
        data = dataset("00")
        data["events"].append({**data["events"][0], "id": "duplicate", "correct": True,
                              "timestamp": (START+timedelta(seconds=90)).isoformat()})
        report, traces = replay(data)
        self.assertEqual(report["samples"]["ignored"], {"duplicate_first": 1})
        self.assertEqual(traces[1]["algorithms"]["rules_v2"]["score"], 31)

    def test_orphan_review_does_not_create_evidence(self):
        data = dataset("00")
        data["events"].append({**data["events"][0], "id": "review", "kind": "review", "correct": True,
                              "timestamp": (START+timedelta(seconds=30)).isoformat()})
        report, traces = replay(data)
        self.assertEqual(report["samples"]["ignored"]["orphan_or_early_review"], 1)
        self.assertEqual(traces[1]["algorithms"]["rules_v2"]["score"], 31)

    def test_timezone_order_is_chronological_not_string_order(self):
        data = dataset("10", times=["2026-01-01T08:01:00+08:00", "2026-01-01T00:02:00Z"])
        data["events"].reverse()
        _, traces = replay(data)
        self.assertEqual(traces[0]["id"], "f-000")
        self.assertEqual(traces[1]["algorithms"]["raw_accuracy_v1"]["score"], 100)

    def test_brier_proxy_hand_calculation_and_auc_single_class(self):
        report, _ = replay(dataset("10"), min_history=1, min_predictions=1, min_learners=1)
        self.assertEqual(report["algorithms"]["raw_accuracy_v1"]["score_proxy_brier"]["value"], 1)
        self.assertAlmostEqual(report["algorithms"]["rules_v2"]["score_proxy_brier"]["value"], .67**2)
        self.assertIsNone(report["algorithms"]["rules_v2"]["score_auc"]["value"])
        self.assertEqual(_auc([(.5, 1), (.5, 0)]), .5)

    def test_insufficient_learner_gate_does_not_emit_accuracy(self):
        report, _ = replay(dataset("10"*30))
        metric = report["algorithms"]["rules_v2"]["score_proxy_brier"]
        self.assertGreater(metric["n"], 20)
        self.assertIsNone(metric["value"])
        self.assertIn("learners>=2", metric["reason"])

    def test_raw_and_recent_baselines_diverge_and_s2_matches_real_service(self):
        _, traces = replay(dataset("00000111111"))
        states = traces[-1]["algorithms"]
        self.assertEqual(states["raw_accuracy_v1"]["score"], 50)
        self.assertEqual(states["recent5_accuracy_v1"]["score"], 100)
        self.assertEqual(states["rules_v2"]["score"], 58)

    def test_fixture_has_reproducible_rules_and_explicit_source(self):
        report, traces = replay(make_fixture())
        self.assertEqual((report, traces), replay(make_fixture()))
        self.assertEqual(report["source"]["kind"], "synthetic")
        self.assertEqual(report["samples"]["first_answers"], 480)
        self.assertEqual(report["algorithms"]["rules_v2"]["small_sample"]["early_promotions"], 0)
        self.assertGreater(report["algorithms"]["raw_accuracy_v1"]["small_sample"]["early_promotions"], 0)
        for a in ALGORITHMS:
            self.assertEqual(report["algorithms"][a]["difficulty"]["out_of_bounds"], 0)
            trend = report["algorithms"][a]["trend_score_change"]
            self.assertGreater(trend["improving"]["mean"], 0)
            self.assertLess(trend["declining"]["mean"], 0)

    def test_prospective_ranking_uses_later_distinct_questions_as_labels(self):
        data = dataset("101010101010")
        data["topics"].append({**data["topics"][0], "topic_id": "other"})
        for event in data["events"]:
            if not event["correct"]:
                event["topic_id"] = "other"
        report, traces = replay(data, min_predictions=1, min_learners=1)
        for algorithm in ALGORITHMS:
            metric = report["algorithms"][algorithm]["ranking_pairwise_concordance"]
            self.assertGreater(metric["n"], 0)
            self.assertEqual(metric["value"], 1)
        self.assertEqual(traces[2]["algorithms"]["rules_v2"]["selected_topic"], "other")

    def test_validation_rejects_malformed_ids_outcomes_times_and_difficulty(self):
        for field, value in (("difficulty", 0), ("difficulty", True), ("correct", 1), ("kind", "anything"),
                             ("timestamp", "2026-01-01"), ("topic_id", "missing")):
            data = dataset("1")
            data["events"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_dataset(data)
        data = dataset("1")
        data["source"]["kind"] = "unknown"
        with self.assertRaises(ValueError):
            replay(data)

    def test_changed_question_identity_is_rejected(self):
        data = dataset("10")
        data["events"][1]["question_id"] = data["events"][0]["question_id"]
        data["events"][1]["difficulty"] = 3
        with self.assertRaises(ValueError):
            replay(data)

    def test_artifacts_are_reproducible_and_csv_has_three_rows_per_decision(self):
        report, traces = replay(dataset("10101"))
        with tempfile.TemporaryDirectory() as folder:
            write_report(report, traces, folder)
            files = ("report.json", "report.md", "decisions.csv")
            first = {name: (Path(folder)/name).read_bytes() for name in files}
            write_report(report, traces, folder)
            self.assertEqual(first, {name: (Path(folder)/name).read_bytes() for name in files})
            self.assertEqual(len((Path(folder)/"decisions.csv").read_text(encoding="utf-8-sig").splitlines()), 16)


class ReadOnlyExportTest(unittest.TestCase):
    def test_export_scopes_sanitizes_and_preserves_database_exactly(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"test.db"
            with sqlite3.connect(path) as db:
                db.executescript("""
                    CREATE TABLE learning_materials(id INTEGER,user_id INTEGER,content TEXT);
                    CREATE TABLE topics(id INTEGER,material_id INTEGER);
                    CREATE TABLE questions(id INTEGER,material_id INTEGER,topic_id INTEGER,difficulty INTEGER,question TEXT);
                    CREATE TABLE question_attempts(id INTEGER,user_id INTEGER,question_id INTEGER,is_correct INTEGER,created_at TEXT,user_answer TEXT);
                    CREATE TABLE review_attempts(id INTEGER,user_id INTEGER,question_id INTEGER,is_correct INTEGER,created_at TEXT);
                    INSERT INTO learning_materials VALUES(1,1,'PRIVATE CONTENT'),(2,2,'PRIVATE CONTENT');
                    INSERT INTO topics VALUES(1,1),(2,2);
                    INSERT INTO questions VALUES(1,1,1,2,'PRIVATE QUESTION'),(2,2,2,2,'PRIVATE QUESTION'),(3,1,2,2,'BROKEN'),(4,1,NULL,2,'UNLINKED');
                    INSERT INTO question_attempts VALUES(1,1,1,0,'2026-01-01 00:01:00','SECRET ANSWER'),(2,2,2,1,'2026-01-01 00:01:00','SECRET ANSWER'),(3,2,1,1,'2026-01-01 00:01:00','FOREIGN'),(4,1,3,1,'2026-01-01 00:01:00','BROKEN'),(5,1,4,1,'2026-01-01 00:01:00','UNLINKED');
                    INSERT INTO review_attempts VALUES(1,1,1,1,'2026-01-01 00:02:00');
                """)
            db.close()
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            data = export_history(path, user_ids=[1], key=b"x"*32)
            self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(len(data["events"]), 2)
            self.assertEqual(data, export_history(path, user_ids=[1], key=b"x"*32))
            serialized = json.dumps(data)
            self.assertNotIn("PRIVATE", serialized)
            self.assertNotIn("SECRET", serialized)
            self.assertEqual(len({e["learner_id"] for e in data["events"]}), 1)
            self.assertEqual(data["source"]["coverage"]["skipped"]["missing_topic_or_invalid_ownership_or_link"], 2)
            report, _ = replay(data)
            self.assertEqual(report["source"]["kind"], "real_history")
            with self.assertRaises(ValueError):
                export_history(path, key=b"short")

    def test_missing_database_cannot_be_created(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"missing.db"
            with self.assertRaises(FileNotFoundError):
                export_history(path)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
