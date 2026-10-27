import re

from app.services.topic_scope import markdown_sections


def _tail_overlap(parts, size):
    text = "\n".join(parts)
    if len(text) <= size:
        return text
    return text[-size:]


def split_text_legacy(text: str, chunk_size: int = 500, chunk_overlap: int = 80):
    """把文本切成语义更完整的 chunk。

    与旧实现的关键区别：
    1. 相邻的短段落（包括标题行）会合并到接近 chunk_size 才切分，
       避免“标题”和“正文”被拆成两个碎片，导致检索只命中标题；
    2. 只有超长段落才做硬切，并在相邻 chunk 之间保留 chunk_overlap 字符重叠。
    """
    if not text:
        return []

    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 先按空行分段落；没有空行时退化为按行。
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        paragraphs = [line.strip() for line in text.split("\n") if line.strip()]

    chunks = []
    current = []
    current_len = 0

    for para in paragraphs:
        # 单段就超过 chunk_size：先 flush 已累积内容，再对长段硬切。
        if len(para) > chunk_size:
            if current:
                chunks.append("\n".join(current))
                current, current_len = [], 0
            step = max(1, chunk_size - chunk_overlap)
            start = 0
            while start < len(para):
                chunks.append(para[start:start + chunk_size])
                start += step
            continue

        # 合并短段落，接近 chunk_size 时才切分。
        if current and current_len + len(para) + 1 > chunk_size:
            chunks.append("\n".join(current))
            overlap_text = _tail_overlap(current, chunk_overlap)
            current = [overlap_text] if overlap_text else []
            current_len = len(overlap_text) if overlap_text else 0

        current.append(para)
        current_len += len(para) + (1 if current else 0)

    if current:
        chunks.append("\n".join(current))

    return [c for c in chunks if c.strip()]


def split_text(text: str, chunk_size: int = 500, chunk_overlap: int = 80):
    """Keep Markdown sections apart so short peer topics receive their own chunk."""
    sections, headings = [], []
    for section in markdown_sections(text or ""):
        lines = [line for line in section.splitlines() if line.strip()]
        if lines and all(re.match(r"^\s{0,3}#{1,6}\s+\S", line) for line in lines):
            headings.append(section)
            continue
        sections.append("\n\n".join([*headings, section]))
        headings = []
    if headings:
        # A heading-only document is still content, not an empty upload.
        sections.append("\n\n".join(headings))
    return [chunk for section in sections
            for chunk in split_text_legacy(section, chunk_size, chunk_overlap)]
