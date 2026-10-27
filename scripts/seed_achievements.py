"""Explicit starter definitions for an empty achievement catalog; no user XP writes."""


def seed(db):
    from app.models import Achievement
    if db.query(Achievement.id).first() is not None:
        return 0
    db.add_all([
        Achievement(name="初次练习", description="完成第一道练习", xp_reward=5,
                    condition_type="answer_count", condition_value=1),
        Achievement(name="持续练习", description="累计完成十道练习", xp_reward=20,
                    condition_type="answer_count", condition_value=10),
        Achievement(name="连续答对", description="连续答对三道练习", xp_reward=10,
                    condition_type="correct_streak", condition_value=3),
    ])
    db.commit()
    return 3


def main():
    from app.database import SessionLocal
    with SessionLocal() as db:
        print(f"Starter achievement definitions created: {seed(db)}")


if __name__ == "__main__":
    main()
