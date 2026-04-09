"""Staleness and contradiction detection for rules.

Solves the hardest problem in persistent memory: knowing when something
you learned is no longer true, and when two things you learned conflict.

Staleness detection:
- Rules decay over time (exponential half-life)
- Rules that haven't been pulled recently lose confidence
- Rules whose context has changed (detected via embedding drift) get flagged

Contradiction detection:
- High embedding similarity + opposite sentiment = contradiction
- Uses antonym/negation patterns to detect semantic opposition
- When contradictions are found, keeps the newer/higher-scored rule
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# Negation pairs - if rule A says X and rule B says "not X", they contradict
NEGATION_PATTERNS = [
    (re.compile(r"\balways\b", re.I), re.compile(r"\bnever\b", re.I)),
    (re.compile(r"\bprefers?\b", re.I), re.compile(r"\bavoids?\b", re.I)),
    (re.compile(r"\bprefers?\b", re.I), re.compile(r"\bhates?\b", re.I)),
    (re.compile(r"\buse\b", re.I), re.compile(r"\bdon'?t use\b", re.I)),
    (re.compile(r"\bshould\b", re.I), re.compile(r"\bshouldn'?t\b", re.I)),
    (re.compile(r"\bwants?\b", re.I), re.compile(r"\bdoesn'?t want\b", re.I)),
    (re.compile(r"\blikes?\b", re.I), re.compile(r"\bdislikes?\b", re.I)),
    (re.compile(r"\byes\b", re.I), re.compile(r"\bno\b", re.I)),
    (re.compile(r"\benable\b", re.I), re.compile(r"\bdisable\b", re.I)),
    (re.compile(r"\binclude\b", re.I), re.compile(r"\bexclude\b", re.I)),
    (re.compile(r"\bconcise\b", re.I), re.compile(r"\bverbose\b", re.I)),
    (re.compile(r"\bdetailed\b", re.I), re.compile(r"\bbrief\b", re.I)),
]


@dataclass
class StaleRule:
    rule_id: str
    text: str
    reason: str  # "age_decay", "no_recent_use", "superseded", "contradicted"
    confidence_loss: float  # how much confidence should be reduced
    details: dict


@dataclass
class Contradiction:
    rule_a_id: str
    rule_a_text: str
    rule_b_id: str
    rule_b_text: str
    similarity: float  # embedding similarity (high = same topic)
    contradiction_score: float  # how contradictory they are
    resolution: str  # "keep_a", "keep_b", "flag_for_review"
    reason: str


class StalenessDetector:
    def __init__(self, ml_dir: Path, kb_dir: Path):
        self._ml_dir = ml_dir
        self._kb_dir = kb_dir

    def detect_stale(
        self,
        half_life_days: float = 30.0,
        min_age_days: float = 7.0,
        inactive_threshold_days: float = 14.0,
    ) -> list[StaleRule]:
        """Find rules that are likely stale.

        Three staleness signals:
        1. Age decay: rules older than half_life lose confidence exponentially
        2. Inactivity: rules not used in inactive_threshold days
        3. Superseded: a newer rule covers the same topic with higher score
        """
        from synesis.ml.scorer import RuleScorer
        from synesis.ml.embeddings import EmbeddingEngine

        scorer = RuleScorer(self._ml_dir)
        engine = EmbeddingEngine(self._ml_dir)
        rules = self._load_rules()
        now = datetime.now()
        stale = []

        for rule_id, text, timestamp in rules:
            score_data = scorer.get_score_data(rule_id)
            reasons = []

            # 1. Age decay
            if timestamp:
                try:
                    age = (now - datetime.fromisoformat(timestamp)).days
                except Exception:
                    age = 0

                if age > min_age_days:
                    # Exponential decay: confidence = 0.5^(age/half_life)
                    decay = 0.5 ** (age / half_life_days)
                    confidence_loss = 1.0 - decay
                    if confidence_loss > 0.3:
                        reasons.append(("age_decay", confidence_loss, {
                            "age_days": age,
                            "decay_factor": round(decay, 3),
                        }))

            # 2. Inactivity
            if score_data and score_data.last_used:
                try:
                    last_used = datetime.fromisoformat(score_data.last_used)
                    inactive_days = (now - last_used).days
                    if inactive_days > inactive_threshold_days:
                        loss = min(inactive_days / (inactive_threshold_days * 3), 0.8)
                        reasons.append(("no_recent_use", loss, {
                            "inactive_days": inactive_days,
                        }))
                except Exception:
                    pass
            elif score_data and score_data.times_pulled == 0:
                # Never used at all
                reasons.append(("never_used", 0.2, {}))

            # 3. Superseded - check if a newer rule covers the same topic
            try:
                similar = engine.search(text, k=3)
                for other_id, sim in similar:
                    if other_id == rule_id or sim < 0.7:
                        continue
                    other_score = scorer.get_score_data(other_id)
                    if other_score and score_data:
                        if other_score.mean_reward > score_data.mean_reward + 0.2:
                            reasons.append(("superseded", 0.5, {
                                "superseded_by": other_id,
                                "similarity": round(sim, 3),
                            }))
                            break
            except Exception:
                pass

            if reasons:
                # Take the strongest reason
                reasons.sort(key=lambda r: r[1], reverse=True)
                best_reason, best_loss, best_details = reasons[0]
                stale.append(StaleRule(
                    rule_id=rule_id,
                    text=text,
                    reason=best_reason,
                    confidence_loss=round(best_loss, 3),
                    details=best_details,
                ))

        # Sort by confidence loss (most stale first)
        stale.sort(key=lambda s: s.confidence_loss, reverse=True)
        return stale

    def detect_contradictions(self, similarity_threshold: float = 0.5) -> list[Contradiction]:
        """Find pairs of rules that contradict each other.

        Two rules contradict when:
        1. They're about the same topic (high embedding similarity)
        2. They express opposite intent (negation pattern match)

        Higher similarity + stronger negation = stronger contradiction.
        """
        from synesis.ml.embeddings import EmbeddingEngine
        from synesis.ml.scorer import RuleScorer

        engine = EmbeddingEngine(self._ml_dir)
        scorer = RuleScorer(self._ml_dir)
        rules = self._load_rules()

        if len(rules) < 2:
            return []

        # Embed all rules
        ids = [r[0] for r in rules]
        texts = [r[1] for r in rules]
        timestamps = [r[2] for r in rules]
        vecs = engine.embed(texts)

        # Compute pairwise similarities
        sim_matrix = vecs @ vecs.T

        contradictions = []
        seen_pairs = set()

        for i in range(len(rules)):
            for j in range(i + 1, len(rules)):
                sim = float(sim_matrix[i, j])
                if sim < similarity_threshold:
                    continue

                # Check for negation patterns between the two rules
                neg_score = self._negation_score(texts[i], texts[j])
                if neg_score == 0:
                    continue

                contradiction_score = sim * neg_score
                if contradiction_score < 0.2:
                    continue

                pair_key = tuple(sorted([ids[i], ids[j]]))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                # Resolution: keep newer rule if scores are similar,
                # otherwise keep higher-scored
                score_a = scorer.get_score_data(ids[i])
                score_b = scorer.get_score_data(ids[j])

                resolution, reason = self._resolve_contradiction(
                    ids[i], texts[i], timestamps[i], score_a,
                    ids[j], texts[j], timestamps[j], score_b,
                )

                contradictions.append(Contradiction(
                    rule_a_id=ids[i],
                    rule_a_text=texts[i],
                    rule_b_id=ids[j],
                    rule_b_text=texts[j],
                    similarity=round(sim, 3),
                    contradiction_score=round(contradiction_score, 3),
                    resolution=resolution,
                    reason=reason,
                ))

        contradictions.sort(key=lambda c: c.contradiction_score, reverse=True)
        return contradictions

    def _negation_score(self, text_a: str, text_b: str) -> float:
        """Score how much two texts express opposite intents."""
        score = 0.0
        for pattern_pos, pattern_neg in NEGATION_PATTERNS:
            # A has positive, B has negative (or vice versa)
            if pattern_pos.search(text_a) and pattern_neg.search(text_b):
                score += 0.5
            elif pattern_neg.search(text_a) and pattern_pos.search(text_b):
                score += 0.5

        # Direct negation: one rule contains "not" + key phrase from other
        words_a = set(re.findall(r'\b\w{4,}\b', text_a.lower()))
        words_b = set(re.findall(r'\b\w{4,}\b', text_b.lower()))
        shared = words_a & words_b

        if shared:
            # Same topic words but one has negation
            a_has_neg = bool(re.search(r"\b(not|no|don'?t|never|without)\b", text_a, re.I))
            b_has_neg = bool(re.search(r"\b(not|no|don'?t|never|without)\b", text_b, re.I))
            if a_has_neg != b_has_neg:  # One negated, one not
                score += 0.3 * len(shared) / max(len(words_a | words_b), 1)

        return min(score, 1.0)

    def _resolve_contradiction(
        self,
        id_a: str, text_a: str, ts_a: str, score_a,
        id_b: str, text_b: str, ts_b: str, score_b,
    ) -> tuple[str, str]:
        """Decide which contradicting rule to keep."""
        # If one has significantly better score, keep it
        if score_a and score_b:
            if score_a.mean_reward > score_b.mean_reward + 0.3:
                return "keep_a", f"rule A has better reward ({score_a.mean_reward:.2f} vs {score_b.mean_reward:.2f})"
            if score_b.mean_reward > score_a.mean_reward + 0.3:
                return "keep_b", f"rule B has better reward ({score_b.mean_reward:.2f} vs {score_a.mean_reward:.2f})"

        # If scores are similar, prefer the newer rule (user preferences change)
        try:
            dt_a = datetime.fromisoformat(ts_a) if ts_a else datetime.min
            dt_b = datetime.fromisoformat(ts_b) if ts_b else datetime.min
            if dt_b > dt_a:
                return "keep_b", "newer rule (preferences may have changed)"
            elif dt_a > dt_b:
                return "keep_a", "newer rule (preferences may have changed)"
        except Exception:
            pass

        return "flag_for_review", "scores and ages are similar, needs human review"

    def apply_staleness(self, stale_rules: list[StaleRule], threshold: float = 0.6) -> dict:
        """Apply staleness findings: reduce scores for stale rules, remove severely stale ones."""
        from synesis.ml.scorer import RuleScorer

        scorer = RuleScorer(self._ml_dir)
        reduced = 0
        removed = 0

        for sr in stale_rules:
            if sr.confidence_loss >= threshold:
                # Severely stale - penalize the score
                scorer.record_outcome(sr.rule_id, reward=-0.3)
                reduced += 1
            elif sr.confidence_loss >= 0.8:
                # Extremely stale - heavy penalty
                scorer.record_outcome(sr.rule_id, reward=-0.8)
                removed += 1

        return {"reduced": reduced, "removed": removed}

    def resolve_contradictions(self, contradictions: list[Contradiction]) -> dict:
        """Apply contradiction resolutions: remove the losing rule."""
        from synesis.ml.consolidator import RuleConsolidator

        consolidator = RuleConsolidator(self._ml_dir, self._kb_dir)
        resolved = 0
        flagged = 0

        remove_ids = set()
        for c in contradictions:
            if c.resolution == "keep_a":
                remove_ids.add(c.rule_b_id)
                resolved += 1
            elif c.resolution == "keep_b":
                remove_ids.add(c.rule_a_id)
                resolved += 1
            else:
                flagged += 1

        if remove_ids:
            consolidator._remove_rules(remove_ids)

        return {"resolved": resolved, "flagged": flagged}

    def _load_rules(self) -> list[tuple[str, str, str]]:
        """Load rules with timestamps. Returns (id, text, timestamp)."""
        from synesis.ml.retriever import _rule_id

        rules_path = self._kb_dir / "_agent" / "rules.md"
        if not rules_path.exists():
            return []

        rules = []
        for line in rules_path.read_text(encoding="utf-8").split("\n"):
            match = re.match(r"^- \[([\dT:.+-]+)\]\s*(.+)$", line.strip())
            if match:
                timestamp = match.group(1)
                text = match.group(2).strip()
                if text:
                    rules.append((_rule_id(text), text, timestamp))

        return rules
