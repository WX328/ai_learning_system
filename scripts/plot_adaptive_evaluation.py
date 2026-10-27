"""Publication artifacts from measured report/CSV only; no invented missing bars.

Optional dependency: python -m pip install -r evaluation/requirements.txt
Each figure is exported to vector PDF/SVG and 300-dpi PNG.
"""
import argparse
from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path


def generate_figures(report_dir, output_dir, *, experiment_report=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    from evaluation.adaptive_replay import ALGORITHMS

    report_dir, output_dir = Path(report_dir), Path(output_dir)
    report = json.loads((report_dir/"report.json").read_text(encoding="utf-8"))
    if hashlib.sha256((report_dir/"decisions.csv").read_bytes()).hexdigest() != report["decisions_csv_sha256"]:
        raise ValueError("CSV does not match report fingerprint; regenerate the replay report")
    with (report_dir/"decisions.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    source = report["source"]["kind"]
    label = "SYNTHETIC prescribed sequences - rule behavior only" if source == "synthetic" else "REAL observational history - no causal learning claim"
    footer = f"{label}\n{report['evaluation_version']} | rules_v2 | SHA256 {report['dataset_sha256'][:16]} | correlated observations"
    output_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
        "axes.spines.top": False, "axes.spines.right": False,
        "svg.fonttype": "none", "pdf.fonttype": 42})
    colors = ("#6e7781", "#c27428", "#235f9b")
    labels = ("Historical accuracy", "Recent-5 accuracy", "S2 rules_v2")
    saved = []

    def finish(fig, name, title):
        fig.suptitle(title, fontsize=14)
        fig.text(.5, .025, footer, ha="center", va="bottom", fontsize=8, color="#444444")
        fig.tight_layout(rect=(0, .14, 1, .93))
        for suffix in ("svg", "pdf", "png"):
            path = output_dir/f"{name}.{suffix}"
            fig.savefig(path, dpi=300, facecolor="white")
            saved.append(path.name)
        plt.close(fig)

    groups = defaultdict(list)
    for row in rows:
        groups[row["learner_id"], row["material_id"], row["topic_id"]].append(row)
    # A single observed trajectory, never the average of different learners' time axes.
    track = max(sorted(groups), key=lambda k: len(groups[k]), default=None)
    track_rows = groups[track] if track is not None else []
    for field, name, title, ylabel in (("score_before", "mastery", "Mastery trajectory: one observed topic", "Rule index / 100 (not probability)"),
            ("recommended_difficulty", "difficulty", "Recommended difficulty under the SAME logged history", "Recommended level before answer")):
        fig, ax = plt.subplots(figsize=(9, 4.8))
        for algorithm, color, legend in zip(ALGORITHMS, colors, labels):
            points = [r for r in track_rows if r["algorithm"] == algorithm]
            ys = [float(r[field]) if r[field] else float("nan") for r in points]
            ax.plot(range(1, len(points)+1), ys, label=legend, color=color, marker="o", markersize=3)
        ax.set(xlabel="Decision index within this topic (before answer)", ylabel=ylabel)
        ax.set_xlim(.5, max(1, len(points))+.5)
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.set_ylim((0, 100) if field == "score_before" else (.8, 5.2))
        if field == "recommended_difficulty":
            ax.set_yticks(range(1, 6))
        ax.grid(axis="y", alpha=.18)
        if track_rows:
            ax.legend(loc="best", frameon=False)
        else:
            ax.text(.5, .5, "No eligible history", transform=ax.transAxes, ha="center")
        finish(fig, name, title)

    fig, axes = plt.subplots(2, 2, figsize=(10, 7))
    for ax, key, title in zip(axes.flat,
            ("score_proxy_brier", "score_auc", "ranking_pairwise_concordance", "trend_direction_response"),
            ("Uncalibrated score-proxy Brier (lower)", "Score AUC (higher)", "Future-order concordance (higher)", "Observed-block trend response")):
        for index, (algorithm, color) in enumerate(zip(ALGORITHMS, colors)):
            metric = report["algorithms"][algorithm][key]
            if metric["value"] is None:
                ax.text(index, .05, f"N/A\nn={metric['n']}", ha="center", fontsize=9)
            else:
                ax.bar(index, metric["value"], color=color, width=.58)
                ax.text(index, metric["value"]+.025, f"{metric['value']:.3f}\nn={metric['n']}", ha="center", fontsize=8)
        ax.set_xticks(range(3), ["History", "Recent-5", "S2"])
        ax.set_xlim(-.6, 2.6)
        ax.set_ylim(0, 1.18)
        ax.set_title(title, fontsize=10)
        ax.grid(axis="y", alpha=.16)
    finish(fig, "comparison", "Algorithm comparison: descriptive proxies, common eligibility rules")

    fig, axes = plt.subplots(1, 3, figsize=(10, 4.6))
    values = (report["samples"]["first_answers"], report["algorithms"][ALGORITHMS[0]]["score_proxy_brier"]["n"], report["samples"]["learners"])
    for ax, value, title in zip(axes, values, ("Distinct first answers", "Eligible prediction targets", "Observed learners")):
        ax.bar([0], [value], color="#235f9b", width=.45)
        ax.text(0, value+.03*max(1, value), str(value), ha="center")
        ax.set(xticks=[], ylim=(0, max(1, value)*1.25), title=title, ylabel="Count")
        ax.grid(axis="y", alpha=.16)
    finish(fig, "sample_counts", "Actual sample counts (answers are not independent learners)")

    if experiment_report:
        experiment = json.loads(Path(experiment_report).read_text(encoding="utf-8"))
        fig, axes = plt.subplots(1, 2, figsize=(9, 4.8))
        for index, arm in enumerate(("fixed", "adaptive")):
            group = experiment["groups"][arm]
            axes[0].bar(index, group["complete"], color=colors[index+1])
            axes[0].text(index, group["complete"]+.05, f"{group['complete']}/{group['assigned']}", ha="center")
            if group["mean_gain"] is None:
                axes[1].text(index, .08, "N/A\nno complete\nobservations", ha="center", fontsize=8)
            else:
                axes[1].bar(index, group["mean_gain"], color=colors[index+1])
        for ax in axes:
            ax.set_xticks([0, 1], ["Fixed", "Adaptive"])
            ax.set_xlim(-.6, 1.6)
        axes[0].set(title="Complete / assigned research codes", ylabel="Participants", ylim=(0, max(g["assigned"] for g in experiment["groups"].values())+1))
        axes[1].set(title="Post minus pre, complete participants only", ylabel="Mean score gain", ylim=(-1, 1))
        axes[1].axhline(0, color="gray", linewidth=.6)
        # This plot has its OWN source; do not inherit the replay dataset label.
        old_footer = footer
        footer = f"{experiment['source']} | {experiment['protocol']} | plan SHA256 {experiment['plan_sha256'][:16]}\nNo real learning-effect result without completed real observations."
        finish(fig, "experiment_samples", "Learning experiment: observation availability")
        footer = old_footer
    manifest = {"source": source, "dataset_sha256": report["dataset_sha256"], "evaluation_version": report["evaluation_version"],
        "implementation_sha256": report["implementation_sha256"], "decisions_csv_sha256": report["decisions_csv_sha256"],
        "algorithms": list(ALGORITHMS), "matplotlib": matplotlib.__version__, "config": report["config"],
        "trajectory_topic_decisions": len(track_rows)//3, "artifacts": saved,
        "limits": report["limitations"], "format": "vector PDF/SVG and 300dpi PNG"}
    (output_dir/"figures.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--experiment-report", type=Path)
    args = parser.parse_args()
    result = generate_figures(args.report_dir, args.output_dir, experiment_report=args.experiment_report)
    print(f"Saved {len(result['artifacts'])} figure artifacts ({result['source']})")


if __name__ == "__main__":
    main()
