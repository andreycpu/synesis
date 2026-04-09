"""Contradiction detection for rules.

Called when a new rule is added via learn(). Checks the new rule against
all existing rules for semantic contradiction. Stores active contradictions
in ml/contradictions.json so orient() can surface them.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

NEGATION_PAIRS = [
    (re.compile(r"\balways\b", re.I), re.compile(r"\bnever\b", re.I)),
    (re.compile(r"\bprefers?\b", re.I), re.compile(r"\bavoids?\b", re.I)),
    (re.compile(r"\bprefers?\b", re.I), re.compile(r"\bhates?\b", re.I)),
    (re.compile(r"\buse\b", re.I), re.compile(r"\bdon'?t use\b", re.I)),
    (re.compile(r"\bshould\b", re.I), re.compile(r"\bshouldn'?t\b", re.I)),
    (re.compile(r"\bwants?\b", re.I), re.compile(r"\bdoesn'?t want\b", re.I)),
    (re.compile(r"\blikes?\b", re.I), re.compile(r"\bdislikes?\b", re.I)),
    (re.compile(r"\benable\b", re.I), re.compile(r"\bdisable\b", re.I)),
    (re.compile(r"\binclude\b", re.I), re.compile(r"\bexclude\b", re.I)),
    (re.compile(r"\bconcise\b", re.I), re.compile(r"\bverbose\b", re.I)),
    (re.compile(r"\bdetailed\b", re.I), re.compile(r"\bbrief\b", re.I)),
]


@dataclass
class ContradictionRecord:
    rule_a_id: str
    rule_a_text: str
    rule_b_id: str
    rule_b_text: str
    similarity: float
    detected: str  # ISO timestamp
    resolved: bool = False
    resolution: str = ""  # "keep_a", "keep_b", ""


class ContradictionDetector:
    def __init__(self, ml_dir: Path, kb_dir: Path):
        self._ml_dir = ml_dir
        self._kb_dir = kb_dir
        self._path = ml_dir / "contradictions.json"
        ml_dir.mkdir(parents=True, exist_ok=True)

    def check_new_rule(self, new_rule_text: str) -> list[ContradictionRecord]:
        """Check a newly added rule against all existing rules.

        Called from learn(). Returns any contradictions found.
        Stores them in contradictions.json.
        """
        from synesis.ml.retriever import _rule_id
        from synesis.ml.embeddings import EmbeddingEngine

        engine = EmbeddingEngine(self._ml_dir)
        new_id = _rule_id(new_rule_text)

        # Get existing rules
        existing = self._load_existing_rules()
        if not existing:
            return []

        # Embed the new rule and find similar ones
        try:
            results = engine.search(new_rule_text, k=5)
        except Exception:
            # Index might not exist yet
            return []

        contradictions = []
        for other_id, similarity in results:
            if other_id == new_id or similarity < 0.5:
                continue

            other_text = existing.get(other_id, "")
            if not other_text:
                continue

            neg_score = self._negation_score(new_rule_text, other_text)
            if neg_score == 0:
                continue

            # High similarity + negation = contradiction
            if similarity * neg_score >= 0.2:
                record = ContradictionRecord(
                    rule_a_id=new_id,
                    rule_a_text=new_rule_text,
                    rule_b_id=other_id,
                    rule_b_text=other_text,
                    similarity=round(similarity, 3),
                    detected=datetime.now().isoformat(),
                )
                contradictions.append(record)

        if contradictions:
            self._save_contradictions(contradictions)

        return contradictions

    def get_active_contradictions(self) -> list[ContradictionRecord]:
        """Get all unresolved contradictions."""
        all_records = self._load_contradictions()
        return [c for c in all_records if not c.resolved]

    def get_contradictions_for_rule(self, rule_id: str) -> list[ContradictionRecord]:
        """Get active contradictions involving a specific rule."""
        active = self.get_active_contradictions()
        return [c for c in active if c.rule_a_id == rule_id or c.rule_b_id == rule_id]

    def resolve(self, rule_a_id: str, rule_b_id: str, keep: str) -> bool:
        """Mark a contradiction as resolved. keep = 'a' or 'b'."""
        all_records = self._load_contradictions()
        for c in all_records:
            pair = {c.rule_a_id, c.rule_b_id}
            if pair == {rule_a_id, rule_b_id}:
                c.resolved = True
                c.resolution = f"keep_{keep}"
                self._save_all(all_records)
                return True
        return False

    def auto_resolve(self) -> dict:
        """Auto-resolve contradictions by keeping the higher-scored rule.

        Called during the training loop.
        """
        from synesis.ml.scorer import RuleScorer
        from synesis.ml.consolidator import RuleConsolidator

        scorer = RuleScorer(self._ml_dir)
        active = self.get_active_contradictions()

        resolved = 0
        flagged = 0
        remove_ids = set()

        for c in active:
            score_a = scorer.get_score_data(c.rule_a_id)
            score_b = scorer.get_score_data(c.rule_b_id)

            mean_a = score_a.mean_reward if score_a else 0.0
            mean_b = score_b.mean_reward if score_b else 0.0

            if abs(mean_a - mean_b) > 0.3:
                if mean_a > mean_b:
                    c.resolved = True
                    c.resolution = "keep_a"
                    remove_ids.add(c.rule_b_id)
                else:
                    c.resolved = True
                    c.resolution = "keep_b"
                    remove_ids.add(c.rule_a_id)
                resolved += 1
            else:
                # Keep the newer one (rule_a is always the newer one since
                # it was just added when the contradiction was detected)
                c.resolved = True
                c.resolution = "keep_a"
                remove_ids.add(c.rule_b_id)
                resolved += 1

        if remove_ids:
            consolidator = RuleConsolidator(self._ml_dir, self._kb_dir)
            consolidator._remove_rules(remove_ids)

        self._save_all(self._load_contradictions())
        return {"resolved": resolved, "flagged": flagged}

    def _negation_score(self, text_a: str, text_b: str) -> float:
        score = 0.0
        for pattern_pos, pattern_neg in NEGATION_PAIRS:
            if pattern_pos.search(text_a) and pattern_neg.search(text_b):
                score += 0.5
            elif pattern_neg.search(text_a) and pattern_pos.search(text_b):
                score += 0.5

        words_a = set(re.findall(r'\b\w{4,}\b', text_a.lower()))
        words_b = set(re.findall(r'\b\w{4,}\b', text_b.lower()))
        shared = words_a & words_b

        if shared:
            a_has_neg = bool(re.search(r"\b(not|no|don'?t|never|without)\b", text_a, re.I))
            b_has_neg = bool(re.search(r"\b(not|no|don'?t|never|without)\b", text_b, re.I))
            if a_has_neg != b_has_neg:
                score += 0.3 * len(shared) / max(len(words_a | words_b), 1)

        return min(score, 1.0)

    def _load_existing_rules(self) -> dict[str, str]:
        """Load rule_id -> text mapping."""
        path = self._ml_dir / "rule_texts.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _load_contradictions(self) -> list[ContradictionRecord]:
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return [ContradictionRecord(**c) for c in data]
        except Exception:
            return []

    def _save_contradictions(self, new_records: list[ContradictionRecord]) -> None:
        existing = self._load_contradictions()
        existing.extend(new_records)
        self._save_all(existing)

    def _save_all(self, records: list[ContradictionRecord]) -> None:
        self._path.write_text(
            json.dumps([asdict(c) for c in records], indent=2),
            encoding="utf-8",
        )
