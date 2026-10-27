"""Reviewable actual items. No model calls, production DB or inferred labels."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
import unicodedata

SCHEMA = "reviewed_question_bank_v1"
CHECKS = ("content", "topic", "difficulty", "form_equivalence", "family_disjoint")
LABELS = ("A", "B", "C", "D")


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def normalized(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip().casefold()


def content_hash(item):
    # Ignore labels/order; relabeling the same choices cannot evade duplication.
    return fingerprint([normalized(item["stem"]), sorted(normalized(v) for v in item["options"].values())])


def review_hash(item):
    return fingerprint({k: v for k, v in item.items() if k not in {"review", "content_hash"}})


def required_text(value, name, limit=20000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"invalid {name}")


def validate_actual_bank(bank, *, require_approved=False):
    from evaluation.learning_experiment import validate_bank
    if bank.get("schema_version") != SCHEMA or bank.get("data_kind") not in {"demo", "real_candidate"}:
        raise ValueError("an actual reviewed question bank with an explicit data_kind is required")
    required_text(bank.get("bank_id"), "bank_id", 128)
    required_text(bank.get("version"), "version", 128)
    topics = bank.get("topics", {})
    if not isinstance(topics, dict) or not topics:
        raise ValueError("topic definitions required")
    for key, value in topics.items():
        required_text(key, "topic_id", 128)
        required_text(value, "topic definition")
    stems, families = set(), set()
    for item in bank["items"]:
        required_text(item.get("stem"), "stem")
        stem = normalized(item["stem"])
        required_text(item.get("family_id"), "family_id", 128)
        family = normalized(item["family_id"])
        if stem in stems or family in families:
            raise ValueError("reused question stem or normalized family; review bank disjointness")
        stems.add(stem)
        families.add(family)
        required_text(item.get("explanation"), "explanation")
        if item.get("topic_id") not in topics:
            raise ValueError("item topic is not defined")
        options = item.get("options")
        if not isinstance(options, dict) or set(options) != set(LABELS) or item.get("answer") not in LABELS:
            raise ValueError("four labeled choices and one answer required")
        for value in options.values():
            required_text(value, "choice")
        if len({normalized(v) for v in options.values()}) != 4:
            raise ValueError("duplicate answer choices")
        provenance = item.get("provenance", {})
        if provenance.get("kind") not in {"ai_generated", "human_authored", "reference_adapted"}:
            raise ValueError("explicit item provenance required")
        required_text(provenance.get("reference"), "provenance reference")
        review = item.get("review", {})
        if review.get("status") not in {"draft", "pending_review", "approved", "rejected"}:
            raise ValueError("explicit review status required")
        if review["status"] == "approved":
            required_text(review.get("reviewer"), "human reviewer code", 128)
            when = datetime.fromisoformat(review.get("reviewed_at", ""))
            if when.tzinfo is None:
                raise ValueError("review time must have timezone")
            if review.get("content_sha256") != review_hash(item):
                raise ValueError("item changed since approval; re-review required")
            if set(review.get("checks", {})) != set(CHECKS) or any(review["checks"][c] is not True for c in CHECKS):
                raise ValueError("all human review checks required")
        elif require_approved:
            raise ValueError(f"item {item['item_id']} has no valid human approval")
        if item.get("content_hash") != content_hash(item):
            raise ValueError("content_hash differs from normalized actual question")
    validate_bank(bank)  # S3 owns blueprint, distinct family and difficulty rules.
    if require_approved and bank["data_kind"] != "real_candidate":
        raise ValueError("demo bank cannot be used for real experiments")
    return bank


def prepare_bank(bank):
    """Compute machine fingerprints; does not grant human approval."""
    result = deepcopy(bank)
    for item in result["items"]:
        item["content_hash"] = content_hash(item)
    validate_actual_bank(result)
    return result


def review_item(bank, item_id, *, reviewer, checks, approved, note=""):
    result = prepare_bank(bank)
    required_text(reviewer, "human reviewer code", 128)
    if type(approved) is not bool:
        raise ValueError("explicit approval/rejection required")
    item = next((i for i in result["items"] if i["item_id"] == item_id), None)
    if item is None:
        raise ValueError("unknown item")
    if approved and (set(checks) != set(CHECKS) or any(checks[k] is not True for k in CHECKS)):
        raise ValueError("complete each human review check before approval")
    previous = item.get("review", {})
    item["review"] = {"status": "approved" if approved else "rejected", "reviewer": reviewer,
        "reviewed_at": datetime.now(timezone.utc).isoformat(), "checks": checks,
        "content_sha256": review_hash(item), "note": note,
        "previous_review_sha256": fingerprint(previous)}
    validate_actual_bank(result)
    return result


def public_question(bank, item_id):
    item = next(i for i in bank["items"] if i["item_id"] == item_id)
    # Participant display allowlist; no answer, explanation, provenance or review.
    return {k: deepcopy(item[k]) for k in ("item_id", "stem", "options")}


def review_packet(bank):
    validate_actual_bank(bank)
    lines = ["# 研究者审题册（含答案；禁止提供给参与者）", "",
        f"题库：{bank['bank_id']} / {bank['version']}；来源：{bank['data_kind']}。",
        "自动生成内容仍须人工逐题审核；难度与 A/B 等价性不是软件可以证明的。", ""]
    for item in bank["items"]:
        lines += [f"## {item['item_id']} · {item['pool']} · {item['topic_id']} · 难度 {item['difficulty']}",
            f"家族：{item['family_id']}；审核：{item['review']['status']}。", "", item["stem"], ""]
        lines += [f"- {k}: {item['options'][k]}" for k in LABELS]
        lines += ["", f"答案：{item['answer']}；解析：{item['explanation']}",
            f"来源：{item['provenance']}", f"待核验：{', '.join(CHECKS)}", ""]
    return "\n".join(lines)
