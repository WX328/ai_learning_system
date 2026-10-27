"""One-off rebuild of every material's vector index with the new chunker + embedding config.

Run from the project root:  python rebuild_embeddings.py
Replaces existing chunks (topic links are reset; re-run topic extraction to re-link).
"""
import json

from app.database import SessionLocal
from app.models import LearningChunk, LearningMaterial
from app.services.chunker import split_text
from app.services.embedding import EmbeddingError, embed_texts


def rebuild():
    db = SessionLocal()
    total = 0
    failed = []
    try:
        materials = db.query(LearningMaterial).order_by(LearningMaterial.id).all()
        for material in materials:
            chunks = split_text(material.content)
            if not chunks:
                print(f"material {material.id} skipped (empty)")
                continue
            try:
                vectors = embed_texts(chunks)
            except EmbeddingError as exc:
                failed.append((material.id, str(exc)))
                print(f"material {material.id} FAILED: {exc}")
                continue
            db.query(LearningChunk).filter(
                LearningChunk.material_id == material.id
            ).delete()
            for index, (content, vector) in enumerate(zip(chunks, vectors)):
                db.add(LearningChunk(
                    material_id=material.id,
                    chunk_index=index,
                    content=content,
                    embedding=json.dumps(vector),
                    topic_id=None,
                ))
            db.commit()
            total += len(chunks)
            print(f"material {material.id} '{material.title[:20]}': {len(chunks)} chunks")
        print(f"TOTAL: {total} chunks rebuilt across {len(materials)} materials")
        if failed:
            print(f"FAILED: {failed}")
    finally:
        db.close()


if __name__ == "__main__":
    rebuild()
