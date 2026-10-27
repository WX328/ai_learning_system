"""Bounded local request guards; no automatic paid retries."""
from collections import defaultdict, deque
from threading import BoundedSemaphore, Lock
from time import monotonic
from fastapi import Depends, HTTPException, Request
from starlette.responses import JSONResponse
from app.core.dependencies import get_current_user

MAX_BODY_BYTES = 12 * 1024 * 1024
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARS = 200_000
MAX_INDEX_CHUNKS = 128


class ModelRequestBudget:
    def __init__(self, limit=20, concurrent=2, clock=monotonic):
        self.limit, self.clock = limit, clock
        self.slots = BoundedSemaphore(concurrent)
        self.lock, self.events = Lock(), defaultdict(deque)

    def enter(self, user_id):
        now = self.clock()
        with self.lock:
            for key in list(self.events):
                while self.events[key] and self.events[key][0] <= now-60:
                    self.events[key].popleft()
                if not self.events[key]:
                    del self.events[key]
            if len(self.events.get(user_id, ())) >= self.limit:
                raise HTTPException(429, "模型请求过于频繁，请稍后重试", headers={"Retry-After": "60"})
            if not self.slots.acquire(blocking=False):
                raise HTTPException(429, "模型服务繁忙，请稍后重试", headers={"Retry-After": "5"})
            self.events[user_id].append(now)

    def leave(self):
        self.slots.release()


budget_lock = Lock()


def model_request_guard(request: Request, user=Depends(get_current_user)):
    with budget_lock:
        if not hasattr(request.app.state, "model_budget"):
            request.app.state.model_budget = ModelRequestBudget()
        budget = request.app.state.model_budget
    budget.enter(user.id)
    try:
        yield
    finally:
        budget.leave()


class BodyLimitMiddleware:
    """Limit streaming bodies without trusting Content-Length, before parsing."""
    def __init__(self, app, limit=MAX_BODY_BYTES):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        frames, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > self.limit:
                return await JSONResponse({"detail": "请求内容超过 12 MiB 限制"}, status_code=413)(scope, receive, send)
            frames.append(message)
            if not message.get("more_body", False):
                break
        async def replay():
            return frames.pop(0) if frames else await receive()
        await self.app(scope, replay, send)
