"""Small-study protocol and local facilitator workflow, entirely outside the app DB."""
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import random
from statistics import mean

from evaluation.adaptive_replay import assess, check_id, digest, time_value
from app.services.topic_mastery import mastery_priority, MODEL_VERSION

PROTOCOL = "learning_experiment_v1"
COLUMNS = ("participant_id", "phase", "item_id", "timestamp", "correct", "actual_difficulty",
           "requested_difficulty", "duration_seconds", "decision_id")


def validate_bank(bank):
    items = bank["items"]
    ids, contents, families = set(), set(), set()
    blueprint = {p: Counter() for p in ("A", "B", "learning")}
    for item in items:
        for k in ("item_id", "topic_id", "content_hash", "family_id"):
            check_id(item[k])
        if item["pool"] not in blueprint or type(item["difficulty"]) is not int or item["difficulty"] not in range(1, 6):
            raise ValueError("invalid item pool or difficulty")
        for value, seen in ((item["item_id"], ids), (item["content_hash"], contents), (item["family_id"], families)):
            if value in seen:
                raise ValueError("reused item, content or question family; pre/learning/post must be disjoint")
            seen.add(value)
        blueprint[item["pool"]][item["topic_id"], item["difficulty"]] += 1
    if not blueprint["A"] or blueprint["A"] != blueprint["B"]:
        raise ValueError("A/B forms require matching topic/difficulty counts")
    topics = {topic for topic, _ in blueprint["A"]}
    if topics != {topic for topic, _ in blueprint["learning"]}:
        raise ValueError("test and learning topics must match")
    for topic in topics:
        if {d for t, d in blueprint["learning"] if t == topic} != set(range(1, 6)):
            raise ValueError("learning bank must cover difficulty 1..5 for each topic")
    return items


def make_plan(bank, participants, *, seed=20261023, fixed_difficulty=2, learning_steps=12, source="real_experiment"):
    validate_bank(bank)
    if source not in {"real_experiment", "synthetic_experiment", "demo_experiment"}:
        raise ValueError("explicit experiment source required")
    if source != "synthetic_experiment":
        from evaluation.experiment_bank import validate_actual_bank
        validate_actual_bank(bank, require_approved=source == "real_experiment")
        if source == "demo_experiment" and bank["data_kind"] != "demo":
            raise ValueError("demonstration sessions require a demo bank")
    if not participants or len(set(participants)) != len(participants):
        raise ValueError("participant research codes must be nonempty and unique")
    for code in participants:
        check_id(code)
    if type(fixed_difficulty) is not int or fixed_difficulty not in range(1, 6) or type(learning_steps) is not int or learning_steps < 1:
        raise ValueError("invalid fixed difficulty or learning steps")
    fixed_items = [item for item in bank["items"] if item["pool"] == "learning" and item["difficulty"] == fixed_difficulty]
    if len(fixed_items) < learning_steps:
        raise ValueError("not enough distinct fixed-level items for learning_steps")
    rng = random.Random(seed)
    codes = sorted(participants)
    rng.shuffle(codes)
    # Each full block balances both arms and A/B versus B/A forms.
    combinations = [("fixed", "A"), ("adaptive", "B"), ("adaptive", "A"), ("fixed", "B")]
    assignments = []
    for offset in range(0, len(codes), 4):
        block = combinations.copy()
        rng.shuffle(block)
        # For the final two participants still balance arms.
        if len(codes)-offset == 2:
            block = [rng.choice([v for v in combinations if v[0] == arm]) for arm in ("fixed", "adaptive")]
            rng.shuffle(block)
        for code, (arm, pre) in zip(codes[offset:offset+4], block):
            assignments.append({"participant_id": code, "arm": arm, "pre_form": pre,
                                "post_form": "B" if pre == "A" else "A"})
    return {"protocol": PROTOCOL, "source": source, "seed": seed,
        "production_model": MODEL_VERSION, "fixed_difficulty": fixed_difficulty,
        "learning_steps": learning_steps, "bank": bank, "bank_sha256": digest(bank),
        "assignments": sorted(assignments, key=lambda r: r["participant_id"]),
        "instructions": "Same rules_v2 topic priority in both arms; only difficulty policy differs. Pre/post evidence is not fed into learning. No pre/post feedback until post-test completed."}


def validate_plan(plan):
    if plan.get("protocol") != PROTOCOL or plan.get("production_model") != MODEL_VERSION:
        raise ValueError("unsupported experiment/model version")
    # Regeneration detects changed seed, assignments, bank, source and configuration.
    expected = make_plan(plan["bank"], [p["participant_id"] for p in plan["assignments"]],
        seed=plan["seed"], fixed_difficulty=plan["fixed_difficulty"],
        learning_steps=plan["learning_steps"], source=plan["source"])
    if plan != expected:
        raise ValueError("plan changed or does not match deterministic assignment")


