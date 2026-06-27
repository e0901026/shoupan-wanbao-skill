---
name: shoupan-zhoubao
description: Use when an agent needs to generate or improve one A-share weekly report HTML from completed daily closing reports, especially when aggregating 贵州茅台 weekly performance, sector fund-flow changes, divergence signals, news timelines, institutional evidence, dividend-adjusted returns, and weekly review corrections.
---

# 收盘周报

This skill generates one weekly report from completed daily closing reports. It is separate from `shoupan-wanbao`; do not apply weekly aggregation rules to daily reports.

## Dependencies

- `shoupan-wanbao`: must generate daily HTML and preferably `data/archive/analysis_YYYY-MM-DD.json`.
- `pa-pa-le`: use when weekly institutional evidence, ETF data, comments, dynamic pages, or source-status checks need crawling beyond built-in scripts.

Daily reports provide facts. The weekly report reviews, aggregates, corrects, and interprets the week.

## Inputs And Output

Run from the repo root:

```bash
python scripts/run_weekly.py --root . --dates YYYY-MM-DD YYYY-MM-DD ... --output-dir output
python scripts/render_index.py --output-dir output
```

Output:

```bash
output/a_share_weekly_report_START_END.html
```

Every weekly HTML page should include a `导出PDF` link to the sibling PDF filename. PDF is generated on demand and must preserve the rendered webpage as a long screenshot-style single-page PDF:

```bash
python scripts/export_pdf.py --html output/a_share_weekly_report_START_END.html
```

Use `--mode print` only as a degraded fallback when full-page screenshot capture is unavailable.

Optional institutional evidence package:

```bash
python scripts/fetch_institutional_evidence.py --stock-code 600519 --start-date START --end-date END --out data/institutional_evidence_START_END.json
```

## Title And Scope

Weekly report HTML must keep the existing weekly report style and use a dated title in both `<title>` and `<h1>`:

```text
YYYY年MM月DD日-MM月DD日贵州茅台周报
```

The index page is only a navigation hub. Do not inline, reformat, or replace the weekly HTML.

## Return Rules

Separate three concepts:

- **含分红总回报**: primary decision metric. Use the previous trading day's baseline price, final close, and official cash dividends whose ex-dividend date falls inside the week.
- **行情日涨跌累计**: secondary reference. Compound the market data provider's daily percentage changes; label it as the provider quote-return view.
- **首尾收盘价裸变化**: explanation only. It is affected by ex-dividend price adjustment and must never be described as actual profit/loss.

Dividend facts must come from official announcements when available. For SSE implementation-announcement tables, parse `股权登记日`, `除权（息）日`, `现金红利发放日`, and `每股现金红利`; do not infer these from media headlines. If official dates are missing, say so and do not compute cash total return from guessed dates.

## Fund-Flow Rules

Weekly sector fund-flow tables must first net the same sector across all daily visible inflow/outflow records, then split into weekly net-inflow and net-outflow groups. A sector must not appear in both weekly TOP tables. Add a note that days where the sector did not enter the daily TOP list are not included in the weekly visible-sample table.

Always append a fixed comparison table in the fund-flow section for `白酒Ⅱ`, the primary stock as a stock-as-sector row such as `贵州茅台`, and `非白酒` when available. This table is not TOP-filtered and must include net inflow, 超大单, 大单, 小单, 涨跌幅, 成交额, and 净流入率.

Four divergence tables are weekly reviews of daily signals. They should identify repeated/large signals and correct overconfident daily interpretations.

## Institutional Evidence Rules

Separate evidence strength:

- same-week structured data such as block trades, margin financing, LHB records, and ETF share changes may participate in the week's interpretation.
- ETF share declines are redemption/allocation clues only; do not state they prove the ETF already sold the primary stock unless holdings and trade evidence support that.
- fund holdings are usually quarterly-lagged exposure evidence; they identify who holds the stock, not who sold this week.
- stale northbound/foreign-holding data must be recorded as a source gap and excluded from same-week buy/sell conclusions.

## Weekly Review Rules

The weekly report is not a pasted stack of daily reports. It should:

- summarize the week's most important daily-review conclusions and correct any conclusion later disproved by price, total return, fund-flow, or news evidence.
- dedupe news into reverse-chronological event development, not repeated article lists.
- remove low-value sentiment timelines unless they add a clear investor-relevant signal.
- make follow-up strategy improvements explicit for future daily reports.

## Validation

Before presenting the weekly report as final:

```bash
python -m unittest tests.test_report_center
python scripts/run_weekly.py --root . --dates START ... END --output-dir output
```
