from app.database import SessionLocal
from app.services.adaptive import get_weakest_topic


db = SessionLocal()

try:
    result = get_weakest_topic(
        user_id=1,
        db=db
    )

    print("\n========== 最薄弱知识点 ==========")

    if result is None:
        print("当前没有薄弱知识点")

    else:
        print("知识点ID:", result["topic_id"])
        print("知识点:", result["topic_name"])
        print("掌握度:", result["mastery_score"])
        print("正确率:", result["correct_rate"])
        print("答题次数:", result["attempt_count"])

finally:
    db.close()