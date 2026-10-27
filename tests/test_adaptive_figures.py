"""Optional plotting dependency: verify actual artifacts and missing-data behavior."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree

from evaluation.adaptive_replay import replay
from evaluation.learning_experiment import analyze
from scripts.evaluate_adaptive import write_report
from scripts.plot_adaptive_evaluation import generate_figures
from test_adaptive_evaluation import dataset
from test_learning_experiment import plan


@unittest.skipUnless(importlib.util.find_spec("matplotlib"), "optional evaluation/requirements.txt not installed")
class AdaptiveFiguresTest(unittest.TestCase):
    def test_vector_raster_figures_show_na_and_correct_separate_experiment_source(self):
        report, traces = replay(dataset("10101"))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_report(report, traces, root)
            experiment = root/"experiment.json"
            experiment.write_text(json.dumps(analyze(plan(), [])), encoding="utf-8")
            manifest = generate_figures(root, root/"figures", experiment_report=experiment)
            self.assertEqual(len(manifest["artifacts"]), 15)
            self.assertEqual(manifest["dataset_sha256"], report["dataset_sha256"])
            for name in manifest["artifacts"]:
                path = root/"figures"/name
                self.assertGreater(path.stat().st_size, 1000)
                if path.suffix == ".svg":
                    ElementTree.parse(path)
            comparison = (root/"figures/comparison.svg").read_text(encoding="utf-8")
            self.assertIn("N/A", comparison)
            self.assertIn("SYNTHETIC", comparison)
            self.assertIn("synthetic_experiment", (root/"figures/experiment_samples.svg").read_text(encoding="utf-8"))
            self.assertTrue((root/"figures/mastery.png").read_bytes().startswith(b"\x89PNG"))
            self.assertTrue((root/"figures/mastery.pdf").read_bytes().startswith(b"%PDF"))

    def test_mixed_csv_and_report_are_rejected(self):
        report, traces = replay(dataset("1"))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_report(report, traces, root)
            with (root/"decisions.csv").open("a", encoding="utf-8") as stream:
                stream.write("tampered\n")
            with self.assertRaises(ValueError):
                generate_figures(root, root/"figures")


if __name__ == "__main__":
    unittest.main()
