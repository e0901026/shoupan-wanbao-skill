from __future__ import annotations

import argparse
import re
from typing import Any, Dict, List
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from common import load_yaml, now_iso, write_json


def compact_text(text: str, max_chars: int = 140) -> str:
    clean = " ".join(text.split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 1].rstrip() + "…"


def extract_rating_and_target(text: str) -> Dict[str, str]:
    clean = " ".join(text.split())
    rating_words = "强推|买入|跑赢行业|增持|推荐|持有|中性"
    target_match = re.search(r"目标价(?:为|至|设定为|上调至|维持)?\s*([0-9]{3,4}(?:\.[0-9]+)?)\s*元", clean)
    rating_match = re.search(rf"(?:维持|给予|首次覆盖|上调至)?.{{0,30}}?[“\"]?({rating_words})[”\"]?评级", clean)
    result: Dict[str, str] = {}
    if target_match:
        result["target_price"] = f"{target_match.group(1)} 元"
    if rating_match:
        result["rating"] = rating_match.group(1)
    return result


def parse_sina_research_list_html(
    html_text: str,
    target_date: str | None = None,
    max_items: int = 8,
) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html_text, "html.parser")
    items: List[Dict[str, Any]] = []
    for row in soup.select("table tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")]
        if len(cells) < 6 or not cells[0].isdigit():
            continue
        report_date = cells[3]
        if target_date and report_date > target_date:
            continue
        link = row.find("a", href=True)
        title = cells[1]
        items.append(
            {
                "title": title,
                "institution": cells[4] or "机构暂缺",
                "analyst": cells[5] or "研究员暂缺",
                "rating": "评级暂缺",
                "target_price": "目标价暂缺",
                "date": report_date,
                "url": urljoin("https://stock.finance.sina.com.cn/", link["href"]) if link else "",
                "summary": compact_text(f"公开研报标题要点：{title}", 90),
                "source": "新浪财经研究报告",
            }
        )
        if len(items) >= max_items:
            break
    return items


def parse_sina_research_detail_summary(html_text: str, fallback_title: str) -> str:
    return parse_sina_research_detail(html_text, fallback_title)["summary"]


def parse_sina_research_detail(html_text: str, fallback_title: str) -> Dict[str, str]:
    soup = BeautifulSoup(html_text, "html.parser")
    body = soup.select_one(".content") or soup.select_one(".blk_container") or soup.find("p")
    if not body:
        text = f"公开研报标题要点：{fallback_title}"
        return {"summary": compact_text(text, 90), **extract_rating_and_target(text)}
    text = body.get_text(" ", strip=True)
    markers = ["投资要点", "事件", "点评", "盈利预测", "风险提示"]
    marker = next((m for m in markers if m in text), "")
    if marker:
        summary_text = text[text.find(marker) :]
    else:
        summary_text = text
    return {"summary": compact_text(summary_text, 140), **extract_rating_and_target(text)}


def fetch_sina_research_detail_summary(url: str, fallback_title: str) -> str:
    if not url:
        return compact_text(f"公开研报标题要点：{fallback_title}", 90)
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    resp.raise_for_status()
    resp.encoding = "gbk"
    return parse_sina_research_detail_summary(resp.text, fallback_title)


def fetch_sina_research_detail(url: str, fallback_title: str) -> Dict[str, str]:
    if not url:
        text = f"公开研报标题要点：{fallback_title}"
        return {"summary": compact_text(text, 90), **extract_rating_and_target(text)}
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    resp.raise_for_status()
    resp.encoding = "gbk"
    return parse_sina_research_detail(resp.text, fallback_title)


def fetch_sina_research(symbol: str, target_date: str | None, max_items: int) -> List[Dict[str, Any]]:
    market_symbol = f"sh{symbol}" if symbol.startswith("6") else f"sz{symbol}"
    url = "https://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml"
    params = {"symbol": market_symbol, "t1": "all"}
    resp = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    resp.raise_for_status()
    resp.encoding = "gbk"
    items = parse_sina_research_list_html(resp.text, target_date=target_date, max_items=max_items)
    for item in items:
        try:
            detail = fetch_sina_research_detail(item.get("url", ""), item.get("title", ""))
            item.update(detail)
        except Exception as exc:  # noqa: BLE001
            item["summary"] = compact_text(f"公开研报标题要点：{item.get('title', '')}", 90)
            item["detail_error"] = str(exc)
    return items


def build_quality(items: List[Dict[str, Any]], errors: List[str]) -> Dict[str, Any]:
    if items:
        return {
            "level": "ok",
            "source_mode": "sina_research",
            "summary": f"机构观点数据可用，已获取 {len(items)} 条公开研报记录。",
            "item_count": len(items),
        }
    return {
        "level": "empty",
        "source_mode": "none",
        "summary": "机构观点暂缺；公开源未返回匹配研报。",
        "item_count": 0,
        "error_count": len(errors),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--date", help="Research cutoff date in YYYY-MM-DD format. Defaults to latest available.")
    args = parser.parse_args()
    config = load_yaml(args.config)
    primary_symbol = str(config.get("primary_stock", {}).get("symbol", "600519"))
    max_items = int(config.get("research", {}).get("max_items", 8))

    errors: List[str] = []
    items: List[Dict[str, Any]] = []
    sources: List[str] = []
    try:
        items = fetch_sina_research(primary_symbol, target_date=args.date, max_items=max_items)
        if items:
            sources.append("新浪财经研究报告")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"sina research failed for {primary_symbol}: {exc}")

    write_json(
        args.out,
        {
            "generated_at": now_iso(),
            "sources": sources or ["新浪财经研究报告 / 授权研报 API"],
            "errors": errors,
            "quality": build_quality(items, errors),
            "items": items,
            "note": "研报正文存在版权限制；本模块仅保留公开列表字段、短摘要和原始链接，不得编造评级或目标价。",
        },
    )


if __name__ == "__main__":
    main()
