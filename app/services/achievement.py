from app.models import Achievement, UserAchievement


def check_achievements(
    user_id: int,
    db,
    answer_count: int,
    correct_streak:int
):
    achievements = db.query(Achievement).all()

    new_achievements = []

    for achievement in achievements:

        # 1. 判断用户是否已经获得这个成就
        user_achievement = db.query(UserAchievement).filter(
            UserAchievement.user_id == user_id,
            UserAchievement.achievement_id == achievement.id
        ).first()

        if user_achievement is not None:
            continue

        # 2. 根据成就类型判断条件
        condition_met = False

        if achievement.condition_type == "answer_count":
            condition_met = (
                answer_count >= achievement.condition_value
            )

        elif achievement.condition_type =="correct_streak":
            condition_met = (
                correct_streak >= achievement.condition_value
            )

        # 3. 如果条件满足，就解锁成就
        if condition_met:
            user_achievement = UserAchievement(
                user_id=user_id,
                achievement_id=achievement.id
            )

            db.add(user_achievement)

            new_achievements.append(achievement)

    return new_achievements