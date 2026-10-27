"""Content-based material identity without deleting legacy learning records."""
import hashlib

from sqlalchemy import func

from app.models import LearningMaterial, LearningChunk, Topic


def normalize_content(content: str) -> str:
    # Keep meaningful internal whitespace (especially indentation in code).
    return content.replace("\r\n", "\n").replace("\r", "\n").strip().lstrip("\ufeff").strip()


def content_key(content: str) -> str:
    return hashlib.sha256(normalize_content(content).encode("utf-8")).hexdigest()


def material_catalog(db, user_id):
    materials = db.query(LearningMaterial).filter(
        LearningMaterial.user_id == user_id
    ).order_by(LearningMaterial.id).all()
    chunk_counts = dict(db.query(LearningChunk.material_id, func.count(LearningChunk.id)).join(
        LearningMaterial, LearningMaterial.id == LearningChunk.material_id
    ).filter(LearningMaterial.user_id == user_id).group_by(LearningChunk.material_id).all())
    indexed_counts = dict(db.query(LearningChunk.material_id, func.count(LearningChunk.id)).join(
        LearningMaterial, LearningMaterial.id == LearningChunk.material_id
    ).filter(LearningMaterial.user_id == user_id, LearningChunk.embedding.isnot(None),
             LearningChunk.embedding != "").group_by(LearningChunk.material_id).all())
    topic_counts = dict(db.query(Topic.material_id, func.count(Topic.id)).join(
        LearningMaterial, LearningMaterial.id == Topic.material_id
    ).filter(LearningMaterial.user_id == user_id).group_by(Topic.material_id).all())
    groups = {}
    for material in materials:
        groups.setdefault(content_key(material.content), []).append(material)
    catalog = {}
    for key, copies in groups.items():
        def rank(material):
            chunks = chunk_counts.get(material.id, 0)
            indexed = chunks > 0 and indexed_counts.get(material.id, 0) == chunks
            has_topics = topic_counts.get(material.id, 0) > 0
            return (indexed and has_topics, indexed, has_topics, -material.id)
        canonical = max(copies, key=rank)
        chunks = chunk_counts.get(canonical.id, 0)
        catalog[key] = {
            "material": canonical,
            "duplicate_ids": sorted(m.id for m in copies if m.id != canonical.id),
            "chunk_count": chunks,
            "indexed": chunks > 0 and indexed_counts.get(canonical.id, 0) == chunks,
            "topic_count": topic_counts.get(canonical.id, 0),
        }
    return catalog


def serialize_material(entry, reused=False):
    material = entry["material"]
    return {
        "id": material.id,
        "user_id": material.user_id,
        "title": material.title,
        "content": material.content,
        "material_type": material.material_type,
        "created_at": material.created_at,
        "duplicate_ids": entry["duplicate_ids"],
        "chunk_count": entry["chunk_count"],
        "indexed": entry["indexed"],
        "topic_count": entry["topic_count"],
        "has_topics": entry["topic_count"] > 0,
        "reused": reused,
    }


def list_unique_materials(db, user_id):
    return sorted((serialize_material(entry) for entry in material_catalog(db, user_id).values()),
                  key=lambda material: material["id"])


def store_unique_materials(db, user_id, drafts):
    """Serialize check+insert on this project's SQLite DB, including across workers.

    Call before mutating this request's session. Authentication only reads the DB;
    SQLite's legacy transaction mode has not begun a DBAPI transaction for that read.
    No model calls or file reads occur while holding the short write transaction.
    """
    prepared = [{**draft, "content": normalize_content(draft["content"])} for draft in drafts]
    if any(not draft["content"] for draft in prepared):
        raise ValueError("资料内容不能为空")
    if not prepared:
        return []
    connection = db.connection()
    if connection.dialect.name != "sqlite":
        raise RuntimeError("资料并发去重目前适配此项目的 SQLite 数据库")
    try:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        catalog = material_catalog(db, user_id)
        result = []
        for draft in prepared:
            key = content_key(draft["content"])
            reused = key in catalog
            if not reused:
                material = LearningMaterial(user_id=user_id, title=draft["title"],
                                            content=draft["content"], material_type=draft["material_type"])
                db.add(material)
                db.flush()
                catalog[key] = {"material": material, "duplicate_ids": [], "chunk_count": 0,
                                "indexed": False, "topic_count": 0}
            result.append(serialize_material(catalog[key], reused=reused))
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
