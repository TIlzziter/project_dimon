"""Пишет демо-ролик по шагам презентации: живой сайт, подписи и голос Irina.

Запуск из корня:
    .venv\\Scripts\\python.exe scripts\\record_demo.py

Сайт для съёмки — 127.0.0.1:8091, база data/slide-capture.
Демо на порту 8080 не трогает.
"""

from __future__ import annotations

import subprocess
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright

import scripts.capture_demo as cap

OUT = ROOT / "docs" / "features" / "duty-journal" / "demo.mp4"
WORK = Path.home() / "AppData" / "Local" / "Temp" / "duty-video"
LAYOUT_CSS = (
    ".phone{width:430px !important;margin-left:36px !important;margin-right:auto !important}"
)
INIT_LAYOUT = """
(() => {
  const css = "%s";
  const apply = () => {
    const parent = document.head || document.documentElement;
    if (!parent) return;
    let style = document.getElementById("demo-style");
    if (!style) {
      style = document.createElement("style");
      style.id = "demo-style";
      parent.appendChild(style);
    }
    style.textContent = css;
  };
  apply();
  document.addEventListener("DOMContentLoaded", apply);
})();
""" % LAYOUT_CSS

LINES = [
    "Вход в журнал. Логин, пароль и кнопка Войти.",
    "Администратор выбирает, кто заступает следующим, и нажимает Назначить.",
    "Справочники уже заполнены. Новое значение сервиса добавляется здесь.",
    "Сдать смену пока нельзя: следующий дежурный ещё не назван. Кнопка серая.",
    "Внизу четыре действия: событие, обход, отчёт и распоряжение.",
    "Новое событие. Тип: авария или плановые работы. Дальше участок и повреждение.",
    "Отметьте потерянные сервисы и что из них на резерве. Затем Подтвердить.",
    "В ленте авария: оранжевая метка, номер и статус открыто.",
    "На экране входа видно, кто сейчас дежурит.",
    "Бригадир пишет комментарий и добавляет его в карточку.",
    "Статус стал прокомментировано. Текст комментария виден в карточке.",
    "Обход. Заббикс без галочки. Температура сорок два и выше горит красным.",
    "В ленте обход с замечанием.",
    "Распоряжение. Текст, бригадир и группа смена. Затем Подтвердить.",
    "Пока распоряжение не открыто, нижние кнопки погасли. Номер нужно открыть.",
    "Сдача. Красный индикатор сдачу не блокирует. У СИЗ комментарий, затем Сдать смену.",
    "Бригадиру то же распоряжение открывается на весь экран. Нужно подтвердить.",
    "Приёмка показывает комментарий сдачи и строку для группы смена.",
    "Пока отмечены не все галочки, кнопка Принять смену оранжевая. Сорок два градуса с обхода красные.",
    "Когда все галочки стоят, кнопка становится зелёной.",
    "В сводке остаётся комментарий: перчатки на поверке.",
    "Сводку можно сохранить в PDF и отправить на печать.",
    "У следующего дежурного незакрытая авария розовая. Распоряжение снова держит кнопки.",
    "Кнопка Отчёт создаёт сводку с номером ОТ. Её тоже можно сохранить и напечатать.",
    "Событие закрыто. Метка зелёная, статус закрыто.",
]


def ffmpeg() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def synth_all(folder: Path) -> list[tuple[Path, float]]:
    folder.mkdir(parents=True, exist_ok=True)
    jobs = []
    for index, text in enumerate(LINES, start=1):
        wav = (folder / f"{index:02d}.wav").as_posix()
        jobs.append(f"$s.SetOutputToWaveFile('{wav}')")
        jobs.append(f"$s.Speak(@'\n{text}\n'@)")
        jobs.append("$s.SetOutputToNull()")
    script = "\n".join(
        [
            "Add-Type -AssemblyName System.Speech",
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer",
            "$s.SelectVoice('Microsoft Irina Desktop')",
            "$s.Rate = -1",
            *jobs,
            "$s.Dispose()",
        ]
    )
    ps1 = folder / "speak.ps1"
    ps1.write_text(script, encoding="utf-8-sig")
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
        check=True,
    )
    ready = []
    for index in range(1, len(LINES) + 1):
        path = folder / f"{index:02d}.wav"
        with wave.open(str(path)) as handle:
            seconds = handle.getnframes() / float(handle.getframerate())
        ready.append((path, seconds))
        print(f"voice {index:02d} {seconds:.1f}s")
    return ready


