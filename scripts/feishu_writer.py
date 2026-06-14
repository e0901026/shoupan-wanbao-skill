from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv

from common import env_value, load_yaml, read_json


class FeishuClient:
    """飞书写入脚本骨架。

    推荐生产方案：
    - 如果 Hermes 已经连接飞书，优先让 Hermes 调用原生飞书动作创建文档、写正文、发卡片。
    - 如果需要在脚本内直连飞书，使用自建应用，并开启相应文档和消息权限。

    注意：飞书 OpenAPI 版本可能变化。上线前请按当前官方文档核对 endpoint、scope 和 body 结构。
    """

    def __init__(self, app_id: str, app_secret: str) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.base = "https://open.feishu.cn/open-apis"
        self._token: Optional[str] = None

    def tenant_access_token(self) -> str:
        if self._token:
            return self._token
        url = f"{self.base}/auth/v3/tenant_access_token/internal"
        resp = requests.post(url, json={"app_id": self.app_id, "app_secret": self.app_secret}, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") not in (0, None):
            raise RuntimeError(f"Feishu token error: {data}")
        token = data.get("tenant_access_token")
        if not token:
            raise RuntimeError(f"Feishu token missing: {data}")
        self._token = token
        return token

    def headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.tenant_access_token()}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def create_docx(self, title: str, folder_token: Optional[str] = None) -> Dict[str, Any]:
        url = f"{self.base}/docx/v1/documents"
        body: Dict[str, Any] = {"title": title}
        if folder_token:
            body["folder_token"] = folder_token
        resp = requests.post(url, headers=self.headers(), json=body, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def send_interactive_card(self, receive_id_type: str, receive_id: str, card: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base}/im/v1/messages"
        params = {"receive_id_type": receive_id_type}
        body = {
            "receive_id": receive_id,
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
        }
        resp = requests.post(url, headers=self.headers(), params=params, json=body, timeout=20)
        resp.raise_for_status()
        return resp.json()


def build_card(title: str, summary: str, doc_url: str) -> Dict[str, Any]:
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": title}},
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": summary}},
            {"tag": "action", "actions": [{"tag": "button", "text": {"tag": "plain_text", "content": "查看完整飞书文档"}, "url": doc_url, "type": "primary"}]},
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--analysis", required=True)
    args = parser.parse_args()

    load_dotenv()
    config = load_yaml(args.config)
    report_md = Path(args.report).read_text(encoding="utf-8")
    analysis = read_json(args.analysis, default={}) or {}

    title_line = next((line.strip("# ") for line in report_md.splitlines() if line.startswith("# ")), "📊 股市收盘晚报")
    summary = "\n".join(
        [
            "**日报已生成**",
            "请查看飞书文档完整内容。",
            f"抓取时间：{analysis.get('generated_at', '暂缺')}",
        ]
    )

    feishu_cfg = config.get("feishu", {})
    dry_run = bool(feishu_cfg.get("dry_run", True))
    if dry_run:
        out = Path(args.report).with_suffix(".feishu_dry_run.json")
        out.write_text(
            json.dumps({"title": title_line, "summary": summary, "report_preview": report_md[:2000]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"dry_run=true，已写入：{out}")
        return

    app_id = env_value(feishu_cfg.get("app_id_env"))
    app_secret = env_value(feishu_cfg.get("app_secret_env"))
    receive_id = env_value(feishu_cfg.get("receive_id_env"))
    folder_token = env_value(feishu_cfg.get("folder_token_env"))
    receive_id_type = feishu_cfg.get("receive_id_type", "chat_id")
    if not app_id or not app_secret or not receive_id:
        raise RuntimeError("缺少 FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_RECEIVE_ID 环境变量")

    client = FeishuClient(app_id, app_secret)
    doc = client.create_docx(title=title_line, folder_token=folder_token)

    # 注意：这里只创建文档和发卡片。真正把 Markdown 写成飞书块，需要按当前 docx block API 拆块写入。
    # 如果 Hermes 已经连接飞书，推荐让 Hermes 原生飞书工具完成“写正文”。
    doc_token = (doc.get("data") or {}).get("document", {}).get("document_id") or (doc.get("data") or {}).get("document_id")
    doc_url = f"https://feishu.cn/docx/{doc_token}" if doc_token else ""
    card = build_card(title_line, summary, doc_url)
    result = client.send_interactive_card(receive_id_type, receive_id, card)
    print(json.dumps({"doc": doc, "message": result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
