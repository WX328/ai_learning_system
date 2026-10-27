"""Compare old and S2 mastery on deterministic synthetic sequences only.

Run python -m scripts.evaluate_mastery. No DB sessions, writes to learning data,
or model API calls. Both Markdown and machine-readable JSON are emitted.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

from app.services.adaptive import calculate_next_difficulty, explain_difficulty
from app.services.topic_mastery import assess_topic, mastery_priority, MODEL_VERSION

ROOT = Path(__file__).resolve().parents[1]


def evaluate_cases(dataset):
    output = []
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for case in dataset["cases"]:
        levels = case["difficulty"]
        levels = [levels] * len(case["answers"]) if isinstance(levels, int) else levels
        if len(levels) != len(case["answers"]) or any(d not in range(1,6) for d in levels):
            raise ValueError("Invalid fixture difficulty")
        attempts, reviews = [], []
        for i,(answer,difficulty) in enumerate(zip(case["answers"],levels)):
            if answer not in "01":
                raise ValueError("Invalid fixture answer")
            attempts.append((SimpleNamespace(id=i+1, question_id=i+1, is_correct=answer=="1",
                                              created_at=start+timedelta(minutes=i)),
                             SimpleNamespace(id=i+1, difficulty=difficulty)))
        for group in case.get("reviews",[]):
            if not 1 <= group["question"] <= len(attempts):
                raise ValueError("Invalid fixture review question")
            for answer in group["answers"]:
                if answer not in "01":
                    raise ValueError("Invalid fixture review answer")
                reviews.append(SimpleNamespace(id=len(reviews)+1, question_id=group["question"],
                    is_correct=answer=="1", created_at=start+timedelta(days=1,minutes=len(reviews))))
        assessment = assess_topic(attempts,reviews)
        latest = {r.question_id:r for r in reviews}
        old_score = round(sum(latest.get(q.id,a).is_correct for a,q in attempts)/len(attempts)*100) if attempts else None
        current = levels[-1] if levels else 2
        level, explanation = explain_difficulty(assessment["recent_correct_rate"],assessment["recent_attempt_count"],current)
        output.append({"id":case["id"], "name":case["name"], "input":case,
                       "old_mastery_score":old_score,
                       "old_recommended_difficulty":calculate_next_difficulty(assessment["recent_correct_rate"],current),
                       "new_recommended_difficulty":level, "difficulty_reason":explanation,
                       "assessment":assessment})
    by_id={row["id"]:row for row in output}
    selections=[]
    for case in dataset.get("selection_cases",[]):
        indexed=list(enumerate((by_id[id] for id in case["topics"]),start=1))
        old=min(indexed,key=lambda pair:mastery_priority(pair[1]["old_mastery_score"],pair[1]["assessment"]["attempt_count"],pair[0]))[1]
        new=min(indexed,key=lambda pair:mastery_priority(pair[1]["assessment"]["mastery_score"],pair[1]["assessment"]["attempt_count"],pair[0]))[1]
        selections.append({**case,"old_selected":old["id"],"new_selected":new["id"],
                           "new_difficulty":new["new_recommended_difficulty"]})
    return {"model":MODEL_VERSION, "synthetic_only":True, "cases":output,"topic_selections":selections}


def markdown(report):
    lines = ["# S2 掌握度规则模型对比", "",
        "固定合成序列，不连接学习数据库、不调用模型。1 表示首次答对，0 表示首次答错；每位首次答案是一道不同题目。", "",
        "旧算法：每道题采用最新复习结果覆盖首次答案，再取正确率×100；最近首次正确率≥80%即升档。", "",
        "新算法：难度加权、每题复习贡献上限30%、平滑项、历史70%+最近五道30%；升档至少需要三道不同题目。分数是规则指数，不是能力概率。", "",
        "| 场景 | 首次序列 | 旧掌握度 | 新掌握度 | 不同题目 / 已复习题目 | 旧→新推荐难度 |",
        "| --- | --- | ---: | ---: | --- | --- |"]
    show = lambda value: "未知" if value is None else str(value)
    for row in report["cases"]:
        a=row["assessment"]
        lines.append(f"| {row['name']} | {row['input']['answers'] or '无'} | {show(row['old_mastery_score'])} | {show(a['mastery_score'])} | {a['attempt_count']} / {a['reviewed_question_count']} | {row['old_recommended_difficulty']}→{row['new_recommended_difficulty']} |")
    names={row["id"]:row["name"] for row in report["cases"]}
    lines += ["", "## 多知识点选择对比", "", "下列场景将上表序列视作同一资料中的不同知识点，按真实推荐服务共用的优先级规则选点；同分时按输入知识点顺序。", "",
              "| 场景 | 旧算法选择 | 新算法选择 | 新推荐难度 |", "| --- | --- | --- | ---: |"]
    for row in report["topic_selections"]:
        lines.append(f"| {row['name']} | {names[row['old_selected']]} | {names[row['new_selected']]} | {row['new_difficulty']} |")
    lines += ["", "可以复现的行为：一题全对不会直接达到满分；同题重复复习不增加样本或分数；相同总体正确率下，近期改善和退步产生不同结果；难度会改变证据权重。", "",
        "这些案例验证确定性与规则合理性，不构成真实学习者预测准确率验证。题目难度来自现有1～5标注，尚未校准；参数和80分阈值仍需后续真实反馈检验。", ""]
    for row in report["cases"]:
        lines += [f"## {row['name']}", "", row["assessment"]["mastery_reason"], "", row["difficulty_reason"], ""]
    return "\n".join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset",type=Path,default=ROOT/"evaluation/mastery_s2_sequences.json")
    parser.add_argument("--output",type=Path,default=ROOT/"evaluation/reports/mastery-s2")
    args=parser.parse_args()
    report=evaluate_cases(json.loads(args.dataset.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.with_suffix(".json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    args.output.with_suffix(".md").write_text(markdown(report),encoding="utf-8")
    print(f"已评估 {len(report['cases'])} 组固定序列：{args.output.with_suffix('.md')}")


if __name__ == "__main__":
    main()
