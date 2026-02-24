# Signal Discovery MCP Server

Autonomous time-series signal discovery for Claude Code. Point it at any dataset with a timestamp and get:

- **Mode 1 — Baseline Discovery**: What does "normal" look like? (trend, seasonality, residual profile)
- **Mode 2 — Deviation Detection**: What's different right now? (anomalies, trend shifts, regime changes)
- **Mode 3 — Forecast & Scenarios**: What should we expect? (confidence-bounded projections)

## Quick Setup

### 1. Install dependencies

```bash
cd signal-discovery-mcp
pip install -e .

# For forecasting (Mode 3):
pip install -e ".[forecast]"

# For everything:
pip install -e ".[all]"
```

### 2. Configure Claude Code

Add to your `~/.claude/claude_desktop_config.json` or project `.mcp.json`:

```json
{
  "mcpServers": {
    "signal-discovery": {
      "command": "python",
      "args": ["-m", "signal_discovery.server"],
      "cwd": "/path/to/signal-discovery-mcp",
      "env": {
        "PYTHONPATH": "./src"
      }
    }
  }
}
```

### 3. Test locally

```bash
PYTHONPATH=./src python -m signal_discovery.server
```

## Usage via Claude Code

Once configured, Claude Code has four new tools:

### `inspect_dataset`
```
"Look at the data in sales_data.csv and tell me what we're working with"
```

### `discover_baseline`
```
"Run a baseline analysis on transactions.csv using the 'order_date' timestamp column"
```

### `detect_deviations`
```
"Check the latest data against our baseline — are there any anomalies?"
```

### `project_forecast`
```
"Project revenue forward 90 days with scenarios"
```

## Architecture

See [ARCHITECTURE.md](./ARCHITECTURE.md) for full technical spec including tool schemas,
analysis engine details (STL, ruptures, stumpy, Prophet), baseline store format,
and Layer 2 correlation design.

## Project Structure

```
signal-discovery-mcp/
├── ARCHITECTURE.md              # Full technical spec
├── README.md                    # This file
├── pyproject.toml               # Python project config
├── claude_code_config.json      # MCP config for Claude Code
└── src/
    └── signal_discovery/
        ├── __init__.py
        ├── server.py            # MCP server (tool registration)
        ├── ingest.py            # Shared data loading & utilities
        └── tools/
            ├── __init__.py
            ├── inspect.py       # inspect_dataset tool
            ├── baseline.py      # discover_baseline (Mode 1)
            ├── deviations.py    # detect_deviations (Mode 2)
            └── forecast.py      # project_forecast (Mode 3)
```
