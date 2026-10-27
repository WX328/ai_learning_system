import json

from app.core.settings import deepseek_client


def local_answer_feedback(is_correct: bool, explanation: str | None) -> str:
    return ("回答正确。" if is_correct else "这题还需要巩固。") + (
        explanation or "请回顾相关学习资料。"
    )

def build_answer_feedback_prompt(
        *,
        question:str,
        options :dict[str,str | None],
        user_answer:str,
        correct_answer:str,
        explanation:str | None,
) -> str:
    payload = {
        "question":question,
        "options":options,
        "user_answer":user_answer,
        "correct_answer":correct_answer,
        "is_correct":user_answer == correct_answer,
        "explanation":explanation or "",
    }

    return (
        "你是一名耐心的学习教练。根据以下答题信息，用中文给出 2 到 4 句反馈。"
        "先判断学生作答情况；答错时说明关键误区并给出下一步建议；答对时肯定关键理解并给出巩固建议。"
        "不要编造资料中没有的信息，不要使用 Markdown 标题。\n\n"
        f"答题数据：\n{json.dumps(payload, ensure_ascii=False)}"
    )

def generate_answer_feedback(
        *,
        question:str,
        options:dict[str,str | None],
        user_answer:str,
        correct_answer:str,
        explanation:str | None
) -> str:
    prompt = build_answer_feedback_prompt(
        question=question,
        options=options,
        user_answer=user_answer,
        correct_answer=correct_answer,
        explanation=explanation,
    )

    response = deepseek_client("feedback").chat.completions.create(
        model="deepseek-chat",
        max_tokens=768,
        messages=[
            {
                "role":"system",
                "content":"你是一名耐心、准确的AI学习教练。",
            },
            {"role":"user","content":prompt},

        ],
    )

    feedback = response.choices[0].message.content
    if not feedback or not feedback.strip():
        raise ValueError("AI未返回有效反馈")

    return feedback.strip()
