from app.database import SessionLocal
from app.services.retriever import search_similar_chunks

db = SessionLocal()

query = "装饰器有什么作用？"
material_id = 3   # 改成你刚才创建的 Python基础知识 的实际 ID

thresholds = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]

for threshold in thresholds:

    print("\n==============================")
    print("Threshold =", threshold)
    print("==============================")

    results = search_similar_chunks(
        query=query,
        material_id=material_id,
        db=db,
        top_k=3,
        similarity_threshold=threshold
    )

    print("返回结果数量：", len(results))

    for result in results:
        print("相似度：", result["similarity"])
        print("Chunk：", result["chunk"].content[:100])
        print("--------------------")

db.close()
