from app.services.topic_extractor import extract_topics,save_topics
from app.database import SessionLocal


content = """
Python装饰器是一种设计模式。

装饰器本质上是一个函数，
它接收一个函数作为参数，
并返回一个新的函数。

装饰器可以在不修改原函数代码的情况下增强函数功能。

Python使用 @ 语法来使用装饰器。
"""


db = SessionLocal()

try:
    topics = extract_topics(content)

    saved_topics = save_topics(
        material_id=1,
        topics=topics,
        db=db
    )

    print("\n========== 保存结果 ==========")

    for topic in saved_topics:
        print("ID:", topic.id)
        print("名称:", topic.name)
        print("描述:", topic.description)

finally:
    db.close()