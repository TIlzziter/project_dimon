import re
from pathlib import Path

import pytest

from app import create_app
from app.config import Settings


FONT = Path(r"C:\Windows\Fonts\arial.ttf")


@pytest.fixture()
def settings(tmp_path):
    return Settings(
        host="127.0.0.1",
        port=8080,
        data_dir=tmp_path,
        secret_key="test",
        cookie_secure=False,
        pdf_font=str(FONT) if FONT.is_file() else None,
    )


@pytest.fixture()
def client(settings):
    return create_app(settings).test_client()


def login(client, name, password):
    response = client.post(
        "/login",
        data={"login": name, "password": password},
        follow_redirects=True,
    )
    assert response.status_code == 200
    return response.get_data(as_text=True)


def logout(client):
    client.post("/logout", follow_redirects=True)


def one(pattern, html):
    found = re.search(pattern, html, re.S)
    assert found, pattern
    return found.group(1)


def test_health(client):
    assert client.get("/health").get_data(as_text=True) == "ok"


def test_manual_scenario(client, settings):
    page = login(client, "admin", "admin")
    for text in ("Сочи — Анапа", "Заббикс", "Документация", "Аппаратная 0 этаж КСЗИ", "ЦТОДУСС"):
        assert text in page

    group_id = one(r'name="groups" value="(\d+)" data-group="смена"', page)

    def add_user(login_name, full_name, duty, brigadier, in_shift):
        data = {
            "login": login_name,
            "password": login_name,
            "full_name": full_name,
            "position": "бригадир" if brigadier else "дежурный смены",
        }
        if duty:
            data["can_duty"] = "1"
        if brigadier:
            data["is_brigadier"] = "1"
        if in_shift:
            data["groups"] = group_id
        response = client.post("/admin/users", data=data, follow_redirects=True)
        assert response.status_code == 200
        return response.get_data(as_text=True)

    add_user("duty1", "Дежурный первый", True, False, True)
    add_user("duty2", "Дежурный второй", True, False, True)
    page = add_user("brig", "Бригадир смены", False, True, False)
    duty1 = one(r'value="(\d+)" data-login="duty1"', page)
    duty2 = one(r'value="(\d+)" data-login="duty2"', page)
    brig = one(r'action="/admin/users/(\d+)">\s*<p><strong data-login="brig"', page)

    client.post("/admin/assign", data={"user_id": duty1}, follow_redirects=True)
    logout(client)

    page = login(client, "duty1", "duty1")
    assert "Смену принял" in page
    assert "Дежурный первый" in page
    assert "ещё не назначил следующего" in page
    assert 'href="/events/new"' in page

    page = client.post(
        "/events/new",
        data={
            "type": "ac",
            "section_from": "Сочи — Анапа",
            "damage": "порыв кабеля",
            "lost": ["телефонная связь", "передача данных"],
            "reserve": ["передача данных"],
        },
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "AC" in page
    assert "tone-accident" in page
    assert "открыто" in page
    event_id = one(r"/events/(\d+)", page)

    logout(client)
    page = login(client, "brig", "brig")
    assert "Завершить событие" not in page
    comment = client.post(
        f"/events/{event_id}/comment",
        data={"body": "Бригада выехала"},
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "прокомментировано" in comment
    assert "Бригада выехала" in comment
    assert "Завершить событие" not in comment

    logout(client)
    login(client, "duty1", "duty1")
    round_page = client.get("/rounds/new").get_data(as_text=True)
    mon_ids = dict(re.findall(r'for="mon-(\d+)">([^<]+)', round_page))
    assert "Заббикс" in mon_ids.values()
    checked = [item_id for item_id, name in mon_ids.items() if name != "Заббикс"]
    temp_ids = re.findall(r'name="temp_(\d+)"', round_page)
    assert temp_ids
    payload = {"checked": checked}
    for index, temp_id in enumerate(temp_ids):
        payload[f"temp_{temp_id}"] = "42" if index == 0 else "35"
    round_result = client.post("/rounds/new", data=payload, follow_redirects=True).get_data(as_text=True)
    assert "Обход — есть замечания" in round_result
    assert "Заббикс" in round_result

    blocked = client.post(
        "/orders/new",
        data={"body": "Проверить перчатки", "user_id": brig, "group_id": group_id},
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "Проверить перчатки" in blocked
    assert 'href="/events/new"' not in blocked
    assert "dock-btn disabled" in blocked
    order_id = one(r"/orders/(\d+)", blocked)
    client.get(f"/orders/{order_id}")
    opened = client.get("/shift").get_data(as_text=True)
    assert 'href="/events/new"' in opened

    logout(client)
    login(client, "admin", "admin")
    client.post("/admin/assign", data={"user_id": duty2}, follow_redirects=True)
    logout(client)
    login(client, "duty1", "duty1")
    handover = client.get("/handover").get_data(as_text=True)
    assert "pill bad" in handover
    assert "AC" in handover
    kit_ids = dict(re.findall(r'for="kit-(\d+)">([^<]+)', handover))
    hand_payload = {
        "checked": [item_id for item_id, name in kit_ids.items() if name != "СИЗ"],
    }
    siz = next(item_id for item_id, name in kit_ids.items() if name == "СИЗ")
    hand_payload[f"comment_{siz}"] = "Перчатки на поверке"
    handed = client.post("/handover", data=hand_payload, follow_redirects=True).get_data(as_text=True)
    assert "сдали смену" in handed

    logout(client)
    popup = login(client, "brig", "brig")
    assert "Ознакомьтесь с распоряжением" in popup
    assert "Проверить перчатки" in popup
    client.post(f"/orders/{order_id}/popup", follow_redirects=True)
    logout(client)
    again = login(client, "brig", "brig")
    assert "Ознакомьтесь с распоряжением" not in again

    logout(client)
    login(client, "duty1", "duty1")
    accept = client.get("/accept").get_data(as_text=True)
    assert "Принять смену может только" in accept
    all_checks = re.findall(r'name="checked" value="(\d+)"', accept)
    rejected = client.post(
        "/accept", data={"checked": all_checks}, follow_redirects=True
    ).get_data(as_text=True)
    assert "только назначенный" in rejected
    assert "Сводка смены" not in rejected

    logout(client)
    login(client, "duty2", "duty2")
    accept = client.get("/accept").get_data(as_text=True)
    assert "Перчатки на поверке" in accept
    assert "Группе «смена» нужно ознакомиться" in accept
    assert "btn-wait" in accept
    partial = all_checks[:-1]
    missing = client.post("/accept", data={"checked": partial}, follow_redirects=True).get_data(as_text=True)
    assert "Отметьте все комплекты" in missing
    summary = client.post(
        "/accept", data={"checked": all_checks}, follow_redirects=True
    ).get_data(as_text=True)
    assert "Сводка смены" in summary
    assert "Перчатки на поверке" in summary
    assert "№ОТ" not in summary
    assert "window.print()" in summary
    pdf_url = one(r'href="([^"]*summary\.pdf)"', summary)
    pdf = client.get(pdf_url)
    assert pdf.status_code == 200
    assert pdf.mimetype == "application/pdf"
    assert pdf.data.startswith(b"%PDF")

    shift = client.get("/shift").get_data(as_text=True)
    assert "pin" in shift
    assert "AC" in shift
    assert 'href="/events/new"' not in shift
    new_order = one(r"/orders/(\d+)", shift)
    client.get(f"/orders/{new_order}")
    report = client.post("/reports", follow_redirects=True).get_data(as_text=True)
    assert "№ОТ" in report
    client.post(f"/events/{event_id}/close", follow_redirects=True)
    closed = client.get("/shift").get_data(as_text=True)
    assert "tone-done" in closed
    assert "закрыто" in closed
    assert "Бригада выехала" in closed
    assert 'href="/events/new"' in closed

    logout(client)
    restarted = create_app(settings).test_client()
    restored = login(restarted, "duty2", "duty2")
    assert "Бригада выехала" in restored
    assert "закрыто" in restored
    assert "tone-done" in restored
