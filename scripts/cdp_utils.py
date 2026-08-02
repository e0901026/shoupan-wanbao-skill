from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

from websocket import create_connection


def _no_proxy_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def cdp_json_request(base_url: str, path: str, method: str = "GET") -> Any:
    base = base_url.rstrip("/")
    request = urllib.request.Request(f"{base}{path}", method=method)
    with _no_proxy_opener().open(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


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

    def evaluate(self, expression: str, await_promise: bool = True) -> Any:
        result = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": True,
            },
        )
        remote = result.get("result") or {}
        if "exceptionDetails" in result:
            raise RuntimeError(str(result["exceptionDetails"]))
        return remote.get("value")

    def close(self) -> None:
        self.ws.close()


def open_cdp_page(base_url: str, url: str) -> CdpSession:
    encoded = urllib.parse.quote(url, safe="")
    try:
        target = cdp_json_request(base_url, f"/json/new?{encoded}", method="PUT")
    except Exception:
        targets = cdp_json_request(base_url, "/json")
        target = next((item for item in targets if item.get("type") == "page"), None)
        if not target:
            raise
    websocket_url = target.get("webSocketDebuggerUrl")
    if not websocket_url:
        raise RuntimeError("Chrome DevTools 未返回页面 websocket 地址。")
    session = CdpSession(str(websocket_url))
    session.call("Page.enable")
    session.call("Runtime.enable")
    session.call("Page.navigate", {"url": url})
    return session
