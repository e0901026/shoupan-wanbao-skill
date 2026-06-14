from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from common import env_value, load_yaml, read_json


FEISHU_APP_ENV = ["FEISHU_APP_ID", "FEISHU_APP_SECRET"]
FEISHU_SEND_ENV = ["FEISHU_RECEIVE_ID"]


def clean_text(value: str) -> str:
    return " ".join((value or "").split())


def mask_value(value: str | None) -> str:
    if not value:
        return "<empty>"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-2:]}"


def looks_like_placeholder(value: str | None) -> bool:
    text = (value or "").strip()
    lowered = text.lower()
    if not text:
        return True
    if lowered in {"xxx", "x", "your_tushare_token", "your_token", "none", "null"}:
        return True
    if "..." in text or "…" in text:
        return True
    if lowered.endswith("_xxx") or lowered in {"cli_xxx", "oc_xxx"}:
        return True
    return False


def validate_env_value(name: str, value: str | None) -> str:
    if looks_like_placeholder(value):
        raise RuntimeError(
            f"{name} 缺失、仍是占位符或疑似截断值（当前值预览：{mask_value(value)}）。"
            "请通过环境变量或 .env 提供完整真实值，不能写入 Git 仓库。"
        )
    return str(value).strip()


def required_env_names(doc_only: bool = False) -> List[str]:
    names = list(FEISHU_APP_ENV)
    if not doc_only:
        names.extend(FEISHU_SEND_ENV)
    return names


