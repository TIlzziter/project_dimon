"""Точка входа для gunicorn на сервере: gunicorn wsgi:app

Настройки — из окружения (app/config.py). TRUST_PROXY=1 включает ProxyFix: сайт стоит за nginx,
и Flask должен брать схему (https), хост и IP клиента из X-Forwarded-*. Без nginx не включать.
"""

import os

from app import create_app

app = create_app()

if os.environ.get("TRUST_PROXY", "") == "1":
    from werkzeug.middleware.proxy_fix import ProxyFix

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
