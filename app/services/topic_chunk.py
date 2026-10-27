import json
import time

from app.core.settings import deepseek_client

def match_chunk_to_topic(
    chunk_content: str,
    topics,
    timeout: float = 30.0,
):
    topic_text = "\n".join(
        f"{i + 1}. {topic.name}: {topic.description}"
        for i, topic in enumerate(topics)
    )

    prompt = f"""
你是一名专业的学习内容分析助手。

下面是一个学习资料 Chunk：

{chunk_content}

下面是已经提取出的知识点：

{topic_text}

请判断这个 Chunk 最主要属于哪个知识点。

要求：

1. 只能从提供的知识点中选择。
2. 如果 Chunk 与某个知识点明显相关，返回对应编号。
3. 如果没有明显对应的知识点，返回 0。
4. 只返回 JSON。
5. 不要返回 Markdown。
6. 不要添加 JSON 之外的任何文字。

JSON格式：

{{
    "topic_index": 1
}}
"""

    response = deepseek_client("topic").chat.completions.create(
        model="deepseek-chat",
        max_tokens=64,
        timeout=timeout,
        messages=[
            {
                "role": "system",
                "content": "你是一个专业的知识点分类助手。"
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    content = response.choices[0].message.content

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        raise ValueError("AI返回的内容不是合法JSON")

    return data["topic_index"]

def assign_chunks_to_topics(
    material_id: int,
    db
):
    from app.models import Topic, LearningChunk

    topics = db.query(Topic).filter(
        Topic.material_id == material_id
    ).all()

    chunks = db.query(LearningChunk).filter(
        LearningChunk.material_id == material_id
    ).all()

    if not topics:
        raise ValueError("当前学习资料没有知识点")

    if not chunks:
        raise ValueError("当前学习资料没有Chunk")

    deadline = time.monotonic() + 45
    # Partial chunk linkage is supported by retrieval; never guess a topic.
    # Bound this optional enrichment to eight model calls and 45 seconds.
    for chunk in chunks[:8]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break

        topic_index = match_chunk_to_topic(
            chunk_content=chunk.content,
            topics=topics,
            timeout=min(30.0, remaining),
        )

        if topic_index == 0:
            chunk.topic_id = None
            continue

        if not 1 <= topic_index <= len(topics):
            raise ValueError(
                f"AI返回了无效的topic_index: {topic_index}"
            )

        chunk.topic_id = topics[topic_index - 1].id

    db.commit()

    return chunks
