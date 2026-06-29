#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""前端联调冒烟测试（v8.0 FastAPI 单服务）"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8089"


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
    except urllib.error.URLError as e:
        return 0, {"ok": False, "error": str(e)}


def get_raw(path):
    """获取非 JSON 静态资源。"""
    req = urllib.request.Request(f"{BASE}{path}")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")
    except urllib.error.URLError as e:
        return 0, str(e)


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
    """Wait for API server to be ready."""
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(f"{BASE}/api/health")
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read().decode("utf-8")
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"API server not ready after {timeout}s")


def main():
    # Wait for server
    status, _ = _wait_for_server()
    assert status == 200
    print(f"[OK] /api/health {status}")

    status, data = get("/api/config")
    assert status == 200 and "version" in data
    print(f"[OK] /api/config {status}: version={data.get('version')}")

    status, data = get("/api/status")
    assert status == 200 and "running" in data
    print(f"[OK] /api/status {status}: running={data.get('running', False)}")

    status, data = get("/api/progress")
    assert status == 200 and "running" in data
    print(f"[OK] /api/progress {status}: running={data.get('running', False)}")

    status, data = get("/api/hardware")
    assert status == 200 and isinstance(data, dict)
    print(f"[OK] /api/hardware {status}: keys={list(data.keys())[:3]}")

    status, data = get("/api/logs/dates")
    assert status == 200 and "dates" in data
    print(f"[OK] /api/logs/dates {status}")

    status, data = get("/api/books")
    assert status == 200 and "books" in data
    print(f"[OK] /api/books {status}: count={data.get('count', 0)}")

    status, data = get("/api/disassembly/books")
    assert status == 200 and "books" in data
    print(f"[OK] /api/disassembly/books {status}: count={len(data.get('books', []))}")

    # Static files served by FastAPI StaticFiles
    status, html = get_raw("/")
    assert status == 200 and "番茄小说" in html
    print(f"[OK] / {status}: HTML ok")

    status, css = get_raw("/styles.css")
    assert status == 200 and "--bg" in css
    print(f"[OK] /styles.css {status}: CSS ok")

    status, js = get_raw("/js/main.js")
    assert status == 200 and "init" in js
    print(f"[OK] /js/main.js {status}: JS ok")

    status, js = get_raw("/js/api.js")
    assert status == 200 and "apiFetch" in js
    print(f"[OK] /js/api.js {status}: JS ok")

    llm_ok = _llm_healthy()
    if llm_ok:
        status, data = post("/api/start", {"genre": "末世", "books": ["book1", "book2"]})
        assert status == 200 and data.get("ok")
        print(f"[INFO] /api/start {status}: {data.get('message', data)}")

        status, data = post("/api/stop", {})
        assert status == 200 and data.get("ok")
        print(f"[INFO] /api/stop {status}: {data.get('message', data)}")
    else:
        print("[SKIP] /api/start /api/stop (LLM server not running)")

    print("[DONE] integration smoke test completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
