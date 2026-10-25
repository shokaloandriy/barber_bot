import html
import logging
import re
from datetime import date, datetime, time, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Filter
from aiogram.types import InlineKeyboardButton, Message

import db
from config import ADMIN_IDS, TZ

log = logging.getLogger(__name__)

DT = "%Y-%m-%d %H:%M"
WD = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]
WD_FULL = ["Понеділок", "Вівторок", "Середа", "Четвер", "Пʼятниця", "Субота", "Неділя"]

# статуси, що займають час у графіку
ACTIVE = ("pending", "confirmed", "block", "done")
EMOJI = {"pending": "⏳", "confirmed": "🟢", "done": "✅", "no_show": "🚫", "block": "🔒", "cancelled": "❌"}
STATUS_TXT = {
    "pending": "очікує підтвердження",
    "confirmed": "підтверджено",
    "done": "завершено",
    "no_show": "не прийшов",
    "block": "заблокований час",
    "cancelled": "скасовано",
}

APPT_SQL = """
SELECT a.*, c.name AS cname, c.phone AS cphone, c.tg_id AS ctg, c.username AS cuser,
       s.name AS sname, s.price AS sprice
FROM appointments a
LEFT JOIN clients c ON c.id = a.client_id
LEFT JOIN services s ON s.id = a.service_id
"""


# ---------- доступ ----------

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


class IsAdmin(Filter):
    async def __call__(self, event) -> bool:
        user = getattr(event, "from_user", None)
        return bool(user and user.id in ADMIN_IDS)


# ---------- час і формат ----------

_FAKE_NOW: datetime | None = None  # лише для тестів


def now() -> datetime:
    if _FAKE_NOW:
        return _FAKE_NOW
    return datetime.now(TZ).replace(tzinfo=None, second=0, microsecond=0)


def today() -> date:
    return now().date()


def dts(dt: datetime) -> str:
    return dt.strftime(DT)


def sdt(s: str) -> datetime:
    return datetime.strptime(s, DT)


def d2k(d: date) -> str:
    return d.strftime("%Y%m%d")


def k2d(k: str) -> date:
    return datetime.strptime(k, "%Y%m%d").date()


def fdate(d: date) -> str:
    return f"{WD[d.weekday()]} {d:%d.%m}"


def rel_day(d: date) -> str:
    delta = (d - today()).days
    if delta == 0:
        return "сьогодні"
    if delta == 1:
        return "завтра"
    return fdate(d)


def money(v) -> str:
    return f"{int(round(v or 0)):,}".replace(",", " ") + " грн"


def e(s) -> str:
    return html.escape(str(s)) if s else ""


def btn(text: str, cb) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=cb if isinstance(cb, str) else cb.pack())


def parse_time(s: str | None) -> time | None:
    m = re.fullmatch(r"\s*(\d{1,2})(?:[:.](\d{2}))?\s*", s or "")
    if not m:
        return None
    h, mi = int(m[1]), int(m[2] or 0)
    if h > 23 or mi > 59:
        return None
    return time(h, mi)


def parse_range_note(s: str) -> tuple[time, time, str] | None:
    """'13:00-14:00 обід' -> (13:00, 14:00, 'обід')"""
    m = re.fullmatch(r"\s*(\d{1,2}(?:[:.]\d{2})?)\s*(?:-|–|—|до)\s*(\d{1,2}(?:[:.]\d{2})?)\s*(.*)", s or "", re.S)
    if not m:
        return None
    a, b = parse_time(m[1]), parse_time(m[2])
    if not a or not b or b <= a:
        return None
    return a, b, m[3].strip()


def parse_range(s: str) -> tuple[time, time] | None:
    r = parse_range_note(s)
    if not r or r[2]:
        return None
    return r[0], r[1]


def parse_day(s: str) -> date | None:
    m = re.fullmatch(r"\s*(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\s*", s or "")
    if not m:
        return None
    t = today()
    year = int(m[3]) if m[3] else t.year
    if year < 100:
        year += 2000
    try:
        d = date(year, int(m[2]), int(m[1]))
    except ValueError:
        return None
    if not m[3] and d < t - timedelta(days=60):
        d = d.replace(year=d.year + 1)
    return d


def norm_phone(s: str | None) -> str | None:
    digits = re.sub(r"\D", "", s or "")
    if len(digits) == 10 and digits.startswith("0"):
        digits = "38" + digits
    elif len(digits) == 9:
        digits = "380" + digits
    if not 10 <= len(digits) <= 15:
        return None
    return "+" + digits


def to_int(s: str | None) -> int | None:
    digits = re.sub(r"[^\d]", "", s or "")
    return int(digits) if digits else None


# ---------- графік ----------

def monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


async def day_hours(d: date) -> tuple[time, time] | None:
    """Години роботи на дату. День відкривається лише вручну барбером, інакше — вихідний."""
    row = await db.q1("SELECT t_start, t_end FROM day_overrides WHERE day = ?", d.isoformat())
    if not row or not row["t_start"]:
        return None
    return parse_time(row["t_start"]), parse_time(row["t_end"])


