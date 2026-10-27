from app.database import SessionLocal
from app.services.question_generator import (
    generate_question_from_material,
    save_generated_question
)


db = SessionLocal()

try:
    question_data = generate_question_from_material(
        material_id=1,
        db=db,
        difficulty=2
    )

    print("\n========== AI生成题目 ==========")
    print(question_data)

    question = save_generated_question(
        material_id=1,
        question_data=question_data,
        db=db
    )

    print("\n========== 数据库保存成功 ==========")
    print("题目ID：", question.id)
    print("题目：", question.question)
    print("正确答案：", question.answer)

finally:
    db.close()