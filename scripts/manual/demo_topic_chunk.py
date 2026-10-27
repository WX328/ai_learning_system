from app.database import SessionLocal
from app.services.topic_chunk import assign_chunks_to_topics


db = SessionLocal()

try:
    chunks = assign_chunks_to_topics(
        material_id=1,
        db=db
    )

    print("\n========== 最终结果 ==========")

    for chunk in chunks:
        print(
            "Chunk ID:",
            chunk.id,
            "Topic ID:",
            chunk.topic_id
        )

finally:
    db.close()