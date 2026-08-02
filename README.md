# 收盘晚报 Skill

通用 agent skill，用公开数据生成 A 股每日收盘晚报。当前默认跟踪贵州茅台 `600519.SH`，后续可在 `config.yaml` 的 `tracked_stocks` / `primary_stock` 中扩展更多关注股票。

每日最终输出是 HTML：

```bash
output/a_share_evening_report_YYYY-MM-DD.html
```

`output/report.md` 和 `data/analysis.json` 是中间产物，供调试、飞书发布或其它 agent 复用。
成功生成日报后会归档 `data/archive/analysis_YYYY-MM-DD.json`，供周报分析复用。

## 安装

```bash
python -m pip install -r requirements.txt
cp .env.example .env
```

设置核心数据源 token：

```bash
export TUSHARE_TOKEN="你的 tushare token"
```

运行安装向导：

```bash
python scripts/install.py
```

安装向导会检查：

- `TUSHARE_TOKEN`：核心数据源，缺失时会要求用户提供。
- 飞书凭证：只有选择启用飞书发布时才检查 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_RECEIVE_ID`。

不要把真实 token 写入 Git 仓库。

## 运行

历史日期：

```bash
python scripts/run_daily.py --config config.yaml --date 2026-06-12
```

每日定时：

```bash
python scripts/run_daily.py --config config.yaml
```

默认严格校验板块资金流，生成 HTML 后结束。内部草稿才使用：

```bash
python scripts/run_daily.py --config config.yaml --allow-degraded-fund-flow
```

## 报告中心与定时任务

报告中心只做调度和导航，不改变收盘晚报与周报 HTML 交付件的正文形式。

统一入口：

```bash
python scripts/run_report_center.py --config config.yaml
```

默认行为：

- 交易日 16:00 后：补跑缺失交易日并生成当日收盘晚报。
- 周六 09:00 后：读取本周日报归档，生成周报。
- 周一 08:30 后：生成开盘早报，整理上次收盘后到周一盘前的休市资讯。
- 每次运行后刷新 `output/index.html`，导航到开盘早报、收盘晚报和周报 HTML。
- 日报和早报生成后由报告中心立即执行专用审计；审计失败时停止后续聚合和状态更新。

推荐在 Codex App 中建立三个本机自动任务：交易日 16:00、周六 09:00、周一 08:30，三者都调用 `scripts/run_report_center.py`。报告中心会用交易日历判定实际任务并补跑缺失报告。

不使用 Codex App 时，安装向导也可安装 macOS `launchd` 定时任务；两种调度方式只能启用一种，避免并发写入：

```bash
python scripts/install.py --no-prompt --schedule-dry-run
python scripts/install.py --no-prompt --install-schedule
```

`--schedule-dry-run` 只打印 plist；`--install-schedule` 会写入 `~/Library/LaunchAgents/com.wubaiqi.a-share-report-center.plist` 并执行 `launchctl bootstrap`。定时任务会依次读取仓库 `.env` 和 `~/.config/a-share-report-center/env`，token 不要写入 Git 仓库。

手动生成周报：

```bash
python scripts/run_weekly.py --root . --dates 2026-06-22 2026-06-23 2026-06-24 2026-06-25 2026-06-26
```

手动生成导航页：

```bash
python scripts/render_index.py --output-dir output
```

构建可发布的 GitHub Pages 静态站点（包含长截图 PDF）：

```bash
python scripts/build_site.py --output-dir output --site-dir site --generate-pdfs
```

站点快照写入 `site/`，发布脚本会将该目录同步到 `gh-pages` 分支，由 GitHub Pages 直接托管，不依赖 GitHub Actions。`output/` 仍保持本机运行目录并继续忽略，不提交 token、抓取缓存或原始数据。

无人值守任务可在报告中心成功后执行：

```bash
python scripts/publish_site.py --repo . --push
```

该命令只暂存并提交 `site/`，随后推送当前分支和 `gh-pages` 站点分支；检测到其它已暂存文件时会拒绝自动提交，防止把无关改动或凭证带入站点更新。

按需导出 PDF：

```bash
python scripts/export_pdf.py --html output/a_share_evening_report_YYYY-MM-DD.html
```

## 登录态舆论源

东方财富股吧、今日头条走公开静态抓取。雪球优先走 OpenCli：

```bash
opencli xueqiu comments SH600519 --limit 20 --site-session persistent --window background -f json
```

如果 OpenCli 报 `Browser Bridge extension not connected`，需要安装/启用 OpenCli Browser Bridge extension。OpenCli 不通时，再使用本机登录态 Chrome/CDP：

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.codex-browser-profile/pa-pa-le"
```

