"""Feedback extraction from session data.

No LLM calls. Extracts signals by pattern matching on conversation structure:
- User accepted a suggestion (no correction after assistant message)
- User corrected the agent (correction language detected)
- Rule was retrieved but not used
- Task completed successfully (positive closing)
"""
from __future__ import annotations

import json
import re
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

CORRECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\bno[,.\s]",
        r"\bdon'?t\b",
        r"\binstead\b",
        r"\bwrong\b",
        r"\bactually[,\s]",
        r"\bnot what\b",
        r"\bstop\b",
        r"\bthat'?s not\b",
        r"\bincorrect\b",
        r"\bfix (this|that|it)\b",
        r"\bredo\b",
        r"\brevert\b",
    ]
]

POSITIVE_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\bthanks?\b",
        r"\bperfect\b",
        r"\bgreat\b",
        r"\bexactly\b",
        r"\byes\b",
        r"\blgtm\b",
        r"\blooks good\b",
        r"\bnice\b",
        r"\bawesome\b",
        r"\bship it\b",
    ]
]


@dataclass
class FeedbackSignal:
    timestamp: str
    signal_type: str  # accepted, corrected, ignored, completed
    rule_id: str | None
    context: str  # surrounding text for featurization
    details: dict

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FeedbackSignal":
        return cls(**d)


class FeedbackExtractor:
    def __init__(self, ml_dir: Path):
        self._ml_dir = ml_dir
        self._feedback_path = ml_dir / "feedback.jsonl"
        ml_dir.mkdir(parents=True, exist_ok=True)

    def extract_from_session(self, session_path: Path) -> list[FeedbackSignal]:
        """Extract feedback signals from a JSONL conversation file."""
        signals = []
        messages = self._parse_session(session_path)

        if len(messages) < 2:
            return signals

        for i in range(1, len(messages)):
            prev = messages[i - 1]
            curr = messages[i]

            # Only look at user messages that follow assistant messages
            if prev.get("role") != "assistant" or curr.get("role") != "user":
                continue

            user_text = curr.get("text", "")
            assistant_text = prev.get("text", "")

            if not user_text:
                continue

            # Check for correction
            is_correction = any(p.search(user_text) for p in CORRECTION_PATTERNS)
            is_positive = any(p.search(user_text) for p in POSITIVE_PATTERNS)

            if is_correction and not is_positive:
                signals.append(FeedbackSignal(
                    timestamp=curr.get("timestamp", datetime.now().isoformat()),
                    signal_type="corrected",
                    rule_id=None,
                    context=assistant_text[:500],
                    details={"user_message": user_text[:500]},
                ))
            elif is_positive:
                signals.append(FeedbackSignal(
                    timestamp=curr.get("timestamp", datetime.now().isoformat()),
                    signal_type="accepted",
                    rule_id=None,
                    context=assistant_text[:500],
                    details={"user_message": user_text[:500]},
                ))

        # Check if session ended positively
        if messages and messages[-1].get("role") == "user":
            last_text = messages[-1].get("text", "")
            if any(p.search(last_text) for p in POSITIVE_PATTERNS):
                signals.append(FeedbackSignal(
                    timestamp=messages[-1].get("timestamp", datetime.now().isoformat()),
                    signal_type="completed",
                    rule_id=None,
                    context=last_text[:500],
                    details={},
                ))

        return signals

    def extract_from_directory(self, sessions_dir: Path) -> list[FeedbackSignal]:
        """Process all JSONL session files in a directory tree."""
        all_signals = []
        for f in sessions_dir.rglob("*.jsonl"):
            try:
                signals = self.extract_from_session(f)
                all_signals.extend(signals)
            except Exception as e:
                logger.warning(f"Failed to parse {f}: {e}")
        return all_signals

    def save_feedback(self, signals: list[FeedbackSignal]) -> int:
        """Append signals to feedback.jsonl. Returns count saved."""
        if not signals:
            return 0
        with open(self._feedback_path, "a", encoding="utf-8") as f:
            for s in signals:
                f.write(json.dumps(s.to_dict()) + "\n")
        return len(signals)

    def load_feedback(self) -> list[FeedbackSignal]:
        """Load all accumulated feedback."""
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
        """Parse a JSONL conversation file into message dicts."""
        messages = []
        for line in path.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Handle different JSONL formats
            role = entry.get("type") or entry.get("role", "")
            text = ""

            msg = entry.get("message", {})
            if isinstance(msg, dict):
                content = msg.get("content", "")
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    text = " ".join(
                        c.get("text", "") for c in content
                        if isinstance(c, dict) and c.get("type") == "text"
                    )

            messages.append({
                "role": role,
                "text": text,
                "timestamp": entry.get("timestamp", ""),
            })
        return messages
