from __future__ import annotations

import math
from collections import defaultdict

from synesis.kb.types import KnowledgeEntry

STOP_WORDS = frozenset(
    "the and for are but not you all can had her was one our out has have been some them "
    "than its over such that this with will each from they were which their what there when who "
    "how about into more other would just also then could these does like very your only should".split()
)


class SearchIndex:
    """TF-IDF search index over knowledge entries. No external dependencies."""

    def __init__(self):
        self._docs: dict[str, tuple[KnowledgeEntry, dict[str, float]]] = {}
        self._idf: dict[str, float] = {}
        self._dirty = True

    def add(self, entry: KnowledgeEntry) -> None:
        text = f"{entry.title} {entry.content} {' '.join(entry.tags)} {entry.category}"
        tf = self._compute_tf(self._tokenize(text))
        self._docs[f"{entry.category}/{entry.id}"] = (entry, tf)
        self._dirty = True

    def remove(self, category: str, id: str) -> None:
        self._docs.pop(f"{category}/{id}", None)
        self._dirty = True

    def search(
        self, query: str, limit: int = 10, category: str | None = None
    ) -> list[KnowledgeEntry]:
        if self._dirty:
            self._rebuild_idf()

        query_tf = self._compute_tf(self._tokenize(query))
        query_vec = self._to_tfidf(query_tf)

        scored = []
        for key, (entry, doc_tf) in self._docs.items():
            if category and not key.startswith(f"{category}/"):
                continue
            doc_vec = self._to_tfidf(doc_tf)
            score = self._cosine_similarity(query_vec, doc_vec)
            if score > 0:
                scored.append((entry, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [e for e, _ in scored[:limit]]

    def get_context(
        self, query: str, max_tokens: int = 8000, category: str | None = None
    ) -> list[KnowledgeEntry]:
        results = self.search(query, limit=50, category=category)
        selected = []
        token_count = 0

        for entry in results:
            entry_tokens = self._estimate_tokens(entry)
            if token_count + entry_tokens > max_tokens:
                break
            selected.append(entry)
            token_count += entry_tokens

        return selected

    def clear(self) -> None:
        self._docs.clear()
        self._idf.clear()
        self._dirty = True

    @property
    def size(self) -> int:
        return len(self._docs)

    def _tokenize(self, text: str) -> list[str]:
        cleaned = "".join(c if c.isalnum() or c.isspace() else " " for c in text.lower())
        return [t for t in cleaned.split() if len(t) > 2 and t not in STOP_WORDS]

    def _compute_tf(self, terms: list[str]) -> dict[str, float]:
        counts: dict[str, int] = defaultdict(int)
        for t in terms:
            counts[t] += 1
        max_count = max(counts.values(), default=1)
        return {t: c / max_count for t, c in counts.items()}

    def _rebuild_idf(self) -> None:
        self._idf.clear()
        n = len(self._docs)
        if n == 0:
            return
        term_doc_counts: dict[str, int] = defaultdict(int)
        for _, tf in self._docs.values():
            for term in tf:
                term_doc_counts[term] += 1
        for term, count in term_doc_counts.items():
            self._idf[term] = math.log(n / count)
        self._dirty = False

    def _to_tfidf(self, tf: dict[str, float]) -> dict[str, float]:
        return {t: freq * self._idf.get(t, 0) for t, freq in tf.items()}

    def _cosine_similarity(self, a: dict[str, float], b: dict[str, float]) -> float:
        dot = sum(a[t] * b[t] for t in a if t in b)
        norm_a = math.sqrt(sum(v * v for v in a.values()))
        norm_b = math.sqrt(sum(v * v for v in b.values()))
        denom = norm_a * norm_b
        return dot / denom if denom > 0 else 0.0

    def _estimate_tokens(self, entry: KnowledgeEntry) -> int:
        text = f"{entry.title}\n{entry.category}\n{entry.content}\n{', '.join(entry.tags)}"
        return len(text) // 4