def _next(plan, records, participant):
    assignment = next((p for p in plan["assignments"] if p["participant_id"] == participant), None)
    if assignment is None:
        raise ValueError("participant not assigned")
    rows = [r for r in records if r["participant_id"] == participant]
    items = plan["bank"]["items"]
    item_map = {item["item_id"]: item for item in items}
    used = {r["item_id"] for r in rows}
    phase = None
    for candidate in ("pre", "learning", "post"):
        count = sum(r["phase"] == candidate for r in rows)
        limit = plan["learning_steps"] if candidate == "learning" else sum(
            item["pool"] == assignment[f"{candidate}_form"] for item in items)
        if count < limit:
            phase = candidate
            break
    if phase is None:
        return {"status": "complete", "participant_id": participant}
    if phase in {"pre", "post"}:
        candidates = [item for item in items if item["pool"] == assignment[f"{phase}_form"] and item["item_id"] not in used]
        chosen = sorted(candidates, key=lambda item: (item["topic_id"], item["difficulty"], item["item_id"]))[0]
        requested = chosen["difficulty"]
    else:
        candidates = [item for item in items if item["pool"] == "learning" and item["item_id"] not in used
                      and (assignment["arm"] != "fixed" or item["difficulty"] == plan["fixed_difficulty"])]
        if not candidates:
            return {"status": "bank_exhausted", "participant_id": participant, "phase": phase}
        histories = defaultdict(list)
        for r in rows:
            if r["phase"] == "learning":
                item = item_map[r["item_id"]]
                histories[item["topic_id"]].append({"question_id": item["item_id"], "correct": r["correct"] == "1",
                    "difficulty": item["difficulty"], "_time": time_value(r["timestamp"])})
        states = {t: assess(histories[t], [], MODEL_VERSION) for t in {item["topic_id"] for item in candidates}}
        topic = min(states, key=lambda t: mastery_priority(states[t]["score"], states[t]["count"], t))
        requested = plan["fixed_difficulty"] if assignment["arm"] == "fixed" else states[topic]["difficulty"]
        chosen = min((item for item in candidates if item["topic_id"] == topic),
                     key=lambda item: (abs(item["difficulty"]-requested), item["difficulty"], item["item_id"]))
    result = {"status": "ready", "participant_id": participant, "arm": assignment["arm"],
        "phase": phase, "step": len(rows)+1, "item_id": chosen["item_id"], "topic_id": chosen["topic_id"],
        "requested_difficulty": requested, "actual_difficulty": chosen["difficulty"],
        "deviation": None if requested == chosen["difficulty"] else "requested level exhausted; nearest available, lower on ties",
        "plan_sha256": digest(plan), "history_sha256": digest(rows)}
    result["decision_id"] = digest(result)
    return result


def validate_records(plan, records):
    validate_plan(plan)
    prefix, latest = [], {}
    for raw in records:
        if set(raw) != set(COLUMNS):
            raise ValueError("record columns do not match schema")
        if raw["correct"] not in {"0", "1"}:
            raise ValueError("correct must be 0 or 1")
        participant = raw["participant_id"]
        timestamp = time_value(raw["timestamp"])
        if participant in latest and timestamp <= latest[participant]:
            raise ValueError("participant record timestamps must strictly increase")
        duration = float(raw["duration_seconds"]) if raw["duration_seconds"] else None
        if duration is not None and (not 0 <= duration < float("inf")):
            raise ValueError("duration must be finite and nonnegative")
        expected = _next(plan, prefix, participant)
        if expected["status"] != "ready" or any(str(expected[k]) != raw[k] for k in
                ("phase", "item_id", "actual_difficulty", "requested_difficulty", "decision_id")):
            raise ValueError("record does not match prefix decision (stale, duplicate, wrong phase/item or altered plan)")
        prefix.append(raw)
        latest[participant] = timestamp


def next_item(plan, records, participant):
    validate_records(plan, records)
    return _next(plan, records, participant)


def record_decision(plan, records, decision, correct, *, timestamp=None, duration_seconds=None):
    validate_records(plan, records)
    if type(correct) is not bool:
        raise ValueError("correct must be boolean")
    expected = _next(plan, records, decision["participant_id"])
    if expected != decision or expected["status"] != "ready":
        raise ValueError("stale or changed decision")
    row = {"participant_id": decision["participant_id"], "phase": decision["phase"], "item_id": decision["item_id"],
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(), "correct": str(int(correct)),
        "actual_difficulty": str(decision["actual_difficulty"]), "requested_difficulty": str(decision["requested_difficulty"]),
        "duration_seconds": "" if duration_seconds is None else str(duration_seconds), "decision_id": decision["decision_id"]}
    updated = [*records, row]
    validate_records(plan, updated)
    return updated


