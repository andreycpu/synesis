"""Auto-research style training loop for retrieval optimization.

The "model" is the retrieval pipeline (embeddings + scorer + reward model).
The "metric" is outcome-based: did the retriever surface rules that led to
good outcomes (accepted) and suppress rules that led to bad outcomes (corrected)?
The "training loop" searches for better parameters and retrains components.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from itertools import product
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class Experiment:
    id: str
    params: dict
    metrics: dict
    timestamp: str
    duration_seconds: float
    is_best: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class Trainer:
    def __init__(self, ml_dir: Path, kb_dir: Path):
        self._ml_dir = ml_dir
        self._kb_dir = kb_dir
        self._experiments_path = ml_dir / "experiments.jsonl"
        self._config_path = ml_dir / "config.json"
        ml_dir.mkdir(parents=True, exist_ok=True)

    def run_training_loop(self) -> dict:
        """Full training pipeline."""
        from synesis.ml.scorer import RuleScorer
        from synesis.ml.feedback import FeedbackExtractor
        from synesis.ml.reward_model import RewardModel
        from synesis.ml.retriever import SemanticRetriever
        from synesis.ml.consolidator import RuleConsolidator
        from synesis.ml.staleness import StalenessDetector

        summary = {"timestamp": datetime.now().isoformat(), "steps": {}}

        # Step 1: Extract feedback (with session dedup + rule attribution)
        logger.info("Step 1: Extracting feedback from sessions...")
        extractor = FeedbackExtractor(self._ml_dir, kb_dir=self._kb_dir)
        sessions_dir = Path.home() / ".claude" / "projects"
        new_signals = extractor.extract_from_directory(sessions_dir)
        saved = extractor.save_feedback(new_signals)
        all_feedback = extractor.load_feedback()
        summary["steps"]["feedback"] = {
            "new_signals": saved,
            "total_feedback": len(all_feedback),
            "by_type": self._count_by_type(all_feedback),
            "avg_confidence": round(
                sum(f.confidence for f in all_feedback) / max(len(all_feedback), 1), 3
            ),
            "attributed": sum(1 for s in new_signals if s.rule_ids),
            "unattributed": sum(1 for s in new_signals if not s.rule_ids),
        }

        # Step 2: Update scorer with attributed, confidence-weighted feedback
        logger.info("Step 2: Updating rule scores...")
        scorer = RuleScorer(self._ml_dir)
        score_updates = 0
        for signal in new_signals:
            for rule_id in signal.rule_ids:
                weight = signal.confidence
                if signal.signal_type in ("accepted", "completed"):
                    scorer.record_outcome(rule_id, reward=1.0 * weight)
                    score_updates += 1
                elif signal.signal_type == "corrected":
                    scorer.record_outcome(rule_id, reward=-0.5 * weight)
                    if weight > 0.5:
                        scorer.record_correction(rule_id)
                    score_updates += 1
                elif signal.signal_type == "ignored":
                    scorer.record_outcome(rule_id, reward=-0.2 * weight)
                    score_updates += 1

        scorer.decay_scores(factor=0.98)
        summary["steps"]["scoring"] = {"updates": score_updates}

        # Step 3: Detect staleness and contradictions
        logger.info("Step 3: Detecting staleness and contradictions...")
        detector = StalenessDetector(self._ml_dir, self._kb_dir)

        try:
            stale = detector.detect_stale()
            stale_result = detector.apply_staleness(stale)
            summary["steps"]["staleness"] = {
                "stale_rules_found": len(stale),
                "scores_reduced": stale_result["reduced"],
                "heavily_penalized": stale_result["removed"],
                "top_stale": [
                    {"text": s.text[:60], "reason": s.reason, "loss": s.confidence_loss}
                    for s in stale[:5]
                ],
            }
        except Exception as e:
            logger.warning(f"Staleness detection failed: {e}")
            summary["steps"]["staleness"] = {"error": str(e)}

        try:
            contradictions = detector.detect_contradictions()
            if contradictions:
                contra_result = detector.resolve_contradictions(contradictions)
                summary["steps"]["contradictions"] = {
                    "found": len(contradictions),
                    "resolved": contra_result["resolved"],
                    "flagged_for_review": contra_result["flagged"],
                    "details": [
                        {
                            "a": c.rule_a_text[:50],
                            "b": c.rule_b_text[:50],
                            "score": c.contradiction_score,
                            "resolution": c.resolution,
                        }
                        for c in contradictions[:5]
                    ],
                }
            else:
                summary["steps"]["contradictions"] = {"found": 0}
        except Exception as e:
            logger.warning(f"Contradiction detection failed: {e}")
            summary["steps"]["contradictions"] = {"error": str(e)}

        # Step 4: Rebuild embedding index
        logger.info("Step 4: Building embedding index...")
        retriever = SemanticRetriever(self._ml_dir, self._kb_dir)
        n_rules = retriever.index_rules()
        summary["steps"]["indexing"] = {"rules_indexed": n_rules}

        # Step 5: Train reward model
        logger.info("Step 5: Training reward model...")
        reward_model = RewardModel(self._ml_dir)
        reward_result = reward_model.train(all_feedback, scorer)
        summary["steps"]["reward_model"] = reward_result

        # Step 6: Parameter search with proper train/test split
        logger.info("Step 6: Running parameter search...")
        attributed = [f for f in all_feedback if f.rule_ids]
        if len(attributed) >= 10:
            best_exp = self.search_params(attributed, n_trials=15)
            if best_exp:
                self.save_best_config(best_exp)
                summary["steps"]["param_search"] = {
                    "best_params": best_exp.params,
                    "best_metrics": best_exp.metrics,
                }
            else:
                summary["steps"]["param_search"] = {"status": "no_improvement"}
        else:
            summary["steps"]["param_search"] = {
                "status": "skipped",
                "reason": f"need 10+ attributed signals, have {len(attributed)}",
            }

        # Step 7: Consolidate rules
        logger.info("Step 7: Consolidating rules...")
        consolidator = RuleConsolidator(self._ml_dir, self._kb_dir)
        consol_result = consolidator.run(dry_run=False)
        summary["steps"]["consolidation"] = {
            "merges": len(consol_result.get("merges", [])),
            "pruned": len(consol_result.get("pruned", [])),
            "patterns_found": len(consol_result.get("patterns", [])),
            "new_patterns": consol_result.get("patterns", []),
        }

        # Step 8: Build conversation index
        logger.info("Step 8: Building conversation index...")
        try:
            from synesis.ml.conversation_index import ConversationIndex
            conv_index = ConversationIndex(self._ml_dir, self._kb_dir)
            n_convos = conv_index.build_index()
            summary["steps"]["conversation_index"] = {"conversations_indexed": n_convos}
        except Exception as e:
            logger.warning(f"Conversation indexing failed: {e}")
            summary["steps"]["conversation_index"] = {"error": str(e)}

        # Step 9: Rebuild rule index if rules changed
        if consol_result.get("merges") or consol_result.get("pruned"):
            logger.info("Step 9: Rebuilding rule index after consolidation...")
            n_rules = retriever.index_rules()
            summary["steps"]["reindex"] = {"rules_indexed": n_rules}

        logger.info("Training loop complete.")
        return summary

    def run_experiment(self, params: dict, test_feedback: list) -> Experiment:
        """Test a parameter set against held-out test feedback.

        Outcome-based metric:
        - For POSITIVE signals (accepted/completed) with known rule_ids:
          check if that rule_id appears in top-k retrieval. Hit = good.
        - For NEGATIVE signals (corrected) with known rule_ids:
          check if that rule_id is NOT in top-k retrieval. Absence = good.
        This measures whether the retriever correctly surfaces helpful rules
        and suppresses harmful ones.
        """
        from synesis.ml.retriever import SemanticRetriever

        start = time.time()
        retriever = SemanticRetriever(self._ml_dir, self._kb_dir)

        correct = 0
        n_evaluated = 0
        dcg_total = 0.0

        k = params.get("k", 5)

        for signal in test_feedback:
            if not signal.context or not signal.rule_ids:
                continue

            results = retriever.retrieve(
                query=signal.context,
                k=k,
                embedding_weight=params.get("embedding_weight", 0.7),
                score_weight=params.get("score_weight", 0.3),
            )

            if not results:
                continue

            n_evaluated += 1
            retrieved_ids = [r["rule_id"] for r in results]

            if signal.signal_type in ("accepted", "completed"):
                # Positive: the attributed rule SHOULD be in top-k
                for target_id in signal.rule_ids:
                    if target_id in retrieved_ids:
                        rank = retrieved_ids.index(target_id) + 1
                        correct += 1
                        dcg_total += 1.0 / np.log2(rank + 1)
                        break
            elif signal.signal_type == "corrected":
                # Negative: the attributed rule should NOT be in top-k
                found_bad = False
                for target_id in signal.rule_ids:
                    if target_id in retrieved_ids:
                        found_bad = True
                        break
                if not found_bad:
                    correct += 1  # Correctly suppressed the bad rule

        duration = time.time() - start

        metrics = {
            "accuracy": round(correct / max(n_evaluated, 1), 4),
            "mean_dcg": round(dcg_total / max(n_evaluated, 1), 4),
            "n_evaluated": n_evaluated,
            "correct": correct,
        }

        exp_id = f"exp_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{hash(str(params)) % 10000:04d}"
        exp = Experiment(
            id=exp_id,
            params=params,
            metrics=metrics,
            timestamp=datetime.now().isoformat(),
            duration_seconds=round(duration, 2),
        )

        self._log_experiment(exp)
        return exp

    def search_params(self, feedback: list, n_trials: int = 15) -> Experiment | None:
        """Grid search with proper train/test split."""
        rng = np.random.default_rng(42)
        indices = rng.permutation(len(feedback))
        split = int(len(feedback) * 0.7)
        test_indices = indices[split:]
        test_set = [feedback[i] for i in test_indices]

        if len(test_set) < 3:
            return None

        param_grid = {
            "embedding_weight": [0.5, 0.6, 0.7, 0.8, 0.9],
            "score_weight": [0.1, 0.2, 0.3, 0.4, 0.5],
            "k": [3, 5, 8, 10],
        }

        all_combos = [
            dict(zip(param_grid.keys(), v))
            for v in product(*param_grid.values())
        ]

        if len(all_combos) > n_trials:
            combo_indices = rng.choice(len(all_combos), size=n_trials, replace=False)
            combos = [all_combos[i] for i in combo_indices]
        else:
            combos = all_combos

        best: Experiment | None = None
        for params in combos:
            exp = self.run_experiment(params, test_set)
            if best is None or exp.metrics["accuracy"] > best.metrics["accuracy"]:
                best = exp

        current_config = self.load_config()
        if current_config:
            baseline = self.run_experiment(current_config, test_set)
            if best and best.metrics["accuracy"] <= baseline.metrics["accuracy"]:
                logger.info("Current config is still best.")
                return None

        if best:
            best.is_best = True
            logger.info(f"Best params: {best.params} -> {best.metrics}")

        return best

    def save_best_config(self, experiment: Experiment) -> None:
        config = dict(experiment.params)
        config["_updated"] = datetime.now().isoformat()
        config["_experiment_id"] = experiment.id
        config["_metrics"] = experiment.metrics
        self._config_path.write_text(
            json.dumps(config, indent=2), encoding="utf-8"
        )

    def load_config(self) -> dict:
        if not self._config_path.exists():
            return {}
        try:
            raw = json.loads(self._config_path.read_text(encoding="utf-8"))
            return {k: v for k, v in raw.items() if not k.startswith("_")}
        except Exception:
            return {}

    def get_status(self) -> dict:
        from synesis.ml.scorer import RuleScorer
        from synesis.ml.feedback import FeedbackExtractor
        from synesis.ml.reward_model import RewardModel

        scorer = RuleScorer(self._ml_dir)
        extractor = FeedbackExtractor(self._ml_dir, kb_dir=self._kb_dir)
        feedback = extractor.load_feedback()

        attributed = sum(1 for f in feedback if f.rule_ids)

        status = {
            "n_rules_scored": len(scorer.all_scores()),
            "n_feedback": len(feedback),
            "n_attributed": attributed,
            "feedback_by_type": self._count_by_type(feedback),
            "avg_confidence": round(
                sum(f.confidence for f in feedback) / max(len(feedback), 1), 3
            ),
            "reward_model_trained": RewardModel(self._ml_dir).is_trained(),
            "best_config": self.load_config(),
            "faiss_index_exists": (self._ml_dir / "faiss.index").exists(),
            "n_experiments": self._count_experiments(),
        }

        # Stale rules count
        try:
            from synesis.ml.staleness import StalenessDetector
            detector = StalenessDetector(self._ml_dir, self._kb_dir)
            stale = detector.detect_stale()
            status["n_stale_rules"] = len(stale)
        except Exception:
            pass

        top = scorer.get_top_rules(5)
        if top:
            texts = {}
            txt_path = self._ml_dir / "rule_texts.json"
            if txt_path.exists():
                try:
                    texts = json.loads(txt_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            status["top_rules"] = [
                {"id": rid, "score": round(s, 3), "text": texts.get(rid, "")[:80]}
                for rid, s in top
            ]

        return status

    def _count_by_type(self, feedback: list) -> dict:
        counts: dict[str, int] = {}
        for f in feedback:
            counts[f.signal_type] = counts.get(f.signal_type, 0) + 1
        return counts

    def _count_experiments(self) -> int:
        if not self._experiments_path.exists():
            return 0
        return sum(1 for line in self._experiments_path.read_text().strip().split("\n") if line.strip())

    def _log_experiment(self, exp: Experiment) -> None:
        with open(self._experiments_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(exp.to_dict()) + "\n")
