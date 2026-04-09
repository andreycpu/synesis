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
Session N: agent retrieves rules, acts on them
    |
    v
Feedback extraction: parse session for corrections/acceptances (regex, no LLM)
    |
    v
Score update: UCB1 bandit adjusts rule scores based on outcomes
    |
    v
Reward model: logistic regression learns to predict rule utility
    |
    v
Parameter search: grid search over retrieval weights, keep improvements
    |
    v
Rule consolidation: cluster duplicates, prune dead rules, extract patterns
    |
    v
Session N+1: better retrieval, higher-scoring rules surface first
```

Each cycle makes the next one better. The system has a concrete metric (retrieval precision against feedback), modifies its own parameters, runs experiments, and only keeps improvements.

---

## The ML stack (no LLM calls)

| Component | What it does | ML technique |
|---|---|---|
| **Embeddings** | Semantic understanding of rules | sentence-transformers (all-MiniLM-L6-v2) |
| **Index** | Fast similarity search | FAISS (IndexFlatIP, cosine similarity) |
| **Scorer** | Balance exploitation vs exploration | UCB1 multi-armed bandit |
| **Feedback** | Extract signals from sessions | Regex pattern matching on conversation structure |
| **Reward model** | Predict rule utility in context | Logistic regression (774d features: rule emb + context emb + behavioral signals) |
| **Consolidator** | Merge duplicates, prune dead rules | Agglomerative clustering on embeddings, TF-IDF pattern extraction |
| **Trainer** | Optimize retrieval parameters | Grid search with held-out evaluation (precision@k, NDCG) |

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
1. Extracts feedback signals from your Claude Code sessions
2. Updates UCB1 bandit scores for each rule
3. Rebuilds the FAISS embedding index
4. Retrains the reward model (if enough data)
5. Grid-searches retrieval parameters against held-out feedback
6. Consolidates rules (merge duplicates, prune dead weight, extract patterns)

Run it periodically - weekly is a good cadence. Each run makes retrieval better.

```
  SYNESIS  self-evolving agent memory
  ------------------------------------------

  21:26:25  starting training loop...
  21:26:40  feedback: 4 new, 47 total
  21:26:40  scores updated: 12
  21:26:40  rules indexed: 23
  21:26:40  reward model: accuracy=0.742, n=47
  21:26:40  best params: {'embedding_weight': 0.8, 'score_weight': 0.2, 'k': 5}
  21:26:40  consolidation: 2 merges, 1 pruned, 3 patterns

  21:26:40  training complete
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

The feedback extractor parses JSONL conversation files looking for structural patterns:

- **Correction detected**: user message contains "no", "don't", "wrong", "actually", "instead", "revert" etc. after an assistant message
- **Acceptance detected**: user message contains "thanks", "perfect", "exactly", "lgtm", "looks good" etc.
- **Completion detected**: session ends with positive user message

12 correction patterns and 10 positive patterns, all regex-based. No ambiguity, no LLM interpretation needed.

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

### How consolidation works

1. **Cluster** rules using agglomerative clustering on embeddings (cosine distance, threshold=0.15)
2. **Merge** near-duplicates: keep highest-scored rule in each cluster, remove the rest
3. **Prune** rules with `mean_reward < -0.5` after 5+ uses
4. **Extract** new rule candidates via TF-IDF over correction contexts (what does the agent keep getting wrong?)

### How parameter search works

Like autoresearch but for retrieval:

1. Define parameter grid: `embedding_weight`, `score_weight`, `k`
2. For each combination: run retriever against held-out feedback, measure precision@k and NDCG
3. Compare against current best config
4. Only save new config if it beats the baseline

All experiments are logged to `ml/experiments.jsonl` for auditability.

---

## Project structure

```
synesis/
  ml/               # Self-improvement (the ML layer)
    embeddings.py    # Sentence-transformers + FAISS
    scorer.py        # UCB1 multi-armed bandit
    feedback.py      # Signal extraction from sessions
    reward_model.py  # Logistic regression utility predictor
    consolidator.py  # Clustering + pruning + pattern extraction
    retriever.py     # Combined ranking pipeline
    trainer.py       # Auto-research training loop
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
    feedback.jsonl             # Accumulated feedback signals
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
