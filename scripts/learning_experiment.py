"""Facilitator CLI: plan -> next -> record -> analyze. No web server or model API."""
import argparse
import json
from pathlib import Path

from evaluation.learning_experiment import (make_plan, next_item, record_decision,
    load_records, write_records, analyze, write_analysis)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--bank", type=Path, required=True)
    plan.add_argument("--participants", type=Path, required=True, help="JSON array of research codes, no real names")
    plan.add_argument("--output-dir", type=Path, required=True)
    plan.add_argument("--source", choices=("real_experiment", "synthetic_experiment"), required=True)
    plan.add_argument("--seed", type=int, default=20261023)
    plan.add_argument("--fixed-difficulty", type=int, default=2)
    plan.add_argument("--learning-steps", type=int, default=12)
    for name in ("next", "record", "analyze"):
        command = commands.add_parser(name)
        command.add_argument("--plan", type=Path, required=True)
        command.add_argument("--records", type=Path, required=True)
        if name == "next":
            command.add_argument("--participant", required=True)
            command.add_argument("--output", type=Path, required=True)
        elif name == "record":
            command.add_argument("--decision", type=Path, required=True)
            command.add_argument("--correct", type=int, choices=(0, 1), required=True)
            command.add_argument("--timestamp", help="ISO8601 with timezone, default current UTC")
            command.add_argument("--duration-seconds", type=float)
        else:
            command.add_argument("--output-dir", type=Path, required=True)
            command.add_argument("--minimum-per-arm", type=int, default=5)
    args = parser.parse_args()
    if args.command == "plan":
        result = make_plan(json.loads(args.bank.read_text(encoding="utf-8")),
            json.loads(args.participants.read_text(encoding="utf-8")), seed=args.seed,
            fixed_difficulty=args.fixed_difficulty, learning_steps=args.learning_steps, source=args.source)
        args.output_dir.mkdir(parents=True, exist_ok=False)
        (args.output_dir / "plan.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        write_records(args.output_dir / "records.csv", [])
        print(f"Created {args.output_dir}; only research codes, no production account changes")
        return
    current_plan = json.loads(args.plan.read_text(encoding="utf-8"))
    if args.command == "record":
        # Prevent lost updates by concurrent facilitator processes. A stale
        # decision still fails after the lock and fresh CSV read.
        lock = args.records.with_name(args.records.name + ".lock")
        try:
            lock_handle = lock.open("x", encoding="utf-8")
        except FileExistsError:
            parser.error("record writer is busy (or a stale .lock needs inspection)")
        try:
            with lock_handle:
                records = load_records(args.records)
                updated = record_decision(current_plan, records, json.loads(args.decision.read_text(encoding="utf-8")),
                    bool(args.correct), timestamp=args.timestamp, duration_seconds=args.duration_seconds)
                write_records(args.records, updated)
        finally:
            lock.unlink()
        print(f"Recorded one observation; rows={len(updated)}")
        return
    records = load_records(args.records)
    if args.command == "next":
        result = next_item(current_plan, records, args.participant)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
    else:
        report = analyze(current_plan, records, minimum_per_arm=args.minimum_per_arm)
        write_analysis(report, args.output_dir)
        print(json.dumps(report["gain_difference"], ensure_ascii=False))


if __name__ == "__main__":
    main()
