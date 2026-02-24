# Signal Correlation MCP Server (Layer 2)

Cross-dataset signal correlation engine for Claude Code. Ingests typed signals from multiple Layer 1 instances and discovers relationships that no single dataset can reveal.

Layer 1 answers: "What's happening in this dataset?"
**Layer 2 answers: "What's happening across the business?"**

## What It Does

Given deviation signals from multiple data sources (restaurant POS, experience bookings, web analytics, weather, etc.), Layer 2:

1. **Finds temporal co-occurrences** — signals from different sources happening at the same time
2. **Detects lagged relationships** — signal A reliably precedes signal B by N days (lead indicators)
3. **Identifies spatial alignment** — signals clustering in the same geography across sources
4. **Matches entity-level patterns** — signals affecting the same customers, venues, or products
5. **Compares seasonal shapes** — sources that "move together" structurally
6. **Clusters findings into insights** — grouped, scored, and narrated for action

## Quick Setup

```bash
cd signal-correlation-mcp
pip install -e .

# For full feature set (Granger causality, geo utilities):
pip install -e ".[full]"
```

### Configure Claude Code

Add to your `~/.claude/claude_desktop_config.json` or project `.mcp.json`:

```json
{
  "mcpServers": {
    "signal-correlation": {
      "command": "python",
      "args": ["-m", "signal_correlation.server"],
      "cwd": "/path/to/signal-correlation-mcp",
      "env": {
        "PYTHONPATH": "./src"
      }
    }
  }
}
```

## Usage via Claude Code

### Full workflow: Layer 1 → Layer 2

```
# Step 1: Run Layer 1 on each dataset (using signal-discovery MCP)
"Analyze restaurant_pos.csv — run baseline and detect deviations"
"Analyze jwps_bookings.csv — run baseline and detect deviations"

# Step 2: Register sources with Layer 2
"Register the restaurant POS data as a source — it's POS data covering Edinburgh"
"Register the JWPS bookings as a source — it's booking data at 55.95, -3.21"

# Step 3: Ingest Layer 1 signals
"Ingest the restaurant POS deviations into the correlation engine"
"Ingest the JWPS booking deviations into the correlation engine"

# Step 4: Run correlation
"Correlate all signals — look for temporal and spatial relationships"

# Step 5: Explore findings
"Show me the top insights ranked by actionability"
"Explain the post-tour retail effect insight in detail"
```

### Six MCP Tools

| Tool | Purpose |
|------|---------|
| `register_source` | Declare a data source with semantic context (domain, geography, entity keys) |
| `list_sources` | Show all registered sources and their signal counts |
| `ingest_signals` | Parse Layer 1 output into the canonical signal store |
| `correlate_signals` | Run cross-source correlation analysis → pairwise correlations + insight clusters |
| `query_insights` | Retrieve and filter discovered insights |
| `explain_insight` | Deep-dive: full signal chain, evidence, confidence, alternative explanations |

## Architecture

See [ARCHITECTURE.md](./ARCHITECTURE.md) for full technical specification including:
- All tool input/output schemas
- Five correlation methods with statistical tests
- Signal graph and DBSCAN insight clustering
- DuckDB signal store schema
- Confidence assessment and actionability scoring

## Project Structure

```
signal-correlation-mcp/
├── ARCHITECTURE.md              # Full technical spec
├── README.md                    # This file
├── pyproject.toml               # Python project config
├── claude_code_config.json      # MCP config for Claude Code
└── src/
    └── signal_correlation/
        ├── __init__.py
        ├── server.py            # MCP server (tool registration)
        ├── store.py             # DuckDB signal store (persistence)
        └── tools/
            ├── __init__.py
            ├── sources.py       # register_source, list_sources
            ├── ingest.py        # ingest_signals (Layer 1 → Layer 2 parser)
            ├── correlate.py     # correlate_signals (core engine)
            └── insights.py      # query_insights, explain_insight
```

## How It Relates to Layer 1

```
Layer 1 (signal-discovery-mcp)     Layer 2 (signal-correlation-mcp)
─────────────────────────────      ──────────────────────────────────
Per-dataset analysis:               Cross-dataset analysis:
  inspect_dataset                     register_source
  discover_baseline (Mode 1)   →      ingest_signals (baselines)
  detect_deviations (Mode 2)   →      ingest_signals (deviations)
  project_forecast  (Mode 3)          correlate_signals
                                      query_insights
                                      explain_insight
```

Layer 1 produces typed, timestamped signals from individual datasets.
Layer 2 finds relationships **between** those signals across datasets.
The insight is in the correlation, not in any single signal.
