"""Disposable local UI preview: synthetic account/data, mocked model tools.
Run: python -m scripts.manual.demo_coach_ui
Login: coach-demo / coach-preview-passphrase
"""
from pathlib import Path
import tempfile
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openai.types.chat import ChatCompletionMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import uvicorn

import app.agents.coach as agent
import app.agents.tools as tools
from app.database import Base, get_db
from app.models import User, LearningMaterial, Topic
from app.core.security import hash_password
from app.routers import auth, coach, learning_material, study, rag
from app.schemas.question import QuestionAIOutput


def completion(messages):
    if messages[-1]["role"] == "tool":
        return ChatCompletionMessage(role="assistant", content=
            "资料指出：Depends 用于声明依赖，由框架注入参数。[1]\n先理解它解决的问题，再用一道练习检查理解。")
    practice = "练习" in messages[-1]["content"]
    name = "create_practice" if practice else "search_material"
    arguments = '{"topic":"依赖注入","topic_id":1}' if practice else '{"query":"依赖注入"}'
    return ChatCompletionMessage.model_validate({"role": "assistant", "content": None,
        "tool_calls": [{"id": "demo_tool", "type": "function",
                        "function": {"name": name, "arguments": arguments}}]})


def main():
    with tempfile.TemporaryDirectory(prefix="coach-ui-") as folder:
        engine = create_engine("sqlite:///" + (Path(folder) / "preview.db").as_posix(),
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        with factory() as db:
            user = User(username="coach-demo", password_hash=hash_password("coach-preview-passphrase"))
            db.add(user)
            db.flush()
            material = LearningMaterial(user_id=user.id, title="FastAPI 依赖注入演示资料",
                                        content="Depends 声明依赖，由框架注入参数。")
            db.add(material)
            db.flush()
            db.add(Topic(material_id=material.id, name="依赖注入", description="Depends 的用途"))
            db.commit()

        def get_preview_db():
            with factory() as db:
                yield db

        agent.complete = completion
        tools.search_similar_chunks = lambda *a, **kw: [{
            "chunk": SimpleNamespace(id=1, content="Depends 声明依赖，由框架注入参数。"), "similarity": 0.9}]
        tools.generate_question_from_material = lambda *a, **kw: QuestionAIOutput(
            question="FastAPI 使用什么声明依赖？", option_a="Depends", option_b="Print",
            option_c="Pass", option_d="Break", answer="A",
            explanation="Depends 声明依赖，由框架调用依赖函数。", difficulty=2)
        app = FastAPI()
        for router in [auth.router, coach.router, learning_material.router, study.router, rag.router]:
            app.include_router(router)
        app.dependency_overrides[get_db] = get_preview_db
        frontend = Path(__file__).resolve().parents[2] / "frontend"
        app.mount("/frontend", StaticFiles(directory=frontend), name="frontend")

        @app.middleware("http")
        async def no_cache(request, call_next):
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            return response

        @app.get("/app")
        def index():
            return FileResponse(frontend / "index.html")

        @app.get("/")
        def root():
            return {"message": "Disposable coach preview"}

        try:
            uvicorn.run(app, host="127.0.0.1", port=8766, log_level="warning")
        finally:
            engine.dispose()


if __name__ == "__main__":
    main()
