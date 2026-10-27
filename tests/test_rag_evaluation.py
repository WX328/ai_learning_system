import json
import tempfile
import unittest
from pathlib import Path

from app.services.rag_evaluation import evaluate_cases, load_cases, metrics_for_ranking


class RagEvaluationMetricsTest(unittest.TestCase):
    def test_metrics_measure_rank_and_missing_relevant_chunks(self):
        metrics = metrics_for_ranking([9, 2, 5, 3], [2, 3])
        self.assertEqual(metrics["recall_at_1"], 0)
        self.assertEqual(metrics["recall_at_3"], 0.5)
        self.assertEqual(metrics["recall_at_5"], 1)
        self.assertAlmostEqual(metrics["precision_at_3"], 1 / 3)
        self.assertEqual(metrics["mrr"], 0.5)

    def test_evaluation_aggregates_cases_without_provider_calls(self):
        cases = [
            {"id": "first", "question": "one", "material_id": 1, "topic_id": None,
             "relevant_chunk_ids": [11], "notes": ""},
            {"id": "second", "question": "two", "material_id": 1, "topic_id": None,
             "relevant_chunk_ids": [22], "notes": ""},
        ]
        ranking = {"first": [11, 8], "second": [5, 22]}
        report = evaluate_cases(cases, lambda case: [
            {"chunk_id": chunk_id, "similarity": 0.9} for chunk_id in ranking[case["id"]]
        ])
        self.assertEqual(report["summary"]["case_count"], 2)
        self.assertEqual(report["summary"]["recall_at_1"], 0.5)
        self.assertEqual(report["summary"]["recall_at_3"], 1)
        self.assertEqual(report["summary"]["mrr"], 0.75)

    def test_loader_rejects_duplicate_or_unlabelled_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.json"
            path.write_text(json.dumps({"cases": [
                {"id": "same", "question": "one", "material_id": 1, "relevant_chunk_ids": [1]},
                {"id": "same", "question": "two", "material_id": 1, "relevant_chunk_ids": [2]},
            ]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "重复"):
                load_cases(path)


if __name__ == "__main__":
    unittest.main()
