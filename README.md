# 收盘晚报 Skill

通用 agent skill，用公开数据生成 A 股每日收盘晚报。当前默认跟踪贵州茅台 `600519.SH`，后续可在 `config.yaml` 的 `tracked_stocks` / `primary_stock` 中扩展更多关注股票。

每日最终输出是 HTML：

```bash
output/a_share_evening_report_YYYY-MM-DD.html
```

`output/report.md` 和 `data/analysis.json` 是中间产物，供调试、飞书发布或其它 agent 复用。

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

## 新闻窗口

`scripts/run_daily.py` 会维护 `data/run_state.json`：

- 第一次成功运行：拉取近 30 天相关新闻。
- 后续正常交易日：只拉取当天新闻。
- 如果股票市场休息导致跨天，例如周五后周一运行：拉取休市期间和当天新闻。

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
- 板块资金：优先申万二级行业完整字段源；东方财富不可用时使用 Tushare `moneyflow + daily + index_member_all` 聚合。
- 高价股小单：贵州茅台一手成交金额已超过 Tushare 小单阈值，小单字段只保留为上游成交分档结果，不能按普通低价股的散户小买单解释。
- 同花顺/AkShare：作为覆盖补充或降级草稿，不参与严格正式发布。
- 机构观点：只保留同时具备评级和目标价的观点。
- 新闻：主标、行业、宏观风险三类时间线；券商研报和目标价只放机构观点。

## 验证

```bash
python -m unittest discover -s tests
python scripts/validate_report.py --report output/report.md --analysis data/analysis.json --strict-fund-flow
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
