import json

from app.core.settings import deepseek_client

from app.schemas.question import QuestionAIOutput
from app.services.retriever import search_similar_chunks
from app.models import Question, Topic, LearningChunk, LearningMaterial
from app.services.adaptive import get_next_topic_difficulty


def require_question_topic(material_id, topic_id, db):
    """New questions need an explicit stable topic, never infer one from text."""
    if topic_id is None:
        raise ValueError("请先提取并选择知识点，再生成练习")
    selected = db.query(Topic).filter_by(id=topic_id, material_id=material_id).first()
    if selected is None:
        raise ValueError("知识点不存在或不属于该学习资料")
    return selected

def generate_question(
    context: str,
    difficulty: int = 1,
    topic: str | None = None
):
    prompt = f"""
出题主题：{topic or "学习资料中的核心知识"}
请围绕上述主题出题，其他内容仅作背景；不得编造资料中没有的信息。
你是一名专业的AI学习助手。

请根据下面提供的学习资料生成一道单项选择题。

学习资料：
{context}

要求：

1. 题目必须严格根据学习资料生成。
2. 不要加入学习资料中没有的信息。
3. 必须生成4个选项。
4. 只有一个正确答案。
5. 正确答案必须是 A、B、C 或 D。
6. 必须提供答案解析。
7. 难度为 {difficulty}，范围为1到5。
8. 必须返回合法的JSON。
9. 不要返回Markdown代码块。
10. 不要添加JSON之外的任何文字。

JSON格式：

{{
    "question": "题目内容",
    "option_a": "A选项",
    "option_b": "B选项",
    "option_c": "C选项",
    "option_d": "D选项",
    "answer": "A",
    "explanation": "答案解析",
    "difficulty": {difficulty}
}}
"""
    response = deepseek_client("question").chat.completions.create(
        model="deepseek-chat",
        max_tokens=2048,
        messages=[
            {
                "role":"system",
                "content":"你是一个专业的AI出题助手"
            },
            {
                "role":"user",
                "content":prompt
            }
        ]
    )

    content = response.choices[0].message.content

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        raise ValueError("AI返回的内容不是合法JSON")

    question = QuestionAIOutput(**data)

    return question

def generate_question_from_material(
        material_id:int,
        user_id:int,
        topic:str,
        db,
        current_difficulty:int = 1,
        topic_id:int | None = None,
        adapt_difficulty: bool = True,
):

    if db.query(LearningMaterial.id).filter_by(id=material_id, user_id=user_id).first() is None:
        raise ValueError("学习资料不存在或无权访问")
    selected_topic = require_question_topic(material_id, topic_id, db)
    retrieval_topic_id = topic_id
    if selected_topic is not None:
        topic = selected_topic.name
        # A short document may contain several topics in one unassigned chunk.
        # Search the same material when topic assignment is missing; retain the
        # selected topic for the prompt, difficulty and saved question.
        linked_chunk = db.query(LearningChunk.id).filter(
            LearningChunk.material_id == material_id,
            LearningChunk.topic_id == topic_id,
        ).first()
        if linked_chunk is None:
            retrieval_topic_id = None

    if not adapt_difficulty:
        difficulty = max(1, min(5, current_difficulty))
    else:
        difficulty = get_next_topic_difficulty(
            user_id=user_id,
            topic_id=topic_id,
            current_difficulty=current_difficulty,
            db=db
        )

    results = search_similar_chunks(
        query=topic,
        material_id=material_id,
        db=db,
        top_k=3,
        topic_id=retrieval_topic_id
    )

    if not results:
        raise ValueError(
            "当前学习资料中没有找到足够相关的内容，无法生成题目"
        )

    context ="\n\n".join(
        result["chunk"].content
        for result in results
    )

    return generate_question(
        context=context,
        difficulty=difficulty,
        topic=topic
    )

def save_generated_question(
        material_id:int,
        question_data,
        db,
        topic_id: int | None = None,
        is_adaptive:bool = False,
        commit:bool = True,
):
    require_question_topic(material_id, topic_id, db)
    question = Question(
        material_id=material_id,
        topic_id=topic_id,
        is_adaptive=is_adaptive,
        question_type = "single_choice",
        question=question_data.question,
        option_a=question_data.option_a,
        option_b=question_data.option_b,
        option_c=question_data.option_c,
        option_d=question_data.option_d,
        answer=question_data.answer,
        explanation=question_data.explanation,
        difficulty=question_data.difficulty
    )

    db.add(question)
    if commit:
        db.commit()
    else:
        db.flush()
    db.refresh(question)

    return question
