"""Researcher-hosted actual questions, isolated from all production tables."""
import argparse
import json
from pathlib import Path
import time
from evaluation.experiment_session import create_study, show_next, submit_answer, progress, export_study


def conduct(root, participant):
    print("主持式实验：前后测不反馈答案；学习阶段显示解析。输入 q 暂停；中断后使用相同编号继续。")
    while True:
        display = show_next(root, participant)
        decision = display["decision"]
        print(f"\n来源 {display['source']} | 编号 {participant} | 状态 {decision['status']}")
        if decision["status"] != "ready":
            return
        question = display["question"]
        print(f"{decision['phase']} · 第 {decision['step']} 题\n{question['stem']}")
        for label, text in question["options"].items():
            print(f"  {label}. {text}")
        started = time.monotonic()
        while (answer := input("选择 A/B/C/D（q 暂停）：").strip().upper()) not in {"A", "B", "C", "D", "Q"}:
            print("请输入一个有效选项。")
        if answer == "Q":
            return
        result = submit_answer(root, decision, answer, duration_seconds=round(time.monotonic()-started, 3))
        if decision["phase"] == "learning":
            print(("答对。" if result["correct"] else "需要巩固。") + result["explanation"])
        else:
            print("答案已保存。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("init")
    create.add_argument("--bank", required=True, type=Path)
    create.add_argument("--participants", required=True, type=Path, help="JSON research codes; never real names")
    create.add_argument("--source", required=True, choices=("demo_experiment", "real_experiment"))
    create.add_argument("--seed", type=int, default=20261023)
    create.add_argument("--learning-steps", type=int, default=4)
    create.add_argument("--fixed-difficulty", type=int, default=2)
    for name in ("init", "next", "answer", "conduct", "progress", "export"):
        command = create if name == "init" else commands.add_parser(name)
        command.add_argument("--study", required=True, type=Path)
        if name in {"next", "conduct"}:
            command.add_argument("--participant", required=True)
        if name == "next":
            command.add_argument("--output", type=Path, required=True)
        if name == "answer":
            command.add_argument("--decision", required=True, type=Path)
            command.add_argument("--answer", choices=("A", "B", "C", "D"), required=True)
            command.add_argument("--duration-seconds", type=float)
        if name == "export":
            command.add_argument("--output-dir", required=True, type=Path)
            command.add_argument("--minimum-per-arm", type=int, default=5)
    args = parser.parse_args()
    try:
        if args.command == "init":
            create_study(args.study, json.loads(args.bank.read_text(encoding="utf-8-sig")),
                json.loads(args.participants.read_text(encoding="utf-8-sig")), source=args.source,
                seed=args.seed, learning_steps=args.learning_steps, fixed_difficulty=args.fixed_difficulty)
            result = progress(args.study)
        elif args.command == "next":
            result = show_next(args.study, args.participant)
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
        elif args.command == "answer":
            display = json.loads(args.decision.read_text(encoding="utf-8-sig"))
            result = submit_answer(args.study, display["decision"], args.answer, duration_seconds=args.duration_seconds)
        elif args.command == "conduct":
            conduct(args.study, args.participant)
            return
        elif args.command == "progress":
            result = progress(args.study)
        else:
            result = export_study(args.study, args.output_dir, minimum_per_arm=args.minimum_per_arm)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
