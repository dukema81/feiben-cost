# -*- coding: utf-8 -*-
"""测试夹具：临时库 + 独立端口服务进程内启动"""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "backend")
sys.path.insert(0, BACKEND)

_tmp = tempfile.mkdtemp(prefix="feiben_test_")
os.environ["FEIBEN_DB"] = os.path.join(_tmp, "test.db")
os.environ["PORT"] = "8917"
os.environ["FEIBEN_PREFIX"] = ""

import db  # noqa: E402
import seed  # noqa: E402
import server  # noqa: E402
import cost  # noqa: E402


def _http(method, path, body=None, token=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request("http://127.0.0.1:8917" + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"raw": raw}


@pytest.fixture(scope="session")
def srv():
    db.init()
    seed.seed()
    s = server.ThreadingHTTPServer(("127.0.0.1", 8917), server.Handler)
    th = threading.Thread(target=s.serve_forever, daemon=True)
    th.start()
    time.sleep(0.6)
    yield s
    s.shutdown()


@pytest.fixture(scope="session")
def tok(srv):
    st, d = _http("POST", "/api/auth/login", {"username": "admin", "password": "cost@2026"})
    assert st == 200, d
    return d["token"]


@pytest.fixture(scope="session")
def api(srv):
    class C:
        get = staticmethod(lambda p, **kw: _http("GET", p, **kw))
        post = staticmethod(lambda p, b=None, **kw: _http("POST", p, b or {}, **kw))
        put = staticmethod(lambda p, b=None, **kw: _http("PUT", p, b or {}, **kw))
        delete = staticmethod(lambda p, **kw: _http("DELETE", p, **kw))
    return C()


@pytest.fixture(scope="session")
def cn(srv):
    c = db.connect()
    yield c
    db.close_thread_conns()