def load_records(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(COLUMNS):
            raise ValueError("record CSV header mismatch")
        return list(reader)


def write_records(path, records):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(records)
    temporary.replace(path)


def analyze(plan, records, *, minimum_per_arm=5):
    if type(minimum_per_arm) is not int or minimum_per_arm < 2:
        raise ValueError("minimum_per_arm must be at least two")
    validate_records(plan, records)
    participants = []
    for p in plan["assignments"]:
        rows = [r for r in records if r["participant_id"] == p["participant_id"]]
        complete = _next(plan, records, p["participant_id"])["status"] == "complete"
        counts = {phase: sum(r["phase"] == phase for r in rows) for phase in ("pre", "learning", "post")}
        scores = {phase: mean(int(r["correct"]) for r in rows if r["phase"] == phase) if counts[phase] else None
                  for phase in ("pre", "post")}
        participants.append({**p, "complete": complete, "counts": counts, "pre_score": scores["pre"],
            "post_score": scores["post"], "gain": scores["post"]-scores["pre"] if complete else None,
            "bank_deviations": sum(r["actual_difficulty"] != r["requested_difficulty"] for r in rows),
            "duration_recorded_n": sum(bool(r["duration_seconds"]) for r in rows)})
    groups = {}
    for arm in ("fixed", "adaptive"):
        assigned = [p for p in participants if p["arm"] == arm]
        complete = [p for p in assigned if p["complete"]]
        groups[arm] = {"assigned": len(assigned), "started": sum(any(p["counts"].values()) for p in assigned),
            "complete": len(complete), "incomplete": len(assigned)-len(complete),
            "mean_pre": mean(p["pre_score"] for p in complete) if complete else None,
            "mean_post": mean(p["post_score"] for p in complete) if complete else None,
            "mean_gain": mean(p["gain"] for p in complete) if complete else None}
    enough = all(g["complete"] >= minimum_per_arm for g in groups.values())
    difference = groups["adaptive"]["mean_gain"] - groups["fixed"]["mean_gain"] if enough else None
    ci = None
    if enough:
        # Participant-level resampling. No item-level pseudo-replication.
        rng = random.Random(plan["seed"])
        gains = {arm: [p["gain"] for p in participants if p["arm"] == arm and p["complete"]] for arm in groups}
        samples = sorted(mean(rng.choices(gains["adaptive"], k=len(gains["adaptive"]))) -
                         mean(rng.choices(gains["fixed"], k=len(gains["fixed"]))) for _ in range(2000))
        ci = [samples[49], samples[1949]]
    return {"protocol": PROTOCOL, "source": plan["source"], "plan_sha256": digest(plan),
        "records_sha256": digest(records), "participants": participants, "groups": groups,
        "gain_difference": {"value": difference, "status": "descriptive" if enough else "not_evaluable",
            "minimum_complete_per_arm": minimum_per_arm, "bootstrap_95_percentile": ci,
            "reason": None if enough else "insufficient complete participants per arm"},
        "limitations": ["Not a claim of improved learning; inspect baseline balance, attrition and form equivalence.",
            "Correctness is facilitator-recorded; metadata/hash checks cannot verify human grading or form equivalence.",
            "Synthetic experiment records never constitute real learner evidence.",
            "Bootstrap interval is exploratory, participant-level, and unreliable with very small samples."]}


def write_analysis(report, path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    (path / "experiment.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    lines = ["# S3 学习实验报告", "", f"来源：`{report['source']}`；协议：`{report['protocol']}`。", "",
        "| 模式 | 已分配 | 已开始 | 完整前测/学习/后测 | 不完整 | 前测均分 | 后测均分 | 平均增量 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    fmt = lambda x: "不可评估" if x is None else f"{x:.4f}"
    for name, g in report["groups"].items():
        lines.append(f"| {name} | {g['assigned']} | {g['started']} | {g['complete']} | {g['incomplete']} | {fmt(g['mean_pre'])} | {fmt(g['mean_post'])} | {fmt(g['mean_gain'])} |")
    effect = report["gain_difference"]
    lines += ["", f"自适应减固定的平均增量差：{fmt(effect['value'])}；状态：{effect['status']}。",
        f"参与者级探索性 bootstrap 区间：{effect['bootstrap_95_percentile']}；每组至少完整 {effect['minimum_complete_per_arm']} 人。", "",
        "所有均分只针对完整参与者；分配与退出样本数同时披露。不能将离线分数优势或模拟增量声称为真实学习提升。", ""]
    lines += [f"- {s}" for s in report["limitations"]]
    (path / "experiment.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    with (path / "participants.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        fields = ["participant_id", "arm", "pre_form", "post_form", "complete", "pre_score", "post_score", "gain", "bank_deviations"]
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report["participants"])
