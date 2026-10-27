"""Local BM25 retrieval with cached, scope-specific indexes.

Callers filter the chunks by material/topic/owner before passing them here.
The cache contains text and index data only; live ORM objects never enter it.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from math import log1p
import re
from typing import Any, Iterable


K1 = 1.5
B = 0.75
_PARTS = re.compile(
    r"[A-Za-z0-9_]+(?:[.\-][A-Za-z0-9_]+)*"
    r"|[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002ebef]+"
)
_ASCII_START = re.compile(r"[A-Za-z0-9_]")


def tokenize(text: str) -> list[str]:
    """Split Chinese for search while preserving exact ASCII identifiers."""
    tokens = []
    for part in _PARTS.findall(text or ""):
        if _ASCII_START.match(part):
            tokens.append(part.casefold())
        else:
            # Lazy import: disabling hybrid retrieval does not initialize jieba.
            import jieba

            tokens.extend(word.casefold() for word in jieba.cut_for_search(part) if word.strip())
    return tokens


@dataclass(frozen=True)
class _BM25Index:
    ids: tuple[int, ...]
    lengths: tuple[int, ...]
    average_length: float
    postings: dict[str, tuple[tuple[int, int], ...]]
    idf: dict[str, float]


@lru_cache(maxsize=32)
def _build_index(corpus: tuple[tuple[int, str], ...]) -> _BM25Index:
    """A new upload/deletion/content edit creates a different immutable key."""
    lengths = []
    postings = defaultdict(list)
    for position, (_, content) in enumerate(corpus):
        terms = Counter(tokenize(content))
        lengths.append(sum(terms.values()))
        for term, frequency in terms.items():
            postings[term].append((position, frequency))
    count = len(corpus)
    return _BM25Index(
        ids=tuple(chunk_id for chunk_id, _ in corpus),
        lengths=tuple(lengths),
        average_length=sum(lengths) / count if count else 0.0,
        postings={term: tuple(rows) for term, rows in postings.items()},
        # Positive Lucene IDF keeps common terms useful in small materials.
        idf={term: log1p((count - len(rows) + 0.5) / (len(rows) + 0.5))
             for term, rows in postings.items()},
    )


def search_bm25_chunks(query: str, chunks: Iterable[Any], top_k: int = 10) -> list[dict]:
    """Return matched chunks ordered by BM25 score, then ascending chunk id."""
    if top_k <= 0:
        return []
    query_terms = Counter(tokenize(query))
    if not query_terms:
        return []
    by_id = {int(chunk.id): chunk for chunk in chunks}
    if not by_id:
        return []
    corpus = tuple((chunk_id, chunk.content or "") for chunk_id, chunk in sorted(by_id.items()))
    index = _build_index(corpus)
    scores = defaultdict(float)
    for term, query_frequency in query_terms.items():
        for position, frequency in index.postings.get(term, ()):
            normalizer = K1 * (1 - B + B * index.lengths[position] / index.average_length)
            scores[position] += (query_frequency * index.idf[term] * frequency * (K1 + 1)
                                 / (frequency + normalizer))
    ranked = sorted(scores, key=lambda position: (-scores[position], index.ids[position]))[:top_k]
    return [{"chunk": by_id[index.ids[position]], "bm25_score": float(scores[position])}
            for position in ranked]
