"""Снимает экраны живого сайта и собирает визуальную презентацию.

Запуск из корня репозитория:
    .venv\\Scripts\\python.exe scripts\\capture_demo.py

Сайт для снимков поднимается на 127.0.0.1:8091, база — data/slide-capture.
Демо на порту 8080 эта команда не трогает.
"""

from __future__ import annotations

import html
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright

from app import create_app
from app.config import Settings
from app.db import connect
from app.domain import seed_demo

OUT = ROOT / "docs" / "features" / "duty-journal" / "slides"
DEMO = ROOT / "docs" / "features" / "duty-journal" / "demo.html"
EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
BASE = "http://127.0.0.1:8091"
MIN_CROP = 700


def edge_path() -> str:
    for path in EDGE_CANDIDATES:
        if Path(path).is_file():
            return path
    raise RuntimeError("Edge не найден")


def boot() -> None:
    settings = Settings(
        host="127.0.0.1",
        port=8091,
        data_dir=ROOT / "data" / "slide-capture",
        secret_key="slides",
        cookie_secure=False,
        pdf_font=None,
    )
    db = settings.db_path
    for suffix in ("", "-wal", "-shm"):
        extra = db.parent / f"{db.name}{suffix}" if suffix else db
        if extra.exists():
            extra.unlink()
    app = create_app(settings)
    connection = connect(db)
    seed_demo(connection)
    connection.commit()
    connection.close()

    def serve() -> None:
        try:
            app.run(host="127.0.0.1", port=8091, debug=False, use_reloader=False)
        except Exception as exc:
            print("SERVER", exc)

    threading.Thread(target=serve, daemon=True).start()
    for _ in range(50):
        try:
            with urllib.request.urlopen(BASE + "/health", timeout=1) as response:
                if response.read() == b"ok":
                    return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("сайт для снимков не поднялся")


def _sticky(locator) -> bool:
    return locator.evaluate(
        """el => {
            let node = el;
            while (node && node !== document.body) {
                if (getComputedStyle(node).position === "sticky") return true;
                node = node.parentElement;
            }
            return false;
        }"""
    )


def prepare_view(page, locators) -> None:
    normals = [locator for locator in locators if not _sticky(locator)]
    if not normals:
        locators[0].scroll_into_view_if_needed()
        page.wait_for_timeout(120)
        return
    tops = []
    bottoms = []
    for locator in normals:
        metrics = locator.evaluate(
            """el => {
                const rect = el.getBoundingClientRect();
                return {top: rect.top + window.scrollY, bottom: rect.bottom + window.scrollY};
            }"""
        )
        tops.append(metrics["top"])
        bottoms.append(metrics["bottom"])
    top = min(tops)
    bottom = max(bottoms)
    height = page.viewport_size["height"]
    span = bottom - top
    if span + 160 <= height:
        scroll = max(0, top - (height - span) / 2)
    else:
        scroll = max(0, top - 72)
    page.evaluate("y => window.scrollTo(0, y)", scroll)
    page.wait_for_timeout(150)


def shoot(page, name, title, targets):
    print("shot", name)
    locators = [locator for locator, _label in targets]
    prepare_view(page, locators)
    boxes = []
    labels = []
    viewport = page.viewport_size
    for locator, label in targets:
        box = locator.bounding_box()
        if box is None:
            raise RuntimeError(f"не виден элемент: {label}")
        if box["y"] < -1 or box["y"] + box["height"] > viewport["height"] + 1:
            raise RuntimeError(
                f"элемент вне экрана: {label} y={box['y']:.0f} h={box['height']:.0f}"
            )
        boxes.append(box)
        labels.append(label)
    phone = page.locator(".phone").bounding_box()
    if phone is None:
        raise RuntimeError("нет колонки .phone")
    visible_top = max(phone["y"], 0)
    visible_bottom = min(phone["y"] + phone["height"], viewport["height"])
    visible_left = max(phone["x"], 0)
    visible_right = min(phone["x"] + phone["width"], viewport["width"])
    pad = 52
    top = min(box["y"] for box in boxes) - pad
    bottom = max(box["y"] + box["height"] for box in boxes) + pad
    if bottom - top < MIN_CROP:
        extra = MIN_CROP - (bottom - top)
        top -= extra * 0.42
        bottom += extra * 0.58
    top = max(top, visible_top)
    bottom = min(bottom, visible_bottom)
    if bottom - top < 360:
        bottom = min(visible_bottom, top + MIN_CROP)
        top = max(visible_top, bottom - MIN_CROP)
    for box, label in zip(boxes, labels):
        if box["y"] < top - 1 or box["y"] + box["height"] > bottom + 1:
            raise RuntimeError(f"{label} не попал в кадр")
        if box["x"] < visible_left - 1 or box["x"] + box["width"] > visible_right + 1:
            raise RuntimeError(f"{label} шире колонки")
    clip = {
        "x": visible_left,
        "y": top,
        "width": visible_right - visible_left,
        "height": bottom - top,
    }
    path = OUT / name
    page.screenshot(path=str(path), clip=clip)
    spots = []
    for box, label in zip(boxes, labels):
        spots.append(
            {
                "label": label,
                "l": (box["x"] - clip["x"]) / clip["width"] * 100,
                "t": (box["y"] - clip["y"]) / clip["height"] * 100,
                "w": box["width"] / clip["width"] * 100,
                "h": box["height"] / clip["height"] * 100,
            }
        )
    print(" ok", name, f"{clip['width']:.0f}x{clip['height']:.0f}", len(spots))
    return {"file": f"slides/{name}", "title": title, "spots": spots}


