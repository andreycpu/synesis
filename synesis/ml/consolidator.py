"""Rule consolidation - merge duplicates, prune dead rules, extract patterns.

Uses agglomerative clustering on embeddings to find near-duplicate rules,
TF-IDF over correction events to discover recurring feedback themes.
No LLM calls.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


class RuleConsolidator:
    def __init__(self, ml_dir: Path, kb_dir: Path):
        self._ml_dir = ml_dir
        self._kb_dir = kb_dir

        from synesis.ml.embeddings import EmbeddingEngine
        from synesis.ml.scorer import RuleScorer

        self._embeddings = EmbeddingEngine(ml_dir)
        self._scorer = RuleScorer(ml_dir)

    def cluster_rules(self, threshold: float = 0.15) -> list[list[str]]:
        """Cluster rules by embedding similarity. Returns groups of rule IDs."""
        from sklearn.cluster import AgglomerativeClustering

        rules = self._parse_rules()
        if len(rules) < 2:
            return [[r[0]] for r in rules]

        ids = [r[0] for r in rules]
        texts = [r[1] for r in rules]
        vecs = self._embeddings.embed(texts)

        # Cosine distance = 1 - cosine_similarity
        # Normalized vectors: cosine_sim = dot product, so distance = 1 - dot
        clustering = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=threshold,
            metric="cosine",
            linkage="average",
        )
        labels = clustering.fit_predict(vecs)

        clusters: dict[int, list[str]] = {}
        for rule_id, label in zip(ids, labels):
            clusters.setdefault(label, []).append(rule_id)

        return list(clusters.values())

    def merge_duplicates(self, dry_run: bool = False) -> list[dict]:
        """Merge near-duplicate rules. Keeps the highest-scored rule in each cluster."""
        clusters = self.cluster_rules()
        texts = self._load_rule_texts()
        merges = []

        for cluster in clusters:
            if len(cluster) < 2:
                continue

            # Pick the one with highest UCB score
            scored = [(rid, self._scorer.score_rule(rid)) for rid in cluster]
            scored.sort(key=lambda x: x[1], reverse=True)
            keep = scored[0][0]
            remove = [s[0] for s in scored[1:]]

            merges.append({
                "kept": keep,
                "kept_text": texts.get(keep, ""),
                "removed": remove,
                "removed_texts": [texts.get(r, "") for r in remove],
            })

        if not dry_run and merges:
            self._apply_merges(merges)

        return merges

    def prune_low_scoring(self, min_score: float = -0.5, min_uses: int = 5) -> list[dict]:
        """Remove rules that consistently score poorly after sufficient usage."""
        texts = self._load_rule_texts()
        pruned = []

        for rule_id, score_data in self._scorer.all_scores().items():
            if score_data.times_pulled < min_uses:
                continue
            if score_data.mean_reward < min_score:
                pruned.append({
                    "rule_id": rule_id,
                    "text": texts.get(rule_id, ""),
                    "mean_reward": score_data.mean_reward,
                    "times_pulled": score_data.times_pulled,
                    "times_corrected": score_data.times_corrected,
                })

        if pruned:
            remove_ids = {p["rule_id"] for p in pruned}
            self._remove_rules(remove_ids)

        return pruned

    def extract_patterns(self, min_frequency: int = 3) -> list[str]:
        """Find recurring themes in correction feedback using TF-IDF.

        Returns candidate new rules derived from what the agent keeps getting wrong.
        """
        from sklearn.feature_extraction.text import TfidfVectorizer

        from synesis.ml.feedback import FeedbackExtractor

        extractor = FeedbackExtractor(self._ml_dir)
        feedback = extractor.load_feedback()

        # Collect correction contexts
        corrections = [
            f.details.get("user_message", "") + " " + f.context
            for f in feedback
            if f.signal_type == "corrected" and (f.context or f.details.get("user_message"))
        ]

        if len(corrections) < min_frequency:
            return []

        # TF-IDF to find important terms in corrections
        vectorizer = TfidfVectorizer(
            max_features=50,
            stop_words="english",
            ngram_range=(2, 4),  # bigrams to 4-grams
            min_df=min(min_frequency, max(2, len(corrections) // 3)),
        )

        try:
            tfidf = vectorizer.fit_transform(corrections)
        except ValueError:
            return []

        # Top terms by mean TF-IDF score
        feature_names = vectorizer.get_feature_names_out()
        mean_scores = np.array(tfidf.mean(axis=0)).flatten()
        top_indices = mean_scores.argsort()[::-1][:10]

        patterns = []
        for idx in top_indices:
            term = feature_names[idx]
            score = mean_scores[idx]
            if score > 0.05:
                patterns.append(f"User frequently corrects about: {term}")

        return patterns

    def run(self, dry_run: bool = False) -> dict:
        """Full consolidation pass: cluster, merge, prune, extract."""
        results = {
            "timestamp": datetime.now().isoformat(),
            "merges": [],
            "pruned": [],
            "patterns": [],
        }

        try:
            results["merges"] = self.merge_duplicates(dry_run=dry_run)
        except Exception as e:
            logger.warning(f"Merge failed: {e}")
            results["merge_error"] = str(e)

        try:
            results["pruned"] = self.prune_low_scoring()
        except Exception as e:
            logger.warning(f"Prune failed: {e}")
            results["prune_error"] = str(e)

        try:
            results["patterns"] = self.extract_patterns()
        except Exception as e:
            logger.warning(f"Pattern extraction failed: {e}")
            results["pattern_error"] = str(e)

        return results

    def _parse_rules(self) -> list[tuple[str, str]]:
        from synesis.ml.retriever import _rule_id
        rules_path = self._kb_dir / "_agent" / "rules.md"
        if not rules_path.exists():
            return []
        content = rules_path.read_text(encoding="utf-8")
        rules = []
        for line in content.split("\n"):
            match = re.match(r"^- \[[\dT:.+-]+\]\s*(.+)$", line.strip())
            if match:
                text = match.group(1).strip()
                if text:
                    rules.append((_rule_id(text), text))
        return rules

    def _load_rule_texts(self) -> dict[str, str]:
        import json
        path = self._ml_dir / "rule_texts.json"
        if not path.exists():
            # Fall back to parsing rules.md
            return {r[0]: r[1] for r in self._parse_rules()}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _apply_merges(self, merges: list[dict]) -> None:
        """Rewrite rules.md removing merged-away rules."""
        remove_texts = set()
        for m in merges:
            remove_texts.update(m["removed_texts"])
        self._remove_rules_by_text(remove_texts)

    def _remove_rules(self, rule_ids: set[str]) -> None:
        texts = self._load_rule_texts()
        remove_texts = {texts[rid] for rid in rule_ids if rid in texts}
        self._remove_rules_by_text(remove_texts)

    def _remove_rules_by_text(self, remove_texts: set[str]) -> None:
        rules_path = self._kb_dir / "_agent" / "rules.md"
        if not rules_path.exists():
            return

        lines = rules_path.read_text(encoding="utf-8").split("\n")
        kept = []
        for line in lines:
            match = re.match(r"^- \[[\dT:.+-]+\]\s*(.+)$", line.strip())
            if match and match.group(1).strip() in remove_texts:
                continue
            kept.append(line)

        rules_path.write_text("\n".join(kept), encoding="utf-8")
