from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    login TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL DEFAULT '',
    position TEXT NOT NULL DEFAULT '',
    is_admin INTEGER NOT NULL DEFAULT 0,
    can_duty INTEGER NOT NULL DEFAULT 0,
    is_brigadier INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    is_shift_group INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_groups (
    user_id INTEGER NOT NULL,
    group_id INTEGER NOT NULL,
    PRIMARY KEY (user_id, group_id)
);

CREATE TABLE IF NOT EXISTS directories (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE (kind, name)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS shifts (
    id INTEGER PRIMARY KEY,
    duty_user_id INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    handed_at TEXT,
    ended_at TEXT,
    status TEXT NOT NULL,
    next_user_id INTEGER,
    prev_shift_id INTEGER
);

CREATE TABLE IF NOT EXISTS kit_marks (
    id INTEGER PRIMARY KEY,
    shift_id INTEGER NOT NULL,
    phase TEXT NOT NULL,
    item_id INTEGER NOT NULL,
    item_name TEXT NOT NULL,
    checked INTEGER NOT NULL,
    comment TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    number TEXT NOT NULL UNIQUE,
    shift_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    closed_at TEXT,
    department TEXT NOT NULL DEFAULT '',
    line TEXT NOT NULL DEFAULT '',
    section_from TEXT NOT NULL DEFAULT '',
    section_to TEXT NOT NULL DEFAULT '',
    damage TEXT NOT NULL DEFAULT '',
    reporter_name TEXT NOT NULL DEFAULT '',
    reporter_phone TEXT NOT NULL DEFAULT '',
    services_lost TEXT NOT NULL DEFAULT '[]',
    services_reserve TEXT NOT NULL DEFAULT '[]',
    link_kind TEXT,
    link_key TEXT
);

CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY,
    event_id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rounds (
    id INTEGER PRIMARY KEY,
    number TEXT NOT NULL UNIQUE,
    shift_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    ok INTEGER NOT NULL,
    summary TEXT NOT NULL,
    monitoring TEXT NOT NULL,
    temperatures TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    number TEXT NOT NULL UNIQUE,
    shift_id INTEGER NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    announced_shift_id INTEGER
);

CREATE TABLE IF NOT EXISTS order_people (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    user_id INTEGER,
    full_name TEXT NOT NULL,
    position TEXT NOT NULL DEFAULT '',
    group_name TEXT NOT NULL DEFAULT '',
    via_shift_group INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS order_reads (
    order_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    read_at TEXT NOT NULL,
    PRIMARY KEY (order_id, user_id)
);

CREATE TABLE IF NOT EXISTS order_popups (
    order_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    acked_at TEXT,
    PRIMARY KEY (order_id, user_id)
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY,
    number TEXT NOT NULL UNIQUE,
    shift_id INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS counters (
    name TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
"""

DIRECTORIES = {
    "service": ["телефонная связь", "связь совещаний", "передача данных"],
    "section": ["Сочи — Анапа"],
    "room": [
        "Аппаратная 0 этаж КСЗИ",
        "Аппаратная 2 этаж КСЗИ",
        "Аппаратная 9 этаж КСЗИ",
        "Аппаратная 11 этаж КСЗИ",
    ],
    "monitoring": ["ЦТОДУСС", "Заббикс", "АДМ-16"],
    "kit": ["Документация", "Инструмент", "СИЗ"],
    "department": [],
}


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=3000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def seed(conn: sqlite3.Connection, password_hash: str) -> None:
    if conn.execute("SELECT 1 FROM users WHERE login='admin'").fetchone() is None:
        conn.execute(
            """INSERT INTO users
               (login, password_hash, full_name, position, is_admin)
               VALUES ('admin', ?, 'Администратор', 'администратор', 1)""",
            (password_hash,),
        )
    if conn.execute("SELECT 1 FROM groups WHERE is_shift_group=1").fetchone() is None:
        conn.execute(
            "INSERT INTO groups (name, is_shift_group) VALUES ('смена', 1)"
        )
    for kind, names in DIRECTORIES.items():
        for name in names:
            conn.execute(
                "INSERT OR IGNORE INTO directories (kind, name, active) VALUES (?, ?, 1)",
                (kind, name),
            )
    conn.commit()