def wav_format(path: Path) -> tuple[int, int, int]:
    with wave.open(str(path)) as handle:
        return handle.getnchannels(), handle.getsampwidth(), handle.getframerate()


def write_silence(path: Path, seconds: float, fmt: tuple[int, int, int]) -> None:
    channels, width, rate = fmt
    frames = max(0, int(seconds * rate))
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(width)
        handle.setframerate(rate)
        handle.writeframes(b"\x00" * frames * width * channels)


def pin_layout(page) -> None:
    page.evaluate(
        """(css) => {
            const parent = document.head || document.documentElement;
            let style = document.getElementById("demo-style");
            if (!style) {
                style = document.createElement("style");
                style.id = "demo-style";
                parent.appendChild(style);
            }
            style.textContent = css;
        }""",
        LAYOUT_CSS,
    )


def show(page, title: str, lines: list[str], say: str, locators) -> None:
    pin_layout(page)
    if locators:
        cap.prepare_view(page, locators)
    phone = page.locator(".phone").bounding_box()
    if phone is None:
        raise RuntimeError(f"нет колонки на кадре «{title}»")
    boxes = []
    viewport = page.viewport_size
    for locator in locators:
        box = locator.bounding_box()
        if box is None:
            raise RuntimeError(f"не виден элемент на кадре «{title}»")
        outside_x = box["x"] < phone["x"] - 2 or box["x"] + box["width"] > phone["x"] + phone["width"] + 2
        outside_y = box["y"] < -2 or box["y"] + box["height"] > viewport["height"] + 2
        if outside_x or outside_y:
            raise RuntimeError(
                f"подсветка вне колонки на кадре «{title}»: "
                f"x={box['x']:.0f} y={box['y']:.0f} "
                f"phone={phone['x']:.0f}+{phone['width']:.0f}"
            )
        boxes.append(box)
    page.evaluate(
        """({title, lines, say, boxes}) => {
            document.querySelectorAll(".demo-hl").forEach((node) => node.remove());
            let aside = document.getElementById("demo-cap");
            if (!aside) {
                aside = document.createElement("aside");
                aside.id = "demo-cap";
                document.body.appendChild(aside);
            }
            aside.style.cssText = "position:fixed;top:28px;left:500px;width:740px;color:#f4f7fb;font-family:Segoe UI,Arial,sans-serif;z-index:10002";
            const items = lines.map((line, index) =>
                `<div style="display:flex;gap:12px;align-items:center;margin:0 0 14px;font-size:26px;line-height:1.25">
                   <b style="flex:none;width:34px;height:34px;border-radius:50%;background:#ff5a1f;color:#fff;display:flex;align-items:center;justify-content:center;font-size:18px">${index + 1}</b>
                   <span>${line}</span>
                 </div>`
            ).join("");
            aside.innerHTML = `<h1 style="margin:0 0 18px;font-size:40px;font-weight:700">${title}</h1>${items}<p style="margin:22px 0 0;font-size:22px;line-height:1.35;color:#d5e4f2">${say}</p>`;
            boxes.forEach((box, index) => {
                const ring = document.createElement("i");
                ring.className = "demo-hl";
                ring.style.cssText = `position:fixed;left:${box.x - 4}px;top:${box.y - 4}px;width:${box.w + 8}px;height:${box.h + 8}px;border:3px solid #ff5a1f;border-radius:10px;box-shadow:0 0 0 3px #fff,0 0 0 8px rgba(255,90,31,.45);pointer-events:none;z-index:10000`;
                const badge = document.createElement("b");
                badge.className = "demo-hl";
                badge.textContent = String(index + 1);
                badge.style.cssText = `position:fixed;left:${box.x - 16}px;top:${box.y - 16}px;width:30px;height:30px;border-radius:50%;background:#ff5a1f;color:#fff;display:flex;align-items:center;justify-content:center;font:700 16px Segoe UI,Arial,sans-serif;box-shadow:0 0 0 3px #fff;z-index:10001;pointer-events:none`;
                document.body.appendChild(ring);
                document.body.appendChild(badge);
            });
        }""",
        {
            "title": title,
            "lines": lines,
            "say": say,
            "boxes": [
                {"x": box["x"], "y": box["y"], "w": box["width"], "h": box["height"]}
                for box in boxes
            ],
        },
    )


