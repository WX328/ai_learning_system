"""SELECT-only association audit; aggregate output, no repair/backfill mode."""
import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3


def audit(database):
    path = Path(database).resolve(strict=True)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    results = {}
    with closing(sqlite3.connect(path.as_uri()+"?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        for name, table in (("questions", "questions"), ("first_answers", "question_attempts"), ("reviews", "review_attempts")):
            is_question = table == "questions"
            sql = ("SELECT q.id AS question_id,q.topic_id,q.material_id,m.id AS material_exists,"
                   "t.id AS topic_exists,t.material_id AS topic_material,m.user_id AS owner_id,")
            sql += "NULL AS learner_id FROM questions q " if is_question else f"a.user_id AS learner_id FROM {table} a LEFT JOIN questions q ON q.id=a.question_id "
            sql += "LEFT JOIN learning_materials m ON m.id=q.material_id LEFT JOIN topics t ON t.id=q.topic_id"
            counts = Counter()
            for row in db.execute(sql):
                if row["question_id"] is None:
                    reason = "missing_question"
                elif row["material_exists"] is None:
                    reason = "missing_material"
                elif not is_question and row["learner_id"] != row["owner_id"]:
                    reason = "invalid_ownership"
                elif row["topic_id"] is None:
                    reason = "null_topic"
                elif row["topic_exists"] is None:
                    reason = "missing_topic"
                elif row["topic_material"] != row["material_id"]:
                    reason = "cross_material_topic"
                else:
                    reason = "valid"
                counts[reason] += 1
            results[name] = {"total": sum(counts.values()), "categories": dict(sorted(counts.items()))}
        results["duplicate_topic_name_groups"] = db.execute(
            "SELECT COUNT(*) FROM (SELECT material_id,name FROM topics GROUP BY material_id,name HAVING COUNT(*)>1)").fetchone()[0]
        db.rollback()
    return {"source": "read_only_production_snapshot", "database_sha256_before": before,
        "database_sha256_after": hashlib.sha256(path.read_bytes()).hexdigest(), "counts": results,
        "classification": "exclusive first matching reason; NULL question topic is not inferred from text",
        "limitations": "External concurrent writes may change file hashes; no historical entrypoint provenance is available."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.database)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(result["counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
