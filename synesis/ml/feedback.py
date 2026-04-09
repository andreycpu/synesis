"""Feedback extraction from session data.

No LLM calls. Extracts signals using structural analysis of conversations.

Attribution strategy (layered, in priority order):
1. RETRIEVAL LEDGER (ground truth): The retriever logs which rules were served
   and when to retrieval_ledger.jsonl. If a feedback signal's timestamp falls
   within a session window that had ledger entries, those rules are attributed.
   This is exact - we know what was served.
2. TEXT MATCHING (fallback): If no ledger data exists for the time window,
   fall back to checking if rule content words appear in the assistant response.
   This catches sessions before the ledger existed or where orient() wasn't called.

Session dedup via processed_sessions.json prevents duplicate extraction.
Confidence scoring reduces false positives from broad pattern matching.
"""
from __future__ import annotations

import hashlib
import json
import re
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

STRONG_CORRECTION = [
    re.compile(p, re.IGNORECASE) for p in [
        r"^no[,.\s]",
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
        r"^(thanks?|ty|thx)\b",
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
    confidence: float  # 0.0 to 1.0
    rule_ids: list[str]  # rules attributed to this signal
    context: str
    details: dict
    session_hash: str = ""
    attribution_source: str = ""  # "ledger", "text_match", ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FeedbackSignal":
        if "rule_id" in d and "rule_ids" not in d:
            rid = d.pop("rule_id")
            d["rule_ids"] = [rid] if rid else []
        if "confidence" not in d:
            d["confidence"] = 0.5
        if "session_hash" not in d:
            d["session_hash"] = ""
        if "attribution_source" not in d:
            d["attribution_source"] = ""
        return cls(**d)


class FeedbackExtractor:
    def __init__(self, ml_dir: Path, kb_dir: Path | None = None):
        self._ml_dir = ml_dir
        self._kb_dir = kb_dir
        self._feedback_path = ml_dir / "feedback.jsonl"
        self._processed_path = ml_dir / "processed_sessions.json"
        self._ledger_path = ml_dir / "retrieval_ledger.jsonl"
        ml_dir.mkdir(parents=True, exist_ok=True)
        self._rules_cache: list[tuple[str, str]] | None = None
        self._ledger_cache: list[dict] | None = None

    # ---- Retrieval ledger (ground truth attribution) ----

    def _load_ledger(self) -> list[dict]:
        """Load the retrieval ledger. Each entry has timestamp + rule_ids."""
        if self._ledger_cache is not None:
            return self._ledger_cache

        if not self._ledger_path.exists():
            self._ledger_cache = []
            return self._ledger_cache

        entries = []
        for line in self._ledger_path.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except Exception:
                continue

        self._ledger_cache = entries
        return entries

    def _attribute_from_ledger(self, signal_timestamp: str, window_minutes: int = 30) -> list[str]:
        """Find which rules were served near a feedback signal's timestamp.

        Looks at the retrieval ledger for entries within window_minutes of
        the signal. Returns the union of all rule_ids that were served.
        This is ground truth - the retriever logged exactly what it served.
        """
        ledger = self._load_ledger()
        if not ledger:
            return []

        try:
            signal_dt = datetime.fromisoformat(signal_timestamp)
        except Exception:
            return []

        window = timedelta(minutes=window_minutes)
        rule_ids = set()

        for entry in ledger:
            try:
                entry_dt = datetime.fromisoformat(entry["timestamp"])
            except Exception:
                continue

            # Ledger entry must be BEFORE the feedback (rules served, then user reacted)
            # and within the window
            diff = signal_dt - entry_dt
            if timedelta(0) <= diff <= window:
                rule_ids.update(entry.get("rule_ids", []))

        return list(rule_ids)

    # ---- Text matching (fallback attribution) ----

    def _load_rules(self) -> list[tuple[str, str]]:
        if self._rules_cache is not None:
            return self._rules_cache

        if self._kb_dir is None:
            self._rules_cache = []
            return self._rules_cache

        from synesis.ml.retriever import _rule_id

        rules_path = self._kb_dir / "_agent" / "rules.md"
        if not rules_path.exists():
            self._rules_cache = []
            return self._rules_cache

        rules = []
        for line in rules_path.read_text(encoding="utf-8").split("\n"):
            match = re.match(r"^- \[[\dT:.+-]+\]\s*(.+)$", line.strip())
            if match:
                text = match.group(1).strip()
                if text:
                    rules.append((_rule_id(text), text))

        self._rules_cache = rules
        return rules

    def _match_rules_in_text(self, assistant_text: str) -> list[str]:
        """Fallback: find which rules appear in an assistant message via word overlap."""
        if not assistant_text:
            return []

        rules = self._load_rules()
        if not rules:
            return []

        assistant_lower = assistant_text.lower()
        matched_ids = []

        for rule_id, rule_text in rules:
            rule_words = set(re.findall(r'\b\w{4,}\b', rule_text.lower()))
            if not rule_words:
                continue

            hits = sum(1 for w in rule_words if w in assistant_lower)
            coverage = hits / len(rule_words)

            if coverage >= 0.6:
                matched_ids.append(rule_id)

        return matched_ids

    # ---- Extraction ----

    def extract_from_session(self, session_path: Path) -> list[FeedbackSignal]:
        """Extract feedback signals from a JSONL conversation file.

        Attribution priority:
        1. Check retrieval ledger for rules served near the signal's timestamp
        2. Fall back to text matching if no ledger data
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
                # Layer 1: Try ledger-based attribution (ground truth)
                ledger_rules = self._attribute_from_ledger(signal.timestamp)
                if ledger_rules:
                    signal.rule_ids = ledger_rules
                    signal.attribution_source = "ledger"
                else:
                    # Layer 2: Fall back to text matching
                    text_rules = self._match_rules_in_text(assistant_text)
                    if text_rules:
                        signal.rule_ids = text_rules
                        signal.attribution_source = "text_match"

                signals.append(signal)

        return signals

    def _classify_message(
        self, user_text: str, assistant_text: str, msg: dict, session_hash: str
    ) -> FeedbackSignal | None:
        strong_corrections = sum(1 for p in STRONG_CORRECTION if p.search(user_text))
        weak_corrections = sum(1 for p in WEAK_CORRECTION if p.search(user_text))
        correction_score = strong_corrections * 0.4 + weak_corrections * 0.15

        strong_positives = sum(1 for p in STRONG_POSITIVE if p.search(user_text))
        weak_positives = sum(1 for p in WEAK_POSITIVE if p.search(user_text))
        positive_score = strong_positives * 0.4 + weak_positives * 0.15

        is_short = len(user_text) < 200
        is_continuation = any(p.search(user_text) for p in CONTINUATION_PATTERNS)

        if is_continuation:
            correction_score *= 0.3
            positive_score *= 0.5

        if not is_short:
            correction_score *= 0.5
            positive_score *= 0.5

        if correction_score > 0 and positive_score > 0:
            correction_score *= 0.5
            positive_score *= 0.5

        min_confidence = 0.25

        if correction_score >= min_confidence and correction_score > positive_score:
            return FeedbackSignal(
                timestamp=msg.get("timestamp", datetime.now().isoformat()),
                signal_type="corrected",
                confidence=round(min(correction_score, 1.0), 3),
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
            return FeedbackSignal(
                timestamp=msg.get("timestamp", datetime.now().isoformat()),
                signal_type="accepted",
                confidence=round(min(positive_score, 1.0), 3),
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

    def extract_from_directory(self, sessions_dir: Path) -> list[FeedbackSignal]:
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
