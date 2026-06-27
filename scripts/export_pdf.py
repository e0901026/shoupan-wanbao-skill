from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from websocket import create_connection


CHROME_CANDIDATES = [
    "chromium",
    "google-chrome",
    "chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]


class CdpSession:
    def __init__(self, websocket_url: str, timeout: int = 30) -> None:
        os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
        os.environ.setdefault("no_proxy", "127.0.0.1,localhost")
        self.ws = create_connection(
            websocket_url,
            timeout=timeout,
            max_size=None,
            suppress_origin=True,
            http_no_proxy=["127.0.0.1", "localhost"],
        )
        self.seq = 0

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.seq += 1
        message_id = self.seq
        self.ws.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        while True:
            response = json.loads(self.ws.recv())
            if response.get("id") != message_id:
                continue
            if "error" in response:
                raise RuntimeError(f"CDP {method} failed: {response['error']}")
            return response.get("result") or {}

    def close(self) -> None:
        self.ws.close()


def find_chrome() -> str | None:
    for candidate in CHROME_CANDIDATES:
        resolved = shutil.which(candidate)
        path = Path(candidate)
        if resolved:
            return resolved
        if path.exists() and path.is_file():
            return str(path)
    return None


def find_browser_pdf_engine() -> list[str] | None:
    if shutil.which("wkhtmltopdf"):
        return ["wkhtmltopdf"]
    chrome = find_chrome()
    return [chrome] if chrome else None


def browser_pdf_available() -> bool:
    return find_browser_pdf_engine() is not None


def _json_request(url: str, method: str = "GET") -> dict[str, Any]:
    request = urllib.request.Request(url, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _wait_for_devtools_port(user_data_dir: Path) -> int:
    port_file = user_data_dir / "DevToolsActivePort"
    for _ in range(80):
        if port_file.exists():
            lines = port_file.read_text(encoding="utf-8").splitlines()
            if lines and lines[0].strip().isdigit():
                return int(lines[0].strip())
        time.sleep(0.1)
    raise RuntimeError("Chrome DevTools 端口启动超时。")


def _launch_chrome(chrome: str, user_data_dir: Path) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--allow-file-access-from-files",
            "--remote-allow-origins=*",
            "--remote-debugging-port=0",
            f"--user-data-dir={user_data_dir}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _open_page(port: int) -> str:
    targets = _json_request(f"http://127.0.0.1:{port}/json")
    target = next((item for item in targets if item.get("type") == "page"), None)
    websocket_url = target.get("webSocketDebuggerUrl") if target else None
    if not websocket_url:
        raise RuntimeError("Chrome 未返回页面调试地址。")
    return str(websocket_url)


def capture_full_page_png(
    html_file: Path,
    png_file: Path,
    width: int = 1280,
    device_scale_factor: float = 1.0,
) -> Path:
    chrome = find_chrome()
    if not chrome:
        raise RuntimeError("未找到 Chrome/Chromium，无法生成长截图 PDF。")
    with tempfile.TemporaryDirectory() as tmp:
        user_data_dir = Path(tmp) / "chrome-profile"
        process = _launch_chrome(chrome, user_data_dir)
        session: CdpSession | None = None
        try:
            port = _wait_for_devtools_port(user_data_dir)
            websocket_url = _open_page(port)
            session = CdpSession(websocket_url)
            session.call("Page.enable")
            session.call("Runtime.enable")
            session.call("Page.navigate", {"url": html_file.resolve().as_uri()})
            time.sleep(0.5)
            session.call(
                "Runtime.evaluate",
                {
                    "expression": "document.fonts ? document.fonts.ready.then(() => true) : true",
                    "awaitPromise": True,
                },
            )
            time.sleep(0.25)
            dimensions = session.call(
                "Runtime.evaluate",
                {
                    "expression": """
(() => {
  const b = document.body;
  const e = document.documentElement;
  return {
    width: Math.ceil(Math.max(b.scrollWidth, e.scrollWidth, b.offsetWidth, e.offsetWidth, e.clientWidth)),
    height: Math.ceil(Math.max(b.scrollHeight, e.scrollHeight, b.offsetHeight, e.offsetHeight, e.clientHeight))
  };
})()
""",
                    "returnByValue": True,
                },
            )["result"]["value"]
            viewport_width = max(width, int(dimensions["width"]))
            viewport_height = max(1, int(dimensions["height"]))
            session.call(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": viewport_width,
                    "height": viewport_height,
                    "deviceScaleFactor": device_scale_factor,
                    "mobile": False,
                },
            )
            session.call(
                "Runtime.evaluate",
                {
                    "expression": "document.querySelectorAll('.pdf-export').forEach((el) => { el.style.display = 'none'; });",
                },
            )
            screenshot = session.call(
                "Page.captureScreenshot",
                {"format": "png", "fromSurface": True, "captureBeyondViewport": True},
            )
            png_file.parent.mkdir(parents=True, exist_ok=True)
            png_file.write_bytes(base64.b64decode(screenshot["data"]))
            return png_file
        finally:
            if session:
                session.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def png_to_single_page_pdf(png_file: Path, pdf_file: Path) -> Path:
    trim_bottom_whitespace(png_file)
    with Image.open(png_file) as image:
        width, height = image.size
    pdf_file.parent.mkdir(parents=True, exist_ok=True)
    doc = canvas.Canvas(str(pdf_file), pagesize=(width, height))
    doc.drawImage(ImageReader(str(png_file)), 0, 0, width=width, height=height)
    doc.showPage()
    doc.save()
    return pdf_file


def trim_bottom_whitespace(png_file: Path, margin: int = 80) -> Path:
    with Image.open(png_file) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        background = Image.new("RGB", rgb.size, rgb.getpixel((width - 1, height - 1)))
        bbox = ImageChops.difference(rgb, background).getbbox()
        if not bbox:
            return png_file
        bottom = min(height, bbox[3] + margin)
        if bottom < height:
            rgb.crop((0, 0, width, bottom)).save(png_file)
    return png_file


def export_print_pdf(html_path: str | Path, out_path: str | Path | None = None) -> Path:
    html_file = Path(html_path)
    if not html_file.exists():
        raise FileNotFoundError(html_file)
    pdf_file = Path(out_path) if out_path else html_file.with_suffix(".pdf")
    pdf_file.parent.mkdir(parents=True, exist_ok=True)

    engine = find_browser_pdf_engine()
    if engine and Path(engine[0]).name == "wkhtmltopdf":
        subprocess.run([engine[0], "--enable-local-file-access", str(html_file), str(pdf_file)], check=True)
        return pdf_file
    if engine:
        subprocess.run(
            [
                engine[0],
                "--headless",
                "--disable-gpu",
                "--no-pdf-header-footer",
                f"--print-to-pdf={pdf_file}",
                html_file.resolve().as_uri(),
            ],
            check=True,
        )
        return pdf_file
    if shutil.which("pandoc") and (shutil.which("pdflatex") or shutil.which("tectonic")):
        subprocess.run(["pandoc", str(html_file), "-o", str(pdf_file)], check=True)
        return pdf_file
    raise RuntimeError("未找到可用 PDF 导出工具：需要 Chrome/Chromium、wkhtmltopdf，或 pandoc+pdflatex/tectonic。")


def export_pdf(
    html_path: str | Path,
    out_path: str | Path | None = None,
    mode: str = "screenshot",
    width: int = 1280,
    device_scale_factor: float = 1.0,
) -> Path:
    html_file = Path(html_path)
    if not html_file.exists():
        raise FileNotFoundError(html_file)
    pdf_file = Path(out_path) if out_path else html_file.with_suffix(".pdf")
    if mode == "print":
        return export_print_pdf(html_file, pdf_file)
    if mode != "screenshot":
        raise ValueError("mode must be 'screenshot' or 'print'")

    with tempfile.TemporaryDirectory() as tmp:
        png_file = Path(tmp) / f"{html_file.stem}.png"
        capture_full_page_png(html_file, png_file, width=width, device_scale_factor=device_scale_factor)
        return png_to_single_page_pdf(png_file, pdf_file)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", required=True)
    parser.add_argument("--out")
    parser.add_argument("--mode", choices=["screenshot", "print"], default="screenshot")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--device-scale-factor", type=float, default=1.0)
    args = parser.parse_args()
    print(export_pdf(args.html, args.out, mode=args.mode, width=args.width, device_scale_factor=args.device_scale_factor))


if __name__ == "__main__":
    main()
