"""Барбер: виручка, допродаж, середній чек, конверсія, неявки."""
from collections import defaultdict
from datetime import date, timedelta

from aiogram import Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db
from cb import FinCB
from utils import IsAdmin, e, fdate, money, safe_edit, sdt, today

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

PERIODS = [("d", "Сьогодні"), ("y", "Вчора"), ("w", "Тиждень"), ("m", "Місяць"), ("pm", "Мин. місяць"),
           ("30", "30 днів")]


def period(p: str) -> tuple[date, date, str]:
    t = today()
    if p == "y":
        y = t - timedelta(days=1)
        return y, y, "Вчора"
    if p == "w":
        start = t - timedelta(days=t.weekday())
        return start, start + timedelta(days=6), "Цей тиждень"
    if p == "m":
        start = t.replace(day=1)
        nxt = (start + timedelta(days=32)).replace(day=1)
        return start, nxt - timedelta(days=1), "Цей місяць"
    if p == "pm":
        end = t.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end, "Минулий місяць"
    if p == "30":
        return t - timedelta(days=29), t, "Останні 30 днів"
    return t, t, "Сьогодні"


def _kb(active: str):
    kb = InlineKeyboardBuilder()
    for code, label in PERIODS:
        kb.button(text=("• " if code == active else "") + label, callback_data=FinCB(p=code))
    kb.adjust(3)
    return kb.as_markup()


async def report(p: str) -> str:
    d1, d2, title = period(p)
    lo, hi = f"{d1.isoformat()} 00:00", f"{(d2 + timedelta(days=1)).isoformat()} 00:00"
    done = await db.q(
        "SELECT a.id, a.price, a.start_at, s.name sname FROM appointments a "
        "LEFT JOIN services s ON s.id = a.service_id "
        "WHERE a.status = 'done' AND a.start_at >= ? AND a.start_at < ?", lo, hi,
    )
    sales = await db.q(
        "SELECT sa.appointment_id, sa.item_name, sa.price FROM sales sa "
        "JOIN appointments a ON a.id = sa.appointment_id "
        "WHERE a.status = 'done' AND a.start_at >= ? AND a.start_at < ?", lo, hi,
    )
    other = await db.q(
        "SELECT status, COUNT(*) n FROM appointments WHERE start_at >= ? AND start_at < ? "
        "AND status IN ('no_show', 'cancelled') GROUP BY status", lo, hi,
    )
    new_clients = await db.q1("SELECT COUNT(*) n FROM clients WHERE created_at >= ? AND created_at < ?", lo, hi)

    period_txt = f"{d1:%d.%m}" if d1 == d2 else f"{d1:%d.%m} – {d2:%d.%m}"
    lines = [f"💰 <b>{title}</b> ({period_txt})", ""]
    n = len(done)
    svc = sum(a["price"] or 0 for a in done)
    ups = sum(s["price"] for s in sales)
    total = svc + ups
    if not n:
        lines.append("Закритих візитів немає.")
    else:
        with_ups = len({s["appointment_id"] for s in sales})
        lines += [
            f"💵 <b>Виручка: {money(total)}</b>",
            f"   ✂️ послуги: {money(svc)}",
            f"   🛍 допродаж: {money(ups)} ({round(ups / total * 100) if total else 0}%)",
            "",
            f"👥 Клієнтів: {n} · середній чек: {money(total / n)}",
            f"🛍 Купили щось додатково: {with_ups} з {n} ({round(with_ups / n * 100)}%)",
        ]
    st = {r["status"]: r["n"] for r in other}
    if st.get("no_show") or st.get("cancelled"):
        lines.append(f"🚫 Неявок: {st.get('no_show', 0)} · ❌ скасувань: {st.get('cancelled', 0)}")
    lines.append(f"🆕 Нових клієнтів у базі: {new_clients['n']}")

    if n:
        by_svc = defaultdict(lambda: [0, 0])
        for a in done:
            by_svc[a["sname"] or "—"][0] += 1
            by_svc[a["sname"] or "—"][1] += a["price"] or 0
        lines += ["", "<b>Послуги:</b>"]
        for name, (cnt, s) in sorted(by_svc.items(), key=lambda x: -x[1][1]):
            lines.append(f" • {e(name)} — {cnt} шт · {money(s)}")
        if sales:
            by_item = defaultdict(lambda: [0, 0])
            for s in sales:
                by_item[s["item_name"]][0] += 1
                by_item[s["item_name"]][1] += s["price"]
            lines += ["", "<b>Допродаж:</b>"]
            for name, (cnt, s) in sorted(by_item.items(), key=lambda x: -x[1][1])[:8]:
                lines.append(f" • {e(name)} — {cnt} шт · {money(s)}")
        if d1 != d2:
            by_day = defaultdict(lambda: [0, 0])
            ups_by_appt = defaultdict(int)
            for s in sales:
                ups_by_appt[s["appointment_id"]] += s["price"]
            for a in done:
                d = sdt(a["start_at"]).date()
                by_day[d][0] += 1
                by_day[d][1] += (a["price"] or 0) + ups_by_appt[a["id"]]
            lines += ["", "<b>По днях:</b>"]
            for d in sorted(by_day):
                cnt, s = by_day[d]
                lines.append(f" {fdate(d)} — {cnt} кл · {money(s)}")
    return "\n".join(lines)


async def send(m: Message) -> None:
    await m.answer(await report("d"), reply_markup=_kb("d"))


@router.callback_query(FinCB.filter())
async def switch(cb: CallbackQuery, callback_data: FinCB):
    await safe_edit(cb.message, await report(callback_data.p), _kb(callback_data.p))
    await cb.answer()
