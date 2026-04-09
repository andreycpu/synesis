"""Metrics history for proving the loop compounds.

Records a snapshot after each training run. Tracks:
- Attribution rate (% of feedback signals with rule_ids)
- Feedback quality (avg confidence)
- Scoring health (% of rules with >0 pulls)
- Retrieval quality (best experiment accuracy from param search)
- Rule health (% stale, % contradicted)
- Conversation coverage (indexed conversations)

If the system is truly self-improving, these metrics should trend
upward over time. If they're flat or declining, the loop is broken.

Stored in ml/metrics_history.jsonl - one snapshot per training run.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class MetricsHistory:
    def __init__(self, ml_dir: Path):
        self._ml_dir = ml_dir
        self._path = ml_dir / "metrics_history.jsonl"
        ml_dir.mkdir(parents=True, exist_ok=True)

    def record_snapshot(self, training_summary: dict) -> dict:
        """Extract key metrics from a training run summary and append to history.

        Returns the snapshot for display.
        """
        steps = training_summary.get("steps", {})

        fb = steps.get("feedback", {})
        scoring = steps.get("scoring", {})
        staleness = steps.get("staleness", {})
        contradictions = steps.get("contradictions", {})
        indexing = steps.get("indexing", {})
        param_search = steps.get("param_search", {})
        reward = steps.get("reward_model", {})
        conv_index = steps.get("conversation_index", {})

        total_feedback = fb.get("total_feedback", 0)
        new_signals = fb.get("new_signals", 0)
        attributed_new = fb.get("attributed", 0)

        snapshot = {
            "timestamp": training_summary.get("timestamp", datetime.now().isoformat()),
            "run_number": self._count_runs() + 1,

            # Feedback health
            "total_feedback": total_feedback,
            "new_signals": new_signals,
            "attribution_rate": round(
                attributed_new / max(new_signals, 1), 3
            ),
            "avg_confidence": fb.get("avg_confidence", 0),
            "by_type": fb.get("by_type", {}),

            # Attribution source breakdown
            "attribution_sources": self._count_attribution_sources(),

            # Scoring health
            "score_updates": scoring.get("updates", 0),
            "rules_indexed": indexing.get("rules_indexed", 0),

            # Retrieval quality (from param search)
            "best_accuracy": param_search.get("best_metrics", {}).get("accuracy"),
            "best_params": param_search.get("best_params"),

            # Reward model
            "reward_model_accuracy": reward.get("accuracy"),
            "reward_model_samples": reward.get("n_samples"),

            # Health indicators
            "stale_rules": staleness.get("stale_rules_found", 0) if isinstance(staleness, dict) else 0,
            "contradictions_found": contradictions.get("found", 0) if isinstance(contradictions, dict) else 0,
            "contradictions_resolved": contradictions.get("resolved", 0) if isinstance(contradictions, dict) else 0,

            # Coverage
            "conversations_indexed": conv_index.get("conversations_indexed", 0),
        }

        # Append to history
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(snapshot) + "\n")

        return snapshot

    def get_history(self) -> list[dict]:
        """Load full metrics history."""
        if not self._path.exists():
            return []
        snapshots = []
        for line in self._path.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                snapshots.append(json.loads(line))
            except Exception:
                continue
        return snapshots

    def get_trend(self) -> dict:
        """Analyze whether key metrics are improving over time.

        Returns a trend report with direction indicators.
        """
        history = self.get_history()
        if len(history) < 2:
            return {"status": "insufficient_data", "runs": len(history)}

        recent = history[-1]
        older = history[0] if len(history) <= 3 else history[-4]  # compare to ~3 runs ago

        def direction(new, old):
            if new is None or old is None:
                return "no_data"
            if new > old * 1.05:
                return "improving"
            elif new < old * 0.95:
                return "declining"
            return "stable"

        trends = {
            "runs_analyzed": len(history),
            "first_run": history[0].get("timestamp", "?")[:10],
            "latest_run": recent.get("timestamp", "?")[:10],
            "metrics": {
                "attribution_rate": {
                    "current": recent.get("attribution_rate"),
                    "baseline": older.get("attribution_rate"),
                    "trend": direction(
                        recent.get("attribution_rate"),
                        older.get("attribution_rate"),
                    ),
                },
                "avg_confidence": {
                    "current": recent.get("avg_confidence"),
                    "baseline": older.get("avg_confidence"),
                    "trend": direction(
                        recent.get("avg_confidence"),
                        older.get("avg_confidence"),
                    ),
                },
                "retrieval_accuracy": {
                    "current": recent.get("best_accuracy"),
                    "baseline": older.get("best_accuracy"),
                    "trend": direction(
                        recent.get("best_accuracy"),
                        older.get("best_accuracy"),
                    ),
                },
                "reward_model_accuracy": {
                    "current": recent.get("reward_model_accuracy"),
                    "baseline": older.get("reward_model_accuracy"),
                    "trend": direction(
                        recent.get("reward_model_accuracy"),
                        older.get("reward_model_accuracy"),
                    ),
                },
                "stale_rules": {
                    "current": recent.get("stale_rules"),
                    "baseline": older.get("stale_rules"),
                    "trend": direction(  # for stale rules, lower is better
                        older.get("stale_rules", 0),
                        recent.get("stale_rules", 0),
                    ),
                },
                "total_feedback": {
                    "current": recent.get("total_feedback"),
                    "baseline": older.get("total_feedback"),
                    "trend": direction(
                        recent.get("total_feedback"),
                        older.get("total_feedback"),
                    ),
                },
            },
        }

        # Overall verdict
        metric_trends = [
            v["trend"] for v in trends["metrics"].values()
            if v["trend"] != "no_data"
        ]
        improving = metric_trends.count("improving")
        declining = metric_trends.count("declining")

        if improving > declining:
            trends["verdict"] = "COMPOUNDING"
        elif declining > improving:
            trends["verdict"] = "DEGRADING"
        else:
            trends["verdict"] = "STABLE"

        return trends

    def _count_runs(self) -> int:
        if not self._path.exists():
            return 0
        return sum(1 for line in self._path.read_text().strip().split("\n") if line.strip())

    def _count_attribution_sources(self) -> dict:
        """Count attribution sources across all feedback."""
        feedback_path = self._ml_dir / "feedback.jsonl"
        if not feedback_path.exists():
            return {}

        counts: dict[str, int] = {"ledger": 0, "text_match": 0, "none": 0}
        for line in feedback_path.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                source = d.get("attribution_source", "")
                if source == "ledger":
                    counts["ledger"] += 1
                elif source == "text_match":
                    counts["text_match"] += 1
                elif not d.get("rule_ids"):
                    counts["none"] += 1
                else:
                    counts["text_match"] += 1  # has rule_ids but no source tag
            except Exception:
                continue

        return counts
