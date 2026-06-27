from __future__ import annotations

import argparse
import html
import re
import shutil
import subprocess
from pathlib import Path
from typing import List

from report_html_utils import ensure_pdf_export_link


STYLE = """
body {
  color: #1f2933;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.68;
  margin: 0 auto;
  max-width: 1080px;
  padding: 32px 24px 64px;
}
h1, h2, h3 { color: #102a43; line-height: 1.28; }
h1 { font-size: 30px; margin-bottom: 28px; }
h2 { border-bottom: 1px solid #d9e2ec; font-size: 22px; margin-top: 34px; padding-bottom: 8px; }
h3 { font-size: 18px; margin-top: 24px; }
a { color: #2563eb; font-weight: 700; text-decoration: none; }
a:hover { text-decoration: underline; }
table { border-collapse: collapse; display: block; margin: 14px 0 24px; overflow-x: auto; width: 100%; }
th, td { border: 1px solid #bcccdc; padding: 8px 10px; text-align: left; white-space: nowrap; }
th { background: #f0f4f8; font-weight: 700; }
td:not(:first-child), th:not(:first-child) { text-align: right; }
hr { border: 0; border-top: 1px solid #d9e2ec; margin: 28px 0; }
p { margin: 10px 0; }
ul { padding-left: 24px; }
strong { color: #102a43; }
abbr { cursor: help; text-decoration: underline dotted; }
"""


def inline_markdown(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', escaped)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(
        r"&lt;abbr title=&quot;(.+?)&quot;&gt;(.+?)&lt;/abbr&gt;",
        r'<abbr title="\1">\2</abbr>',
        escaped,
    )
    return escaped


def split_table_row(line: str) -> List[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def is_table_separator(line: str) -> bool:
    cells = split_table_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def render_table(lines: List[str]) -> str:
    header = split_table_row(lines[0])
    body = [split_table_row(line) for line in lines[2:]]
    out = ["<table>", "<thead><tr>"]
    out.extend(f"<th>{inline_markdown(cell)}</th>" for cell in header)
    out.append("</tr></thead>")
    out.append("<tbody>")
    for row in body:
        out.append("<tr>")
        out.extend(f"<td>{inline_markdown(cell)}</td>" for cell in row)
        out.append("</tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


def fallback_markdown_to_html(markdown_text: str, title: str) -> str:
    lines = markdown_text.splitlines()
    body: List[str] = []
    i = 0
    in_list = False
    while i < len(lines):
        line = lines[i].rstrip()
        if not line:
            if in_list:
                body.append("</ul>")
                in_list = False
            i += 1
            continue
        if line.startswith("|") and i + 1 < len(lines) and is_table_separator(lines[i + 1]):
            if in_list:
                body.append("</ul>")
                in_list = False
            table_lines = [line, lines[i + 1].rstrip()]
            i += 2
            while i < len(lines) and lines[i].rstrip().startswith("|"):
                table_lines.append(lines[i].rstrip())
                i += 1
            body.append(render_table(table_lines))
            continue
        if line.startswith("---"):
            if in_list:
                body.append("</ul>")
                in_list = False
            body.append("<hr>")
        elif line.startswith("### "):
            if in_list:
                body.append("</ul>")
                in_list = False
            body.append(f"<h3>{inline_markdown(line[4:])}</h3>")
        elif line.startswith("## "):
            if in_list:
                body.append("</ul>")
                in_list = False
            body.append(f"<h2>{inline_markdown(line[3:])}</h2>")
        elif line.startswith("# "):
            if in_list:
                body.append("</ul>")
                in_list = False
            body.append(f"<h1>{inline_markdown(line[2:])}</h1>")
        elif line.startswith("- "):
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{inline_markdown(line[2:])}</li>")
        else:
            if in_list:
                body.append("</ul>")
                in_list = False
            body.append(f"<p>{inline_markdown(line)}</p>")
        i += 1
    if in_list:
        body.append("</ul>")
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="zh-CN">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{html.escape(title)}</title>",
            f"<style>{STYLE}</style>",
            "</head>",
            "<body>",
            *body,
            "</body>",
            "</html>",
        ]
    )


def render_with_pandoc(report: Path, out: Path, title: str) -> None:
    header = out.with_suffix(".pandoc-header.html")
    header.write_text(f"<style>{STYLE}</style>\n", encoding="utf-8")
    subprocess.run(
        [
            "pandoc",
            str(report),
            "-s",
            "--metadata",
            f"title={title}",
            "--include-in-header",
            str(header),
            "-o",
            str(out),
        ],
        check=True,
    )
    ensure_pdf_export_link(out)


def write_fallback_html(report: Path, out: Path, title: str) -> None:
    markdown_text = report.read_text(encoding="utf-8")
    out.write_text(fallback_markdown_to_html(markdown_text, title), encoding="utf-8")
    ensure_pdf_export_link(out)


def default_title(report: Path) -> str:
    for line in report.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return "A股收盘晚报"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--title", help="HTML document title. Defaults to the first Markdown H1.")
    parser.add_argument("--no-pandoc", action="store_true", help="Use the built-in HTML renderer even when pandoc exists.")
    args = parser.parse_args()

    report = Path(args.report)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    title = args.title or default_title(report)

    if not args.no_pandoc and shutil.which("pandoc"):
        render_with_pandoc(report, out, title)
    else:
        write_fallback_html(report, out, title)


if __name__ == "__main__":
    main()
