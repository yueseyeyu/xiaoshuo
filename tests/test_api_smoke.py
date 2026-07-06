# -*- coding: utf-8 -*-
"""
test_api_smoke.py — 后端API接口连通性测试
=========================================
测试所有核心API端点的基本可用性（基于实际路由表）。
"""
import json
import sys
import time
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8089"

passed = 0
failed = 0


def api_get(path, timeout=10):
    try:
        resp = urllib.request.urlopen(f"{BASE}{path}", timeout=timeout)
        return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.readable() else "{}"
        try:
            return e.code, json.loads(body)
        except:
            return e.code, {"raw": body}
    except Exception as e:
        return -1, {"error": str(e)}


def api_post(path, data, timeout=30):
    try:
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            f"{BASE}{path}", body,
            {"Content-Type": "application/json"}
        )
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.readable() else "{}"
        try:
            return e.code, json.loads(body)
        except:
            return e.code, {"raw": body}
    except Exception as e:
        return -1, {"error": str(e)}


def check(name, status, body, expected_status=200, key_check=None):
    global passed, failed
    ok = status == expected_status
    if ok and key_check:
        for k in key_check:
            if k not in body:
                ok = False
                break
    if ok:
        print(f"  [OK] {name} (HTTP {status})")
        passed += 1
    else:
        print(f"  [FAIL] {name} (HTTP {status}) body={str(body)[:200]}")
        failed += 1


def test_health():
    s, b = api_get("/api/health")
    check("GET /api/health", s, b, key_check=["status"])


def test_hardware():
    s, b = api_get("/api/hardware")
    check("GET /api/hardware", s, b)


def test_books():
    s, b = api_get("/api/books")
    check("GET /api/books", s, b)


def test_projects():
    s, b = api_get("/api/projects")
    check("GET /api/projects", s, b)


def test_reports_overview():
    s, b = api_get("/api/reports/overview")
    check("GET /api/reports/overview", s, b)


def test_settings():
    s, b = api_get("/api/settings")
    check("GET /api/settings", s, b)


def test_model_status():
    s, b = api_get("/api/model/status")
    check("GET /api/model/status", s, b)


def test_model_info():
    s, b = api_get("/api/model-info")
    check("GET /api/model-info", s, b)


def test_stats():
    s, b = api_get("/api/stats")
    check("GET /api/stats", s, b)


def test_style_rules():
    s, b = api_get("/api/style/rules")
    check("GET /api/style/rules", s, b)


def test_startup_status():
    s, b = api_get("/api/startup-status")
    check("GET /api/startup-status", s, b)


def test_techniques():
    s, b = api_get("/api/techniques")
    check("GET /api/techniques", s, b)


def test_project_demo():
    s, b = api_get("/api/projects/demo")
    check("GET /api/projects/demo", s, b)


def _get_real_project_id():
    """获取一个真实项目ID用于子路由测试"""
    s, b = api_get("/api/projects")
    if s == 200 and b.get("projects"):
        return b["projects"][0]["id"]
    return None


def test_project_chapters():
    pid = _get_real_project_id()
    if not pid:
        print("  [SKIP] No project available")
        return
    s, b = api_get(f"/api/projects/{pid}/chapters")
    check(f"GET /api/projects/{pid}/chapters", s, b)


def test_project_skeleton():
    pid = _get_real_project_id()
    if not pid:
        print("  [SKIP] No project available")
        return
    s, b = api_get(f"/api/projects/{pid}/skeleton")
    check(f"GET /api/projects/{pid}/skeleton", s, b)


def test_project_world():
    pid = _get_real_project_id()
    if not pid:
        print("  [SKIP] No project available")
        return
    s, b = api_get(f"/api/projects/{pid}/world")
    check(f"GET /api/projects/{pid}/world", s, b)


def test_project_characters():
    pid = _get_real_project_id()
    if not pid:
        print("  [SKIP] No project available")
        return
    s, b = api_get(f"/api/projects/{pid}/characters")
    check(f"GET /api/projects/{pid}/characters", s, b)


def main():
    print("=" * 60)
    print("  API Smoke Test — 后端接口连通性")
    print("=" * 60)

    tests = [
        ("Health", test_health),
        ("Hardware", test_hardware),
        ("Books", test_books),
        ("Projects", test_projects),
        ("Reports Overview", test_reports_overview),
        ("Settings", test_settings),
        ("Model Status", test_model_status),
        ("Model Info", test_model_info),
        ("Stats", test_stats),
        ("Style Rules", test_style_rules),
        ("Startup Status", test_startup_status),
        ("Techniques", test_techniques),
        ("Project Demo", test_project_demo),
        ("Project Demo Chapters", test_project_chapters),
        ("Project Demo Skeleton", test_project_skeleton),
        ("Project Demo World", test_project_world),
        ("Project Demo Characters", test_project_characters),
    ]

    for name, func in tests:
        print(f"\n[{name}]")
        try:
            func()
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
            import traceback
            traceback.print_exc()
            global failed
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"  Result: {passed} passed / {failed} failed")
    print(f"{'=' * 60}")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
