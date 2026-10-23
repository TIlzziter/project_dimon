"""Настройки процесса.

Сейчас всё читается из окружения и имеет локальные значения по умолчанию.
На виртуалке с белым адресом меняются только они, код тот же:

- HOST=0.0.0.0, чтобы слушать сеть виртуалки
- PORT=8080
- DATA_DIR=/var/lib/duty-journal
- SECRET_KEY=<длинная случайная строка>
- COOKIE_SECURE=1, когда перед процессом появится https
- PDF_FONT=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf

В эту версию не входят прокси, сертификат, файрвол и ограничение попыток входа.
Их ставят снаружи процесса, когда появится бета.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _find_font() -> str | None:
    candidates = [
        os.environ.get("PDF_FONT", ""),
        r"C:\Windows\Fonts\arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if path and Path(path).is_file():
            return path
    return None


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    data_dir: Path
    secret_key: str
    cookie_secure: bool
    pdf_font: str | None

    @property
    def db_path(self) -> Path:
        return self.data_dir / "journal.sqlite"


def load_settings() -> Settings:
    data_dir = Path(os.environ.get("DATA_DIR", "data")).resolve()
    return Settings(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8080")),
        data_dir=data_dir,
        secret_key=os.environ.get("SECRET_KEY", "local-dev-only"),
        cookie_secure=os.environ.get("COOKIE_SECURE", "") == "1",
        pdf_font=_find_font(),
    )
