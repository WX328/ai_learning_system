"""Replay an explicit dataset; write aggregate JSON, Markdown and per-decision CSV."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import platform
import sys

from evaluation.adaptive_replay import ALGORITHMS, replay


def markdown(report):
    source = report["source"]["kind"]
    label = "模拟数据：仅验证规则行为" if source == "synthetic" else "真实历史：观察性描述，不能推断学习收益"
    lines = ["# S3 自适应算法离线回放报告", "", label, "",
        f"评估版本：`{report['evaluation_version']}`；生产算法：`{report['production_model']}`。",
        f"数据 SHA256：`{report['dataset_sha256']}`。", "",
        "## 样本量与时间口径", "", "```json", json.dumps(report["samples"], ensure_ascii=False, indent=2), "```", "",
        "所有算法使用相同历史；先冻结当前时间戳的全部决策，再纳入该时间的答案和复习。首次重复提交只取最早记录。",
        "预测目标为当前新题首次正误；至少已有三道不同题目才纳入，冷启动不填 0 或 50%。",
        "知识点排序以之后窗口内实际首次表现作代理标签；结果不反馈算法，且不能证明推荐的因果收益。", "",
        "## 共同样本上的比较", "",
        "| 算法 | score-proxy Brier ↓ | AUC ↑ | 排序一致性 ↑ | 趋势方向响应 |",
        "| --- | --- | --- | --- | --- |"]
    show = lambda m: f"{m['value']:.4f} (n={m['n']}, learners={m['learners']})" if m["value"] is not None else f"不可评估 (n={m['n']}, learners={m['learners']}; {m['reason']})"
    for name, metrics in report["algorithms"].items():
        lines.append("| " + " | ".join([name] + [show(metrics[k]) for k in
            ("score_proxy_brier", "score_auc", "ranking_pairwise_concordance", "trend_direction_response")]) + " |")
    lines += ["", "S2 分数不是校准概率；Brier 仅把分数/100 当作未校准预测代理，不称为能力概率或预测准确率。AUC 还要求正负两类结果。",
        "不足预设样本数或学习者数的指标为 null/不可评估；描述值没有独立样本显著性保证。", "",
        "## 少样本稳定性与难度动作", "",
        "| 算法 | 前四题极端分占比 / n | 分数平均绝对跳变 / 对数 | 少于三题升档 / 决策数 | 升档 / 降档 / 总决策 |",
        "| --- | --- | --- | --- | --- |"]
    fmt = lambda x: "不可评估" if x is None else f"{x:.3f}"
    for name, m in report["algorithms"].items():
        s, d = m["small_sample"], m["difficulty"]
        lines.append(f"| {name} | {fmt(s['extreme_score_fraction'])} / {s['n']} | {fmt(s['mean_absolute_score_jump'])} / {s['jump_pairs']} | {s['early_promotions']} / {s['promotion_decisions_n']} | {d['up']} / {d['down']} / {d['n']} |")
    lines += ["", "稳定性是分数的描述性性质，不是越平滑越能促进学习；难度动作没有已验证的最优标签。",
        "趋势用相邻、不重叠的五题块正确率变化≥20个百分点作规则响应标签，并非真实能力变化。", "",
        "## 评估配置", "", "```json", json.dumps(report["config"], ensure_ascii=False, indent=2), "```", "",
        "## 解释边界", ""] + [f"- {s}" for s in report["limitations"]]
    if report["source"].get("coverage"):
        lines += ["", "## 导出覆盖率", "", "```json", json.dumps(report["source"]["coverage"], ensure_ascii=False, indent=2), "```",
            "缺少知识点关联的答题无法参与知识点评估；历史目录采用首次观察时间，无法复原当时未练知识点及待答题状态。"]
    return "\n".join(lines) + "\n"


def write_report(report, traces, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    fields = ["event_id", "learner_id", "material_id", "topic_id", "timestamp", "question_id", "correct", "logged_difficulty",
              "algorithm", "history_count", "score_before", "current_difficulty", "recommended_difficulty", "selected_topic", "selected_difficulty", "ranking"]
    with (output / "decisions.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for t in traces:
            for name in ALGORITHMS:
                a = t["algorithms"][name]
                writer.writerow({"event_id": t["id"], **{k: t[k] for k in ("learner_id", "material_id", "topic_id", "timestamp", "question_id")},
                    "correct": int(t["correct"]), "logged_difficulty": t["difficulty"], "algorithm": name,
                    "history_count": a["count"], "score_before": a["score"], "current_difficulty": a["current_difficulty"],
                    "recommended_difficulty": a["difficulty"], "selected_topic": a["selected_topic"],
                    "selected_difficulty": a["selected_difficulty"], "ranking": json.dumps(a["ranking"])})
    report = {**report, "decisions_csv_sha256": hashlib.sha256((output / "decisions.csv").read_bytes()).hexdigest()}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "report.md").write_text(markdown(report), encoding="utf-8")
    (output / "environment.json").write_text(json.dumps({"python": sys.version, "platform": platform.platform(),
        "note": "Report content is deterministic for fixed input/config; this environment manifest may differ."}, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--min-predictions", type=int, default=20)
    parser.add_argument("--min-learners", type=int, default=2)
    parser.add_argument("--min-history", type=int, default=3)
    parser.add_argument("--horizon", type=int, default=10)
    args = parser.parse_args()
    report, traces = replay(json.loads(args.dataset.read_text(encoding="utf-8")),
        min_predictions=args.min_predictions, min_learners=args.min_learners,
        min_history=args.min_history, horizon=args.horizon)
    write_report(report, traces, args.output_dir)
    print(f"{report['source']['kind']}: {report['samples']['first_answers']} first answers; {args.output_dir / 'report.md'}")


if __name__ == "__main__":
    main()
