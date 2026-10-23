from __future__ import annotations

from flask import Flask

from app.config import Settings, load_settings
from app.db import connect, init_db, seed
from app.domain import hash_password
from app.web import register


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or load_settings()
    app = Flask(__name__)
    app.config["SECRET_KEY"] = settings.secret_key
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = settings.cookie_secure
    app.config["SETTINGS"] = settings
    connection = connect(settings.db_path)
    init_db(connection)
    seed(connection, hash_password("admin"))
    connection.close()
    register(app)
    return app
