from app.database import SessionLocal
from app.services.adaptive import get_weak_topics


db = SessionLocal()

try:
    weak_topics = get_weak_topics(
        user_id=1,
        db=db
    )

    print("\n========== 薄弱知识点 ==========")

    if not weak_topics:
        print("当前没有发现薄弱知识点")

    else:
        for mastery, topic in weak_topics:
            print(
                "知识点:",
                topic.name
            )
            print(
                "掌握度:",
                mastery.mastery_score
            )
            print(
                "正确率:",
                mastery.correct_rate
            )
            print(
                "答题次数:",
                mastery.attempt_count
            )
            print("--------------------")

finally:
    db.close()