def follow(page, locator, ready: str) -> None:
    with page.expect_navigation():
        locator.click()
    page.wait_for_selector(ready)


def login(page, user, password):
    page.goto(BASE + "/login", wait_until="domcontentloaded")
    page.fill("#login", user)
    page.fill("#password", password)
    follow(page, page.locator("button:has-text('Войти')"), "nav.tools")


def logout(page):
    follow(page, page.locator("nav.tools button:has-text('Выход')"), "#login")


def label_for(page, text):
    label = page.locator("label", has_text=text).first
    field_id = label.get_attribute("for")
    if field_id:
        return page.locator(f"#{field_id}")
    return label.locator("input").first


def write_html(slides) -> None:
    sections = []
    for index, slide in enumerate(slides):
        rings = []
        for number, spot in enumerate(slide["spots"], start=1):
            rings.append(
                f'<i class="ring" style="left:{spot["l"]:.2f}%;top:{spot["t"]:.2f}%;'
                f'width:{spot["w"]:.2f}%;height:{spot["h"]:.2f}%"></i>'
                f'<b class="n" style="left:{spot["l"]:.2f}%;top:{spot["t"]:.2f}%">{number}</b>'
            )
        legend = "".join(
            f"<li><b>{number}</b>{html.escape(spot['label'])}</li>"
            for number, spot in enumerate(slide["spots"], start=1)
        )
        sections.append(
            f"""<section class="slide{' active' if index == 0 else ''}">
  <h1>{html.escape(slide['title'])}</h1>
  <div class="row">
    <div class="frame">
      <img src="{slide['file']}" alt="{html.escape(slide['title'])}">
      {''.join(rings)}
    </div>
    <ol>{legend}</ol>
  </div>
</section>"""
        )
    document = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Демо: журнал дежурной смены</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: #0e1c2b; color: #f4f7fb; font-family: "Segoe UI", Arial, sans-serif; }}
    .slide {{ display: none; min-height: 100vh; padding: 22px 36px 64px; }}
    .slide.active {{ display: block; }}
    h1 {{ margin: 0 0 12px; font-size: 34px; font-weight: 700; }}
    .row {{
      display: flex; gap: 36px; align-items: center; justify-content: center;
      height: calc(100vh - 118px);
    }}
    .frame {{ position: relative; align-self: center; flex: none; }}
    .frame img {{
      display: block;
      max-height: calc(100vh - 140px);
      max-width: min(760px, 58vw);
      width: auto; height: auto;
      border-radius: 18px;
      box-shadow: 0 18px 50px rgba(0,0,0,.4);
    }}
    .ring {{
      position: absolute; pointer-events: none; border-radius: 10px;
      border: 3px solid #ff5a1f;
      box-shadow: 0 0 0 3px #fff, 0 0 0 8px rgba(255,90,31,.5);
    }}
    .ring {{ z-index: 1; }}
    .n {{
      position: absolute; z-index: 2; transform: translate(-16px, -16px);
      background: #ff5a1f; color: #fff; width: 30px; height: 30px; border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      font-size: 16px; box-shadow: 0 0 0 3px #fff;
    }}
    ol {{ list-style: none; margin: 0; padding: 0; width: 320px; flex: none; }}
    li {{ display: flex; gap: 12px; align-items: center; font-size: 26px; line-height: 1.25; margin: 0 0 18px; }}
    li b {{
      background: #ff5a1f; color: #fff; width: 36px; height: 36px; border-radius: 50%;
      display: flex; align-items: center; justify-content: center; flex: none; font-size: 18px;
    }}
    .bar {{
      position: fixed; left: 0; right: 0; bottom: 0;
      display: flex; justify-content: space-between; align-items: center;
      padding: 8px 24px; background: #0095da; color: #bff9fb;
    }}
    button {{ font: inherit; font-size: 22px; background: transparent; color: inherit; border: 0; cursor: pointer; }}
    @page {{ size: 13.333in 7.5in; margin: 0; }}
    @media print {{
      .bar {{ display: none !important; }}
      .slide {{
        display: flex !important;
        flex-direction: column;
        width: 13.333in;
        height: 7.5in;
        min-height: 0;
        padding: 0.32in 0.42in 0.28in;
        break-after: page;
        page-break-after: always;
        overflow: hidden;
        background: #0e1c2b;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }}
      .slide:last-of-type {{ break-after: auto; page-break-after: auto; }}
      h1 {{ font-size: 28px; margin-bottom: 8px; }}
      .row {{ height: auto; flex: 1; min-height: 0; gap: 28px; }}
      .frame img {{ max-height: 6.15in; max-width: 8.4in; }}
      ol {{ width: 3.3in; }}
      li {{ font-size: 20px; margin-bottom: 12px; }}
    }}
  </style>
</head>
<body>
{''.join(sections)}
<div class="bar"><button type="button" id="prev">←</button><span id="count"></span><button type="button" id="next">→</button></div>
<script>
  const slides = [...document.querySelectorAll(".slide")];
  let index = 0;
  const count = document.getElementById("count");
  function show(next) {{
    index = (next + slides.length) % slides.length;
    slides.forEach((slide, i) => slide.classList.toggle("active", i === index));
    count.textContent = (index + 1) + " / " + slides.length;
  }}
  document.getElementById("prev").onclick = () => show(index - 1);
  document.getElementById("next").onclick = () => show(index + 1);
  document.addEventListener("keydown", (event) => {{
    if (event.key === "ArrowRight" || event.key === "PageDown" || event.key === " ") {{
      event.preventDefault();
      show(index + 1);
    }}
    if (event.key === "ArrowLeft" || event.key === "PageUp") show(index - 1);
  }});
  const asked = Number(new URLSearchParams(location.search).get("slide"));
  show(Number.isFinite(asked) && asked >= 1 ? asked - 1 : 0);
</script>
</body>
</html>
"""
    DEMO.write_text(document, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    boot()
    slides = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=edge_path(), headless=True)
        page = browser.new_page(viewport={"width": 1100, "height": 900}, device_scale_factor=2)
        page.set_default_timeout(12000)

        page.goto(BASE + "/login", wait_until="domcontentloaded")
        page.fill("#login", "duty1")
        page.fill("#password", "duty1")
        slides.append(shoot(page, "01-login.png", "Вход", [
            (page.locator("#login"), "логин"),
            (page.locator("#password"), "пароль"),
            (page.locator("button:has-text('Войти')"), "войти"),
        ]))

        login(page, "admin", "admin")
        page.select_option("#user_id", label="Дежурный первый (duty1)")
        slides.append(shoot(page, "02-assign.png", "Кто заступает", [
            (page.locator("#user_id"), "следующий дежурный"),
            (page.locator("button:has-text('Назначить')"), "назначить"),
        ]))
        slides.append(shoot(page, "03-services.png", "Справочник сервисов", [
            (page.locator("#dir-service h2"), "список сервисов"),
            (page.locator("#dir-service input[placeholder='Новое значение']"), "новое значение"),
            (page.locator("#dir-service button:has-text('Добавить')"), "добавить"),
        ]))
        follow(page, page.locator("button:has-text('Назначить')"), "text=Следующий: Дежурный первый")

        login(page, "duty1", "duty1")
        slides.append(shoot(page, "04-shift.png", "Сдать пока нельзя", [
            (page.locator("button.action"), "сдать смену"),
            (page.locator(".hint"), "сначала назвать следующего"),
        ]))
        slides.append(shoot(page, "05-dock.png", "Действия смены", [
            (page.locator(".dock-btn", has_text="Событие"), "событие"),
            (page.locator(".dock-btn", has_text="Обход"), "обход"),
            (page.locator(".dock-btn", has_text="Отчёт"), "отчёт"),
            (page.locator(".dock-btn", has_text="Распоряжение"), "распоряжение"),
        ]))

        page.goto(BASE + "/events/new", wait_until="domcontentloaded")
        page.select_option("#type", "ac")
        page.fill("#section_from", "Сочи — Анапа")
        page.fill("#damage", "порыв кабеля")
        page.locator("label", has_text="телефонная связь").first.locator("input").check()
        page.locator("label", has_text="передача данных").first.locator("input").check()
        page.locator("label", has_text="передача данных").nth(1).locator("input").check()
        slides.append(shoot(page, "06-event-fields.png", "Новое событие", [
            (page.locator("#type"), "авария или плановые"),
            (page.locator("#section_from"), "участок"),
            (page.locator("#damage"), "повреждение"),
        ]))
        slides.append(shoot(page, "07-event-save.png", "Сервисы и запись", [
            (page.locator("label", has_text="телефонная связь").first, "потерянные"),
            (page.locator("label", has_text="передача данных").nth(1), "на резерве"),
            (page.locator("button:has-text('Подтвердить')"), "подтвердить"),
        ]))
        follow(page, page.locator("button:has-text('Подтвердить')"), "article.tone-accident")
        page.goto(BASE + "/shift", wait_until="domcontentloaded")
        slides.append(shoot(page, "08-accident.png", "Авария в ленте", [
            (page.locator("article.tone-accident .mark"), "оранжевая метка"),
            (page.locator("article.tone-accident .num"), "номер AC"),
            (page.locator("article.tone-accident .status"), "открыто"),
        ]))

        logout(page)
        page.fill("#login", "brig")
        page.fill("#password", "brig")
        slides.append(shoot(page, "09-banner.png", "Чья смена", [
            (page.locator(".banner"), "кто сейчас дежурит"),
            (page.locator("#login"), "логин бригадира"),
            (page.locator("button:has-text('Войти')"), "войти"),
        ]))
        follow(page, page.locator("button:has-text('Войти')"), "input[placeholder='Комментарий']")
        page.locator("input[placeholder='Комментарий']").fill("Бригада выехала")
        slides.append(shoot(page, "10-comment.png", "Комментарий бригадира", [
            (page.locator("input[placeholder='Комментарий']"), "текст"),
            (page.locator("button:has-text('Добавить комментарий')"), "добавить"),
        ]))
        follow(page, page.locator("button:has-text('Добавить комментарий')"), ".comment")
        slides.append(shoot(page, "11-commented.png", "Статус сменился", [
            (page.locator(".status"), "прокомментировано"),
            (page.locator(".comment"), "текст в карточке"),
        ]))

        logout(page)
        login(page, "duty1", "duty1")
        page.goto(BASE + "/rounds/new", wait_until="domcontentloaded")
        for name in ("ЦТОДУСС", "АДМ-16"):
            label_for(page, name).check()
        temps = page.locator(".temp-input")
        temps.nth(0).fill("42")
        for index in range(1, temps.count()):
            temps.nth(index).fill("35")
        temps.first.evaluate(
            "el => el.dispatchEvent(new Event('input', {bubbles: true}))"
        )
        page.wait_for_selector(".temp b.hot")
        slides.append(shoot(page, "12-round.png", "Обход", [
            (page.locator(".check", has_text="Заббикс"), "Заббикс без галочки"),
            (page.locator(".temp b.hot"), "42 и выше — красным"),
            (page.locator("button:has-text('Завершить обход')"), "завершить обход"),
        ]))
        follow(page, page.locator("button:has-text('Завершить обход')"), "text=есть замечания")
        slides.append(shoot(page, "13-round-feed.png", "Замечание в ленте", [
            (page.locator("article", has_text="есть замечания"), "обход с замечанием"),
        ]))

        page.goto(BASE + "/orders/new", wait_until="domcontentloaded")
        page.fill("#body", "Проверить перчатки")
        page.locator("label", has_text="Бригадир смены").locator("input").check()
        page.locator("label", has_text='группа «смена»').locator("input").check()
        slides.append(shoot(page, "14-order.png", "Распоряжение", [
            (page.locator("#body"), "текст"),
            (page.locator("label", has_text="Бригадир смены"), "человек в лист"),
            (page.locator("label", has_text='группа «смена»'), "группа «смена»"),
            (page.locator("button:has-text('Подтвердить')"), "подтвердить"),
        ]))
        follow(page, page.locator("button:has-text('Подтвердить')"), ".dock-btn.disabled")
        slides.append(shoot(page, "15-locked.png", "Кнопки ждут распоряжение", [
            (page.locator("a[href^='/orders/']"), "открыть номер"),
            (page.locator(".dock"), "кнопки погасли"),
        ]))
        follow(page, page.locator("a[href^='/orders/']"), "table")

        logout(page)
        login(page, "admin", "admin")
        page.select_option("#user_id", label="Дежурный второй (duty2)")
        follow(page, page.locator("button:has-text('Назначить')"), "text=Следующий: Дежурный второй")

        logout(page)
        login(page, "duty1", "duty1")
        page.goto(BASE + "/handover", wait_until="domcontentloaded")
        label_for(page, "Документация").check()
        label_for(page, "Инструмент").check()
        page.locator(".check", has_text="СИЗ").locator("input[type='text']").fill("Перчатки на поверке")
        slides.append(shoot(page, "16-handover.png", "Сдача смены", [
            (page.locator(".pill.bad"), "есть незакрытое"),
            (page.locator(".check", has_text="СИЗ").locator("input[type='text']"), "комментарий к СИЗ"),
            (page.locator("form button:has-text('Сдать смену')"), "сдать смену"),
        ]))
        follow(page, page.locator("form button:has-text('Сдать смену')"), "text=Вы сдали смену")

        logout(page)
        login(page, "brig", "brig")
        slides.append(shoot(page, "17-popup.png", "Ознакомление", [
            (page.locator(".popup"), "текст распоряжения"),
            (page.locator("button:has-text('Подтвердить')"), "подтвердить"),
        ]))
        follow(page, page.locator("button:has-text('Подтвердить')"), "text=Смену принял")

        logout(page)
        login(page, "duty2", "duty2")
        page.wait_for_selector("#accept-btn")
        slides.append(shoot(page, "18-accept-note.png", "Что сдал предыдущий", [
            (page.locator(".note", has_text="Перчатки"), "комментарий сдачи"),
            (page.locator("h2", has_text="Группе"), "строка для группы «смена»"),
        ]))
        slides.append(shoot(page, "19-accept-wait.png", "Кнопка ещё оранжевая", [
            (page.locator("#accept-form .check", has_text="АДМ-16"), "галочки ещё пустые"),
            (page.locator(".temp b.hot"), "42° с обхода"),
            (page.locator("#accept-btn"), "принять нельзя"),
        ]))
        page.locator("#accept-form input[name='checked']").evaluate_all(
            "boxes => boxes.forEach(box => { box.checked = true; box.dispatchEvent(new Event('change', {bubbles:true})); })"
        )
        page.wait_for_selector("#accept-btn.btn-go")
        slides.append(shoot(page, "20-accept-go.png", "Можно принимать", [
            (page.locator("#accept-form .check", has_text="АДМ-16"), "все галочки стоят"),
            (page.locator("#accept-btn"), "кнопка зелёная"),
        ]))
        follow(page, page.locator("#accept-btn"), "a:has-text('Сохранить PDF')")
        slides.append(shoot(page, "21-summary-kit.png", "Комментарий в сводке", [
            (page.locator("p", has_text="Перчатки на поверке"), "СИЗ не сдан"),
        ]))
        slides.append(shoot(page, "22-summary-pdf.png", "Файл сводки", [
            (page.locator("a:has-text('Сохранить PDF')"), "сохранить PDF"),
            (page.locator("button:has-text('Печать')"), "печать"),
        ]))

        page.goto(BASE + "/shift", wait_until="domcontentloaded")
        slides.append(shoot(page, "23-pin.png", "Незакрытое у следующего", [
            (page.locator("article.tone-accident.pin"), "розовая карточка"),
            (page.locator("article.pin .status"), "ещё не закрыто"),
            (page.locator("a[href^='/orders/']"), "распоряжение снова держит кнопки"),
        ]))
        follow(page, page.locator("a[href^='/orders/']"), "table")
        page.goto(BASE + "/shift", wait_until="domcontentloaded")
        follow(page, page.locator("button.dock-btn", has_text="Отчёт"), "text=№ОТ")
        slides.append(shoot(page, "24-report.png", "Отчёт", [
            (page.locator("p", has_text="№ОТ"), "номер отчёта"),
            (page.locator("a:has-text('Сохранить PDF')"), "сохранить PDF"),
            (page.locator("button:has-text('Печать')"), "печать"),
        ]))
        page.goto(BASE + "/shift", wait_until="domcontentloaded")
        follow(page, page.locator("button:has-text('Завершить событие')"), "text=закрыто")
        slides.append(shoot(page, "25-closed.png", "Событие закрыто", [
            (page.locator("article", has_text="закрыто").locator(".mark"), "зелёная метка"),
            (page.locator("article", has_text="закрыто").locator(".status"), "закрыто"),
        ]))
        browser.close()
    write_html(slides)
    print("slides", len(slides))


if __name__ == "__main__":
    main()
