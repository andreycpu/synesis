"""Feedback extraction from session data.

No LLM calls. Extracts signals using structural analysis of conversations:
- Message position (reaction vs continuation)
- Message length relative to context (short = reaction, long = new topic)
- Multi-signal voting (multiple correction indicators = higher confidence)
- Retroactive rule attribution via embedding similarity

Previous version had high false-positive rates from broad regex matching.
This version scores confidence and requires multiple structural signals.
"""
from __future__ import annotations

import hashlib
import json
import re
import logging
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Correction patterns grouped by strength.
# Strong: almost always means correction regardless of context.
# Weak: only counts as correction when combined with other signals.
STRONG_CORRECTION = [
    re.compile(p, re.IGNORECASE) for p in [
        r"^no[,.\s]",  # "no" at START of message only
        r"\bthat'?s (not |in)?correct\b",
        r"\bthat'?s wrong\b",
        r"\bredo (this|that|it)\b",
        r"\brevert (this|that|it)\b",
        r"\bundo (this|that|it)\b",
        r"\bwhy did you\b",
        r"\bi (said|asked|meant|wanted)\b",
        r"\bi didn'?t (say|ask|mean|want)\b",
    ]
]

WEAK_CORRECTION = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\binstead\b",
        r"\bactually[,\s]",
        r"\bnot what\b",
        r"\bdon'?t\b",
        r"\bstop\b",
        r"\bfix (this|that|it)\b",
        r"\bchange (this|that|it)\b",
    ]
]

STRONG_POSITIVE = [
    re.compile(p, re.IGNORECASE) for p in [
        r"^(thanks?|ty|thx)\b",  # Thanks at start = reaction to what just happened
        r"\bperfect\b",
        r"\bexactly\b",
        r"\blgtm\b",
        r"\blooks good\b",
        r"\bship it\b",
        r"\bwell done\b",
        r"\bnice work\b",
    ]
]

WEAK_POSITIVE = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\bgreat\b",
        r"\bnice\b",
        r"\bawesome\b",
        r"\bcool\b",
        r"\bgood\b",
        r"^yes\b",
    ]
]

# Patterns that indicate the user is just continuing a conversation,
# not reacting to the agent's output. These reduce correction confidence.
CONTINUATION_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"^(now|next|also|and|ok so|alright)\b",
        r"^(can you|could you|please|let'?s)\b",
        r"^(what about|how about|what if)\b",
    ]
]


@dataclass
class FeedbackSignal:
    timestamp: str
    signal_type: str  # accepted, corrected, ignored, completed
    confidence: float  # 0.0 to 1.0 - how confident are we in this signal
    rule_ids: list[str]  # rules attributed to this signal (can be multiple)
    context: str
    details: dict
    session_hash: str = ""  # for dedup across training runs

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FeedbackSignal":
        # Handle old format with single rule_id
        if "rule_id" in d and "rule_ids" not in d:
            rid = d.pop("rule_id")
            d["rule_ids"] = [rid] if rid else []
        if "confidence" not in d:
            d["confidence"] = 0.5
        if "session_hash" not in d:
            d["session_hash"] = ""
        return cls(**d)


