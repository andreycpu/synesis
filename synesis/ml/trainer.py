"""Auto-research style training loop for retrieval optimization.

Like Karpathy's autoresearch: run experiments, measure metrics,
keep improvements, discard failures, iterate. But instead of
training a language model, we optimize the retrieval system.

The "model" is the retrieval pipeline (embeddings + scorer + reward model).
The "metric" is retrieval quality measured against feedback ground truth.
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
        """Full training pipeline. The auto-research loop for retrieval.

        Steps:
        1. Extract feedback from recent sessions
        2. Update scorer with feedback signals
        3. Rebuild embedding index
        4. Retrain reward model
        5. Run parameter search experiments
        6. Consolidate rules (merge, prune, extract)
        7. Save best config

        Returns summary of all steps.
        """
        from synesis.ml.embeddings import EmbeddingEngine
        from synesis.ml.scorer import RuleScorer
        from synesis.ml.feedback import FeedbackExtractor
        from synesis.ml.reward_model import RewardModel
        from synesis.ml.retriever import SemanticRetriever
        from synesis.ml.consolidator import RuleConsolidator

        summary = {"timestamp": datetime.now().isoformat(), "steps": {}}

        # Step 1: Extract feedback
        logger.info("Step 1: Extracting feedback from sessions...")
        extractor = FeedbackExtractor(self._ml_dir)
        sessions_dir = Path.home() / ".claude" / "projects"
        new_signals = extractor.extract_from_directory(sessions_dir)
        saved = extractor.save_feedback(new_signals)
        all_feedback = extractor.load_feedback()
        summary["steps"]["feedback"] = {
            "new_signals": saved,
            "total_feedback": len(all_feedback),
            "by_type": self._count_by_type(all_feedback),
        }

        # Step 2: Update scorer with feedback
        logger.info("Step 2: Updating rule scores from feedback...")
        scorer = RuleScorer(self._ml_dir)
        score_updates = 0
        for signal in new_signals:
            if signal.rule_id:
                if signal.signal_type in ("accepted", "completed"):
                    scorer.record_outcome(signal.rule_id, reward=1.0)
                    score_updates += 1
                elif signal.signal_type == "corrected":
                    scorer.record_correction(signal.rule_id)
                    score_updates += 1
                elif signal.signal_type == "ignored":
                    scorer.record_outcome(signal.rule_id, reward=-0.2)
                    score_updates += 1

        scorer.decay_scores(factor=0.98)
        summary["steps"]["scoring"] = {"updates": score_updates}

        # Step 3: Rebuild embedding index
        logger.info("Step 3: Building embedding index...")
        retriever = SemanticRetriever(self._ml_dir, self._kb_dir)
        n_rules = retriever.index_rules()
        summary["steps"]["indexing"] = {"rules_indexed": n_rules}

        # Step 4: Train reward model
        logger.info("Step 4: Training reward model...")
        reward_model = RewardModel(self._ml_dir)
        reward_result = reward_model.train(all_feedback, scorer)
        summary["steps"]["reward_model"] = reward_result

        # Step 5: Parameter search
        logger.info("Step 5: Running parameter search experiments...")
        if len(all_feedback) >= 10:
            best_exp = self.search_params(all_feedback, n_trials=15)
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
                "reason": f"need 10+ feedback signals, have {len(all_feedback)}",
            }

        # Step 6: Consolidate rules
        logger.info("Step 6: Consolidating rules...")
        consolidator = RuleConsolidator(self._ml_dir, self._kb_dir)
        consol_result = consolidator.run(dry_run=False)
        summary["steps"]["consolidation"] = {
            "merges": len(consol_result.get("merges", [])),
            "pruned": len(consol_result.get("pruned", [])),
            "patterns_found": len(consol_result.get("patterns", [])),
            "new_patterns": consol_result.get("patterns", []),
        }

        # Step 7: Rebuild index after consolidation
        if consol_result.get("merges") or consol_result.get("pruned"):
            logger.info("Step 7: Rebuilding index after consolidation...")
            n_rules = retriever.index_rules()
            summary["steps"]["reindex"] = {"rules_indexed": n_rules}

        logger.info("Training loop complete.")
        return summary

    def run_experiment(self, params: dict, feedback: list) -> Experiment:
        """Test a parameter set against held-out feedback data.

        The metric: for each feedback event where a rule was relevant,
        how highly does the retriever rank that rule? We measure
        precision@k and NDCG.
        """
        from synesis.ml.retriever import SemanticRetriever

        start = time.time()
        retriever = SemanticRetriever(self._ml_dir, self._kb_dir)

        # Evaluate: for each positive feedback, check if retriever finds it
        hits_at_k = 0
        dcg_total = 0.0
        n_evaluated = 0

        k = params.get("k", 5)

        for signal in feedback:
            if not signal.context:
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

            # Check if any result is contextually relevant to the feedback
            # Use embedding similarity as proxy for relevance
            if signal.signal_type in ("accepted", "completed"):
                # For positive signals: good results should be at the top
                if results[0]["similarity"] > 0.3:
                    hits_at_k += 1
                    dcg_total += 1.0 / np.log2(2)  # rank 1
                elif len(results) > 1 and results[1]["similarity"] > 0.3:
                    hits_at_k += 1
                    dcg_total += 1.0 / np.log2(3)  # rank 2

        duration = time.time() - start

        metrics = {
            "precision_at_k": hits_at_k / max(n_evaluated, 1),
            "mean_dcg": dcg_total / max(n_evaluated, 1),
            "n_evaluated": n_evaluated,
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
        """Grid search over retrieval parameters. Returns best experiment."""
        param_grid = {
            "embedding_weight": [0.5, 0.6, 0.7, 0.8, 0.9],
            "score_weight": [0.1, 0.2, 0.3, 0.4, 0.5],
            "k": [3, 5, 8, 10],
        }

        # Generate all combinations, sample if too many
        all_combos = [
            dict(zip(param_grid.keys(), v))
            for v in product(*param_grid.values())
        ]

        if len(all_combos) > n_trials:
            rng = np.random.default_rng(42)
            indices = rng.choice(len(all_combos), size=n_trials, replace=False)
            combos = [all_combos[i] for i in indices]
        else:
            combos = all_combos

        best: Experiment | None = None
        current_config = self.load_config()

        for params in combos:
            exp = self.run_experiment(params, feedback)
            if best is None or exp.metrics["mean_dcg"] > best.metrics["mean_dcg"]:
                best = exp

        # Compare against current config
        if current_config:
            baseline = self.run_experiment(current_config, feedback)
            if best and best.metrics["mean_dcg"] <= baseline.metrics["mean_dcg"]:
                logger.info("Current config is still best. No change.")
                baseline.is_best = True
                return None  # No improvement

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
        """Current state of the ML system."""
        from synesis.ml.scorer import RuleScorer
        from synesis.ml.feedback import FeedbackExtractor
        from synesis.ml.reward_model import RewardModel

        scorer = RuleScorer(self._ml_dir)
        extractor = FeedbackExtractor(self._ml_dir)
        feedback = extractor.load_feedback()

        status = {
            "n_rules_scored": len(scorer.all_scores()),
            "n_feedback": len(feedback),
            "feedback_by_type": self._count_by_type(feedback),
            "reward_model_trained": RewardModel(self._ml_dir).is_trained(),
            "best_config": self.load_config(),
            "faiss_index_exists": (self._ml_dir / "faiss.index").exists(),
            "n_experiments": self._count_experiments(),
        }

        # Top rules
        top = scorer.get_top_rules(5)
        if top:
            from synesis.ml.retriever import SemanticRetriever
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
