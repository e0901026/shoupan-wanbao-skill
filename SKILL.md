---
name: shoupan-wanbao
description: Use when an agent needs to generate an A-share closing/evening report HTML from public market data, sector fund-flow data, company news, institutional views, retail sentiment, macro/risk events, and source-quality evidence; also use when setting up a reusable scheduled stock watch report currently focused on 贵州茅台 with support for more tracked stocks later.
---

# 收盘晚报

This skill generates a daily A-share closing report. The default tracked stock is 贵州茅台 `600519.SH`; future tracked stocks should be added through `config.yaml`, not hard-coded into scripts.

The final daily artifact is HTML:

```bash
output/a_share_evening_report_YYYY-MM-DD.html
```

`output/report.md` is an intermediate artifact for Feishu, email, or another agent.

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

Default output is HTML only. Use `--publish-feishu` to run the optional HTML-to-Feishu-doc publisher. Use `--allow-degraded-fund-flow` only for internal drafts.

## News Window

Use `scripts/run_daily.py` as the canonical entrypoint:

- First successful run: pull 30 calendar days of relevant news.
- Normal subsequent trading-day run: pull only the report date.
- After market closures: pull from the last successful report date through the current report date, so weekends/holidays are included.

State is stored in `data/run_state.json` by default.

## Report Contract

The report must include:

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

## Fund-Flow Rules

All fund-flow tables must contain:

```text
板块 | 净流入（亿） | 超大单（亿） | 大单（亿） | 小单（亿） | 涨跌幅 % | 成交额（亿） | 净流入率 %
```

Use SW level-2 industry sectors for sector ranking and divergence analysis. Do not mix concept boards, SW level-1, SW level-3, or index boards into industry tables.

Preferred complete sources:

- Eastmoney SW2 full field endpoint.
- Tushare fallback aggregation: `moneyflow + daily + index_member_all`, summed by SW2 membership.

For Tushare moneyflow, bucket definitions are: 小单 `<5万元`, 中单 `5-20万元`, 大单 `20-100万元`, 特大单/超大单 `>=100万元`, based on active buy/sell order statistics. SW2 industry values are sums of constituent-stock bucket net amounts; do not re-bucket by board turnover or one-lot value.

For high-priced stocks such as 贵州茅台 where one board lot already exceeds the 小单 threshold, keep the upstream 小单 field for accounting completeness but do not interpret it as ordinary low-price-stock retail buying. Treat it as the vendor's active-trade bucket based on transaction details, split matching, or odd-lot/fragmented prints; use net flow, 超大单, 大单, turnover, margin financing, and block trades as the primary signal.

AkShare/同花顺 may be used as coverage supplements or degraded drafts. If mandatory fields are missing, strict validation must fail.

## Data Separation

Keep these categories separate: official announcements, market/news articles, institution views/research, structured market data, retail posts/comments, and macro/risk events.

If a source requires login, CAPTCHA, subscription, or user authorization, record it as blocked or ask the user to log in. Do not bypass access controls.

## Validation

Before presenting a report as final, run:

```bash
python -m unittest discover -s tests
python scripts/validate_report.py --report output/report.md --analysis data/analysis.json --strict-fund-flow
```

## Extending Tracked Stocks

Use `config.yaml`:

- `primary_stock`: current main target, default 贵州茅台.
- `peer_stocks`: comparison stocks.
- `tracked_stocks`: future watchlist expansion.

When scripts are extended for multiple primary targets, preserve one report per primary target or make the target explicit in output filenames.
