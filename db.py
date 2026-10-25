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

-- робочі дні: барбер відкриває кожен день вручну; дня немає в таблиці = вихідний
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

INFO_TEXT = (
    "💈 Барбер Андрій\n"
    "📍 вул. Винниченка, 2 (2 поверх)\n"
    "✈️ Telegram: @shkclll\n"
    "📸 Instagram: https://instagram.com/sh.kcl"
)

DEFAULT_SETTINGS = {
    "barber_name": "Андрій",
    "default_remind_days": 28,
    "booking_days": 14,
    "min_lead_min": 60,
    "slot_step": 30,
    "remind_24": 1,
    "remind_2": 1,
    "morning_time": "08:30",
    "haircut_time": "11:00",
    "evening_time": "21:00",
    "info_text": INFO_TEXT,
}

DEFAULT_SERVICES = [
    ("Стрижка", 45, 700),
    ("Стрижка + борода", 60, 900),
    ("Дитяча стрижка", 30, 600),
    ("Стрижка під насадку", 30, 600),
]

DEFAULT_ITEMS = [
    ("Укладка", 600),
    ("Виривання воском", 50),
]


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
    await _ensure_column("appointments", "tips", "INTEGER NOT NULL DEFAULT 0")
    if not await q1("SELECT 1 FROM settings WHERE key = 'migr_v2'"):
        # стара база (нова — порожня, її заповнить _seed): нові контакти, прайс, інтервал 4 тижні
        if await q1("SELECT 1 FROM settings LIMIT 1"):
            await _migrate_v2()
        await _db.execute("INSERT INTO settings(key, value) VALUES('migr_v2', '1')")


async def _migrate_v2() -> None:
    for k in ("barber_name", "info_text", "default_remind_days"):
        await _db.execute("UPDATE settings SET value = ? WHERE key = ?", (str(DEFAULT_SETTINGS[k]), k))
    await _db.execute("UPDATE settings SET value = '30' WHERE key = 'slot_step' AND value = '15'")
    # старі позиції не видаляємо — на них посилаються минулі візити
    await _db.execute("UPDATE services SET active = 0")
    for i, (name, dur, price) in enumerate(DEFAULT_SERVICES):
        await _db.execute(
            "INSERT INTO services(name, duration, price, sort) VALUES(?, ?, ?, ?)", (name, dur, price, i)
        )
    await _db.execute("UPDATE upsell_items SET active = 0")
    for name, price in DEFAULT_ITEMS:
        await _db.execute("INSERT INTO upsell_items(name, price) VALUES(?, ?)", (name, price))


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