async def set_day_hours(d: date, rng: tuple[time, time] | None) -> list:
    """Відкриває день з годинами rng або закриває (None). Повертає записи, що випадають за нові години."""
    if rng:
        await db.ex(
            "INSERT INTO day_overrides(day, t_start, t_end) VALUES(?, ?, ?) "
            "ON CONFLICT(day) DO UPDATE SET t_start = excluded.t_start, t_end = excluded.t_end",
            d.isoformat(), rng[0].strftime("%H:%M"), rng[1].strftime("%H:%M"),
        )
    else:
        await db.ex("DELETE FROM day_overrides WHERE day = ?", d.isoformat())
    out = []
    for a in await day_appts(d):
        if a["status"] not in ("pending", "confirmed"):
            continue
        s, en = sdt(a["start_at"]), sdt(a["end_at"])
        if not rng or s.time() < rng[0] or en.time() > rng[1]:
            out.append(a)
    return out


async def busy_intervals(d: date, exclude_id: int | None = None) -> list[tuple[datetime, datetime]]:
    day_start = datetime.combine(d, time())
    rows = await db.q(
        "SELECT id, start_at, end_at FROM appointments "
        "WHERE status IN ('pending','confirmed','block','done') AND start_at < ? AND end_at > ?",
        dts(day_start + timedelta(days=1)), dts(day_start),
    )
    return [(sdt(r["start_at"]), sdt(r["end_at"])) for r in rows if r["id"] != exclude_id]


async def free_slots(d: date, duration: int, exclude_id: int | None = None, lead_min: int = 0) -> list[str]:
    hours = await day_hours(d)
    if not hours:
        return []
    step = max(5, await db.get_int("slot_step", 15))
    busy = await busy_intervals(d, exclude_id)
    t = datetime.combine(d, hours[0])
    end = datetime.combine(d, hours[1])
    earliest = now() + timedelta(minutes=lead_min)
    dur = timedelta(minutes=duration)
    res = []
    while t + dur <= end:
        if t >= earliest and all(not (t < be and t + dur > bs) for bs, be in busy):
            res.append(t.strftime("%H:%M"))
        t += timedelta(minutes=step)
    return res


async def find_overlap(start: datetime, end: datetime, exclude_id: int | None = None):
    sql = APPT_SQL + (
        " WHERE a.status IN ('pending','confirmed','block','done') AND a.start_at < ? AND a.end_at > ?"
    )
    args = [dts(end), dts(start)]
    if exclude_id:
        sql += " AND a.id != ?"
        args.append(exclude_id)
    return await db.q1(sql + " ORDER BY a.start_at LIMIT 1", *args)


def remind_flags(start: datetime) -> tuple[int, int]:
    """Щоб не надсилати '24-годинне' нагадування, якщо запис зроблено менш ніж за добу."""
    delta = start - now()
    return int(delta < timedelta(hours=24)), int(delta < timedelta(hours=2))


# ---------- записи ----------

async def appt(aid: int):
    return await db.q1(APPT_SQL + " WHERE a.id = ?", aid)


async def day_appts(d: date):
    return await db.q(
        APPT_SQL + " WHERE a.start_at >= ? AND a.start_at < ? AND a.status != 'cancelled' ORDER BY a.start_at",
        f"{d.isoformat()} 00:00", f"{(d + timedelta(days=1)).isoformat()} 00:00",
    )


async def create_appt(client_id, service_id, start: datetime, end: datetime, status: str,
                      created_by: str, note: str | None = None) -> int:
    r24, r2 = remind_flags(start)
    return await db.ex(
        "INSERT INTO appointments(client_id, service_id, start_at, end_at, status, created_by, note, "
        "reminded_24, reminded_2, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        client_id, service_id, dts(start), dts(end), status, created_by, note, r24, r2, dts(now()),
    )


async def sales_of(aid: int):
    return await db.q("SELECT * FROM sales WHERE appointment_id = ? ORDER BY id", aid)


def appt_line(a) -> str:
    s, en = sdt(a["start_at"]), sdt(a["end_at"])
    return f"{fdate(s.date())}, {s:%H:%M}–{en:%H:%M}"


def card_short(a) -> str:
    who = f"👤 {e(a['cname']) or '—'}"
    if a["cphone"]:
        who += f" · {a['cphone']}"
    if a["cuser"]:
        who += f" · @{e(a['cuser'])}"
    return f"{who}\n✂️ {e(a['sname'])} · {money(a['sprice'])}\n📅 {appt_line(a)}"


# ---------- клієнти ----------

async def client(cid: int):
    return await db.q1("SELECT * FROM clients WHERE id = ?", cid)


async def client_by_tg(tg_id: int):
    return await db.q1("SELECT * FROM clients WHERE tg_id = ?", tg_id)


