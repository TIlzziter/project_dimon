from __future__ import annotations

from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from app.domain import (
    ack_popup,
    feed_for,
    accept_shift,
    add_comment,
    add_directory,
    add_group,
    assign_next,
    can_close,
    can_comment,
    check_password,
    close_event,
    create_event,
    create_order,
    create_report,
    create_round,
    create_user,
    deactivate_directory,
    directory,
    display_name,
    duty_is_blocked,
    ensure_first_shift,
    event_comments,
    event_lines,
    event_tone,
    find_linked,
    get_event,
    get_order,
    get_user,
    get_user_by_login,
    groups_of,
    handed_shift,
    is_red,
    kit_marks,
    list_groups,
    list_users,
    mark_order_read,
    next_user,
    open_shift,
    order_people,
    orders_for_shift_group,
    pending_popup,
    rename_directory,
    room_states,
    save_handover,
    shift_by_id,
    split_dt,
    status_label,
    summary_document,
    target_shift_for_event,
    unclosed_rows,
    update_user,
    visible_shift_for,
)
from app.pdf import render_pdf

ROOT = Path(__file__).resolve().parents[1]
INSTRUCTION = ROOT / "docs" / "features" / "duty-journal" / "instruction.html"


def register(app: Flask) -> None:
    @app.before_request
    def open_db():
        from app.db import connect

        g.db = connect(app.config["SETTINGS"].db_path)
        user_id = session.get("user_id")
        g.user = get_user(g.db, user_id) if user_id else None

    @app.teardown_request
    def close_db(exc):
        db = g.pop("db", None)
        if db is None:
            return
        if exc is None:
            db.commit()
        else:
            db.rollback()
        db.close()

    @app.context_processor
    def shell():
        if g.get("user") is None or g.get("db") is None:
            return {}
        shift = open_shift(g.db) or handed_shift(g.db)
        header = {"show": False}
        if shift is not None:
            duty = get_user(g.db, shift["duty_user_id"])
            date, time = split_dt(shift["started_at"])
            action = None
            enabled = False
            if shift["status"] == "open" and shift["duty_user_id"] == g.user["id"]:
                action = "handover"
                enabled = next_user(g.db) is not None
            elif shift["status"] == "handed" and shift["next_user_id"] == g.user["id"]:
                action = "accept"
                enabled = True
            header = {
                "show": True,
                "duty_name": display_name(duty),
                "date": date,
                "time": time,
                "action": action,
                "enabled": enabled,
            }
        return {"viewer": g.user, "header": header, "display_name": display_name}

    @app.get("/health")
    def health():
        return "ok"

    @app.get("/instruction")
    def instruction():
        if not INSTRUCTION.is_file():
            abort(404)
        return send_file(INSTRUCTION)

    def guard():
        if g.user is None:
            return redirect(url_for("login"))
        return None

    def fail(message: str, where: str):
        g.db.rollback()
        flash(message)
        return redirect(url_for(where))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            user = get_user_by_login(g.db, request.form.get("login", "").strip())
            if user is None or not check_password(user, request.form.get("password", "")):
                flash("Неверный логин или пароль")
            else:
                session["user_id"] = user["id"]
                return redirect(url_for("index"))
        shift = open_shift(g.db) or handed_shift(g.db)
        banner = None
        if shift is not None:
            duty = get_user(g.db, shift["duty_user_id"])
            date, time = split_dt(shift["started_at"])
            banner = {
                "duty_name": display_name(duty),
                "date": date,
                "time": time,
                "waiting": shift["status"] == "handed",
            }
        return render_template("login.html", banner=banner)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    def index():
        denied = guard()
        if denied:
            return denied
        popup = pending_popup(g.db, g.user["id"])
        if popup is not None:
            return redirect(url_for("popup", order_id=popup["id"]))
        if ensure_first_shift(g.db, g.user):
            return redirect(url_for("shift"))
        handed = handed_shift(g.db)
        if handed is not None and handed["next_user_id"] == g.user["id"]:
            return redirect(url_for("accept"))
        current = open_shift(g.db)
        if current is not None and current["duty_user_id"] == g.user["id"]:
            return redirect(url_for("shift"))
        if g.user["is_brigadier"] and (current is not None or handed is not None):
            return redirect(url_for("shift"))
        if g.user["is_admin"]:
            return redirect(url_for("admin"))
        return redirect(url_for("idle"))

    @app.get("/idle")
    def idle():
        denied = guard()
        if denied:
            return denied
        handed = handed_shift(g.db)
        waiting = None
        if handed is not None and handed["duty_user_id"] == g.user["id"]:
            nxt = get_user(g.db, handed["next_user_id"])
            waiting = display_name(nxt)
        return render_template("idle.html", waiting=waiting)

    @app.get("/shift")
    def shift():
        denied = guard()
        if denied:
            return denied
        current = visible_shift_for(g.db, g.user)
        if current is None:
            return redirect(url_for("index"))
        return render_template("shift.html", feed=feed_for(g.db, current, g.user))

    @app.route("/events/new", methods=["GET", "POST"])
    def event_new():
        denied = guard()
        if denied:
            return denied
        target = target_shift_for_event(g.db, g.user)
        if target is None:
            flash("Создавать события может дежурный открытой смены")
            return redirect(url_for("index"))
        if duty_is_blocked(g.db, g.user) and target["status"] == "open":
            flash("Сначала откройте активные распоряжения")
            return redirect(url_for("shift"))
        link_kind = request.values.get("link_kind") or ""
        link_key = request.values.get("link_key") or ""
        if link_kind not in ("", "monitoring", "room"):
            link_kind = ""
        if link_kind and link_key:
            existing = find_linked(g.db, target["id"], link_kind, link_key)
            if existing is not None and request.method == "GET":
                return redirect(url_for("event", event_id=existing["id"]))
        if request.method == "POST":
            try:
                event_id = create_event(
                    g.db,
                    target["id"],
                    {
                        "type": request.form.get("type"),
                        "department": request.form.get("department"),
                        "line": request.form.get("line"),
                        "section_from": request.form.get("section_from"),
                        "section_to": request.form.get("section_to"),
                        "damage": request.form.get("damage"),
                        "reporter_name": request.form.get("reporter_name"),
                        "reporter_phone": request.form.get("reporter_phone"),
                        "lost": request.form.getlist("lost"),
                        "reserve": request.form.getlist("reserve"),
                        "link_kind": link_kind or None,
                        "link_key": link_key or None,
                    },
                )
            except ValueError as exc:
                return fail(str(exc), "event_new")
            return redirect(url_for("event", event_id=event_id))
        return render_template(
            "event_form.html",
            departments=directory(g.db, "department"),
            sections=directory(g.db, "section"),
            services=directory(g.db, "service"),
            link_kind=link_kind,
            link_key=link_key,
        )

    @app.get("/events/<int:event_id>")
    def event(event_id: int):
        denied = guard()
        if denied:
            return denied
        row = get_event(g.db, event_id)
        if row is None:
            abort(404)
        blocked = duty_is_blocked(g.db, g.user)
        comments = []
        for item in event_comments(g.db, event_id):
            date, time = split_dt(item["created_at"])
            comments.append(
                {
                    "author": item["full_name"] or item["login"],
                    "body": item["body"],
                    "date": date,
                    "time": time,
                }
            )
        return render_template(
            "event.html",
            event=row,
            lines=event_lines(row),
            tone=event_tone(row),
            status=status_label(row["status"]),
            comments=comments,
            can_comment=can_comment(g.db, g.user, row) and not (blocked and not g.user["is_brigadier"]),
            can_close=can_close(g.db, g.user, row) and not blocked,
        )

    @app.post("/events/<int:event_id>/comment")
    def event_comment(event_id: int):
        denied = guard()
        if denied:
            return denied
        row = get_event(g.db, event_id)
        if row is None:
            abort(404)
        if not can_comment(g.db, g.user, row):
            return fail("Комментировать может дежурный или бригадир", "shift")
        if duty_is_blocked(g.db, g.user) and not g.user["is_brigadier"]:
            return fail("Сначала откройте активные распоряжения", "shift")
        try:
            add_comment(g.db, event_id, g.user["id"], request.form.get("body", ""))
        except ValueError as exc:
            g.db.rollback()
            flash(str(exc))
            return redirect(url_for("event", event_id=event_id))
        return redirect(url_for("event", event_id=event_id))

    @app.post("/events/<int:event_id>/close")
    def event_close(event_id: int):
        denied = guard()
        if denied:
            return denied
        row = get_event(g.db, event_id)
        if row is None:
            abort(404)
        if not can_close(g.db, g.user, row):
            return fail("Закрывает событие только дежурный", "shift")
        if duty_is_blocked(g.db, g.user):
            return fail("Сначала откройте активные распоряжения", "shift")
        try:
            close_event(g.db, event_id)
        except ValueError as exc:
            g.db.rollback()
            flash(str(exc))
            return redirect(url_for("event", event_id=event_id))
        return redirect(url_for("shift"))

    @app.route("/rounds/new", methods=["GET", "POST"])
    def round_new():
        denied = guard()
        if denied:
            return denied
        current = open_shift(g.db)
        if current is None or current["duty_user_id"] != g.user["id"]:
            flash("Обход проводит дежурный открытой смены")
            return redirect(url_for("index"))
        if duty_is_blocked(g.db, g.user):
            flash("Сначала откройте активные распоряжения")
            return redirect(url_for("shift"))
        monitors = directory(g.db, "monitoring")
        rooms = directory(g.db, "room")
        linked = {}
        for row in list(monitors) + list(rooms):
            kind = "monitoring" if row["kind"] == "monitoring" else "room"
            found = find_linked(g.db, current["id"], kind, row["name"])
            if found is not None:
                linked[row["id"]] = found["id"]
        if request.method == "POST":
            temps = {}
            for room in rooms:
                temps[room["id"]] = request.form.get(f"temp_{room['id']}", "")
            try:
                create_round(
                    g.db,
                    current["id"],
                    [int(item) for item in request.form.getlist("checked")],
                    temps,
                )
            except ValueError as exc:
                return fail(str(exc), "round_new")
            return redirect(url_for("shift"))
        return render_template(
            "round_form.html", monitors=monitors, rooms=rooms, linked=linked
        )

    @app.route("/orders/new", methods=["GET", "POST"])
    def order_new():
        denied = guard()
        if denied:
            return denied
        current = open_shift(g.db)
        if current is None or current["duty_user_id"] != g.user["id"]:
            flash("Распоряжение создаёт дежурный открытой смены")
            return redirect(url_for("index"))
        if duty_is_blocked(g.db, g.user):
            flash("Сначала откройте активные распоряжения")
            return redirect(url_for("shift"))
        if request.method == "POST":
            try:
                create_order(
                    g.db,
                    current["id"],
                    request.form.get("body", ""),
                    request.form.getlist("user_id"),
                    request.form.getlist("group_id"),
                )
            except ValueError as exc:
                return fail(str(exc), "order_new")
            return redirect(url_for("shift"))
        return render_template(
            "order_form.html", users=list_users(g.db), groups=list_groups(g.db)
        )

    @app.get("/orders/<int:order_id>")
    def order(order_id: int):
        denied = guard()
        if denied:
            return denied
        row = get_order(g.db, order_id)
        if row is None:
            abort(404)
        current = open_shift(g.db)
        if current is not None and current["duty_user_id"] == g.user["id"]:
            mark_order_read(g.db, order_id, g.user["id"])
        return render_template(
            "order.html", order=row, people=order_people(g.db, order_id)
        )

    @app.route("/orders/<int:order_id>/popup", methods=["GET", "POST"])
    def popup(order_id: int):
        denied = guard()
        if denied:
            return denied
        row = get_order(g.db, order_id)
        if row is None:
            abort(404)
        pending = pending_popup(g.db, g.user["id"])
        if pending is None or pending["id"] != order_id:
            return redirect(url_for("index"))
        if request.method == "POST":
            ack_popup(g.db, order_id, g.user["id"])
            return redirect(url_for("index"))
        return render_template("popup.html", order=row)

    @app.route("/handover", methods=["GET", "POST"])
    def handover():
        denied = guard()
        if denied:
            return denied
        current = open_shift(g.db)
        if current is None or current["duty_user_id"] != g.user["id"]:
            flash("Сдавать смену может только дежурный")
            return redirect(url_for("index"))
        kits = directory(g.db, "kit")
        if request.method == "POST":
            comments = {
                row["id"]: request.form.get(f"comment_{row['id']}", "") for row in kits
            }
            try:
                save_handover(
                    g.db,
                    current,
                    [int(item) for item in request.form.getlist("checked")],
                    comments,
                )
            except ValueError as exc:
                return fail(str(exc), "handover")
            return redirect(url_for("idle"))
        return render_template(
            "handover.html",
            kits=kits,
            rows=unclosed_rows(g.db, g.user["id"]),
            red=is_red(g.db, g.user["id"]),
            enabled=next_user(g.db) is not None,
        )

    @app.route("/accept", methods=["GET", "POST"])
    def accept():
        denied = guard()
        if denied:
            return denied
        handed = handed_shift(g.db)
        if handed is None:
            return redirect(url_for("index"))
        assignee = handed["next_user_id"] == g.user["id"]
        kits = directory(g.db, "kit")
        monitors = directory(g.db, "monitoring")
        if request.method == "POST":
            if not assignee:
                return fail("Принять смену может только назначенный дежурный", "accept")
            try:
                accept_shift(
                    g.db,
                    handed,
                    g.user,
                    [int(item) for item in request.form.getlist("checked")],
                )
            except ValueError as exc:
                return fail(str(exc), "accept")
            return redirect(url_for("summary", shift_id=handed["id"]))
        previous = {
            row["item_id"]: row for row in kit_marks(g.db, handed["id"], "handover")
        }
        duty = get_user(g.db, handed["duty_user_id"])
        date, time = split_dt(handed["handed_at"])
        linked = {}
        for row in list(monitors) + list(directory(g.db, "room")):
            kind = "monitoring" if row["kind"] == "monitoring" else "room"
            found = find_linked(g.db, handed["id"], kind, row["name"])
            if found is not None:
                linked[row["id"]] = found["id"]
        return render_template(
            "accept.html",
            kits=kits,
            monitors=monitors,
            rooms=room_states(g.db, handed["id"]),
            previous=previous,
            rows=unclosed_rows(g.db, handed["duty_user_id"]),
            red=bool(unclosed_rows(g.db, handed["duty_user_id"])),
            duty_name=display_name(duty),
            date=date,
            time=time,
            assignee=assignee,
            assignee_name=display_name(get_user(g.db, handed["next_user_id"])),
            notices=orders_for_shift_group(g.db, handed),
            linked=linked,
        )

    @app.post("/reports")
    def report_new():
        denied = guard()
        if denied:
            return denied
        current = open_shift(g.db)
        if current is None or current["duty_user_id"] != g.user["id"]:
            return fail("Отчёт формирует дежурный открытой смены", "shift")
        if duty_is_blocked(g.db, g.user):
            return fail("Сначала откройте активные распоряжения", "shift")
        create_report(g.db, current["id"])
        return redirect(url_for("summary", shift_id=current["id"]))

    @app.get("/shifts/<int:shift_id>/summary")
    def summary(shift_id: int):
        denied = guard()
        if denied:
            return denied
        try:
            document = summary_document(g.db, shift_id)
        except ValueError:
            abort(404)
        return render_template("summary.html", document=document)

    @app.get("/shifts/<int:shift_id>/summary.pdf")
    def summary_pdf(shift_id: int):
        denied = guard()
        if denied:
            return denied
        try:
            document = summary_document(g.db, shift_id)
            payload = render_pdf(document, app.config["SETTINGS"].pdf_font)
        except ValueError as exc:
            flash(str(exc))
            return redirect(url_for("summary", shift_id=shift_id))
        from io import BytesIO

        return send_file(
            BytesIO(payload),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"smena-{shift_id}.pdf",
        )

    @app.get("/admin")
    def admin():
        denied = guard()
        if denied:
            return denied
        if not g.user["is_admin"]:
            abort(403)
        current = open_shift(g.db)
        handed = handed_shift(g.db)
        duty_name = ""
        if current is not None:
            duty_name = display_name(get_user(g.db, current["duty_user_id"]))
        elif handed is not None:
            duty_name = display_name(get_user(g.db, handed["duty_user_id"]))
        users = []
        for user in list_users(g.db):
            users.append(
                {
                    "row": user,
                    "groups": [group["id"] for group in groups_of(g.db, user["id"])],
                }
            )
        return render_template(
            "admin.html",
            users=users,
            groups=list_groups(g.db),
            directories={kind: directory(g.db, kind, active_only=False) for kind in (
                "department",
                "section",
                "service",
                "room",
                "monitoring",
                "kit",
            )},
            duty_options=[user for user in list_users(g.db) if user["can_duty"]],
            next_person=next_user(g.db),
            shift_label=_shift_label(current, handed),
            duty_name=duty_name,
        )

    @app.post("/admin/users")
    def admin_user_create():
        return _admin_post(_create_from_form)

    @app.post("/admin/users/<int:user_id>")
    def admin_user_update(user_id: int):
        return _admin_post(lambda: _update_from_form(user_id))

    @app.post("/admin/groups")
    def admin_group():
        return _admin_post(lambda: add_group(g.db, request.form.get("name", "")))

    @app.post("/admin/directories")
    def admin_directory_add():
        return _admin_post(
            lambda: add_directory(
                g.db, request.form.get("kind", ""), request.form.get("name", "")
            )
        )

    @app.post("/admin/directories/<int:item_id>")
    def admin_directory_edit(item_id: int):
        def action():
            if request.form.get("active") == "0":
                deactivate_directory(g.db, item_id)
            else:
                rename_directory(g.db, item_id, request.form.get("name", ""))

        return _admin_post(action)

    @app.post("/admin/assign")
    def admin_assign():
        return _admin_post(lambda: assign_next(g.db, int(request.form.get("user_id", "0"))))

    def _admin_post(action):
        denied = guard()
        if denied:
            return denied
        if not g.user["is_admin"]:
            abort(403)
        try:
            action()
        except (ValueError, TypeError) as exc:
            return fail(str(exc) if str(exc) else "Проверьте поля формы", "admin")
        return redirect(url_for("admin"))

    def _create_from_form():
        create_user(
            g.db,
            request.form.get("login", ""),
            request.form.get("password", ""),
            request.form.get("full_name", ""),
            request.form.get("position", ""),
            request.form.get("is_admin") == "1",
            request.form.get("can_duty") == "1",
            request.form.get("is_brigadier") == "1",
            request.form.getlist("groups"),
        )

    def _update_from_form(user_id: int):
        update_user(
            g.db,
            user_id,
            request.form.get("full_name", ""),
            request.form.get("position", ""),
            request.form.get("is_admin") == "1",
            request.form.get("can_duty") == "1",
            request.form.get("is_brigadier") == "1",
            request.form.get("password", ""),
            request.form.getlist("groups"),
            g.user["id"],
        )


def _shift_label(current, handed) -> str:
    if current is not None:
        return "открыта"
    if handed is not None:
        return "сдана, ждёт приёмки"
    return "нет"
