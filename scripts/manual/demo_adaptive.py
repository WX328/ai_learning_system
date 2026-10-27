from app.database import SessionLocal
from app.services.adaptive import (
    get_topic_recent_correct_rate,
    get_next_topic_difficulty
)


db = SessionLocal()

try:

    topic_id = 9
    user_id = 1

    rate = get_topic_recent_correct_rate(
        user_id=user_id,
        topic_id=topic_id,
        db=db
    )

    print("Topic正确率:", rate)

    difficulty = get_next_topic_difficulty(
        user_id=user_id,
        topic_id=topic_id,
        current_difficulty=2,
        db=db
    )

    print("下一题难度:", difficulty)

finally:
    db.close()