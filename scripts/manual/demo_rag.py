from app.database import SessionLocal
from app.services.rag import rag_answer

db = SessionLocal()

answer = rag_answer(
    query="装饰器有什么作用？",
    material_id=1,
    db=db,
    top_k=3
)

print("AI回答：")
print(answer)

db.close()