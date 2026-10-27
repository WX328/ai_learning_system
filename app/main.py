from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from contextlib import asynccontextmanager

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from app.core.settings import validate_startup_settings
from app.core.resource_limits import BodyLimitMiddleware
from app.database import engine
from app.routers.user import router as user_router
from app.routers.auth import router as auth_router
from app.routers.learning_record import router as learning_record_router
from app.routers.learning_material import router as learning_material_router
from app.routers.rag import router as rag_router
from app.routers.question import router as question_router
from app.routers import adaptive
from app.routers.study import router as study_router
from app.routers.coach import router as coach_router
from app.routers.admin import router as admin_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_startup_settings()
    script = ScriptDirectory.from_config(
        Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    )
    with engine.connect() as connection:
        current = set(MigrationContext.configure(connection).get_current_heads())
    if current != set(script.get_heads()):
        raise RuntimeError("数据库版本落后，请先运行 alembic upgrade head")
    yield


app=FastAPI(
    title="AI智能学习辅助系统",
    description="基于RAG和大语言模型的自适应智能学习辅助系统",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(user_router)
app.add_middleware(BodyLimitMiddleware)
app.include_router(auth_router)
app.include_router(learning_record_router)
app.include_router(learning_material_router)
app.include_router(rag_router)
app.include_router(question_router)
app.include_router(adaptive.router)
app.include_router(study_router)
app.include_router(coach_router)
app.include_router(admin_router)

frontend_dir = Path(__file__).resolve().parent.parent / "frontend"


@app.middleware("http")
async def disable_frontend_cache(request, call_next):
    """Always serve the current local frontend files while developing."""
    response = await call_next(request)
    if request.url.path == "/app" or request.url.path.startswith("/frontend/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


app.mount("/frontend", StaticFiles(directory=frontend_dir), name="frontend")

@app.get("/app")
def frontend_entry():
    return FileResponse(frontend_dir / "index.html")

@app.get("/")
def root():
    return {
        "message":"AI智能学习辅助系统"
    }


@app.get("/health/live", include_in_schema=False)
def live():
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
def ready():
    from fastapi import HTTPException
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
            current = set(MigrationContext.configure(connection).get_current_heads())
        script = ScriptDirectory.from_config(Config(str(frontend_dir.parent / "alembic.ini")))
        if current != set(script.get_heads()):
            raise ValueError("schema")
    except Exception as exc:
        raise HTTPException(503, "服务暂未就绪") from exc
    return {"status": "ready", "schema": sorted(current)}
