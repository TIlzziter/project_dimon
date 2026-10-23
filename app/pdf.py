from __future__ import annotations

from fpdf import FPDF


def render_pdf(document: dict, font_path: str | None) -> bytes:
    if not font_path:
        raise ValueError("Не найден шрифт для PDF. Задайте переменную PDF_FONT.")
    pdf = FPDF()
    pdf.add_font("Body", "", font_path)
    pdf.set_font("Body", size=12)
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()
    lines = [
        f"Сводка смены {document['date']} {document['time']}",
        f"Дежурный: {document['duty_name']}",
    ]
    if document["end_date"]:
        lines.append(f"Сдана: {document['end_date']} {document['end_time']}")
    lines.append("")
    lines.append("Лента")
    lines.extend(document["lines"])
    lines.append("")
    lines.append("Незакрытое")
    lines.extend(document["unclosed"] or ["нет"])
    lines.append("")
    lines.append("Комплекты")
    if document["kits"]:
        for kit in document["kits"]:
            mark = "отмечено" if kit["checked"] else "не отмечено"
            comment = f" — {kit['comment']}" if kit["comment"] else ""
            lines.append(f"{kit['name']}: {mark}{comment}")
    else:
        lines.append("на этой смене комплекты ещё не сдавались")
    lines.append("")
    lines.append("Мониторинг")
    for row in document["monitoring"]:
        lines.append(f"{row['name']}: {'норма' if row['checked'] else 'без отметки'}")
    lines.append("")
    lines.append("Температуры")
    for room in document["rooms"]:
        if room["value"] is None:
            lines.append(f"{room['name']}: нет данных")
        else:
            lines.append(f"{room['name']}: {room['value']:g}")
    for line in lines:
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(pdf.epw, 7, line or " ")
    return bytes(pdf.output())
