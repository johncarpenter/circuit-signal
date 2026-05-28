# Report Agent Memory

## Workspace Structure
- Segment CSVs: `reports/{run_id}/segments/*.csv` -- columns: `date, transaction_count, total_revenue_usd, avg_transaction_usd`
- Result JSONs: `reports/{run_id}/results/*.json` -- contains `segment_label`, `baseline` (with `baselines[]` array), `deviations` (with `summary`)
- Baselines: `reports/{run_id}/baselines/{segment}/` -- contains `manifest.json`, `columns/`, `decompositions/`
- Charts: `reports/{run_id}/charts/` -- generated PNGs
- Data notes: `output/Data-notes.md` -- unit conversion rules (cents->dollars, UTC->PDT)

## Data Notes for This Project
- **Raw tables are in cents** -- segment CSVs are already converted to dollars (verified: beer avg ~$6.44, JW avg ~$19.75)
- Currency: USD, Timezone: PDT
- Domain: US mid-market casual dining chain, POS transaction records

## Chart Generation Patterns
- Use `matplotlib.use('Agg')` for headless rendering
- Color scheme: Beer = `#D4A017` (amber/gold), JW = `#1B4332` (dark green), Football = `#C41E3A` (red)
- Zero-filled vs trading-day-only averages differ significantly for JW (261 zero-sales days inflate denominator)
- Always note in chart captions whether zero-fill or trading-days-only is used
- `plt.tight_layout()` + `bbox_inches='tight'` on save prevents clipping
- 160 DPI is good balance of quality and file size

## Analytical Notes
- DOW/seasonality tables should use trading-days-only (segment CSV rows) for accuracy
- Charts may use zero-filled date ranges for visual continuity -- note the difference in captions
- JW baseline model explains only 62.4% variance vs 77.4% for beer -- JW data is highly erratic
- JW residuals have extreme skewness (2.55) and kurtosis (24.56) due to bottle service spikes

## Report Structure (see `patterns.md` for full template)
- Link: [patterns.md](./patterns.md)
