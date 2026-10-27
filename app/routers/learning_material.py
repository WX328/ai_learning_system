import json
import io
import zipfile
from pathlib import Path
from xml.etree import ElementTree
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    LearningMaterial,
    LearningChunk,
    LearningRecord,
    QAHistory,
    Question,
    QuestionAttempt,
    ReviewAttempt,
    Topic,
    TopicMastery,
    User,
    CoachSession,
    CoachTurn,
)
from app.schemas.learning_material import LearningMaterialCreate,TopicResponse
from app.core.dependencies import get_current_user
from app.core.resource_limits import (model_request_guard, MAX_FILE_BYTES, MAX_TEXT_CHARS, MAX_INDEX_CHUNKS)
from app.services.chunker import split_text, split_text_legacy
from app.services.embedding import EmbeddingError, embed_texts, embedding_dimensions, embedding_model
from app.services.topic_extractor import (
    extract_and_assign_topics
)
from app.services.material_dedup import content_key, list_unique_materials, store_unique_materials

router = APIRouter(
    prefix="/learning-materials",
    tags=["学习资料"]
)

def extract_uploaded_text(filename: str, content: bytes) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix in {".txt", ".md", ".markdown", ".csv", ".json"}:
        return content.decode("utf-8-sig", errors="replace")
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if archive.getinfo("word/document.xml").file_size > MAX_FILE_BYTES:
                    raise HTTPException(413, "DOCX 解压内容过大")
                xml = archive.read("word/document.xml")
            root = ElementTree.fromstring(xml)
            ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            paragraphs = []
            for paragraph in root.iter(f"{ns}p"):
                words = [node.text or "" for node in paragraph.iter(f"{ns}t")]
                if words:
                    paragraphs.append("".join(words))
            return "\n".join(paragraphs)
        except (KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
            raise HTTPException(status_code=400, detail="DOCX 文件无法解析") from exc
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise HTTPException(status_code=503, detail="PDF 解析依赖未安装，请执行 pip install pypdf") from exc
        try:
            reader = PdfReader(io.BytesIO(content))
            if len(reader.pages) > 100:
                raise HTTPException(413, "PDF 超过 100 页限制")
            parts, size = [], 0
            for page in reader.pages:
                text = page.extract_text() or ""
                size += len(text)
                if size > MAX_TEXT_CHARS:
                    raise HTTPException(413, "资料文字过长")
                parts.append(text)
            return "\n\n".join(parts)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail="PDF 文件无法解析，请确认文件未加密") from exc
    raise HTTPException(status_code=400, detail="暂不支持此文件格式，请上传 TXT、Markdown、DOCX 或 PDF")

@router.post("")
def create_learning_material(
    material:LearningMaterialCreate,
    current_user:User = Depends(get_current_user),
    db:Session = Depends(get_db)
):
    try:
        return store_unique_materials(db, current_user.id, [{
            "title": material.title, "content": material.content,
            "material_type": material.material_type
        }])[0]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/upload")
