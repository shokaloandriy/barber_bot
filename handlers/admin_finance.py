"""Барбер: скільки заробив за тиждень і місяць — послуги, допродаж, чайові."""
from collections import defaultdict
from datetime import date, timedelta

from aiogram import Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db
from cb import FinCB
from utils import IsAdmin, btn, e, money, monday, safe_edit, today

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

MONTHS = ["січень", "лютий", "березень", "квітень", "травень", "червень",
          "липень", "серпень", "вересень", "жовтень", "листопад", "грудень"]


async def _block(title: str, d1: date, d2: date) -> list[str]:
    lo, hi = f"{d1.isoformat()} 00:00", f"{(d2 + timedelta(days=1)).isoformat()} 00:00"
    done = await db.q(
        "SELECT a.price, a.tips, s.name sname FROM appointments a LEFT JOIN services s ON s.id = a.service_id "
        "WHERE a.status = 'done' AND a.start_at >= ? AND a.start_at < ?", lo, hi,
    )
    sales = await db.q(
        "SELECT sa.item_name, sa.price FROM sales sa JOIN appointments a ON a.id = sa.appointment_id "
        "WHERE a.status = 'done' AND a.start_at >= ? AND a.start_at < ?", lo, hi,
    )
    svc = sum(a["price"] or 0 for a in done)
    ups = sum(s["price"] for s in sales)
    tips = sum(a["tips"] or 0 for a in done)
    lines = [f"<b>{title}</b> · {d1:%d.%m}–{d2:%d.%m}",
             f"💰 Заробив: <b>{money(svc + ups + tips)}</b> · клієнтів: {len(done)}"]
    if not done:
        return lines

    def group(rows, key, val):
        g = defaultdict(lambda: [0, 0])
        for r in rows:
            g[r[key] or "—"][0] += 1
            g[r[key] or "—"][1] += r[val] or 0
        return [f"      {e(k)} ×{n} — {money(v)}" for k, (n, v) in sorted(g.items(), key=lambda x: -x[1][1])]

    lines.append(f"   ✂️ Послуги: {money(svc)}")
    lines += group(done, "sname", "price")
    lines.append(f"   🛍 Допродаж: {money(ups)}")
    lines += group(sales, "item_name", "price")
    lines.append(f"   💸 Чайові: {money(tips)}")
    return lines


async def report(prev: bool) -> str:
    t = today()
    w1 = monday(t) - timedelta(days=7 if prev else 0)
    m1 = t.replace(day=1)
    if prev:
        m1 = (m1 - timedelta(days=1)).replace(day=1)
    m2 = (m1 + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    week = await _block("🗓 Минулий тиждень" if prev else "🗓 Цей тиждень", w1, w1 + timedelta(days=6))
    month = await _block(f"📆 {MONTHS[m1.month - 1].capitalize()} {m1.year}", m1, m2)
    return "\n".join(["💰 <b>Фінанси</b>", ""] + week + [""] + month)


def _kb(prev: bool):
    kb = InlineKeyboardBuilder()
    if prev:
        kb.row(btn("➡️ Поточний тиждень і місяць", FinCB(p="cur")))
    else:
        kb.row(btn("⬅️ Минулий тиждень і місяць", FinCB(p="prev")))
    return kb.as_markup()


async def send(m: Message) -> None:
    await m.answer(await report(False), reply_markup=_kb(False))


@router.callback_query(FinCB.filter())
async def switch(cb: CallbackQuery, callback_data: FinCB):
    prev = callback_data.p == "prev"
    await safe_edit(cb.message, await report(prev), _kb(prev))
    await cb.answer()