class FeedbackExtractor:
    def __init__(self, ml_dir: Path):
        self._ml_dir = ml_dir
        self._feedback_path = ml_dir / "feedback.jsonl"
        self._processed_path = ml_dir / "processed_sessions.json"
        ml_dir.mkdir(parents=True, exist_ok=True)

    def extract_from_session(self, session_path: Path) -> list[FeedbackSignal]:
        """Extract feedback signals from a JSONL conversation file.

        Uses structural analysis, not just keyword matching:
        1. Only looks at user messages that are REACTIONS (short, follow assistant)
        2. Scores confidence based on multiple indicators
        3. Filters out continuations (new requests that happen to contain trigger words)
        """
        signals = []
        messages = self._parse_session(session_path)
        session_hash = self._session_hash(session_path)

        if len(messages) < 2:
            return signals

        for i in range(1, len(messages)):
            prev = messages[i - 1]
            curr = messages[i]

            if prev.get("role") != "assistant" or curr.get("role") != "user":
                continue

            user_text = curr.get("text", "").strip()
            assistant_text = prev.get("text", "").strip()

            if not user_text or not assistant_text:
                continue

            signal = self._classify_message(user_text, assistant_text, curr, session_hash)
            if signal:
                signals.append(signal)

        return signals

    def _classify_message(
        self, user_text: str, assistant_text: str, msg: dict, session_hash: str
    ) -> FeedbackSignal | None:
        """Classify a user message as feedback with confidence scoring.

        Confidence is based on:
        - Number of matching patterns (more = higher confidence)
        - Pattern strength (strong > weak)
        - Message structure (short reaction = higher, long continuation = lower)
        - Position indicators (continuation patterns reduce confidence)
        """
        # Score correction signals
        strong_corrections = sum(1 for p in STRONG_CORRECTION if p.search(user_text))
        weak_corrections = sum(1 for p in WEAK_CORRECTION if p.search(user_text))
        correction_score = strong_corrections * 0.4 + weak_corrections * 0.15

        # Score positive signals
        strong_positives = sum(1 for p in STRONG_POSITIVE if p.search(user_text))
        weak_positives = sum(1 for p in WEAK_POSITIVE if p.search(user_text))
        positive_score = strong_positives * 0.4 + weak_positives * 0.15

        # Structural adjustments
        is_short = len(user_text) < 200  # Short messages are more likely reactions
        is_continuation = any(p.search(user_text) for p in CONTINUATION_PATTERNS)

        if is_continuation:
            correction_score *= 0.3  # Heavy discount - "now do X instead" is a new task
            positive_score *= 0.5

        if not is_short:
            # Long messages are usually new requests, not reactions
            correction_score *= 0.5
            positive_score *= 0.5

        # Both signals present = ambiguous, reduce both
        if correction_score > 0 and positive_score > 0:
            correction_score *= 0.5
            positive_score *= 0.5

        # Minimum confidence threshold
        min_confidence = 0.25

        if correction_score >= min_confidence and correction_score > positive_score:
            confidence = min(correction_score, 1.0)
            return FeedbackSignal(
                timestamp=msg.get("timestamp", datetime.now().isoformat()),
                signal_type="corrected",
                confidence=round(confidence, 3),
                rule_ids=[],
                context=assistant_text[:500],
                details={
                    "user_message": user_text[:500],
                    "strong_matches": strong_corrections,
                    "weak_matches": weak_corrections,
                },
                session_hash=session_hash,
            )
        elif positive_score >= min_confidence and positive_score > correction_score:
            confidence = min(positive_score, 1.0)
            return FeedbackSignal(
                timestamp=msg.get("timestamp", datetime.now().isoformat()),
                signal_type="accepted",
                confidence=round(confidence, 3),
                rule_ids=[],
                context=assistant_text[:500],
                details={
                    "user_message": user_text[:500],
                    "strong_matches": strong_positives,
                    "weak_matches": weak_positives,
                },
                session_hash=session_hash,
            )

        return None

    def attribute_rules(self, signals: list[FeedbackSignal]) -> list[FeedbackSignal]:
        """Retroactively attribute feedback signals to rules via embedding similarity.

        For each signal, finds which rules are most similar to the context
        and assigns them as the rules this feedback is about.
        """
        try:
            from synesis.ml.embeddings import EmbeddingEngine
            engine = EmbeddingEngine(self._ml_dir)
        except ImportError:
            return signals

        # Only attribute signals that don't already have rule_ids
        unattributed = [s for s in signals if not s.rule_ids and s.context]
        if not unattributed:
            return signals

        for signal in unattributed:
            results = engine.search(signal.context, k=3)
            # Only attribute if similarity is meaningful (>0.3)
            signal.rule_ids = [rid for rid, sim in results if sim > 0.3]

        return signals

    def extract_from_directory(self, sessions_dir: Path) -> list[FeedbackSignal]:
        """Process JSONL session files, skipping already-processed ones."""
        processed = self._load_processed()
        all_signals = []

        for f in sessions_dir.rglob("*.jsonl"):
            fhash = self._session_hash(f)
            if fhash in processed:
                continue

            try:
                signals = self.extract_from_session(f)
                all_signals.extend(signals)
                processed.add(fhash)
            except Exception as e:
                logger.warning(f"Failed to parse {f}: {e}")

        self._save_processed(processed)

        # Attribute rules to signals
        if all_signals:
            all_signals = self.attribute_rules(all_signals)

        return all_signals

    def save_feedback(self, signals: list[FeedbackSignal]) -> int:
        if not signals:
            return 0
        with open(self._feedback_path, "a", encoding="utf-8") as f:
            for s in signals:
                f.write(json.dumps(s.to_dict()) + "\n")
        return len(signals)

    def load_feedback(self) -> list[FeedbackSignal]:
        if not self._feedback_path.exists():
            return []
        signals = []
        for line in self._feedback_path.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                signals.append(FeedbackSignal.from_dict(json.loads(line)))
            except Exception:
                continue
        return signals

    def feedback_count(self) -> int:
        if not self._feedback_path.exists():
            return 0
        return sum(1 for line in self._feedback_path.read_text().strip().split("\n") if line.strip())

    def _parse_session(self, path: Path) -> list[dict]:
        """Parse a JSONL conversation file into message dicts.

        Handles the real Claude Code JSONL format:
        - type: "user" or "assistant" (skip "queue-operation", "progress")
        - message.message.content: list of {type: "text", text: "..."} blocks
        - message.content: sometimes a string directly
        """
        messages = []
        for line in path.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            role = entry.get("type", "")
            if role not in ("user", "assistant"):
                continue

            text = self._extract_text(entry)
            if not text:
                continue

            messages.append({
                "role": role,
                "text": text,
                "timestamp": entry.get("timestamp", ""),
            })
        return messages

    def _extract_text(self, entry: dict) -> str:
        """Extract text from the nested message structure."""
        # Try: entry.message.message.content (real Claude Code format)
        msg = entry.get("message", {})
        if isinstance(msg, dict):
            inner = msg.get("message", msg)
            if isinstance(inner, dict):
                content = inner.get("content", "")
                if isinstance(content, list):
                    parts = []
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "text":
                            parts.append(c.get("text", ""))
                    return " ".join(parts)
                elif isinstance(content, str):
                    return content

            # Fallback: entry.message.content
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return " ".join(
                    c.get("text", "") for c in content
                    if isinstance(c, dict) and c.get("type") == "text"
                )

        return ""

    def _session_hash(self, path: Path) -> str:
        """Hash based on path + mtime for dedup."""
        stat = path.stat()
        key = f"{path}:{stat.st_size}:{stat.st_mtime}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def _load_processed(self) -> set[str]:
        if not self._processed_path.exists():
            return set()
        try:
            return set(json.loads(self._processed_path.read_text(encoding="utf-8")))
        except Exception:
            return set()

    def _save_processed(self, processed: set[str]) -> None:
        self._processed_path.write_text(
            json.dumps(sorted(processed)), encoding="utf-8"
        )
