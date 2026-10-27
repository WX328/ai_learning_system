"""Independent fixtures only. No real participant data or model calls."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from evaluation.experiment_bank import (CHECKS, prepare_bank, validate_actual_bank, review_item,
    content_hash, review_hash, public_question, review_packet)
from evaluation.experiment_session import (create_study, show_next, submit_answer, progress,
    export_study, load_study)
from evaluation.learning_experiment import make_plan, analyze, load_records
from scripts.create_review_bank import draft_bank


def approved_fixture():
    """Simulated reviewer metadata for unit tests, NEVER a delivered reviewed bank."""
    bank = draft_bank()
    bank["data_kind"] = "real_candidate"
    for item in bank["items"]:
        item["review"] = {"status": "approved", "reviewer": "UNIT-TEST-NOT-HUMAN", "checks": dict.fromkeys(CHECKS, True),
            "reviewed_at": "2026-01-01T00:00:00+00:00", "content_sha256": review_hash(item)}
    return bank


class BankTest(unittest.TestCase):
    def test_draft_has_actual_questions_and_never_qualifies_as_real(self):
        bank = draft_bank()
        validate_actual_bank(bank)
        self.assertEqual(len(bank["items"]), 28)
        self.assertTrue(all(i["review"]["status"] == "pending_review" for i in bank["items"]))
        for source in ("real_experiment",):
            with self.assertRaises(ValueError):
                make_plan(bank, ["R01"], source=source, learning_steps=4)

    def test_metadata_only_real_plan_rejected_but_s3_synthetic_compatible(self):
        from tests.test_learning_experiment import bank
        with self.assertRaises(ValueError):
            make_plan(bank(), ["R01"], source="real_experiment", learning_steps=4)
        self.assertEqual(make_plan(bank(), ["SIM-01"], source="synthetic_experiment", learning_steps=4)["source"], "synthetic_experiment")

    def test_exact_question_duplicate_detected_after_relabeling_and_spacing(self):
        bank = draft_bank()
        original, duplicate = bank["items"][0], bank["items"][1]
        duplicate["stem"] = "  "+original["stem"]+"\n"
        duplicate["options"] = dict(zip("ABCD", reversed(list(original["options"].values()))))
        with self.assertRaisesRegex(ValueError, "reused"):
            prepare_bank(bank)

    def test_same_family_rejected_across_learning_and_test(self):
        bank = draft_bank()
        bank["items"][-1]["family_id"] = "  " + bank["items"][0]["family_id"].upper() + " "
        with self.assertRaisesRegex(ValueError, "family"):
            prepare_bank(bank)

    def test_forms_must_match_and_all_learning_levels_exist(self):
        for index in (0, -1):
            bank = draft_bank()
            if index == 0:
                bank["items"][0]["difficulty"] = 1
            else:
                bank["items"] = [i for i in bank["items"] if not (i["pool"] == "learning" and i["difficulty"] == 5)]
            with self.assertRaises(ValueError):
                prepare_bank(bank)

    def test_all_approval_checks_and_reviewer_required(self):
        bank = draft_bank()
        for reviewer, checks in (("", dict.fromkeys(CHECKS, True)), ("REVIEWER-1", {"content": True})):
            with self.assertRaises(ValueError):
                review_item(bank, bank["items"][0]["item_id"], reviewer=reviewer, checks=checks, approved=True)
        updated = review_item(bank, bank["items"][0]["item_id"], reviewer="REVIEWER-1",
                              checks=dict.fromkeys(CHECKS, True), approved=True)
        self.assertEqual(updated["items"][0]["review"]["status"], "approved")
        self.assertEqual(bank["items"][0]["review"]["status"], "pending_review")

    def test_changes_to_topic_difficulty_family_answer_or_text_invalidate_approval(self):
        for key, value in (("stem", "changed"), ("answer", "C"), ("difficulty", 1), ("topic_id", "dicts"), ("family_id", "changed")):
            bank = approved_fixture()
            bank["items"][0][key] = value
            bank["items"][0]["content_hash"] = content_hash(bank["items"][0])
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "changed since approval"):
                validate_actual_bank(bank, require_approved=True)

    def test_demo_bank_cannot_become_real_by_approving_items(self):
        bank = approved_fixture()
        bank["data_kind"] = "demo"
        with self.assertRaisesRegex(ValueError, "demo bank"):
            make_plan(bank, ["R01"], source="real_experiment", learning_steps=4)

    def test_reviewed_unit_fixture_passes_real_gate_without_touching_production(self):
        # Virtual approvals exercise schema logic only; no human experiment is created.
        plan = make_plan(approved_fixture(), ["UNIT-TEST-CODE"], source="real_experiment", learning_steps=4)
        self.assertEqual(plan["source"], "real_experiment")
        self.assertEqual(plan["bank"]["data_kind"], "real_candidate")

    def test_review_packet_is_explicitly_researcher_only(self):
        text = review_packet(draft_bank())
        self.assertIn("含答案", text)
        self.assertIn("pending_review", text)
        self.assertEqual(set(public_question(draft_bank(), draft_bank()["items"][0]["item_id"])), {"item_id", "stem", "options"})


class SessionTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.study = self.root / "study"
        self.plan = create_study(self.study, draft_bank(), ["DEMO-01", "DEMO-02", "DEMO-03", "DEMO-04"],
                                 source="demo_experiment", learning_steps=4)

    def complete(self, code):
        for step in range(12):
            display = show_next(self.study, code)
            decision = display["decision"]
            answer = "ABCD"[step % 4]  # Script input; not a human observation.
            result = submit_answer(self.study, decision, answer,
                timestamp=(datetime(2026, 1, 1, tzinfo=timezone.utc)+timedelta(seconds=step+1)).isoformat(), duration_seconds=1)
            if decision["phase"] != "learning":
                self.assertEqual(set(result), {"saved", "phase", "source"})
            else:
                self.assertIn("explanation", result)
        self.assertEqual(show_next(self.study, code)["decision"]["status"], "complete")

    def test_end_to_end_both_arms_reuses_s3_and_preserves_answer_choices(self):
        with patch("app.database.SessionLocal") as database, patch("app.core.settings.deepseek_client") as provider:
            for code in ("DEMO-01", "DEMO-02", "DEMO-03", "DEMO-04"):
                self.complete(code)
            plan, state, records = load_study(self.study)
        provider.assert_not_called()
        database.assert_not_called()
        self.assertEqual(len(records), 48)
        self.assertEqual(len(state["observations"]), 48)
        self.assertEqual({p["arm"] for p in plan["assignments"]}, {"fixed", "adaptive"})
        self.assertTrue(all(p["answered"] == p["total"] == 12 for p in progress(self.study)["participants"]))
        result = export_study(self.study, self.root / "export")
        self.assertEqual(result["gain_difference"]["status"], "not_evaluable")
        projected = load_records(Path(result["private_s3"]) / "records.csv")
        self.assertEqual(analyze(plan, projected), analyze(plan, records))

    def test_participant_display_and_pre_post_results_hide_answers(self):
        display = show_next(self.study, "DEMO-01")
        self.assertEqual(set(display["question"]), {"item_id", "stem", "options"})
        self.assertNotIn("explanation", json.dumps(display))
        result = submit_answer(self.study, display["decision"], "A")
        self.assertNotIn("correct", result)
        self.assertNotIn("correct_answer", result)

    def test_duplicate_and_altered_decisions_rejected_without_new_rows(self):
        decision = show_next(self.study, "DEMO-01")["decision"]
        submit_answer(self.study, decision, "A")
        for bad in (decision, {**decision, "item_id": "unknown"}):
            with self.assertRaises(ValueError):
                submit_answer(self.study, bad, "A")
        self.assertEqual(len(load_study(self.study)[2]), 1)

    def test_invalid_answer_duration_and_timestamp_do_not_save(self):
        decision = show_next(self.study, "DEMO-01")["decision"]
        for answer, kwargs in (("X", {}), ("A", {"duration_seconds": float("nan")}), ("A", {"duration_seconds": -1}),
                               ("A", {"timestamp": "2026-01-01"})):
            with self.subTest(answer=answer, kwargs=kwargs), self.assertRaises(ValueError):
                submit_answer(self.study, decision, answer, **kwargs)
        self.assertEqual(load_study(self.study)[2], [])

    def test_held_lock_is_not_removed_or_overwritten(self):
        lock = self.study / "observations.lock"
        lock.write_text("another writer", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "busy"):
            submit_answer(self.study, show_next(self.study, "DEMO-01")["decision"], "A")
        self.assertEqual(lock.read_text(encoding="utf-8"), "another writer")

    def test_plan_or_observed_answer_tampering_detected(self):
        submit_answer(self.study, show_next(self.study, "DEMO-01")["decision"], "A")
        path = self.study / "observations.json"
        state = json.loads(path.read_text())
        state["observations"][0]["answer"] = "B"  # Original correct answer is A or C; choose a different correctness below.
        row = state["observations"][0]["record"]
        row["correct"] = "1" if row["correct"] == "0" else "0"
        state["observations"][0]["answer"] = "A"
        path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "grading"):
            load_study(self.study)

    def test_pseudonymous_export_has_no_question_or_original_code(self):
        self.complete("DEMO-01")
        result = export_study(self.study, self.root / "export")
        public = Path(result["shareable"])
        for path in public.iterdir():
            text = path.read_text(encoding="utf-8-sig")
            self.assertNotIn("DEMO-01", text)
            self.assertNotIn("DEMO-02", text)
            self.assertNotIn("执行 x=", text)
        text = (public / "events.csv").read_text(encoding="utf-8-sig")
        self.assertNotIn("timestamp", text.splitlines()[0])
        self.assertNotIn("answer,", text.splitlines()[0])
        self.assertEqual(json.loads((public / "manifest.json").read_text())["evidence"], "demonstration_only")

    def test_cli_display_answer_progress_and_s3_analysis(self):
        def cli(module, *args):
            result = subprocess.run([sys.executable, "-X", "utf8", "-m", module, *map(str, args)], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            return result
        decision_path = self.root / "decision.json"
        cli("scripts.research_experiment", "next", "--study", self.study, "--participant", "DEMO-01", "--output", decision_path)
        cli("scripts.research_experiment", "answer", "--study", self.study, "--decision", decision_path, "--answer", "A")
        result = cli("scripts.research_experiment", "progress", "--study", self.study)
        self.assertIn('"answered": 1', result.stdout)
        exported = self.root / "export"
        cli("scripts.research_experiment", "export", "--study", self.study, "--output-dir", exported)
        cli("scripts.learning_experiment", "analyze", "--plan", exported / "private-s3/plan.json", "--records", exported / "private-s3/records.csv",
            "--output-dir", self.root / "s3-analysis")

    def test_terminal_conduct_can_pause_resume_and_complete(self):
        args = [sys.executable, "-X", "utf8", "-m", "scripts.research_experiment", "conduct", "--study", str(self.study), "--participant", "DEMO-01"]
        paused = subprocess.run(args, input="q\n", capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(paused.returncode, 0, paused.stderr)
        self.assertEqual(load_study(self.study)[2], [])
        completed = subprocess.run(args, input="A\nB\nC\nD\n"*3, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("demo_experiment", completed.stdout)
        self.assertIn("状态 complete", completed.stdout)
        self.assertEqual(len(load_study(self.study)[2]), 12)

    def test_existing_temporary_file_is_not_deleted_on_failed_save(self):
        temporary = self.study / "observations.json.tmp"
        temporary.write_text("inspect before recovery", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            submit_answer(self.study, show_next(self.study, "DEMO-01")["decision"], "A")
        self.assertEqual(load_study(self.study)[2], [])
        self.assertEqual(temporary.read_text(encoding="utf-8"), "inspect before recovery")
        self.assertFalse((self.study / "observations.lock").exists())


if __name__ == "__main__":
    unittest.main()
