"""Read-only topic scopes, including topics inside older multi-topic chunks."""
import re
import unicodedata

from app.models import LearningChunk, Topic


def markdown_sections(text: str) -> list[str]:
    """Keep headings with their bodies; ignore apparent headings in fenced code."""
    sections, lines = [], []
    fence = None
    for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
        if fence is None and re.match(r"^\s{0,3}#{1,6}\s+\S", line) and lines:
            sections.append("\n".join(lines).strip())
            lines = []
        lines.append(line)
    if lines:
        sections.append("\n".join(lines).strip())
    return [section for section in sections if section]


def mentions_topic(text: str, name: str) -> bool:
    """Match names literally; State must not match Statement or useState."""
    name = unicodedata.normalize("NFKC", name).casefold().strip()
    if not name:
        return False
    text = unicodedata.normalize("NFKC", text).casefold()
    start = r"(?<![a-z0-9_])" if re.match(r"[a-z0-9_]", name) else ""
    end = r"(?![a-z0-9_])" if re.search(r"[a-z0-9_]$", name) else ""
    return re.search(start + re.escape(name) + end, text) is not None


def topic_chunk_content(chunk, topic) -> str | None:
    sections = markdown_sections(chunk.content)
    matching = [section for section in sections if mentions_topic(section, topic.name)]
    if matching:
        # A source keeps its original chunk ID, but supplies only matching sections.
        return "\n\n".join(matching)
    if chunk.topic_id == topic.id:
        # Preserve a model-assigned association even if the name is paraphrased.
        return chunk.content
    return None


def scoped_topic_chunks(db, material_id: int, topic_id: int) -> list[tuple]:
    topic = db.query(Topic).filter(Topic.id == topic_id, Topic.material_id == material_id).first()
    if topic is None:
        return []
    chunks = db.query(LearningChunk).filter(LearningChunk.material_id == material_id).order_by(
        LearningChunk.chunk_index, LearningChunk.id
    ).all()
    rows = []
    for chunk in chunks:
        content = topic_chunk_content(chunk, topic)
        if content and content.strip():
            rows.append((chunk, content))
    return rows
