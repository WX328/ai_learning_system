from app.database import SessionLocal
from app.services.adaptive import (
    generate_question_for_weakest_topic
)


db = SessionLocal()

try:
    result = generate_question_for_weakest_topic(
        user_id=1,
        material_id=1,
        db=db
    )

    print("\n========== 自适应出题 ==========")

    if result is None:
        print("当前没有薄弱知识点")

    else:
        topic = result["topic"]
        question = result["question"]

        print("薄弱知识点:", topic["topic_name"])
        print("掌握度:", topic["mastery_score"])
        print("正确率:", topic["correct_rate"])

        print("\n========== 生成题目 ==========")
        print("题目:", question.question)
        print("A:", question.option_a)
        print("B:", question.option_b)
        print("C:", question.option_c)
        print("D:", question.option_d)
        print("答案:", question.answer)
        print("难度:", question.difficulty)
        print("Topic ID:", question.topic_id)

finally:
    db.close()