class Recorder:
    def __init__(self, page, voices: list[tuple[Path, float]]):
        self.page = page
        self.voices = voices
        self.index = 0
        self.t0 = time.perf_counter()
        self.holds: list[tuple[float, float, Path, float]] = []

    def beat(self, title: str, lines: list[str], locators) -> None:
        path, seconds = self.voices[self.index]
        say = LINES[self.index]
        self.index += 1
        print("beat", self.index, title)
        show(self.page, title, lines, say, locators)
        start = time.perf_counter() - self.t0
        self.page.wait_for_timeout(int((seconds + 0.55) * 1000))
        end = time.perf_counter() - self.t0
        self.holds.append((start, end, path, seconds))


def record(voices: list[tuple[Path, float]]) -> tuple[Path, list[tuple[float, float, Path, float]]]:
    cap.boot()
    video_dir = WORK / "raw"
    video_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=cap.edge_path(), headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            record_video_dir=str(video_dir),
            record_video_size={"width": 1280, "height": 900},
        )
        page = context.new_page()
        page.add_init_script(INIT_LAYOUT)
        page.set_default_timeout(15000)
        rec = Recorder(page, voices)
        page.goto(cap.BASE + "/login", wait_until="domcontentloaded")
        page.fill("#login", "duty1")
        page.fill("#password", "duty1")
        rec.beat("Вход", ["логин", "пароль", "войти"], [
            page.locator("#login"),
            page.locator("#password"),
            page.locator("button:has-text('Войти')"),
        ])

        cap.login(page, "admin", "admin")
        page.select_option("#user_id", label="Дежурный первый (duty1)")
        rec.beat("Кто заступает", ["следующий дежурный", "назначить"], [
            page.locator("#user_id"),
            page.locator("button:has-text('Назначить')"),
        ])
        rec.beat("Справочник сервисов", ["список сервисов", "новое значение", "добавить"], [
            page.locator("#dir-service h2"),
            page.locator("#dir-service input[placeholder='Новое значение']"),
            page.locator("#dir-service button:has-text('Добавить')"),
        ])
        cap.follow(page, page.locator("button:has-text('Назначить')"), "text=Следующий: Дежурный первый")

        cap.login(page, "duty1", "duty1")
        rec.beat("Сдать пока нельзя", ["сдать смену", "сначала назвать следующего"], [
            page.locator("button.action"),
            page.locator(".hint"),
        ])
        rec.beat("Действия смены", ["событие", "обход", "отчёт", "распоряжение"], [
            page.locator(".dock-btn", has_text="Событие"),
            page.locator(".dock-btn", has_text="Обход"),
            page.locator(".dock-btn", has_text="Отчёт"),
            page.locator(".dock-btn", has_text="Распоряжение"),
        ])

        page.goto(cap.BASE + "/events/new", wait_until="domcontentloaded")
        page.select_option("#type", "ac")
        page.fill("#section_from", "Сочи — Анапа")
        page.fill("#damage", "порыв кабеля")
        page.locator("label", has_text="телефонная связь").first.locator("input").check()
        page.locator("label", has_text="передача данных").first.locator("input").check()
        page.locator("label", has_text="передача данных").nth(1).locator("input").check()
        rec.beat("Новое событие", ["авария или плановые", "участок", "повреждение"], [
            page.locator("#type"),
            page.locator("#section_from"),
            page.locator("#damage"),
        ])
        rec.beat("Сервисы и запись", ["потерянные", "на резерве", "подтвердить"], [
            page.locator("label", has_text="телефонная связь").first,
            page.locator("label", has_text="передача данных").nth(1),
            page.locator("button:has-text('Подтвердить')"),
        ])
        cap.follow(page, page.locator("button:has-text('Подтвердить')"), "article.tone-accident")
        page.goto(cap.BASE + "/shift", wait_until="domcontentloaded")
        rec.beat("Авария в ленте", ["оранжевая метка", "номер AC", "открыто"], [
            page.locator("article.tone-accident .mark"),
            page.locator("article.tone-accident .num"),
            page.locator("article.tone-accident .status"),
        ])

        cap.logout(page)
        page.fill("#login", "brig")
        page.fill("#password", "brig")
        rec.beat("Чья смена", ["кто сейчас дежурит", "логин бригадира", "войти"], [
            page.locator(".banner"),
            page.locator("#login"),
            page.locator("button:has-text('Войти')"),
        ])
        cap.follow(page, page.locator("button:has-text('Войти')"), "input[placeholder='Комментарий']")
        page.locator("input[placeholder='Комментарий']").fill("Бригада выехала")
        rec.beat("Комментарий бригадира", ["текст", "добавить"], [
            page.locator("input[placeholder='Комментарий']"),
            page.locator("button:has-text('Добавить комментарий')"),
        ])
        cap.follow(page, page.locator("button:has-text('Добавить комментарий')"), ".comment")
        rec.beat("Статус сменился", ["прокомментировано", "текст в карточке"], [
            page.locator(".status"),
            page.locator(".comment"),
        ])

        cap.logout(page)
        cap.login(page, "duty1", "duty1")
        page.goto(cap.BASE + "/rounds/new", wait_until="domcontentloaded")
        for name in ("ЦТОДУСС", "АДМ-16"):
            cap.label_for(page, name).check()
        temps = page.locator(".temp-input")
        temps.nth(0).fill("42")
        for index in range(1, temps.count()):
            temps.nth(index).fill("35")
        temps.first.evaluate("el => el.dispatchEvent(new Event('input', {bubbles: true}))")
        page.wait_for_selector(".temp b.hot")
        rec.beat("Обход", ["Заббикс без галочки", "42 и выше — красным", "завершить обход"], [
            page.locator(".check", has_text="Заббикс"),
            page.locator(".temp b.hot"),
            page.locator("button:has-text('Завершить обход')"),
        ])
        cap.follow(page, page.locator("button:has-text('Завершить обход')"), "text=есть замечания")
        rec.beat("Замечание в ленте", ["обход с замечанием"], [
            page.locator("article", has_text="есть замечания"),
        ])

        page.goto(cap.BASE + "/orders/new", wait_until="domcontentloaded")
        page.fill("#body", "Проверить перчатки")
        page.locator("label", has_text="Бригадир смены").locator("input").check()
        page.locator("label", has_text='группа «смена»').locator("input").check()
        rec.beat("Распоряжение", ["текст", "человек в лист", "группа «смена»", "подтвердить"], [
            page.locator("#body"),
            page.locator("label", has_text="Бригадир смены"),
            page.locator("label", has_text='группа «смена»'),
            page.locator("button:has-text('Подтвердить')"),
        ])
        cap.follow(page, page.locator("button:has-text('Подтвердить')"), ".dock-btn.disabled")
        rec.beat("Кнопки ждут распоряжение", ["открыть номер", "кнопки погасли"], [
            page.locator("a[href^='/orders/']"),
            page.locator(".dock"),
        ])
        cap.follow(page, page.locator("a[href^='/orders/']"), "table")

        cap.logout(page)
        cap.login(page, "admin", "admin")
        page.select_option("#user_id", label="Дежурный второй (duty2)")
        cap.follow(page, page.locator("button:has-text('Назначить')"), "text=Следующий: Дежурный второй")

        cap.logout(page)
        cap.login(page, "duty1", "duty1")
        page.goto(cap.BASE + "/handover", wait_until="domcontentloaded")
        cap.label_for(page, "Документация").check()
        cap.label_for(page, "Инструмент").check()
        page.locator(".check", has_text="СИЗ").locator("input[type='text']").fill("Перчатки на поверке")
        rec.beat("Сдача смены", ["есть незакрытое", "комментарий к СИЗ", "сдать смену"], [
            page.locator(".pill.bad"),
            page.locator(".check", has_text="СИЗ").locator("input[type='text']"),
            page.locator("form button:has-text('Сдать смену')"),
        ])
        cap.follow(page, page.locator("form button:has-text('Сдать смену')"), "text=Вы сдали смену")

        cap.logout(page)
        cap.login(page, "brig", "brig")
        rec.beat("Ознакомление", ["текст распоряжения", "подтвердить"], [
            page.locator(".popup"),
            page.locator("button:has-text('Подтвердить')"),
        ])
        cap.follow(page, page.locator("button:has-text('Подтвердить')"), "text=Смену принял")

        cap.logout(page)
        cap.login(page, "duty2", "duty2")
        page.wait_for_selector("#accept-btn")
        rec.beat("Что сдал предыдущий", ["комментарий сдачи", "строка для группы «смена»"], [
            page.locator(".note", has_text="Перчатки"),
            page.locator("h2", has_text="Группе"),
        ])
        rec.beat("Кнопка ещё оранжевая", ["галочки ещё пустые", "42° с обхода", "принять нельзя"], [
            page.locator("#accept-form .check", has_text="АДМ-16"),
            page.locator(".temp b.hot"),
            page.locator("#accept-btn"),
        ])
        page.locator("#accept-form input[name='checked']").evaluate_all(
            "boxes => boxes.forEach(box => { box.checked = true; box.dispatchEvent(new Event('change', {bubbles:true})); })"
        )
        page.wait_for_selector("#accept-btn.btn-go")
        rec.beat("Можно принимать", ["все галочки стоят", "кнопка зелёная"], [
            page.locator("#accept-form .check", has_text="АДМ-16"),
            page.locator("#accept-btn"),
        ])
        cap.follow(page, page.locator("#accept-btn"), "a:has-text('Сохранить PDF')")
        rec.beat("Комментарий в сводке", ["СИЗ не сдан"], [
            page.locator("p", has_text="Перчатки на поверке"),
        ])
        rec.beat("Файл сводки", ["сохранить PDF", "печать"], [
            page.locator("a:has-text('Сохранить PDF')"),
            page.locator("button:has-text('Печать')"),
        ])

        page.goto(cap.BASE + "/shift", wait_until="domcontentloaded")
        rec.beat("Незакрытое у следующего", ["розовая карточка", "ещё не закрыто", "распоряжение снова держит кнопки"], [
            page.locator("article.tone-accident.pin"),
            page.locator("article.pin .status"),
            page.locator("a[href^='/orders/']"),
        ])
        cap.follow(page, page.locator("a[href^='/orders/']"), "table")
        page.goto(cap.BASE + "/shift", wait_until="domcontentloaded")
        cap.follow(page, page.locator("button.dock-btn", has_text="Отчёт"), "text=№ОТ")
        rec.beat("Отчёт", ["номер отчёта", "сохранить PDF", "печать"], [
            page.locator("p", has_text="№ОТ"),
            page.locator("a:has-text('Сохранить PDF')"),
            page.locator("button:has-text('Печать')"),
        ])
        page.goto(cap.BASE + "/shift", wait_until="domcontentloaded")
        cap.follow(page, page.locator("button:has-text('Завершить событие')"), "text=закрыто")
        rec.beat("Событие закрыто", ["зелёная метка", "закрыто"], [
            page.locator("article", has_text="закрыто").locator(".mark"),
            page.locator("article", has_text="закрыто").locator(".status"),
        ])
        page.wait_for_timeout(400)
        video = page.video
        context.close()
        browser.close()
        saved = Path(video.path())
    return saved, rec.holds


