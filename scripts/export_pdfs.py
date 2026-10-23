"""PDF рядом с презентацией и инструкцией.

Запуск из корня:
    .venv\\Scripts\\python.exe scripts\\export_pdfs.py

Сайт на порту 8080 не открывает.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright

import scripts.capture_demo as cap

DOCS = ROOT / "docs" / "features" / "duty-journal"


def export(page, source: Path, dest: Path, **options) -> None:
    page.goto(source.as_uri(), wait_until="networkidle")
    page.wait_for_function(
        "() => [...document.images].every((img) => img.complete && img.naturalWidth > 0)"
    )
    page.pdf(path=str(dest), print_background=True, **options)
    print("wrote", dest, dest.stat().st_size)


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=cap.edge_path(), headless=True)
        page = browser.new_page()
        export(
            page,
            DOCS / "demo.html",
            DOCS / "demo.pdf",
            width="13.333in",
            height="7.5in",
            prefer_css_page_size=True,
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
        )
        export(
            page,
            DOCS / "instruction.html",
            DOCS / "instruction.pdf",
            format="A4",
            margin={"top": "16mm", "right": "16mm", "bottom": "16mm", "left": "16mm"},
        )
        browser.close()


if __name__ == "__main__":
    main()
