from app.database import SessionLocal
from app.services.topic_mastery import update_topic_mastery


db = SessionLocal()

try:
    mastery = update_topic_mastery(
        user_id=13,
        topic_id=1,
        db=db
    )

    if mastery is None:
        print("当前知识点还没有答题记录")

    else:
        print("\n========== TopicMastery ==========")
        print("用户ID:", mastery.user_id)
        print("知识点ID:", mastery.topic_id)
        print("答题次数:", mastery.attempt_count)
        print("正确率:", mastery.correct_rate)
        print("掌握度:", mastery.mastery_score)

finally:
    db.close()