def assemble(webm: Path, holds: list[tuple[float, float, Path, float]]) -> None:
    tool = ffmpeg()
    fmt = wav_format(holds[0][2])
    origin = holds[0][0]
    cursor = origin
    pieces: list[Path] = []
    silence_index = 0
    for start, end, wav, spoken in holds:
        gap = start - cursor
        if gap > 0.03:
            silence_index += 1
            gap_path = WORK / f"gap-{silence_index:02d}.wav"
            write_silence(gap_path, gap, fmt)
            pieces.append(gap_path)
        pieces.append(wav)
        tail = (end - start) - spoken
        if tail > 0.03:
            silence_index += 1
            tail_path = WORK / f"tail-{silence_index:02d}.wav"
            write_silence(tail_path, tail, fmt)
            pieces.append(tail_path)
        cursor = end
    extra = 0.4
    silence_index += 1
    end_path = WORK / f"tail-{silence_index:02d}.wav"
    write_silence(end_path, extra, fmt)
    pieces.append(end_path)

    listing = WORK / "audio.txt"
    listing.write_text(
        "".join(f"file '{piece.as_posix()}'\n" for piece in pieces),
        encoding="utf-8",
    )
    narration = WORK / "narration.wav"
    subprocess.run(
        [tool, "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(narration)],
        check=True,
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            tool, "-y",
            "-ss", f"{origin:.3f}", "-i", str(webm),
            "-i", str(narration),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", "-preset", "veryfast",
            "-c:a", "aac", "-b:a", "160k",
            "-movflags", "+faststart",
            "-shortest",
            str(OUT),
        ],
        check=True,
    )
    print("wrote", OUT, OUT.stat().st_size)


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    voices = synth_all(WORK / "voice")
    webm, holds = record(voices)
    if len(holds) != len(LINES):
        raise RuntimeError(f"кадров {len(holds)}, фраз {len(LINES)}")
    assemble(webm, holds)


if __name__ == "__main__":
    main()
