---
name: shoupan-wanbao
description: Use when an agent needs to generate one A-share daily closing/evening report HTML for a single trading day from public market data, sector fund-flow data, company news, institutional views, retail sentiment, macro/risk events, and source-quality evidence; currently focused on 贵州茅台 with support for more tracked stocks later.
---

# 收盘晚报（日报）

This skill generates one daily A-share closing report. It does not generate weekly reports. The default tracked stock is 贵州茅台 `600519.SH`; future tracked stocks should be added through `config.yaml`, not hard-coded into scripts.

The final daily artifact is HTML:

```bash
output/a_share_evening_report_YYYY-MM-DD.html
```

Every generated HTML page should include a `导出PDF` link to the sibling PDF filename. PDF is optional and generated on demand with full-page screenshot fidelity:

```bash
python scripts/export_pdf.py --html output/a_share_evening_report_YYYY-MM-DD.html
```

The default PDF mode captures the rendered browser page as one long screenshot and wraps it into a single-page PDF. Use `--mode print` only as a degraded fallback.

`output/report.md` is an intermediate artifact for Feishu, email, or another agent.
Successful daily runs archive `data/archive/analysis_YYYY-MM-DD.json`; the separate `shoupan-zhoubao` skill consumes those archives.

## Related Skills

- `shoupan-zhoubao`: weekly aggregation and weekly-review rules. Use it after the daily reports exist.
- `pa-pa-le`: shared crawling layer for data gaps, logged-in/dynamic pages, comments, and source-status evidence.

Do not force weekly-report sections or weekly return logic into the daily report.

## Required Crawling Layer

Use `$pa-pa-le` whenever built-in scripts fail, a source returns too little data, comments/social posts are needed, or a logged-in/dynamic page is required. If `$pa-pa-le` is unavailable, read `references/pa-pa-le.md` and follow the same source-status and evidence rules.

## Install

Run:

```bash
python -m pip install -r requirements.txt
python scripts/install.py
```

