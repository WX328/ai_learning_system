"""Export minimal pseudonymous events from an explicitly selected SQLite file.

Only SELECTs in a read-only snapshot; no ORM, startup hooks or production writes.
Names, question text, answers, hashes, credentials, XP and conversations are never
selected. Pseudonymization is not anonymization: keep exports access controlled.
"""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sqlite3


def utc(value):
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).isoformat()


def export_history(database, *, user_ids=(), key=None):
    path = Path(database).resolve(strict=True)
    key = secrets.token_bytes(32) if key is None else key
    if len(key) < 32:
        raise ValueError("pseudonym key must contain at least 32 bytes")

    def pseudonym(kind, value):
        token = hmac.new(key, f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()[:24]
        return f"{kind}-{token}"

    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")  # One snapshot even if the application is concurrently writing.
        counts = {}
        events, skipped = [], Counter()
        # All identifiers in SQL are constants; user scope uses bound parameters.
        for kind, table in (("first", "question_attempts"), ("review", "review_attempts")):
            sql = f"""SELECT a.id,a.user_id,a.question_id,a.is_correct,a.created_at,
                      q.material_id,q.topic_id,q.difficulty,m.user_id AS owner_id,
                      t.material_id AS topic_material_id
                      FROM {table} a
                      LEFT JOIN questions q ON q.id=a.question_id
                      LEFT JOIN learning_materials m ON m.id=q.material_id
                      LEFT JOIN topics t ON t.id=q.topic_id"""
            params = tuple(user_ids)
            if params:
                sql += " WHERE a.user_id IN (" + ",".join("?" for _ in params) + ")"
            rows = db.execute(sql, params).fetchall()
            counts[kind] = len(rows)
            for row in rows:
                if row["owner_id"] != row["user_id"] or row["topic_material_id"] != row["material_id"] or row["topic_id"] is None:
                    skipped["missing_topic_or_invalid_ownership_or_link"] += 1
                    continue
                if row["is_correct"] not in (0, 1) or not isinstance(row["difficulty"], int) or row["difficulty"] not in range(1, 6):
                    skipped["invalid_outcome_or_difficulty"] += 1
                    continue
                try:
                    timestamp = utc(row["created_at"])
                except (ValueError, TypeError):
                    skipped["invalid_timestamp"] += 1
                    continue
                events.append({"id": pseudonym(kind, row["id"]), "order": row["id"],
                    "learner_id": pseudonym("learner", row["user_id"]),
                    "material_id": pseudonym("material", row["material_id"]),
                    "topic_id": pseudonym("topic", row["topic_id"]),
                    "question_id": pseudonym("question", row["question_id"]),
                    "kind": kind, "timestamp": timestamp,
                    "difficulty": row["difficulty"], "correct": bool(row["is_correct"])})
        db.rollback()
    # A conservative catalog: never introduce a topic before its first observed
    # answer. Existing Topic.created_at uses an import-time default and cannot
    # reliably reconstruct historic topic availability.
    first_seen = {}
    for e in events:
        if e["kind"] == "first":
            k = (e["learner_id"], e["material_id"], e["topic_id"])
            first_seen[k] = min(first_seen.get(k, e["timestamp"]), e["timestamp"])
    kept = []
    for e in events:
        k = e["learner_id"], e["material_id"], e["topic_id"]
        if k not in first_seen or e["timestamp"] < first_seen[k]:
            skipped["review_before_observed_topic"] += 1
        else:
            kept.append(e)
    return {"schema_version": 1, "source": {"kind": "real_history",
        "description": "Read-only scoped SQLite snapshot; pseudonymous observational records",
        "catalog_policy": "topic becomes available at first observed first-answer timestamp",
        "topic_tie_break": "opaque topic ID; original numeric ID ordering is not exported",
        "privacy": "HMAC pseudonyms; no question text, answer text or account credentials",
        "coverage": {"read_rows": counts, "exported_events": len(kept), "skipped": dict(skipped)}},
        "topics": [{"learner_id": k[0], "material_id": k[1], "topic_id": k[2], "available_at": t}
                   for k, t in sorted(first_seen.items())],
        "events": sorted(kept, key=lambda e: (e["timestamp"], e["order"], e["id"]))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--user-id", type=int, action="append", default=[])
    parser.add_argument("--pseudonym-key-file", type=Path,
                        help="optional private >=32-byte key for stable pseudonyms across exports")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; choose a new path")
    report = export_history(args.database, user_ids=args.user_id,
                            key=args.pseudonym_key_file.read_bytes() if args.pseudonym_key_file else None)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(report["source"]["coverage"], ensure_ascii=False))


if __name__ == "__main__":
    main()
