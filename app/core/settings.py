"""Environment configuration shared by the API and model integrations."""

import math
import os
from functools import lru_cache

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DEEPSEEK_TIMEOUTS = {
    "coach": ("DEEPSEEK_COACH_TIMEOUT", 20.0),
    "rag": ("DEEPSEEK_RAG_TIMEOUT", 60.0),
    "question": ("DEEPSEEK_QUESTION_TIMEOUT", 60.0),
    "feedback": ("DEEPSEEK_FEEDBACK_TIMEOUT", 15.0),
    "topic": ("DEEPSEEK_TOPIC_TIMEOUT", 60.0),
}


def timeout_seconds(name: str, default: float) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是正数秒数") from exc
    if not math.isfinite(value) or not 0 < value <= 300:
        raise ValueError(f"{name} 必须大于 0 且不超过 300 秒")
    return value


def validate_startup_settings() -> None:
    missing = [name for name in ("SECRET_KEY", "DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY")
               if not os.getenv(name, "").strip()]
    if missing:
        raise RuntimeError("缺少必需配置：" + ", ".join(missing))
    if len(os.getenv("SECRET_KEY", "").encode("utf-8")) < 32:
        raise RuntimeError("SECRET_KEY 至少需要 32 字节随机值")
    if os.getenv("APP_ENV", "local") == "production":
        from urllib.parse import urlparse
        endpoint = urlparse(os.getenv("DASHSCOPE_EMBEDDING_BASE_URL", ""))
        if endpoint.scheme != "https" or not endpoint.hostname:
            raise RuntimeError("部署环境必须配置有效的 HTTPS Embedding 地址")
        endpoint = urlparse(os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
        if endpoint.scheme != "https" or not endpoint.hostname:
            raise RuntimeError("部署环境必须配置有效的 HTTPS DeepSeek 地址")
    for name, default in DEEPSEEK_TIMEOUTS.values():
        timeout_seconds(name, default)
    timeout_seconds("DASHSCOPE_EMBEDDING_TIMEOUT", 30.0)


@lru_cache(maxsize=len(DEEPSEEK_TIMEOUTS))
def deepseek_client(operation: str) -> OpenAI:
    name, default = DEEPSEEK_TIMEOUTS[operation]
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY")
    return OpenAI(
        api_key=api_key,
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        timeout=timeout_seconds(name, default),
        max_retries=0,
    )