async def ensure_client(user, source: str | None = None):
    c = await client_by_tg(user.id)
    if c:
        if c["username"] != user.username or c["bot_blocked"]:
            await db.ex("UPDATE clients SET username = ?, bot_blocked = 0 WHERE id = ?", user.username, c["id"])
            c = await client(c["id"])
        return c
    cid = await db.ex(
        "INSERT INTO clients(tg_id, name, username, source, created_at) VALUES(?,?,?,?,?)",
        user.id, user.full_name, user.username, source or "bot", dts(now()),
    )
    return await client(cid)


async def link_phone(c, phone: str):
    """Якщо барбер уже вніс цього клієнта вручну з таким номером — зливаємо в одну картку."""
    other = await db.q1(
        "SELECT * FROM clients WHERE phone = ? AND id != ? AND tg_id IS NULL ORDER BY id LIMIT 1", phone, c["id"]
    )
    if other:
        await db.ex("UPDATE appointments SET client_id = ? WHERE client_id = ?", other["id"], c["id"])
        await db.ex("DELETE FROM clients WHERE id = ?", c["id"])
        await db.ex(
            "UPDATE clients SET tg_id = ?, username = ?, source = COALESCE(source, ?) WHERE id = ?",
            c["tg_id"], c["username"], c["source"], other["id"],
        )
        return await client(other["id"])
    await db.ex("UPDATE clients SET phone = ? WHERE id = ?", phone, c["id"])
    return await client(c["id"])


async def search_clients(query: str, limit: int = 10):
    query = query.strip()
    digits = re.sub(r"\D", "", query)
    rows = await db.q("SELECT * FROM clients ORDER BY name")
    if len(digits) >= 3:
        res = [r for r in rows if r["phone"] and digits in r["phone"]]
    else:
        ql = query.casefold().lstrip("@")
        res = [r for r in rows if ql in (r["name"] or "").casefold() or ql in (r["username"] or "").casefold()]
    return res[:limit]


async def client_stats(cid: int) -> dict:
    r = await db.q1(
        "SELECT COUNT(*) AS n, COALESCE(SUM(price), 0) AS svc, MAX(start_at) AS last "
        "FROM appointments WHERE client_id = ? AND status = 'done'", cid,
    )
    s = await db.q1(
        "SELECT COALESCE(SUM(sa.price), 0) AS v FROM sales sa JOIN appointments a ON a.id = sa.appointment_id "
        "WHERE a.client_id = ? AND a.status = 'done'", cid,
    )
    ns = await db.q1("SELECT COUNT(*) AS n FROM appointments WHERE client_id = ? AND status = 'no_show'", cid)
    nxt = await db.q1(
        "SELECT start_at FROM appointments WHERE client_id = ? AND status IN ('pending','confirmed') "
        "AND start_at >= ? ORDER BY start_at LIMIT 1", cid, dts(now()),
    )
    total = r["svc"] + s["v"]
    return {
        "visits": r["n"], "total": total, "upsell": s["v"],
        "avg": total / r["n"] if r["n"] else 0,
        "last": sdt(r["last"]).date() if r["last"] else None,
        "no_show": ns["n"],
        "next": sdt(nxt["start_at"]) if nxt else None,
    }


async def due_clients():
    """Клієнти, яким за інтервалом уже час на стрижку і які ще не записані."""
    default = await db.get_int("default_remind_days", 28)
    rows = await db.q(
        "SELECT c.*, MAX(a.start_at) AS last_visit FROM clients c "
        "JOIN appointments a ON a.client_id = c.id AND a.status = 'done' GROUP BY c.id"
    )
    future = {
        r["client_id"] for r in await db.q(
            "SELECT DISTINCT client_id FROM appointments WHERE status IN ('pending','confirmed') AND start_at >= ?",
            dts(now()),
        )
    }
    res = []
    for c in rows:
        if c["id"] in future:
            continue
        interval = c["remind_days"] or default
        last = sdt(c["last_visit"]).date()
        overdue = (today() - last).days - interval
        if overdue >= 0:
            res.append((c, last, interval, overdue))
    res.sort(key=lambda x: x[3])
    return res


# ---------- відправка ----------

async def safe_edit(msg: Message, text: str, kb=None) -> None:
    try:
        await msg.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as err:
        if "not modified" in str(err):
            return
        await msg.answer(text, reply_markup=kb)


async def notify_admins(bot: Bot, text: str, kb=None) -> None:
    for uid in ADMIN_IDS:
        try:
            await bot.send_message(uid, text, reply_markup=kb)
        except Exception as err:  # noqa: BLE001
            log.warning("admin notify failed %s: %s", uid, err)


async def send_client(bot: Bot, tg_id: int | None, text: str, kb=None) -> bool:
    if not tg_id:
        return False
    try:
        await bot.send_message(tg_id, text, reply_markup=kb)
        return True
    except TelegramForbiddenError:
        await db.ex("UPDATE clients SET bot_blocked = 1 WHERE tg_id = ?", tg_id)
    except TelegramBadRequest as err:
        log.warning("send to %s failed: %s", tg_id, err)
    return False
