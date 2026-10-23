import importlib
import sys

from werkzeug.middleware.proxy_fix import ProxyFix


def _load_wsgi(monkeypatch, tmp_path, trust_proxy):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    if trust_proxy:
        monkeypatch.setenv("TRUST_PROXY", "1")
    else:
        monkeypatch.delenv("TRUST_PROXY", raising=False)
    sys.modules.pop("wsgi", None)
    return importlib.import_module("wsgi")


def test_wsgi_health_without_proxy(monkeypatch, tmp_path):
    wsgi = _load_wsgi(monkeypatch, tmp_path, trust_proxy=False)
    assert not isinstance(wsgi.app.wsgi_app, ProxyFix)
    assert wsgi.app.test_client().get("/health").get_data(as_text=True).startswith("ok")


def test_wsgi_trust_proxy_uses_forwarded_proto(monkeypatch, tmp_path):
    wsgi = _load_wsgi(monkeypatch, tmp_path, trust_proxy=True)
    assert isinstance(wsgi.app.wsgi_app, ProxyFix)
    response = wsgi.app.test_client().get("/", headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "example.org"})
    assert response.status_code in (301, 302, 303)
    location = response.headers["Location"]
    assert not location.startswith("http://")
