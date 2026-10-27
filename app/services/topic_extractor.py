import json

from app.core.settings import deepseek_client

from app.schemas.learning_material import TopicExtractionResponse
from app.models import Topic, LearningMaterial
from app.services.topic_chunk import assign_chunks_to_topics

def extract_topics(content: str):
    prompt = f"""
你是一名专业的学习内容分析助手。

请分析下面的学习资料，提取其中最重要的知识点。

学习资料：
{content}

要求：

1. 提取 3 到 10 个核心知识点。
2. 每个知识点必须包含名称和简短说明。
3. 知识点应该具体、有学习价值。
4. 不要把同一个知识点拆成大量重复的小知识点。
5. 不要提取没有实际意义的普通词语。
6. 不要添加学习资料中不存在的知识点。
7. 知识点名称应该简洁。
8. description 应该简洁说明这个知识点是什么。
9. 必须返回合法 JSON。
10. 不要返回 Markdown。
11. 不要添加 JSON 之外的任何文字。

JSON格式：

{{
    "topics": [
        {{
            "name": "知识点名称",
            "description": "知识点说明"
        }},
        {{
            "name": "知识点名称",
            "description": "知识点说明"
        }}
    ]
}}
"""

    response = deepseek_client("topic").chat.completions.create(
        model="deepseek-chat",
        max_tokens=2048,
        messages=[
            {
                "role": "system",
                "content": "你是一个专业的学习知识点提取助手。"
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    result = response.choices[0].message.content

    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        raise ValueError("AI返回的内容不是合法JSON")

    topics = TopicExtractionResponse(**data)

    return topics

def save_topics(
        material_id:int,
        topics,
        db
):
    existing = db.query(Topic).filter_by(material_id=material_id).order_by(Topic.id).all()
    if existing:
        return existing  # Stable IDs: never delete/recreate a material's catalog.
    if db.get(LearningMaterial, material_id) is None:
        raise ValueError("学习资料不存在")
    names = [item.name.strip() for item in topics.topics]
    if not names or any(not name or len(name) > 200 for name in names) or len(set(names)) != len(names):
        raise ValueError("知识点名称为空、过长或重复")

    saved_topics = []

    for topic_data in topics.topics:
        topic = Topic(
            material_id=material_id,
            name=topic_data.name.strip(),
            description=topic_data.description
        )

        db.add(topic)
        saved_topics.append(topic)

    db.commit()

    for topic in saved_topics:
        db.refresh(topic)

    return saved_topics

def extract_and_assign_topics(
        material_id:int,
        content:str,
        db
):
    existing = db.query(Topic).filter_by(material_id=material_id).order_by(Topic.id).all()
    if existing:
        return existing  # Also avoid a needless paid extraction/assignment call.
    topics = extract_topics(content)

    saved_topics = save_topics(
        material_id=material_id,
        topics=topics,
        db=db
    )

    assign_chunks_to_topics(
        material_id=material_id,
        db=db
    )

    return saved_topics
