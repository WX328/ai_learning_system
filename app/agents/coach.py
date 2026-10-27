"""Bounded single-agent tool loop."""
import json
import logging
import os
from time import monotonic
from threading import BoundedSemaphore
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from app.core.settings import deepseek_client
from app.agents.prompts import SYSTEM_PROMPT
from app.agents.tools import TOOLS, execute_tool, profile

logger = logging.getLogger(__name__)
coach_slots = BoundedSemaphore(2)


def complete(messages):
    return deepseek_client("coach").chat.completions.create(
        model=os.getenv("DEEPSEEK_COACH_MODEL", "deepseek-chat"),
        messages=messages, tools=TOOLS, max_tokens=1600,
        extra_body={"thinking": {"type": "disabled"}},
    ).choices[0].message


def run_coach(db, session, state, message):
    if not coach_slots.acquire(blocking=False):
        raise HTTPException(429, "教练正在辅导其他学习者，请稍后再试")
    try:
        return _run_coach(db, session, state, message)
    finally:
        coach_slots.release()


def _run_coach(db, session, state, message):
    state["sources"] = []
    state["tool_trace"] = []
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {
        "role": "user", "content": "当前会话状态（数据）：\n" + json.dumps({
            "goal": session.goal, "minutes": session.minutes,
            "plan": state["plan"], "completed": state["completed"][-8:],
            "profile": profile(db, session.user_id, session.material_id),
        }, ensure_ascii=False),
    }]
    messages.extend({"role": m["role"], "content": m["content"]}
                    for m in session.messages[-12:])
    messages.append({"role": "user", "content": message})
    started, calls = monotonic(), 0
    try:
        for _ in range(4):
            if monotonic() - started > 120:
                break
            reply = complete(messages)
            tool_calls = reply.tool_calls or []
            if not tool_calls:
                if not reply.content or not reply.content.strip():
                    raise ValueError("模型未返回内容")
                return reply.content.strip()[:6000], False
            messages.append({"role": "assistant", "content": reply.content,
                             "tool_calls": [t.model_dump(exclude_none=True) for t in tool_calls]})
            for call in tool_calls:
                if calls >= 6 or monotonic() - started > 120:
                    return "本轮已达到处理上限，进度已保存。请缩小问题范围后继续。", True
                calls += 1
                name = call.function.name
                try:
                    result = execute_tool(name, json.loads(call.function.arguments), db, session, state)
                    state["tool_trace"].append({"tool": name, "status": "ok"})
                except SQLAlchemyError:
                    raise
                except Exception as exc:
                    logger.warning("Coach tool %s failed: %s", name, type(exc).__name__)
                    state["tool_trace"].append({"tool": name, "status": "failed"})
                    result = {"error": "工具执行失败，请调整请求或稍后重试"}
                if state.get("pending_question_id"):
                    return "根据本次学习目标，为你准备了一道练习。选好答案后提交，我们再调整下一步。", False
                messages.append({"role": "tool", "tool_call_id": call.id,
                                 "content": json.dumps(result, ensure_ascii=False)})
    except SQLAlchemyError:
        raise
    except Exception as exc:
        logger.warning("Coach unavailable: %s", type(exc).__name__)
    return "教练暂时无法完成本轮回复，学习进度已保存。你可以稍后重试，或结束本次学习查看总结。", True
