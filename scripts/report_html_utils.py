from __future__ import annotations

import html
import re
from pathlib import Path


PDF_EXPORT_CSS = """
.pdf-export {
  position: fixed;
  right: 18px;
  top: 18px;
  z-index: 9999;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 36px;
  padding: 0 14px;
  border-radius: 8px;
  background: #175cd3;
  color: #fff !important;
  font: 700 14px/1 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  text-decoration: none !important;
  box-shadow: 0 8px 20px rgba(23, 92, 211, 0.22);
}
.pdf-export:hover { background: #0f4db8; text-decoration: none !important; }
@media print { .pdf-export { display: none !important; } }
"""


def pdf_href_for_html(path: str | Path) -> str:
    return Path(path).with_suffix(".pdf").name


def inject_pdf_export_link(html_text: str, pdf_href: str) -> str:
    """Inject a stable sibling-PDF link without changing the report body structure."""
    if 'class="pdf-export"' in html_text:
        return html_text
    href = html.escape(pdf_href, quote=True)
    anchor = f'<a class="pdf-export" href="{href}">导出PDF</a>'
    text = html_text

    if "</style>" in text:
        text = text.replace("</style>", PDF_EXPORT_CSS + "\n</style>", 1)
    elif "</head>" in text:
        text = text.replace("</head>", f"<style>{PDF_EXPORT_CSS}</style>\n</head>", 1)
    else:
        text = f"<style>{PDF_EXPORT_CSS}</style>\n{text}"

    body_match = re.search(r"<body\b[^>]*>", text, re.I)
    if body_match:
        insert_at = body_match.end()
        return text[:insert_at] + "\n" + anchor + text[insert_at:]
    return anchor + "\n" + text


def ensure_pdf_export_link(path: str | Path) -> Path:
    html_path = Path(path)
    text = html_path.read_text(encoding="utf-8", errors="ignore")
    updated = inject_pdf_export_link(text, pdf_href_for_html(html_path))
    if updated != text:
        html_path.write_text(updated, encoding="utf-8")
    return html_path
