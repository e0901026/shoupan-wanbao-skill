from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from export_pdf import export_pdf
from render_index import REPORT_PATTERNS, write_index


def canonical_report_htmls(output_dir: Path) -> list[Path]:
    reports: list[Path] = []
    for path in sorted(output_dir.glob("*.html")):
        if any(pattern.match(path.name) for pattern in REPORT_PATTERNS.values()):
            reports.append(path)
    return reports


def copy_normalized_html(source: Path, destination: Path) -> None:
    text = source.read_text(encoding="utf-8")
    normalized = "\n".join(line.rstrip() for line in text.splitlines()) + "\n"
    destination.write_text(normalized, encoding="utf-8")


def build_site(
    output_dir: str | Path,
    site_dir: str | Path,
    generate_pdfs: bool = False,
) -> dict[str, object]:
    source = Path(output_dir)
    destination = Path(site_dir)
    if not source.exists():
        raise FileNotFoundError(source)

    write_index(source)
    reports = canonical_report_htmls(source)
    if not reports:
        raise RuntimeError("output 目录中没有可发布的正式报告 HTML。")

    destination.mkdir(parents=True, exist_ok=True)
    index_pdf = source / "index.pdf"
    if generate_pdfs and not index_pdf.exists():
        export_pdf(source / "index.html", index_pdf, mode="screenshot")
    keep_names = {"index.html", ".nojekyll", "site-manifest.json"}
    if index_pdf.exists():
        keep_names.add(index_pdf.name)
    for report in reports:
        keep_names.add(report.name)
        pdf = report.with_suffix(".pdf")
        if generate_pdfs and not pdf.exists():
            export_pdf(report, pdf, mode="screenshot")
        if pdf.exists():
            keep_names.add(pdf.name)

    # Remove stale generated artifacts while leaving no unrelated files behind in site/.
    for existing in destination.iterdir():
        if existing.is_file() and existing.name not in keep_names:
            existing.unlink()

    copy_normalized_html(source / "index.html", destination / "index.html")
    if index_pdf.exists():
        shutil.copy2(index_pdf, destination / index_pdf.name)
    for report in reports:
        copy_normalized_html(report, destination / report.name)
        pdf = report.with_suffix(".pdf")
        if pdf.exists():
            shutil.copy2(pdf, destination / pdf.name)

    (destination / ".nojekyll").write_text("", encoding="utf-8")
    counts = {
        kind: sum(1 for path in reports if pattern.match(path.name))
        for kind, pattern in REPORT_PATTERNS.items()
    }
    missing_pdfs = [report.name for report in reports if not report.with_suffix(".pdf").exists()]
    digest = hashlib.sha256()
    for name in sorted(keep_names - {"site-manifest.json", ".nojekyll"}):
        path = source / name
        if path.exists():
            digest.update(name.encode("utf-8"))
            digest.update(path.read_bytes())
    content_hash = digest.hexdigest()
    previous_manifest = {}
    manifest_path = destination / "site-manifest.json"
    if manifest_path.exists():
        try:
            previous_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            previous_manifest = {}
    generated_at = (
        previous_manifest.get("generated_at")
        if previous_manifest.get("content_hash") == content_hash
        else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    manifest: dict[str, object] = {
        "generated_at": generated_at,
        "content_hash": content_hash,
        "report_counts": counts,
        "report_total": len(reports),
        "pdf_total": len(reports) - len(missing_pdfs),
        "missing_pdfs": missing_pdfs,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the static GitHub Pages report site.")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--site-dir", default="site")
    parser.add_argument("--generate-pdfs", action="store_true")
    args = parser.parse_args()
    manifest = build_site(args.output_dir, args.site_dir, generate_pdfs=args.generate_pdfs)
    json.dump(manifest, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
