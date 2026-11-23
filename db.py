import os

import aiosqlite

from config import DB_PATH

_db: aiosqlite.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients(
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id         INTEGER UNIQUE,
    name          TEXT NOT NULL DEFAULT '',
    phone         TEXT,
    username      TEXT,
    source        TEXT,
    note          TEXT,
    remind_days   INTEGER,
    reminders_off INTEGER NOT NULL DEFAULT 0,
    bot_blocked   INTEGER NOT NULL DEFAULT 0,
    last_reminder TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_clients_phone ON clients(phone);

CREATE TABLE IF NOT EXISTS services(
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL,
    duration INTEGER NOT NULL,
    price    INTEGER NOT NULL,
    active   INTEGER NOT NULL DEFAULT 1,
    sort     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS upsell_items(
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    name   TEXT NOT NULL,
    price  INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS appointments(
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id    INTEGER REFERENCES clients(id),
    service_id   INTEGER REFERENCES services(id),
    start_at     TEXT NOT NULL,
    end_at       TEXT NOT NULL,
    status       TEXT NOT NULL,
    price        INTEGER,
    created_by   TEXT NOT NULL DEFAULT 'admin',
    note         TEXT,
    reminded_24  INTEGER NOT NULL DEFAULT 0,
    reminded_2   INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_appt_start ON appointments(start_at);
CREATE INDEX IF NOT EXISTS ix_appt_client ON appointments(client_id);

CREATE TABLE IF NOT EXISTS sales(
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    appointment_id INTEGER NOT NULL REFERENCES appointments(id),
    item_name      TEXT NOT NULL,
    price          INTEGER NOT NULL,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sales_appt ON sales(appointment_id);

CREATE TABLE IF NOT EXISTS work_hours(
    weekday INTEGER PRIMARY KEY,
    t_start TEXT,
    t_end   TEXT
);

CREATE TABLE IF NOT EXISTS day_overrides(
    day     TEXT PRIMARY KEY,
    t_start TEXT,
    t_end   TEXT
);

CREATE TABLE IF NOT EXISTS settings(
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

DEFAULT_SETTINGS = {
    "barber_name": "Барбер",
    "default_remind_days": 21,
    "booking_days": 14,
    "min_lead_min": 60,
    "slot_step": 15,
    "remind_24": 1,
    "remind_2": 1,
    "morning_time": "08:30",
    "haircut_time": "11:00",
    "evening_time": "21:00",
    "info_text": "📍 Адреса: вкажи в налаштуваннях\n📞 Телефон: +380...\n📸 Instagram: @...",
}

DEFAULT_SERVICES = [
    ("Чоловіча стрижка", 45, 400),
    ("Стрижка + борода", 75, 600),
    ("Моделювання бороди", 30, 250),
    ("Дитяча стрижка", 30, 300),
]

DEFAULT_ITEMS = [
    ("Віск / помада для укладки", 350),
    ("Шампунь", 300),
    ("Олія для бороди", 280),
]

# 0 = понеділок ... 6 = неділя
DEFAULT_HOURS = {0: ("10:00", "19:00"), 1: ("10:00", "19:00"), 2: ("10:00", "19:00"),
                 3: ("10:00", "19:00"), 4: ("10:00", "19:00"), 5: ("10:00", "17:00"),
                 6: (None, None)}


async def init() -> None:
    global _db
    folder = os.path.dirname(os.path.abspath(DB_PATH))
    os.makedirs(folder, exist_ok=True)
    _db = await aiosqlite.connect(DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA foreign_keys=ON")
    await _db.executescript(SCHEMA)
    await _migrate()
    await _seed()
    await _db.commit()


async def close() -> None:
    if _db:
        await _db.close()


async def _ensure_column(table: str, column: str, decl: str) -> None:
    """Безпечна міграція: додає колонку, якщо її ще немає. Нові поля додавай сюди, а не в SCHEMA."""
    rows = await q(f"PRAGMA table_info({table})")
    if column not in {r["name"] for r in rows}:
        await _db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


async def _migrate() -> None:
    # приклад на майбутнє:
    # await _ensure_column("clients", "birthday", "TEXT")
    pass


async def _seed() -> None:
    for k, v in DEFAULT_SETTINGS.items():
        await _db.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (k, str(v)))
    if not await q1("SELECT 1 FROM services LIMIT 1"):
        for i, (name, dur, price) in enumerate(DEFAULT_SERVICES):
            await _db.execute(
                "INSERT INTO services(name, duration, price, sort) VALUES(?, ?, ?, ?)", (name, dur, price, i)
            )
    if not await q1("SELECT 1 FROM upsell_items LIMIT 1"):
        for name, price in DEFAULT_ITEMS:
            await _db.execute("INSERT INTO upsell_items(name, price) VALUES(?, ?)", (name, price))
    if not await q1("SELECT 1 FROM work_hours LIMIT 1"):
        for wd, (s, e) in DEFAULT_HOURS.items():
            await _db.execute("INSERT INTO work_hours(weekday, t_start, t_end) VALUES(?, ?, ?)", (wd, s, e))


async def q(sql: str, *args) -> list[aiosqlite.Row]:
    async with _db.execute(sql, args) as cur:
        return await cur.fetchall()


async def q1(sql: str, *args) -> aiosqlite.Row | None:
    async with _db.execute(sql, args) as cur:
        return await cur.fetchone()


async def ex(sql: str, *args) -> int:
    cur = await _db.execute(sql, args)
    await _db.commit()
    return cur.lastrowid


async def get(key: str, default: str = "") -> str:
    row = await q1("SELECT value FROM settings WHERE key = ?", key)
    return row["value"] if row and row["value"] is not None else default


async def get_int(key: str, default: int = 0) -> int:
    try:
        return int(await get(key, str(default)))
    except ValueError:
        return default


async def put(key: str, value) -> None:
    await ex(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        key, str(value),
    )