The installer checks `TUSHARE_TOKEN`. If Feishu publishing is enabled, it also checks `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, and `FEISHU_RECEIVE_ID`. Never commit secrets.

## Run

Historical date:

```bash
python scripts/run_daily.py --config config.yaml --date 2026-06-12
```

Scheduled daily run:

```bash
python scripts/run_daily.py --config config.yaml
```

Default output is HTML only. Use `--publish-feishu` to run the optional Feishu publisher. The publisher defaults to `html_import`, which uploads the final HTML and imports it through Feishu's official file import flow for best visual fidelity. `docx_blocks` is only a downgrade path for editable native blocks and cannot preserve arbitrary HTML/CSS 1:1. Use `--allow-degraded-fund-flow` only for internal drafts.

For Feishu publishing diagnostics, first run `scripts/publish_feishu_html.py --doc-only` to verify document import before sending a share card. Keep `scripts/publish_feishu_html.py` as the single Feishu publishing entrypoint. `FEISHU_RECEIVE_ID` must be a real Feishu receive ID matching `receive_id_type`; do not use labels such as "current channel".

## News Window

Use `scripts/run_daily.py` as the canonical entrypoint:

- First successful run: pull 30 calendar days of relevant news.
- Normal subsequent trading-day run: pull only the report date.
- After market closures: pull from the last successful report date through the current report date, so weekends/holidays are included.
- Historical backfills must reject search results without a verifiable publication time; never insert current search-page results into a past report.

State is stored in `data/run_state.json` by default.

## Daily Report Contract

These rules apply to `output/a_share_evening_report_YYYY-MM-DD.html` and `scripts/run_daily.py`.

The daily report must include:

- primary stock quote and configured peer-stock comparison
- main target news, industry news, and macro/risk timelines
- retail/public opinion sentiment separated from institution views
- institution views only when rating and target price are both available
- SW level-2 industry fund flow
- TOP 10 inflow/outflow and four TOP 5 divergence tables
- 白酒板块 plus configured primary stock as a stock-as-sector row
- fact-grounded comprehensive judgment
- data sources, quality, errors, and risk disclaimer

Brokerage reports, target prices, and ratings must appear only under `机构观点`; do not place them in main target news.

Do not force weekly-report sections into the daily report. Daily output should explain one trading day with same-day market data, news, sentiment, and source quality.

## Daily Strategy Calibration

Daily reports must consume recent `data/archive/analysis_YYYY-MM-DD.json` history when available and apply the weekly-review calibration rules:

- Put dividends, buybacks, and announcement-style positives into a "whether price and fund flow confirmed it" frame. They are not standalone reasons for a bullish conclusion.
- If two or more consecutive trading days show `超大单 > 0`, `大单 < 0`, and weak price action, label it as 承接型分歧, not as a trend reversal unless price, turnover, and 白酒Ⅱ fund flow confirm afterward.
- Sector fund flow must discuss continuity and net-inflow rate. Same-day TOP10 rankings are clues only and cannot replace the multi-day main-line judgment.

## Data Integrity Gates

- Formal industry fund-flow analysis must use a fixed Shenwan Level-2 constituent universe. Eastmoney and Tonghuashun industry boards may be used for cross-checking, but must not be labeled as Shenwan Level-2 or mixed into the formal TOP10 and divergence tables.
- Fetch the SW2021 Level-2 classification list first, then query `index_member_all` separately for every L2 code. A single unfiltered response can be capped and must never be treated as the complete constituent universe. Merge current and historical rows, apply `in_date/out_date` for the report date, and fail on unresolved multiple active memberships.
- Tushare `moneyflow` currently covers the traded Shanghai/Shenzhen constituents used by this skill but not the Beijing Stock Exchange constituents. Record the excluded BJ count and turnover coverage for every formal report. Do not describe the aggregation as full-market SW2 coverage.
- Quotes must retain the previous close and verify `pct_change = (close - previous_close) / previous_close`. On ex-dividend dates, use the quote source's adjusted reference previous close.
- The primary stock quote must match an independent historical quote source. A mismatch or unavailable second source blocks formal publication after retries.
- Main net inflow must equal super-large-order net plus large-order net, and net-inflow rate must equal main net inflow divided by turnover.
- Daily-review conclusions must be generated from the day's price, Baijiu II fund flow, and Kweichow Moutai order-size fund flow. Fixed causal statements that conflict with the data are forbidden.

## Fund-Flow Rules

All fund-flow tables must contain:

```text
板块 | 净流入（亿） | 超大单（亿） | 大单（亿） | 小单（亿） | 涨跌幅 % | 成交额（亿） | 净流入率 %
```

Use SW level-2 industry sectors for sector ranking and divergence analysis. Do not mix concept boards, SW level-1, SW level-3, or index boards into industry tables.

Preferred formal source:

- Tushare aggregation: `moneyflow + daily + index_classify + index_member_all`, with every SW2 code queried separately and membership periods reconciled for the target date.

Eastmoney and Tonghuashun industry-board data are noncanonical supplements only unless their exact SW2 constituent mapping and target date can be verified.

For Tushare moneyflow, bucket definitions are: 小单 `<5万元`, 中单 `5-20万元`, 大单 `20-100万元`, 特大单/超大单 `>=100万元`, based on active buy/sell order statistics. SW2 industry values are sums of constituent-stock bucket net amounts; do not re-bucket by board turnover or one-lot value.

For high-priced stocks such as 贵州茅台 where one board lot already exceeds the 小单 threshold, keep the upstream 小单 field for accounting completeness but do not interpret it as retail buying. The public endpoint does not provide enough raw trade-classification detail to verify why this bucket is nonzero, so do not speculate about its mechanism. Use net flow, 超大单, 大单, turnover, margin financing, and block trades as the primary signal.

AkShare/同花顺 may be used as coverage supplements or degraded drafts. If mandatory fields are missing, strict validation must fail.

## Data Separation

Keep these categories separate: official announcements, market/news articles, institution views/research, structured market data, retail posts/comments, and macro/risk events.

If a source requires login, CAPTCHA, subscription, or user authorization, record it as blocked or ask the user to log in. Do not bypass access controls.

For Xueqiu retail sentiment, static requests may hit Aliyun WAF or return empty anonymous API results. Try `opencli xueqiu comments SYMBOL --site-session persistent` first. If OpenCli Browser Bridge is unavailable, fall back to logged-in Chrome/CDP via `XUEQIU_CDP_URL` or `CHROME_REMOTE_DEBUGGING_URL`. Use Agent Reach only after OpenCli and CDP fail or are unavailable. Do not export cookies; only store normalized public post evidence.

## Validation

Before presenting a report as final, run:

```bash
python -m unittest discover -s tests
python scripts/validate_report.py --report output/report.md --analysis data/analysis.json --strict-fund-flow
python scripts/audit_report_history.py --dates YYYY-MM-DD YYYY-MM-DD
```

## Extending Tracked Stocks

Use `config.yaml`:

- `primary_stock`: current main target, default 贵州茅台.
- `peer_stocks`: comparison stocks.
- `tracked_stocks`: future watchlist expansion.

When scripts are extended for multiple primary targets, preserve one report per primary target or make the target explicit in output filenames.