async def upload_learning_material(
    files: list[UploadFile] = File(...),
    title: str | None = None,
    material_type: str = "document",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not files:
        raise HTTPException(status_code=400, detail="请至少上传一个文件")
    if len(files) > 5:
        raise HTTPException(413, "一次最多上传 5 个文件")
    drafts = []
    for file in files:
        content = await file.read(MAX_FILE_BYTES + 1)
        if len(content) > MAX_FILE_BYTES:
            raise HTTPException(413, "单个文件超过 5 MiB 限制")
        if not content:
            continue
        text = extract_uploaded_text(file.filename or "", content).strip()
        if len(text) > MAX_TEXT_CHARS:
            raise HTTPException(413, "单份资料超过 200000 字符限制")
        if not text:
            continue
        filename = file.filename or "未命名资料"
        file_title = f"{title} - {Path(filename).stem}" if title else Path(filename).stem
        drafts.append({"title": file_title[:200], "content": text, "material_type": material_type})
    if not drafts:
        raise HTTPException(status_code=400, detail="上传文件中没有可提取的文字内容")
    try:
        return store_unique_materials(db, current_user.id, drafts)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.get("")
def get_my_learning_materials(
    current_user:User = Depends(get_current_user),
    db:Session = Depends(get_db)
):
    return list_unique_materials(db, current_user.id)


@router.delete("/{material_id}")
def delete_learning_material(
    material_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a visible material and every hidden duplicate with the same content."""
    material = db.query(LearningMaterial).filter(
        LearningMaterial.id == material_id,
        LearningMaterial.user_id == current_user.id
    ).first()
    if material is None:
        raise HTTPException(status_code=404, detail="学习资料不存在或无权删除")

    target_key = content_key(material.content)
    copies = [item for item in db.query(LearningMaterial).filter(
        LearningMaterial.user_id == current_user.id
    ).all() if content_key(item.content) == target_key]
    material_ids = [item.id for item in copies]
    topic_ids = [item[0] for item in db.query(Topic.id).filter(
        Topic.material_id.in_(material_ids)
    ).all()]
    question_ids = [item[0] for item in db.query(Question.id).filter(
        Question.material_id.in_(material_ids)
    ).all()]

    # Remove dependent rows explicitly. Existing SQLite tables do not define
    # database-level cascade rules, and question history must not be orphaned.
    coach_ids = [row[0] for row in db.query(CoachSession.id).filter(
        CoachSession.material_id.in_(material_ids)
    ).all()]
    if coach_ids:
        db.query(CoachTurn).filter(CoachTurn.session_id.in_(coach_ids)).delete(synchronize_session=False)
        db.query(CoachSession).filter(CoachSession.id.in_(coach_ids)).delete(synchronize_session=False)
    if question_ids:
        db.query(ReviewAttempt).filter(ReviewAttempt.question_id.in_(question_ids)).delete(
            synchronize_session=False
        )
        db.query(QuestionAttempt).filter(QuestionAttempt.question_id.in_(question_ids)).delete(
            synchronize_session=False
        )
        db.query(LearningRecord).filter(
            LearningRecord.content_type == "question",
            LearningRecord.content_id.in_(question_ids)
        ).delete(synchronize_session=False)
        db.query(Question).filter(Question.id.in_(question_ids)).delete(
            synchronize_session=False
        )

    db.query(QAHistory).filter(
        QAHistory.material_id.in_(material_ids)
    ).delete(synchronize_session=False)
    db.query(LearningRecord).filter(
        LearningRecord.content_type.in_(["material", "learning_material"]),
        LearningRecord.content_id.in_(material_ids)
    ).delete(synchronize_session=False)
    db.query(LearningChunk).filter(LearningChunk.material_id.in_(material_ids)).delete(
        synchronize_session=False
    )
    if topic_ids:
        db.query(TopicMastery).filter(TopicMastery.topic_id.in_(topic_ids)).delete(
            synchronize_session=False
        )
        db.query(Topic).filter(Topic.id.in_(topic_ids)).delete(synchronize_session=False)
    db.query(LearningMaterial).filter(LearningMaterial.id.in_(material_ids)).delete(
        synchronize_session=False
    )
    db.commit()

    return {
        "deleted_material_ids": material_ids,
        "deleted_material_count": len(material_ids),
    }

@router.post("/{material_id}/index", dependencies=[Depends(model_request_guard)])
def index_learning_material(
    material_id:int,
    force: bool = Query(False, description="使用当前向量模型重新生成现有 Chunk 的向量"),
    current_user:User = Depends(get_current_user),
    db:Session = Depends(get_db)
):
    material = db.query(LearningMaterial).filter(
        LearningMaterial.id == material_id,
        LearningMaterial.user_id == current_user.id
    ).first()

    if material is None:
        raise HTTPException(
            status_code=404,
            detail="学习资料不存在"
        )

    chunk_texts = split_text(material.content)
    existing_chunks = db.query(LearningChunk).filter(
        LearningChunk.material_id == material.id
    ).order_by(LearningChunk.chunk_index).all()
    chunks_match = (
        len(existing_chunks) == len(chunk_texts)
        and all(existing.chunk_index == index and existing.content == content
                for index, (existing, content) in enumerate(zip(existing_chunks, chunk_texts)))
    )
    if existing_chunks and not chunks_match:
        # Earlier imports merged peer headings. Re-embed that layout in place;
        # changing the splitter must not detach their topic IDs or source IDs.
        legacy_texts = split_text_legacy(material.content)
        if len(existing_chunks) == len(legacy_texts) and all(
            chunk.chunk_index == index and chunk.content == content
            for index, (chunk, content) in enumerate(zip(existing_chunks, legacy_texts))
        ):
            chunk_texts, chunks_match = legacy_texts, True

    if existing_chunks and all(chunk.embedding for chunk in existing_chunks) and not force:
        return {
            "material_id": material.id,
            "chunk_count": len(existing_chunks),
            "reused": True,
            "embedding_model": embedding_model(),
            "embedding_dimensions": embedding_dimensions(),
        }

    # A forced rebuild must not silently detach existing chunks from their topics.
    # With the same splitter configuration, only the embedding values are replaced.
    if force and existing_chunks and not chunks_match:
        raise HTTPException(
            status_code=409,
            detail="资料分段内容已变化，无法在保留知识点关联的情况下重建向量"
        )

    try:
        if len(chunk_texts) > MAX_INDEX_CHUNKS:
            raise HTTPException(413, "资料分段过多，请拆分后建立索引（最多 128 段）")
        vectors = embed_texts(chunk_texts)
    except EmbeddingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if chunks_match:
        for chunk, vector in zip(existing_chunks, vectors):
            chunk.embedding = json.dumps(vector)
    else:
        # A normal first index (or interrupted old index) may safely recreate chunks.
        db.query(LearningChunk).filter(
            LearningChunk.material_id == material.id
        ).delete()
        for index, (content, vector) in enumerate(zip(chunk_texts, vectors)):
            db.add(LearningChunk(
                material_id=material.id,
                chunk_index=index,
                content=content,
                embedding=json.dumps(vector)
            ))

    db.commit()
    return {
        "material_id": material.id,
        "chunk_count": len(chunk_texts),
        "reindexed": bool(force),
        "embedding_model": embedding_model(),
        "embedding_dimensions": embedding_dimensions(),
    }

@router.post(
    "/{material_id}/extract-topics",
    response_model=list[TopicResponse], dependencies=[Depends(model_request_guard)]
)
def extrat_material_topics(
    material_id:int,
    current_user:User = Depends(get_current_user),
    db:Session = Depends(get_db)
):
    material = db.query(LearningMaterial).filter(
        LearningMaterial.id == material_id,
        LearningMaterial.user_id == current_user.id
    ).first()

    if material is None:
        raise HTTPException(
            status_code=404,
            detail="学习资料不存在或无权访问"
        )

    existing_topics = db.query(Topic).filter(Topic.material_id == material_id).all()
    if existing_topics:
        return existing_topics

    saved_topics = extract_and_assign_topics(
        material_id=material_id,
        content=material.content,
        db=db
    )

    return saved_topics

@router.get(
    "/{material_id}/topics",
    response_model=list[TopicResponse]
)
def get_material_topics(
    material_id:int,
    current_user:User = Depends(get_current_user),
    db:Session = Depends(get_db)
):
    material = db.query(LearningMaterial).filter(
        LearningMaterial.id == material_id,
        LearningMaterial.user_id == current_user.id
    ).first()

    if material is None:
        raise HTTPException(
            status_code=404,
            detail="学习资料不存在或无权访问"
        )

    topics = db.query(Topic).filter(
        Topic.material_id == material_id
    ).all()

    return topics
