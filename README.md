# Synesis

Self-evolving agent memory. Stores your conversations as files, then uses local ML models to learn which memories matter, score them, and improve its own retrieval over time.

No cloud. No LLM in the learning loop. The self-improvement runs entirely on your machine using sentence-transformers, FAISS, and scikit-learn.

---

## How it works

Synesis has two layers:

**Layer 1: Raw data as files.** Your conversations, emails, and messages are stored as markdown files on your machine. Agents navigate them with `grep`, `cat`, `tree` - tools they already know.

**Layer 2: ML self-improvement.** A local training loop that learns from how agents use the data. It scores rules, embeds them semantically, trains a reward model, and optimizes its own retrieval parameters - like [Karpathy's autoresearch](https://github.com/karpathy/autoresearch), but for memory retrieval instead of language model training.

### The self-improvement loop

```
Session N: agent retrieves rules (logged to ledger), acts on them
    |
    v
Feedback extraction: structural analysis with confidence scoring (no LLM)
    |
    v
Rule attribution: link feedback to specific rules via ledger + embedding similarity
    |
    v
Score update: UCB1 bandit adjusts scores, weighted by signal confidence
    |
    v
Staleness detection: flag old/unused/superseded rules, penalize scores
    |
    v
Contradiction detection: find opposing rules, resolve or flag for review
    |
    v
Reward model: logistic regression learns to predict rule utility
    |
    v
Parameter search: grid search with proper train/test split, keep improvements
    |
    v
Rule consolidation: cluster duplicates, prune dead rules, extract patterns
    |
    v
Session N+1: better retrieval, stale rules gone, contradictions resolved
```

Each cycle makes the next one better. The system has a concrete metric (retrieval precision against held-out feedback), modifies its own parameters, runs experiments, and only keeps improvements. Feedback that can't be attributed to specific rules is tracked but doesn't pollute the scoring system.

---

## The ML stack (no LLM calls)

| Component | What it does | ML technique |
|---|---|---|
| **Embeddings** | Semantic understanding of rules | sentence-transformers (all-MiniLM-L6-v2) |
| **Index** | Fast similarity search | FAISS (IndexFlatIP, cosine similarity) |
| **Scorer** | Balance exploitation vs exploration | UCB1 multi-armed bandit with confidence weighting |
| **Feedback** | Extract + attribute signals | Structural analysis with multi-signal confidence scoring |
| **Staleness** | Detect outdated/contradicting rules | Exponential decay, embedding drift, negation pattern matching |
| **Reward model** | Predict rule utility in context | Logistic regression (774d features: rule emb + context emb + behavioral signals) |
| **Consolidator** | Merge duplicates, prune dead rules | Agglomerative clustering on embeddings, TF-IDF pattern extraction |
| **Trainer** | Optimize retrieval parameters | Grid search with train/test split (precision@k, NDCG) |

All models run locally. The sentence-transformer downloads once (~90MB) and runs on CPU.

---

## Install

Open Claude Code and say:

> install synesis

That's it. The agent handles everything. When it's done, restart Claude Code.

Or manually:

```bash
curl -fsSL https://raw.githubusercontent.com/andreycpu/synesis/main/install.sh | bash
```

### Install ML dependencies

The base system works without ML (falls back to grep-based retrieval). To enable self-improvement:

```bash
cd ~/.synesis && .venv/bin/pip install -e ".[ml]"
```

### What happens after install

You don't see anything different. Synesis runs silently. But every Claude Code session now:

- Knows your conversation history across all past sessions
- Retrieves the most relevant rules using semantic search (not keyword matching)
- Records learnings and scores them based on outcomes
- Gets measurably better at retrieval over time

### Optional: connect more sources

Run `synesis` in your terminal to connect Gmail, Slack, Notion, etc.

---

## Usage

### Training (the self-improvement cycle)

```bash
synesis train
```

This runs the full pipeline:
1. Extracts feedback signals from sessions (with dedup - won't re-process)
2. Attributes feedback to specific rules via retrieval ledger + embedding similarity
3. Updates UCB1 bandit scores, weighted by signal confidence
4. Detects stale rules (age decay, inactivity, superseded by newer rules)
5. Detects contradicting rules and resolves them (keeps newer/higher-scored)
6. Rebuilds FAISS embedding index
7. Retrains the reward model (if enough attributed data)
8. Grid-searches retrieval parameters with proper train/test split
9. Consolidates rules (merge duplicates, prune dead weight, extract patterns)

Run it periodically - weekly is a good cadence. Each run makes retrieval better.

```
  SYNESIS  self-evolving agent memory
  ------------------------------------------

  21:43:33  starting training loop...
  21:43:44  feedback: 5 new, 52 total (avg confidence: 0.41)
  21:43:44  scores: 14 updates (11 attributed, 3 unattributed)
  21:43:44  staleness: 4 stale rules, 2 penalized
  21:43:44    [age_decay] user prefers tabs over spaces
  21:43:44  contradictions: 1 found, 1 resolved, 0 flagged
  21:43:44    "use verbose logging" vs "keep logs minimal" -> keep_b
  21:43:44  rules indexed: 21
  21:43:44  reward model: accuracy=0.742, n=47
  21:43:44  best params: {'embedding_weight': 0.8, 'score_weight': 0.2, 'k': 5}
  21:43:44  consolidation: 2 merges, 1 pruned, 3 patterns

  21:43:44  training complete
```

### Status

```bash
synesis status
```

Shows current ML metrics: rules scored, feedback signals, model accuracy, best parameters, top-performing rules.

### MCP tools (used by agents automatically)

| Tool | What it does |
|---|---|
| `orient(context)` | Session start - returns relevant rules via ML retrieval |
| `learn(rule)` | Record a new rule (gets scored and embedded) |
| `feedback(signal_type, ...)` | Record a feedback signal (accepted/corrected/ignored) |
| `train()` | Trigger the training loop from within a session |
| `ml_status()` | Show ML system state |
| `tree` | Show directory structure |
| `cat` | Read a file |
| `grep` | Search file contents (regex) |
| `grep_files` | List files matching a pattern |
| `ls` / `find` / `write_file` / `sync` / `stats` | Standard filesystem + sync tools |

### Autonomous optimization

Agents can also modify your setup when they notice patterns:

| Tool | What it does |
|---|---|
| `optimize_hook` | Install a Claude Code hook to automate repeated workflows |
| `optimize_agent_hook` | Install an AI-powered review hook |
| `optimize_instruction` | Add a persistent rule to CLAUDE.md |
| `optimize_script` | Create a reusable script |
| `view_optimizations` | See what the agent has changed (audit log) |

All modifications are validated against allowlists/blocklists and logged to `_agent/optimizations.md`.

---

## Architecture

### How retrieval works (with ML)

When an agent calls `orient(context="working on CRE deal analysis")`:

1. **Embed** the context using sentence-transformers (384d vector)
2. **Search** FAISS index for the 15 nearest rules by cosine similarity
3. **Score** each candidate: `combined = 0.7 * similarity + 0.3 * ucb_score`
4. If reward model is trained: blend in `P(useful | rule, context)` prediction
5. Return top 5 rules ranked by combined score

The weights (0.7, 0.3) are themselves optimized by the training loop.

### How scoring works (UCB1 bandit)

Each rule is an "arm" in a multi-armed bandit:

- **Pulling** = retrieving the rule for a session
- **Reward** = positive feedback (user accepted, task completed)
- **Penalty** = negative feedback (user corrected, rule ignored)
- **UCB1 formula**: `mean_reward + sqrt(2 * ln(total_pulls) / rule_pulls)`

This naturally balances using high-performing rules (exploitation) with trying under-tested rules (exploration). New rules get an exploration bonus. Consistently bad rules sink to the bottom and eventually get pruned.

### How feedback extraction works (no LLM)

The feedback extractor uses structural analysis, not just keyword matching. Three layers of signal quality:

**1. Pattern strength (strong vs weak):**
- Strong correction: "that's wrong", "I said X", "undo this" (high confidence alone)
- Weak correction: "instead", "actually", "don't" (only counts when combined with other signals)
- Strong positive: "thanks" at message start, "perfect", "lgtm" (high confidence alone)
- Weak positive: "great", "nice", "cool" (needs corroboration)

**2. Structural context:**
- Short messages after assistant responses are likely reactions (higher confidence)
- Long messages are usually new requests, even if they contain trigger words (lower confidence)
- Continuation patterns ("now do X", "can you also") heavily discount correction signals

**3. Multi-signal voting:**
- Confidence = (strong_matches * 0.4 + weak_matches * 0.15), capped at 1.0
- If both correction AND positive signals fire, both are discounted (ambiguous)
- Minimum confidence threshold of 0.25 to emit a signal at all

**4. Rule attribution:**
- Every retrieval is logged to a ledger (which rules were served, when)
- Feedback signals are retroactively attributed to rules via embedding similarity
- Only rules with >0.3 cosine similarity to the feedback context get attributed
- Unattributed signals are tracked but don't affect rule scores

**5. Session dedup:**
- Each session file is hashed (path + size + mtime)
- Already-processed sessions are skipped on subsequent training runs
- No duplicate feedback from re-processing the same conversations

### How the reward model works

A logistic regression trained on feedback data. Feature vector (774 dimensions):

- Rule embedding (384d) - what the rule says
- Context embedding (384d) - what the session is about
- Cosine similarity (1d) - how relevant the rule is to context
- Rule age in days (1d)
- Mean reward (1d) - historical performance
- Times pulled (1d)
- Times corrected (1d)
- Success rate (1d)

Predicts `P(useful)` - the probability that retrieving this rule in this context leads to positive feedback. Requires 10+ feedback signals to train. Uses balanced class weights to handle imbalanced data.

### How staleness detection works

The hardest problem in persistent memory: knowing when something you learned is no longer true.

Three staleness signals:

1. **Age decay**: Rules older than 30 days lose confidence exponentially (half-life model). A 60-day-old rule has 25% of its original confidence. This prevents ancient preferences from overriding recent behavior.

2. **Inactivity**: Rules not used in 14+ days get flagged. If the system keeps retrieving other rules instead of this one, it's probably not relevant anymore.

3. **Superseded**: If a newer rule covers the same topic (>0.7 embedding similarity) and has a better score, the older one is marked superseded. Preferences change - the system tracks this.

Stale rules don't get deleted immediately. Their scores get penalized, so they naturally sink in retrieval rankings. Severely stale rules (>0.8 confidence loss) get heavy penalties. The consolidator eventually prunes them.

### How contradiction detection works

When two rules say opposite things, the system catches it:

1. **Same topic detection**: Embedding similarity >0.5 means the rules are about the same thing
2. **Negation detection**: Pattern matching on antonym pairs ("always"/"never", "use"/"don't use", "prefers"/"avoids") plus structural negation analysis (shared content words where one rule has a negation marker and the other doesn't)
3. **Contradiction score**: `embedding_similarity * negation_score` - both high similarity AND clear opposition required

Resolution strategy:
- If one rule has significantly better reward history, keep it
- If scores are similar, keep the newer rule (preferences change over time)
- If both are ambiguous, flag for human review

### How consolidation works

1. **Cluster** rules using agglomerative clustering on embeddings (cosine distance, threshold=0.15)
2. **Merge** near-duplicates: keep highest-scored rule in each cluster, remove the rest
3. **Prune** rules with `mean_reward < -0.5` after 5+ uses
4. **Extract** new rule candidates via TF-IDF over correction contexts (what does the agent keep getting wrong?)

### How parameter search works

Like autoresearch but for retrieval. Critically, uses a **proper train/test split** to avoid circular evaluation:

1. Split attributed feedback 70/30 (train/test)
2. Define parameter grid: `embedding_weight`, `score_weight`, `k`
3. For each combination: run retriever against the **held-out 30% test set**
4. Metric: did the retriever rank the attributed rule highly? (precision@k, NDCG)
5. Compare against current best config
6. Only save new config if it beats the baseline on the test set

The evaluation is non-circular because:
- Feedback signals have rule_ids from the retrieval ledger (what was actually served in past sessions)
- We evaluate whether a DIFFERENT parameter set would rank those same rules
- The test set is never used for training

All experiments are logged to `ml/experiments.jsonl` for auditability.

---

## Project structure

```
synesis/
  ml/               # Self-improvement (the ML layer)
    embeddings.py    # Sentence-transformers + FAISS
    scorer.py        # UCB1 multi-armed bandit
    feedback.py      # Confidence-scored signal extraction with attribution
    reward_model.py  # Logistic regression utility predictor
    staleness.py     # Staleness detection + contradiction resolution
    consolidator.py  # Clustering + pruning + pattern extraction
    retriever.py     # Combined ranking pipeline + retrieval ledger
    trainer.py       # Auto-research training loop with train/test split
  agent/             # Agent self-modification
    learner.py       # Rules and index management
    optimizer.py     # Hook/instruction/script installation
  auth/              # OAuth (PKCE, encrypted token storage)
  connectors/        # Source plugins (Claude Code, Gmail, etc.)
  kb/                # Knowledge base types and storage
  config/            # Configuration manager
  sync/              # Sync engine (raw file writer)
  mcp/               # MCP server (all tools)
  cli.py             # CLI: synesis, synesis train, synesis status
```

### Data directory

```
~/synesis-data/
  config/synesis.yaml          # Configuration
  knowledge/                   # Raw data as markdown files
    claude_code/               # Claude Code conversations
    gmail/                     # Email threads
    _agent/                    # Agent state
      rules.md                 # Learned rules
      preferences.md           # User preferences
      index.md                 # KB index
      optimizations.md         # Audit log
  ml/                          # ML artifacts
    faiss.index                # FAISS similarity index
    embeddings.npz             # Cached embedding vectors
    rule_texts.json            # Rule ID to text mapping
    scores.json                # UCB1 bandit scores
    feedback.jsonl             # Confidence-scored, attributed feedback
    processed_sessions.json    # Session dedup tracking
    retrieval_ledger.jsonl     # Log of which rules were served when
    reward_model.pkl           # Trained sklearn model
    config.json                # Best retrieval parameters
    experiments.jsonl           # Experiment log
```

---

## Why not LLM extraction?

Most knowledge tools run an LLM over your data to "extract" structured knowledge. This is wrong:

1. **Lossy.** The LLM decides at sync time what's important. Context that matters later gets discarded.
2. **Expensive.** Every sync burns API credits.
3. **Unnecessary.** Agents already know `grep`, `cat`, `tree`. The filesystem is the interface.

Synesis stores raw data and lets agents navigate at query time. The ML layer improves *retrieval* (which rules to surface), not *storage* (what to keep).

---

## Connected sources

| Source | How it syncs | Setup |
|---|---|---|
| Claude Code | Reads local files from `~/.claude/` | Automatic |
| Gmail / Calendar / Drive | OAuth, API calls from your machine | Browser login |
| Slack | OAuth, API calls | Browser login |
| Notion | OAuth, API calls | Browser login |
| GitHub | OAuth, API calls | Browser login |
| Twitter / X | OAuth, API calls | Browser login |
| Linear | OAuth, API calls | Browser login |
| Spotify | OAuth, API calls | Browser login |

All data stays on your machine.

---

## For developers

### Adding a connector

```python
from synesis.connectors.base import BaseConnector
from synesis.kb.types import RawConversation

class MyConnector(BaseConnector):
    name = "my_service"
    def validate(self) -> bool: ...
    def fetch(self, since: str | None = None) -> list[RawConversation]: ...
```

Register in `synesis/connectors/__init__.py`.

---

## License

MIT
