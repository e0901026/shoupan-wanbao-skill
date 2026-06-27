from __future__ import annotations

import argparse
import html
import re
from pathlib import Path
from typing import Dict, List

from report_html_utils import ensure_pdf_export_link


REPORT_PATTERNS = {
    "morning": re.compile(r"a_share_morning_report_(\d{4}-\d{2}-\d{2})\.html$"),
    "daily": re.compile(r"a_share_evening_report_(\d{4}-\d{2}-\d{2})\.html$"),
    "weekly": re.compile(r"a_share_weekly_report_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.html$"),
}


def strip_tags(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def extract_title_and_summary(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    title_match = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.S | re.I) or re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I)
    summary_match = re.search(r"<p[^>]*>(.*?)</p>", text, re.S | re.I)
    title = strip_tags(title_match.group(1)) if title_match else path.stem
    summary = strip_tags(summary_match.group(1)) if summary_match else ""
    return title, summary[:180]


def scan_reports(output_dir: Path) -> Dict[str, List[Dict[str, str]]]:
    groups: Dict[str, List[Dict[str, str]]] = {"morning": [], "daily": [], "weekly": []}
    for path in sorted(output_dir.glob("*.html")):
        if path.name == "index.html":
            continue
        for kind, pattern in REPORT_PATTERNS.items():
            match = pattern.match(path.name)
            if not match:
                continue
            title, summary = extract_title_and_summary(path)
            date_label = " 至 ".join(match.groups()) if kind == "weekly" else match.group(1)
            pdf_path = path.with_suffix(".pdf")
            groups[kind].append(
                {
                    "date": date_label,
                    "title": title,
                    "summary": summary,
                    "href": path.name,
                    "pdf": pdf_path.name if pdf_path.exists() else "",
                }
            )
            break
    for items in groups.values():
        items.sort(key=lambda item: item["date"], reverse=True)
    return groups


def render_group(title: str, items: List[Dict[str, str]]) -> str:
    if not items:
        return f"<section><h2>{html.escape(title)}</h2><p class=\"muted\">暂无报告。</p></section>"
    rows = []
    for item in items:
        pdf = f'<a href="{html.escape(item["pdf"])}">PDF</a>' if item.get("pdf") else '<span class="muted">按需生成</span>'
        rows.append(
            "<tr>"
            f"<td>{html.escape(item['date'])}</td>"
            f"<td><a href=\"{html.escape(item['href'])}\">{html.escape(item['title'])}</a></td>"
            f"<td>{html.escape(item.get('summary') or '')}</td>"
            f"<td>{pdf}</td>"
            "</tr>"
        )
    return (
        f"<section><h2>{html.escape(title)}</h2>"
        "<table><thead><tr><th>日期</th><th>报告</th><th>摘要</th><th>PDF</th></tr></thead><tbody>"
        + "\n".join(rows)
        + "</tbody></table></section>"
    )


def render_index(groups: Dict[str, List[Dict[str, str]]]) -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>A股报告中心</title>
<style>
body{font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif;color:#172033;background:#f6f8fb;margin:0}
main{max-width:1160px;margin:0 auto;padding:32px 24px 56px}
h1{margin:0 0 8px;font-size:30px} h2{margin-top:30px;border-bottom:1px solid #dce3ee;padding-bottom:8px}
a{color:#175cd3;text-decoration:none;font-weight:700} a:hover{text-decoration:underline}
table{width:100%;border-collapse:collapse;background:#fff;border:1px solid #dce3ee;border-radius:8px;overflow:hidden}
th,td{border-bottom:1px solid #dce3ee;padding:9px 10px;text-align:left;vertical-align:top}
th{background:#eef3fa}.muted{color:#667085}
</style>
</head>
<body><main>
<h1>A股报告中心</h1>
<p class="muted">这里仅作为导航入口，报告正文仍跳转到对应 HTML 交付件。</p>
""" + "\n".join(
        [
            render_group("开盘早报", groups["morning"]),
            render_group("收盘晚报", groups["daily"]),
            render_group("周报分析", groups["weekly"]),
        ]
    ) + "\n</main></body></html>"


def write_index(output_dir: str | Path) -> Path:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for html_path in out_dir.glob("*.html"):
        if html_path.name != "index.html":
            ensure_pdf_export_link(html_path)
    out = out_dir / "index.html"
    out.write_text(render_index(scan_reports(out_dir)), encoding="utf-8")
    ensure_pdf_export_link(out)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="output")
    args = parser.parse_args()
    print(write_index(args.output_dir))


if __name__ == "__main__":
    main()
