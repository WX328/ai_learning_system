"""Prepare, inspect and individually review actual experimental questions."""
import argparse
import json
from pathlib import Path
from evaluation.experiment_bank import (CHECKS, prepare_bank, review_item, review_packet,
                                        validate_actual_bank)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "validate", "packet", "review"):
        command = commands.add_parser(name)
        command.add_argument("--bank", type=Path, required=True)
        if name != "validate":
            command.add_argument("--output", type=Path, required=True)
        else:
            command.add_argument("--require-approved", action="store_true")
        if name == "review":
            command.add_argument("--item", required=True)
            command.add_argument("--reviewer", required=True, help="human reviewer research code")
            command.add_argument("--decision", choices=("approve", "reject"), required=True)
            command.add_argument("--checked", action="append", choices=CHECKS, default=[])
            command.add_argument("--note", default="")
    args = parser.parse_args()
    try:
        bank = json.loads(args.bank.read_text(encoding="utf-8-sig"))
        if args.command == "validate":
            validate_actual_bank(bank, require_approved=args.require_approved)
            print(f"Valid {bank['data_kind']} bank; items={len(bank['items'])}; approved gate={args.require_approved}")
            return
        if args.command == "prepare":
            result = prepare_bank(bank)
        elif args.command == "review":
            result = review_item(bank, args.item, reviewer=args.reviewer,
                checks={c: c in args.checked for c in CHECKS}, approved=args.decision == "approve", note=args.note)
        else:
            result = None
        output = review_packet(bank) if args.command == "packet" else json.dumps(result, ensure_ascii=False, indent=2)+"\n"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(output)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
