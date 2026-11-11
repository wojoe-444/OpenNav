import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from opennav.viewer import compare, server


def test_divergence_finds_the_detour():
    # a goes straight east; b detours ~1.1 km north, ~0.9 km east, and back (~3.1 km off a).
    a = [(33.75, -84.40 + i * 0.001) for i in range(31)]
    b = a[:10] + [(33.76, -84.39 + i * 0.001) for i in range(11)] + a[21:]
    runs = compare.divergence(b, a)
    assert len(runs) == 1
    assert 2800 < runs[0]["length_m"] < 3400
    assert compare.divergence(a, a) == []


@pytest.fixture
def api_server(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENNAV_DATA_DIR", str(tmp_path))
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html><title>OpenNav</title>")
    (static / "assets").mkdir()
    (static / "assets" / "app.js").write_text("export {}")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(server.Api(), static))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _get(url, method="GET"):
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_api_without_ground_truth(api_server):
    status, body = _get(f"{api_server}/api/cases")
    assert status == 200
    cases = json.loads(body)
    assert any(c["id"] == "smyrna-to-atl" and c["has_truth"] is False for c in cases)

    status, body = _get(f"{api_server}/api/cases/smyrna-to-atl")
    d = json.loads(body)
    assert status == 200 and d["official"] is None and "opennav case run" in d["official_error"]

    assert _get(f"{api_server}/api/cases/nope")[0] == 404
    assert _get(f"{api_server}/api/cases/smyrna-to-atl/rerun")[0] == 404  # POST only


def test_static_falls_back_to_index(api_server):
    status, body = _get(f"{api_server}/some/page")
    assert status == 200 and b"OpenNav" in body
    status, body = _get(f"{api_server}/../../etc/passwd")
    assert b"root:" not in body


def test_module_scripts_get_a_javascript_type(api_server):
    with urllib.request.urlopen(f"{api_server}/assets/app.js") as r:
        assert r.headers["Content-Type"].startswith("text/javascript")


def test_bind_skips_a_busy_port():
    busy = server.bind("127.0.0.1", 0, server.make_handler(server.Api()))
    port = busy.server_address[1]
    try:
        other = server.bind("127.0.0.1", port, server.make_handler(server.Api()))
        assert other.server_address[1] != port
        other.server_close()
    finally:
        busy.server_close()
