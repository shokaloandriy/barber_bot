"""Фонові задачі: нагадування перед візитом, «пора на стрижку», ранковий і вечірній звіти.

Простий цикл раз на хвилину. Дата останнього запуску щоденних задач зберігається в БД,
тож після рестарту на Railway нічого не дублюється і не губиться.
"""
import asyncio
import logging
from datetime import timedelta

from aiogram import Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db
from cb import ApptCB
from config import ADMIN_IDS
from utils import (APPT_SQL, btn, day_hours, dts, due_clients, e, fdate, notify_admins, now, parse_time, rel_day,
                   sdt, send_client, today)
from views import kb_client_appt, render_day

log = logging.getLogger(__name__)


async def visit_reminders(bot: Bot) -> None:
    n = now()
    info = await db.get("info_text")
    if await db.get_int("remind_24", 1):
        rows = await db.q(
            APPT_SQL + " WHERE a.status = 'confirmed' AND a.reminded_24 = 0 AND a.start_at <= ? AND a.start_at > ?",
            dts(n + timedelta(hours=24)), dts(n),
        )
        for a in rows:
            s = sdt(a["start_at"])
            if s - n > timedelta(hours=3):
                await send_client(
                    bot, a["ctg"],
                    f"🔔 Нагадую про запис <b>{rel_day(s.date())} о {s:%H:%M}</b>\n✂️ {e(a['sname'])}\n\n"
                    "Якщо плани змінились — перенесіть або скасуйте, будь ласка, щоб звільнити час іншим 🙏",
                    kb_client_appt(a["id"], with_ok=True),
                )
            await db.ex("UPDATE appointments SET reminded_24 = 1 WHERE id = ?", a["id"])
    if await db.get_int("remind_2", 1):
        rows = await db.q(
            APPT_SQL + " WHERE a.status = 'confirmed' AND a.reminded_2 = 0 AND a.start_at <= ? AND a.start_at > ?",
            dts(n + timedelta(hours=2)), dts(n),
        )
        for a in rows:
            s = sdt(a["start_at"])
            await send_client(bot, a["ctg"],
                              f"⏰ Чекаємо вас сьогодні о <b>{s:%H:%M}</b> ✂️ {e(a['sname'])}\n\n{e(info)}")
            await db.ex("UPDATE appointments SET reminded_2 = 1 WHERE id = ?", a["id"])


async def haircut_reminders(bot: Bot) -> int:
    sent = 0
    for c, last, interval, overdue in await due_clients():
        if not c["tg_id"] or c["reminders_off"] or c["bot_blocked"] or c["tg_id"] in ADMIN_IDS:
            continue
        # одне нагадування на кожен «цикл» між візитами
        if c["last_reminder"] and c["last_reminder"] >= last.isoformat():
            continue
        days = (today() - last).days
        name = (c["name"] or "").split(" ")[0]
        kb = InlineKeyboardBuilder()
        kb.row(btn("✂️ Записатися", "c:book"))
        kb.row(btn("🔕 Не нагадувати", "c:roff"))
        ok = await send_client(
            bot, c["tg_id"],
            f"Привіт, {e(name)}! 👋\nЗ останньої стрижки минуло вже {days} дн. — саме час освіжитись ✂️\n\n"
            "Обирайте зручний час 👇",
            kb.as_markup(),
        )
        await db.ex("UPDATE clients SET last_reminder = ? WHERE id = ?", today().isoformat(), c["id"])
        sent += ok
        await asyncio.sleep(0.05)
    if sent:
        await notify_admins(bot, f"🔔 Надіслано нагадувань «пора на стрижку»: {sent}")
    return sent


async def morning_digest(bot: Bot) -> None:
    text, kb = await render_day(today())
    pending = await db.q1(
        "SELECT COUNT(*) n FROM appointments WHERE status = 'pending' AND start_at >= ?", dts(now())
    )
    if pending["n"]:
        text += f"\n\n⏳ Непідтверджених заявок: <b>{pending['n']}</b>"
    if not any([await day_hours(today() + timedelta(days=i)) for i in range(1, 8)]):
        text += "\n\n⚠️ На наступні 7 днів не відкрито жодного робочого дня — клієнти не можуть записатись. " \
                "Відкрий дні в «🗓 Графік роботи»."
    await notify_admins(bot, "☀️ <b>Доброго ранку!</b>\n\n" + text, kb)


async def evening_digest(bot: Bot) -> None:
    rows = await db.q(
        APPT_SQL + " WHERE a.status IN ('confirmed','pending') AND a.end_at <= ? AND a.start_at >= ? "
        "ORDER BY a.start_at",
        dts(now()), dts(now() - timedelta(days=3)),
    )
    if not rows:
        return
    kb = InlineKeyboardBuilder()
    lines = ["🌙 <b>Незакриті візити</b>", "Закрий їх, щоб фінанси й нагадування були точними:", ""]
    for a in rows:
        s = sdt(a["start_at"])
        lines.append(f"• {fdate(s.date())} {s:%H:%M} — {e(a['cname'])}, {e(a['sname'])}")
        kb.button(text=f"{s:%d.%m %H:%M} {(a['cname'] or '')[:12]}", callback_data=ApptCB(a="v", id=a["id"]))
    kb.adjust(2)
    await notify_admins(bot, "\n".join(lines), kb.as_markup())


DAILY = [
    ("morning", "morning_time", morning_digest),
    ("haircut", "haircut_time", haircut_reminders),
    ("evening", "evening_time", evening_digest),
]


async def tick(bot: Bot) -> None:
    await visit_reminders(bot)
    n = now()
    key = n.date().isoformat()
    for job, time_key, fn in DAILY:
        t = parse_time(await db.get(time_key))
        if t and n.time() >= t and await db.get(f"last_{job}") != key:
            await db.put(f"last_{job}", key)
            await fn(bot)


async def run(bot: Bot) -> None:
    while True:
        try:
            await tick(bot)
        except Exception:  # noqa: BLE001
            log.exception("scheduler tick failed")
        await asyncio.sleep(60)
