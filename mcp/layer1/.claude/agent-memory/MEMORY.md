# Signal Discovery Agent Memory

## Prophet Activation
Prophet is an optional dependency (`[project.optional-dependencies] forecast = ["prophet>=1.1"]`).
`HAS_PROPHET` is captured at module import time. If Prophet is installed AFTER the MCP server
starts, the server will still report `HAS_PROPHET = False` and use linear fallback forecasts.
Fix: restart Claude Code (which restarts the MCP server process).

To verify: `uv run python -c "from signal_discovery.tools.forecast import HAS_PROPHET; print(HAS_PROPHET)"`

## Budget/Personal Finance Data Patterns
- Transaction amounts are NEGATIVE for debits (money out). Positive amounts = credits/refunds.
- "Decreasing trend" in the raw amount = amounts going more negative = more spending.
- Always set `min_segment_size=5` (or lower) for personal transaction data — categories rarely have 50+ rows.
- For personal budgets, segment by `parent_category` (13 values) not `category` (18 values) — parent is better balanced.
- The `date` column in transaction CSVs may not be auto-detected as timestamp by inspect_dataset; the data-loader DOES detect it correctly.

## Small Dataset Behavior (< 20 rows per segment)
- STL decomposition requires enough periods to detect seasonality. With 5-17 rows, most segments will report "Insufficient data for seasonal decomposition."
- Only the largest/most frequent segments will have meaningful deviation detection.
- Correlation engine returns strength=0.0 when working only with discrete anomaly events (not continuous time series). Confidence scores (0.5-0.9) are still meaningful.
- Forecast trustworthy horizon will be 4-13 days for sparse data — communicate this caveat clearly.
