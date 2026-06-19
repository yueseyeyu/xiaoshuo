#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""前端联调冒烟测试"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8090"


def get(path):
    req = urllib.request.Request(f"{BASE}{path}")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = {"ok": False, "error": body}
        return e.code, data


def post(path, body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def _llm_healthy():
    """Check if the main LLM server is reachable (port 8000 by default)."""
    try:
        urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2)
        return True
    except Exception:
        pass
    try:
        urllib.request.urlopen("http://127.0.0.1:8000/v1/models", timeout=2)
        return True
    except Exception:
        return False


def _wait_for_server(timeout=30):
    """Wait for progress server to be ready (first request may be slow)."""
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(f"{BASE}/api/status")
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"Progress server not ready after {timeout}s")


def main():
    # API endpoints
    status, data = _wait_for_server()
    assert status == 200 and data["ok"]
    print(f"[OK] /api/status {status}: running={data['data']['running']}")

    status, data = get("/api/progress")
    assert status == 200 and data["ok"]
    print(f"[OK] /api/progress {status}: {len(data['data'])} books")

    # Genre filter
    encoded = urllib.parse.quote("仙侠")
    status, data = get(f"/api/progress?genre={encoded}")
    assert status == 200 and data["ok"]
    print(f"[OK] /api/progress?genre=仙侠 {status}: {len(data['data'])} books")

    status, data = get("/api/hardware")
    assert status == 200 and data["ok"]
    print(f"[OK] /api/hardware {status}: gpu_temp={data['data'].get('gpu_temp')}")

    status, data = get("/api/logs")
    assert status == 200 and data["ok"]
    print(f"[OK] /api/logs {status}: {len(data['data'])} logs")

    # Static files
    with urllib.request.urlopen(f"{BASE}/", timeout=5) as r:
        html = r.read().decode("utf-8")
        assert "番茄拆书舱" in html
        print(f"[OK] / {r.status}: HTML ok")

    with urllib.request.urlopen(f"{BASE}/css/tokens.css", timeout=5) as r:
        css = r.read().decode("utf-8")
        assert "--bg-primary" in css
        print(f"[OK] /css/tokens.css {r.status}: CSS ok")

    with urllib.request.urlopen(f"{BASE}/js/main.js", timeout=5) as r:
        js = r.read().decode("utf-8")
        assert "init()" in js
        print(f"[OK] /js/main.js {r.status}: JS ok")

    llm_ok = _llm_healthy()
    if llm_ok:
        # Start with selected books
        status, data = post("/api/start", {"genre": "末世", "books": ["book1", "book2"]})
        assert status == 200 and data["ok"]
        print(f"[INFO] /api/start {status}: {data.get('message', data)}")

        status, data = post("/api/stop", {})
        assert status == 200 and data["ok"]
        print(f"[INFO] /api/stop {status}: {data.get('message', data)}")
    else:
        print("[SKIP] /api/start /api/stop (LLM server not running)")

    # P2: new endpoints (404 for missing data is expected)
    status, data = get("/api/book/nonexistent")
    assert status == 404 and not data["ok"]
    print(f"[OK] /api/book/nonexistent {status}")

    status, data = get("/api/score/nonexistent")
    assert status == 404 and not data["ok"]
    print(f"[OK] /api/score/nonexistent {status}")

    print("[DONE] integration smoke test completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
