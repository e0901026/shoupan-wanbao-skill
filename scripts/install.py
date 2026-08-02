from __future__ import annotations

import argparse
import html
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import List

import yaml


BASE_REQUIRED_TOKENS = ["TUSHARE_TOKEN"]
FEISHU_REQUIRED_TOKENS = ["FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_RECEIVE_ID"]
DEFAULT_LAUNCHD_LABEL = "com.wubaiqi.a-share-report-center"
DEFAULT_USER_ENV_FILE = Path.home() / ".config" / "a-share-report-center" / "env"


def missing_required_tokens(enable_feishu: bool) -> List[str]:
    required = list(BASE_REQUIRED_TOKENS)
    if enable_feishu:
        required.extend(FEISHU_REQUIRED_TOKENS)
    return [name for name in required if not os.getenv(name)]


def load_env_file(path: str | Path) -> None:
    env_path = Path(path).expanduser()
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


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


def build_report_center_command(repo_dir: Path, python_path: Path, env_file: Path | None = None) -> str:
    script = repo_dir / "scripts" / "run_report_center.py"
    env_paths = [repo_dir / ".env"]
    if env_file:
        env_paths.append(env_file.expanduser())
    source_parts = [f'[ -f {shlex.quote(str(path))} ] && . {shlex.quote(str(path))}' for path in env_paths]
    source_cmd = "; ".join(source_parts)
    pythonpath = f"{repo_dir / 'scripts'}:{repo_dir / '.deps'}"
    return (
        "set -a; "
        f"{source_cmd}; "
        "set +a; "
        f"export PYTHONPATH={shlex.quote(pythonpath)}${{PYTHONPATH:+:$PYTHONPATH}}; "
        f"exec {shlex.quote(str(python_path))} {shlex.quote(str(script))} "
        f"--config {shlex.quote(str(repo_dir / 'config.yaml'))} "
        f"--root {shlex.quote(str(repo_dir))}"
    )


def build_launchd_plist(
    repo_dir: Path,
    python_path: Path,
    label: str = DEFAULT_LAUNCHD_LABEL,
    env_file: Path | None = DEFAULT_USER_ENV_FILE,
) -> str:
    command = html.escape(build_report_center_command(repo_dir=repo_dir, python_path=python_path, env_file=env_file))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>-lc</string>
    <string>{command}</string>
  </array>
  <key>WorkingDirectory</key><string>{repo_dir}</string>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>16</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Weekday</key><integer>6</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>30</integer></dict>
  </array>
  <key>StandardOutPath</key><string>{repo_dir / "data" / "report_center.launchd.out.log"}</string>
  <key>StandardErrorPath</key><string>{repo_dir / "data" / "report_center.launchd.err.log"}</string>
</dict>
</plist>
"""


def write_launchd_plist(
    repo_dir: Path,
    python_path: Path,
    out_path: Path | None = None,
    env_file: Path | None = DEFAULT_USER_ENV_FILE,
) -> Path:
    out = out_path or (Path.home() / "Library" / "LaunchAgents" / f"{DEFAULT_LAUNCHD_LABEL}.plist")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_launchd_plist(repo_dir=repo_dir, python_path=python_path, env_file=env_file), encoding="utf-8")
    return out


def install_launchd_plist(plist_path: Path, label: str = DEFAULT_LAUNCHD_LABEL) -> None:
    domain = f"gui/{os.getuid()}"
    service = f"{domain}/{label}"
    subprocess.run(["launchctl", "bootout", domain, str(plist_path)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["launchctl", "bootstrap", domain, str(plist_path)], check=True)
    subprocess.run(["launchctl", "enable", service], check=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--example", default="config.example.yaml")
    parser.add_argument("--enable-feishu", action="store_true", help="Enable Feishu document/card publishing.")
    parser.add_argument("--install-schedule", action="store_true", help="Install and load a launchd plist for the report center.")
    parser.add_argument("--schedule-dry-run", action="store_true", help="Print launchd plist instead of writing it.")
    parser.add_argument("--env-file", default=str(DEFAULT_USER_ENV_FILE), help="User-level env file sourced by launchd, in addition to repo .env.")
    parser.add_argument("--no-prompt", action="store_true", help="Do not ask questions; use flags and fail fast on missing tokens.")
    args = parser.parse_args()

    env_file = Path(args.env_file).expanduser()
    load_env_file(Path.cwd() / ".env")
    load_env_file(env_file)

    if args.schedule_dry_run and not args.install_schedule:
        print(build_launchd_plist(repo_dir=Path.cwd(), python_path=Path(sys.executable), env_file=env_file))
        return

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
    if args.install_schedule or args.schedule_dry_run:
        repo_dir = Path.cwd()
        python_path = Path(sys.executable)
        plist = build_launchd_plist(repo_dir=repo_dir, python_path=python_path)
        if args.schedule_dry_run:
            print(plist)
        else:
            out = write_launchd_plist(repo_dir=repo_dir, python_path=python_path, env_file=env_file)
            install_launchd_plist(out)
            print(f"已安装并加载 launchd 定时任务：{out}")
            print("后续由 macOS launchd 自动触发；缺失报告会在下一次触发时补跑。")


if __name__ == "__main__":
    main()