def ensure_feishu_ok(resp: requests.Response, action: str) -> Dict[str, Any]:
    body = resp.text[:2000]
    if resp.status_code >= 400:
        raise RuntimeError(f"Feishu API {action} HTTP {resp.status_code}: {body}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise RuntimeError(f"Feishu API {action} returned non-JSON body: {body}") from exc
    code = data.get("code")
    if code not in (0, None):
        raise RuntimeError(f"Feishu API {action} business error: {json.dumps(data, ensure_ascii=False)}")
    return data


def html_title(soup: BeautifulSoup, fallback: str = "A股收盘晚报") -> str:
    h1 = soup.find("h1")
    if h1:
        return clean_text(h1.get_text(" ", strip=True)) or fallback
    if soup.title:
        return clean_text(soup.title.get_text(" ", strip=True)) or fallback
    return fallback


def html_to_docx_blocks(html_text: str, max_blocks: int = 300) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html_text, "html.parser")
    root = soup.body or soup
    blocks: List[Dict[str, Any]] = []
    for node in root.find_all(["h1", "h2", "h3", "p", "li", "table"], recursive=True):
        if node.find_parent(["table"]) and node.name != "table":
            continue
        text = clean_text(node.get_text(" ", strip=True))
        if not text:
            continue
        if node.name == "table":
            rows = []
            for tr in node.find_all("tr"):
                row = [clean_text(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"])]
                if row:
                    rows.append(row)
            if rows:
                blocks.append({"block_type": "table", "rows": rows})
        else:
            block_type = {
                "h1": "heading1",
                "h2": "heading2",
                "h3": "heading3",
                "li": "bullet",
            }.get(node.name, "paragraph")
            links = [a.get("href") for a in node.find_all("a", href=True)]
            blocks.append({"block_type": block_type, "text": text, "links": links})
        if len(blocks) >= max_blocks:
            break
    return blocks


def lark_text(text: str) -> Dict[str, Any]:
    return {"elements": [{"text_run": {"content": text}}]}


def block_to_feishu_children(block: Dict[str, Any]) -> List[Dict[str, Any]]:
    block_type = block.get("block_type")
    if block_type == "table":
        rows = block.get("rows") or []
        text = "\n".join(" | ".join(str(cell) for cell in row) for row in rows)
        return [{"block_type": 2, "text": lark_text(text[:2000])}]
    text = str(block.get("text") or "")
    if block.get("links"):
        link_text = " ".join(str(link) for link in block.get("links") if link)
        if link_text:
            text = f"{text}\n{link_text}"
    # Feishu docx block_type values: 2 text, 3 heading1, 4 heading2, 5 heading3, 12 bullet-like text.
    type_map = {"paragraph": 2, "heading1": 3, "heading2": 4, "heading3": 5, "bullet": 12}
    return [{"block_type": type_map.get(block_type, 2), "text": lark_text(text[:2000])}]


class FeishuHtmlPublisher:
    def __init__(self, app_id: str, app_secret: str) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.base = "https://open.feishu.cn/open-apis"
        self._token: Optional[str] = None

    def tenant_access_token(self) -> str:
        if self._token:
            return self._token
        resp = requests.post(
            f"{self.base}/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=20,
        )
        data = ensure_feishu_ok(resp, "tenant_access_token")
        token = data.get("tenant_access_token")
        if not token:
            raise RuntimeError(f"Feishu token missing: {data}")
        self._token = token
        return token

    def headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.tenant_access_token()}", "Content-Type": "application/json; charset=utf-8"}

    def create_docx(self, title: str, folder_token: Optional[str]) -> str:
        body: Dict[str, Any] = {"title": title}
        if folder_token:
            body["folder_token"] = folder_token
        resp = requests.post(f"{self.base}/docx/v1/documents", headers=self.headers(), json=body, timeout=20)
        data = ensure_feishu_ok(resp, "create docx")
        document = (data.get("data") or {}).get("document") or {}
        token = document.get("document_id") or (data.get("data") or {}).get("document_id")
        if not token:
            raise RuntimeError(f"Feishu document id missing: {data}")
        return token

    def append_blocks(self, document_id: str, blocks: List[Dict[str, Any]]) -> Dict[str, Any]:
        children: List[Dict[str, Any]] = []
        for block in blocks:
            children.extend(block_to_feishu_children(block))
        resp = requests.post(
            f"{self.base}/docx/v1/documents/{document_id}/blocks/{document_id}/children",
            headers=self.headers(),
            json={"children": children[:300]},
            timeout=30,
        )
        return ensure_feishu_ok(resp, "append docx blocks")

    def send_card(self, receive_id_type: str, receive_id: str, card: Dict[str, Any]) -> Dict[str, Any]:
        resp = requests.post(
            f"{self.base}/im/v1/messages",
            headers=self.headers(),
            params={"receive_id_type": receive_id_type},
            json={"receive_id": receive_id, "msg_type": "interactive", "content": json.dumps(card, ensure_ascii=False)},
            timeout=20,
        )
        return ensure_feishu_ok(resp, "send card")


def build_share_card(title: str, doc_url: str, generated_at: str) -> Dict[str, Any]:
    content = f"分享卡片：收盘晚报 HTML 已转换为飞书文档。\n生成时间：{generated_at or '暂缺'}"
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": title}},
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": content}},
            {"tag": "action", "actions": [{"tag": "button", "text": {"tag": "plain_text", "content": "查看飞书文档"}, "url": doc_url, "type": "primary"}]},
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--html", required=True)
    parser.add_argument("--analysis", required=True)
    parser.add_argument("--dry-run-out", help="Where to write dry-run preview JSON.")
    parser.add_argument("--doc-only", action="store_true", help="Create/update Feishu doc only; do not send share card.")
    parser.add_argument("--receive-id", help="Override FEISHU_RECEIVE_ID for the share card target.")
    parser.add_argument("--receive-id-type", help="Override Feishu receive_id_type: chat_id/open_id/user_id/email.")
    parser.add_argument("--env-file", default=".env", help="Dotenv file to load. Defaults to .env.")
    args = parser.parse_args()

    load_dotenv(args.env_file, override=False)
    config = load_yaml(args.config)
    html_text = Path(args.html).read_text(encoding="utf-8")
    analysis = read_json(args.analysis, default={}) or {}
    soup = BeautifulSoup(html_text, "html.parser")
    title = html_title(soup)
    blocks = html_to_docx_blocks(html_text)
    feishu_cfg = config.get("feishu", {})
    dry_run = bool(feishu_cfg.get("dry_run", True))
    generated_at = analysis.get("generated_at") or ""

    if dry_run:
        out = Path(args.dry_run_out) if args.dry_run_out else Path(args.html).with_suffix(".feishu_dry_run.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "title": title,
                    "html": args.html,
                    "docx_blocks": blocks,
                    "card_preview": build_share_card(title, "https://feishu.cn/docx/DRY_RUN", generated_at),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"dry_run=true，已写入：{out}")
        return

    app_id_env = feishu_cfg.get("app_id_env") or "FEISHU_APP_ID"
    app_secret_env = feishu_cfg.get("app_secret_env") or "FEISHU_APP_SECRET"
    receive_id_env = feishu_cfg.get("receive_id_env") or "FEISHU_RECEIVE_ID"
    folder_token_env = feishu_cfg.get("folder_token_env") or "FEISHU_FOLDER_TOKEN"
    app_id = validate_env_value(app_id_env, env_value(app_id_env))
    app_secret = validate_env_value(app_secret_env, env_value(app_secret_env))
    receive_id = args.receive_id or env_value(receive_id_env)
    if not args.doc_only:
        receive_id = validate_env_value(receive_id_env, receive_id)
    folder_token = env_value(folder_token_env)
    if folder_token and looks_like_placeholder(folder_token):
        folder_token = None
    receive_id_type = args.receive_id_type or feishu_cfg.get("receive_id_type", "chat_id")

    publisher = FeishuHtmlPublisher(app_id, app_secret)
    document_id = publisher.create_docx(title, folder_token)
    append_result = publisher.append_blocks(document_id, blocks)
    doc_url = f"https://feishu.cn/docx/{document_id}"
    result = {"document_id": document_id, "doc_url": doc_url, "append": append_result}
    if not args.doc_only:
        result["message"] = publisher.send_card(receive_id_type, str(receive_id), build_share_card(title, doc_url, generated_at))
    else:
        result["message"] = "doc_only=true，已跳过分享卡片发送。"
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
