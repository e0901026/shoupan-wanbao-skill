from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import List

import yaml


BASE_REQUIRED_TOKENS = ["TUSHARE_TOKEN"]
FEISHU_REQUIRED_TOKENS = ["FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_RECEIVE_ID"]


def missing_required_tokens(enable_feishu: bool) -> List[str]:
    required = list(BASE_REQUIRED_TOKENS)
    if enable_feishu:
        required.extend(FEISHU_REQUIRED_TOKENS)
    return [name for name in required if not os.getenv(name)]


def write_config(example_path: str | Path, config_path: str | Path, enable_feishu: bool) -> None:
    example = Path(example_path)
    config = Path(config_path)
    payload = yaml.safe_load(example.read_text(encoding="utf-8")) or {}
    feishu = dict(payload.get("feishu") or {})
    feishu["dry_run"] = not enable_feishu
    payload["feishu"] = feishu
    config.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    suffix = "Y/n" if default else "y/N"
    value = input(f"{prompt} [{suffix}] ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes", "是", "需要"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--example", default="config.example.yaml")
    parser.add_argument("--enable-feishu", action="store_true", help="Enable Feishu document/card publishing.")
    parser.add_argument("--no-prompt", action="store_true", help="Do not ask questions; use flags and fail fast on missing tokens.")
    args = parser.parse_args()

    enable_feishu = args.enable_feishu
    if not args.no_prompt and not enable_feishu:
        enable_feishu = ask_yes_no("是否启用 HTML 转飞书文档并发送分享卡片？", default=False)

    config = Path(args.config)
    if not config.exists():
        write_config(args.example, config, enable_feishu=enable_feishu)
        print(f"已生成 {config}")
    else:
        write_config(config, config, enable_feishu=enable_feishu)
        print(f"已更新 {config} 的 feishu.dry_run")

    missing = missing_required_tokens(enable_feishu=enable_feishu)
    if missing:
        print("安装检查未通过，缺少以下环境变量：")
        for name in missing:
            print(f"- {name}")
        print("请通过 shell 环境、系统密钥管理或定时任务环境注入，禁止写入 Git 仓库。")
        raise SystemExit(2)

    print("安装检查通过。")
    print("默认输出 HTML：output/a_share_evening_report_YYYY-MM-DD.html")
    if enable_feishu:
        print("飞书发布已启用：run_daily.py --publish-feishu 会转换 HTML 并发送分享卡片。")
    else:
        print("飞书发布未启用：run_daily.py 默认只生成 HTML。")


if __name__ == "__main__":
    main()