在该 Chrome 中登录雪球并确认能看到 `贵州茅台` / `SH600519` 讨论后，运行：

```bash
XUEQIU_CDP_URL=http://127.0.0.1:9222 python scripts/fetch_sentiment.py --config config.yaml --date YYYY-MM-DD --out data/sentiment.json
```

脚本按 `OpenCli -> CDP -> Agent Reach` 的优先级尝试雪球；当前环境未发现 Agent Reach CLI/connector 时会在 source status 中明确标注。脚本只保存公开帖子摘要、作者、时间、链接和互动数，不导出 cookie 或 token。

## 新闻窗口

`scripts/run_daily.py` 会维护 `data/run_state.json`：

- 第一次成功运行：拉取近 30 天相关新闻。
- 后续正常交易日：只拉取当天新闻。
- 如果股票市场休息导致跨天，例如周五后周一运行：拉取休市期间和当天新闻。
- 历史回填不使用无法核验发布时间的搜索页结果，避免把当前新闻倒填到过去日期。

可以用 `--state-file` 指定独立状态文件。

## 可选飞书发布

第一次安装时选择启用飞书发布，或手动设置 `feishu.dry_run: false` 并提供飞书环境变量。

发布命令：

```bash
python scripts/run_daily.py --config config.yaml --publish-feishu
```

流程：

1. 生成 `output/a_share_evening_report_YYYY-MM-DD.html`
2. `scripts/publish_feishu_html.py` 默认使用 `html_import`：先上传 HTML，再通过飞书官方导入任务导入为新版文档
3. 发送飞书文档分享卡片

默认 `feishu.dry_run: true` 时不会调用真实飞书 API，只会生成 `.feishu_dry_run.json` 预览。

`html_import` 是追求“尽量 1:1 还原 HTML 样式和数据”的主路径。`docx_blocks` 仅作为降级模式，优点是正文更像飞书原生可编辑块，缺点是飞书 block API 不支持任意 HTML/CSS，不能保证视觉 1:1。

如果只想先验证 HTML 能否转换为飞书文档，不发送分享卡片：

```bash
python scripts/publish_feishu_html.py --config config.yaml --html output/a_share_evening_report_YYYY-MM-DD.html --analysis data/analysis.json --doc-only
```

`FEISHU_RECEIVE_ID` 必须是真实的飞书接收 ID，不能写“当前频道”。`receive_id_type` 要与 ID 类型匹配，例如 `chat_id` 通常对应 `oc_...`。脚本会拒绝 `xxx`、`...`、截断 secret 等占位值；飞书返回 400 时会输出响应 body 便于定位。

## 爬爬乐

本 skill 依赖爬爬乐作为通用抓取层。运行环境已安装 `$pa-pa-le` 时优先使用它；没有安装时可参考 `references/pa-pa-le.md`。

所有抓取必须记录来源、URL、发布时间、抓取时间、状态和失败原因。公告、新闻、机构观点、散户评论、宏观事件不能混在一起。

## 数据源策略

- 行情：优先 Tushare `daily + daily_basic`，失败时回退公开行情源。
- 板块资金：使用 Tushare `moneyflow + daily`，按 `index_classify` 返回的每一个申万二级代码分别查询 `index_member_all`，结合入选/剔除日期聚合。禁止把一次性上限返回当作完整成分集。
- 覆盖边界：正式资金表为申万二级沪深成分口径；Tushare `moneyflow` 未覆盖的北交所成分必须披露排除数量和成交额缺口。
- 高价股小单：贵州茅台一手成交金额已超过 Tushare 小单阈值，小单字段只保留为上游字段；公开接口不足以复核其逐笔归类机制，不把它解释为散户，也不猜测形成原因。
- 同花顺/AkShare：作为覆盖补充或降级草稿，不参与严格正式发布。
- 机构观点：只保留同时具备评级和目标价的观点。
- 新闻：主标、行业、宏观风险三类时间线；券商研报和目标价只放机构观点。

## 验证

```bash
python -m unittest discover -s tests
python scripts/validate_report.py --report output/report.md --analysis data/analysis.json --strict-fund-flow
python scripts/audit_report_history.py --dates YYYY-MM-DD YYYY-MM-DD
python scripts/audit_morning_history.py --window YYYY-MM-DD "PREVIOUS_CLOSE_DATE 15:00" "YYYY-MM-DD 08:30"
```

## 发布到 GitHub

应提交：

- `SKILL.md`
- `README.md`
- `config.example.yaml`
- `requirements.txt`
- `scripts/`
- `templates/`
- `tests/`
- `references/`
- `agents/`

不要提交：

- `.env`
- `.venv/`
- `.deps/`
- `data/`
- `output/`
- 任何真实 token 或账户凭证
