"""Print material chunks to make human labelling of rag_eval.json straightforward."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.models import LearningChunk, LearningMaterial


def main() -> int:
    parser = argparse.ArgumentParser(description="列出资料分段 ID，供 RAG 评测集标注使用")
    parser.add_argument("--material-id", type=int, required=True, help="资料 ID")
    parser.add_argument("--preview", type=int, default=160, help="每段预览字符数")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出完整分段")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        material = db.query(LearningMaterial).filter(LearningMaterial.id == args.material_id).first()
        if material is None:
            print(f"资料 {args.material_id} 不存在", file=sys.stderr)
            return 2
        chunks = db.query(LearningChunk).filter(
            LearningChunk.material_id == args.material_id
        ).order_by(LearningChunk.chunk_index).all()
        rows = [{"id": chunk.id, "chunk_index": chunk.chunk_index, "topic_id": chunk.topic_id,
                 "content": chunk.content} for chunk in chunks]
        if args.json:
            print(json.dumps({"material_id": material.id, "title": material.title, "chunks": rows},
                             ensure_ascii=False, indent=2))
            return 0
        print(f"资料 {material.id}: {material.title}（共 {len(rows)} 段）")
        for row in rows:
            preview = " ".join(row["content"].split())[:args.preview]
            print(f"[{row['id']}] chunk={row['chunk_index']} topic={row['topic_id']}: {preview}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
