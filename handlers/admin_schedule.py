"""Барбер: графік роботи, день, дії із записом, закриття візиту (послуга → допродаж → чайові), блок часу."""
import re
from datetime import datetime, time, timedelta

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db
from cb import ApptCB, BlockSt, DayCB, Done, SaleCB, SchedCB, SchedSt
from handlers import admin_book, booking
from utils import (IsAdmin, appt, btn, day_hours, dts, e, fdate, find_overlap, k2d, now, parse_range,
                   parse_range_note, remind_flags, safe_edit, sdt, send_client, set_day_hours, to_int, today)
from views import (kb_book_again, kb_client_appt, render_appt, render_close_price, render_close_tips,
                   render_close_ups, render_day, render_sched, render_sched_day)

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


async def send_day(m: Message, d) -> None:
    text, kb = await render_day(d)
    await m.answer(text, reply_markup=kb)


async def send_sched(m: Message) -> None:
    text, kb = await render_sched(today())
    await m.answer(text, reply_markup=kb)


@router.callback_query(DayCB.filter(F.a == "v"))
async def day_view(cb: CallbackQuery, callback_data: DayCB, state: FSMContext):
    await state.clear()
    text, kb = await render_day(k2d(callback_data.day))
    await safe_edit(cb.message, text, kb)
    await cb.answer()


# ---------- графік роботи ----------

def _warn(appts) -> str:
    if not appts:
        return ""
    rows = "\n".join(f"• {fdate(sdt(a['start_at']).date())} {sdt(a['start_at']):%H:%M} — {e(a['cname'])}"
                     for a in appts)
    return f"⚠️ <b>Ці записи випадають за години роботи — перенеси або скасуй їх:</b>\n{rows}\n\n"


@router.callback_query(SchedCB.filter(F.a == "wk"))
async def sched_week(cb: CallbackQuery, callback_data: SchedCB, state: FSMContext):
    await state.clear()
    text, kb = await render_sched(k2d(callback_data.day))
    await safe_edit(cb.message, text, kb)
    await cb.answer()


@router.callback_query(SchedCB.filter(F.a == "d"))
async def sched_day(cb: CallbackQuery, callback_data: SchedCB, state: FSMContext):
    await state.clear()
    text, kb = await render_sched_day(k2d(callback_data.day))
    await safe_edit(cb.message, text, kb)
    await cb.answer()


@router.callback_query(SchedCB.filter(F.a == "set"))
async def sched_set(cb: CallbackQuery, callback_data: SchedCB):
    d = k2d(callback_data.day)
    v = callback_data.v
    rng = None if v == "off" else (time(int(v[:2]), int(v[2:4])), time(int(v[5:7]), int(v[7:9])))
    warn = await set_day_hours(d, rng)
    text, kb = await render_sched(d)
    await safe_edit(cb.message, _warn(warn) + text, kb)
    await cb.answer(f"{fdate(d)}: " + (f"{rng[0]:%H:%M}–{rng[1]:%H:%M}" if rng else "вихідний"))


@router.callback_query(SchedCB.filter(F.a == "cus"))
async def sched_custom(cb: CallbackQuery, callback_data: SchedCB, state: FSMContext):
    await state.clear()
    await state.set_state(SchedSt.custom)
    await state.update_data(day=callback_data.day)
    kb = InlineKeyboardBuilder()
    kb.row(btn("✖️ Скасувати", SchedCB(a="d", day=callback_data.day)))
    await safe_edit(cb.message, f"✍️ Години на <b>{fdate(k2d(callback_data.day))}</b>, наприклад "
                                "<code>10-19</code> або <code>09:30-18:00</code>", kb.as_markup())
    await cb.answer()


@router.message(SchedSt.custom, F.text)
async def sched_custom_input(m: Message, state: FSMContext):
    rng = parse_range(m.text)
    if not rng:
        await m.answer("Не зрозумів. Напиши так: <code>10-19</code> або <code>09:30-18:00</code>")
        return
    d = k2d((await state.get_data())["day"])
    await state.clear()
    warn = await set_day_hours(d, rng)
    text, kb = await render_sched(d)
    await m.answer(f"✅ {fdate(d)}: {rng[0]:%H:%M}–{rng[1]:%H:%M}\n\n" + _warn(warn) + text, reply_markup=kb)


@router.callback_query(SchedCB.filter(F.a == "copy"))
async def sched_copy(cb: CallbackQuery, callback_data: SchedCB):
    start = k2d(callback_data.day)
    warn = []
    for i in range(7):
        d = start + timedelta(days=i)
        if d < today():
            continue
        warn += await set_day_hours(d, await day_hours(d - timedelta(days=7)))
    text, kb = await render_sched(start)
    await safe_edit(cb.message, _warn(warn) + text, kb)
    await cb.answer("Скопійовано з минулого тижня")


@router.callback_query(DayCB.filter(F.a == "add"))
async def day_add(cb: CallbackQuery, callback_data: DayCB, state: FSMContext):
    await admin_book.start(cb.message, state, date=callback_data.day)
    await cb.answer()


# ---------- блок часу ----------

@router.callback_query(DayCB.filter(F.a == "blk"))
async def day_block(cb: CallbackQuery, callback_data: DayCB, state: FSMContext):
    await state.clear()
    await state.set_state(BlockSt.rng)
    await state.update_data(day=callback_data.day)
    kb = InlineKeyboardBuilder()
    kb.row(btn("✖️ Скасувати", "x"))
    await cb.message.answer(
        f"🔒 Блок часу на {fdate(k2d(callback_data.day))}.\n"
        "Введи проміжок і (за бажанням) коментар:\n<code>13:00-14:00 обід</code>",
        reply_markup=kb.as_markup(),
    )
    await cb.answer()


@router.message(BlockSt.rng, F.text)
async def block_input(m: Message, state: FSMContext):
    r = parse_range_note(m.text)
    if not r:
        await m.answer("Формат: <code>13:00-14:00 обід</code>")
        return
    d = k2d((await state.get_data())["day"])
    start, end = datetime.combine(d, r[0]), datetime.combine(d, r[1])
    conflict = await find_overlap(start, end)
    if conflict:
        s = sdt(conflict["start_at"])
        await m.answer(f"⚠️ У цей проміжок вже є запис о {s:%H:%M} ({e(conflict['cname']) or 'блок'}). "
                       "Спершу перенеси або скасуй його.")
        return
    await db.ex(
        "INSERT INTO appointments(start_at, end_at, status, created_by, note, reminded_24, reminded_2, created_at) "
        "VALUES(?, ?, 'block', 'admin', ?, 1, 1, ?)", dts(start), dts(end), r[2] or None, dts(now()),
    )
    await state.clear()
    await send_day(m, d)


# ---------- картка запису ----------

async def _load(cb: CallbackQuery, aid: int):
    a = await appt(aid)
    if not a:
        await cb.answer("Запис не знайдено", show_alert=True)
    return a


async def _refresh(cb: CallbackQuery, aid: int, prefix: str = "") -> None:
    text, kb = await render_appt(await appt(aid))
    await safe_edit(cb.message, prefix + text, kb)


@router.callback_query(ApptCB.filter(F.a == "v"))
async def appt_view(cb: CallbackQuery, callback_data: ApptCB, state: FSMContext):
    await state.clear()
    if await _load(cb, callback_data.id):
        await _refresh(cb, callback_data.id)
        await cb.answer()


@router.callback_query(ApptCB.filter(F.a == "cf"))
async def appt_confirm(cb: CallbackQuery, callback_data: ApptCB, bot: Bot):
    a = await _load(cb, callback_data.id)
    if not a:
        return
    if a["status"] != "pending":
        await cb.answer("Цей запис уже оброблено", show_alert=True)
        await _refresh(cb, a["id"])
        return
    r24, r2 = remind_flags(sdt(a["start_at"]))
    await db.ex("UPDATE appointments SET status = 'confirmed', reminded_24 = ?, reminded_2 = ? WHERE id = ?",
                r24, r2, a["id"])
    await send_client(
        bot, a["ctg"],
        f"✅ <b>Запис підтверджено!</b>\n\n✂️ {e(a['sname'])}\n📅 {fdate(sdt(a['start_at']).date())}, "
        f"{sdt(a['start_at']):%H:%M}\n\nЧекаємо на вас 💈",
        kb_client_appt(a["id"]),
    )
    await _refresh(cb, a["id"])
    await cb.answer("Підтверджено ✅")


@router.callback_query(ApptCB.filter(F.a == "rj"))
async def appt_reject(cb: CallbackQuery, callback_data: ApptCB, bot: Bot):
    a = await _load(cb, callback_data.id)
    if not a:
        return
    if a["status"] != "pending":
        await cb.answer("Цей запис уже оброблено", show_alert=True)
        await _refresh(cb, a["id"])
        return
    await db.ex("UPDATE appointments SET status = 'cancelled' WHERE id = ?", a["id"])
    s = sdt(a["start_at"])
    await send_client(
        bot, a["ctg"],
        f"😔 На жаль, барбер не зможе прийняти вас {fdate(s.date())} о {s:%H:%M}.\nОберіть, будь ласка, інший час:",
        kb_book_again(),
    )
    await _refresh(cb, a["id"])
    await cb.answer("Відхилено")


@router.callback_query(ApptCB.filter(F.a == "cx"))
async def appt_cancel_ask(cb: CallbackQuery, callback_data: ApptCB):
    kb = InlineKeyboardBuilder()
    kb.row(btn("Так, скасувати", ApptCB(a="cxy", id=callback_data.id)),
           btn("Ні", ApptCB(a="v", id=callback_data.id)))
    await cb.message.edit_reply_markup(reply_markup=kb.as_markup())
    await cb.answer("Точно скасувати?")


@router.callback_query(ApptCB.filter(F.a == "cxy"))
async def appt_cancel(cb: CallbackQuery, callback_data: ApptCB, bot: Bot):
    a = await _load(cb, callback_data.id)
    if not a:
        return
    await db.ex("UPDATE appointments SET status = 'cancelled' WHERE id = ?", a["id"])
    s = sdt(a["start_at"])
    if s > now():
        await send_client(
            bot, a["ctg"],
            f"❌ Ваш запис на {fdate(s.date())} о {s:%H:%M} скасовано барбером.\nМожна обрати інший час:",
            kb_book_again(),
        )
    text, kb = await render_day(s.date())
    await safe_edit(cb.message, "❌ Запис скасовано.\n\n" + text, kb)
    await cb.answer("Скасовано")


@router.callback_query(ApptCB.filter(F.a == "ns"))
async def appt_no_show(cb: CallbackQuery, callback_data: ApptCB):
    if await _load(cb, callback_data.id):
        await db.ex("UPDATE appointments SET status = 'no_show' WHERE id = ?", callback_data.id)
        await _refresh(cb, callback_data.id)
        await cb.answer("Позначено: не прийшов")


@router.callback_query(ApptCB.filter(F.a == "ub"))
async def appt_unblock(cb: CallbackQuery, callback_data: ApptCB):
    a = await _load(cb, callback_data.id)
    if not a:
        return
    await db.ex("UPDATE appointments SET status = 'cancelled' WHERE id = ?", a["id"])
    text, kb = await render_day(sdt(a["start_at"]).date())
    await safe_edit(cb.message, text, kb)
    await cb.answer("Блок знято")


@router.callback_query(ApptCB.filter(F.a == "rs"))
async def appt_resched(cb: CallbackQuery, callback_data: ApptCB, state: FSMContext):
    a = await _load(cb, callback_data.id)
    if a:
        await booking.start_resched(cb.message, state, "admin_resched", a, edit=False)
        await cb.answer()


# ---------- закриття візиту: 1) послуга 2) допродаж 3) чайові ----------
# Кнопки кроків несуть id запису, тому працюють і після перезапуску бота; текстовий ввід — через стан.

_STEPS = {Done.price: render_close_price, Done.ups: render_close_ups, Done.tips: render_close_tips}


async def _step(msg: Message, state: FSMContext, aid: int, st, edit: bool) -> None:
    await state.clear()
    await state.set_state(st)
    await state.update_data(appt_id=aid)
    text, kb = await _STEPS[st](await appt(aid))
    if edit:
        await safe_edit(msg, text, kb)
    else:
        await msg.answer(text, reply_markup=kb)


@router.callback_query(ApptCB.filter(F.a == "done"))
async def appt_done(cb: CallbackQuery, callback_data: ApptCB, state: FSMContext):
    if await _load(cb, callback_data.id):
        await _step(cb.message, state, callback_data.id, Done.price, edit=True)
        await cb.answer()


async def _set_price(msg: Message, state: FSMContext, aid: int, price: int, edit: bool) -> None:
    await db.ex("UPDATE appointments SET status = 'done', price = ?, completed_at = COALESCE(completed_at, ?) "
                "WHERE id = ?", price, dts(now()), aid)
    await _step(msg, state, aid, Done.ups, edit)


@router.callback_query(SaleCB.filter(F.a == "price"))
async def close_price_btn(cb: CallbackQuery, callback_data: SaleCB, state: FSMContext):
    await _set_price(cb.message, state, callback_data.ap, callback_data.it, edit=True)
    await cb.answer()


@router.message(Done.price, F.text)
async def close_price_text(m: Message, state: FSMContext):
    price = to_int(m.text)
    if price is None:
        await m.answer("Напиши суму числом, наприклад 700")
        return
    await _set_price(m, state, (await state.get_data())["appt_id"], price, edit=False)


async def _add_sale(aid: int, name: str, price: int) -> None:
    await db.ex("INSERT INTO sales(appointment_id, item_name, price, created_at) VALUES(?, ?, ?, ?)",
                aid, name, price, dts(now()))


@router.callback_query(SaleCB.filter(F.a == "add"))
async def close_ups_btn(cb: CallbackQuery, callback_data: SaleCB, state: FSMContext):
    it = await db.q1("SELECT * FROM upsell_items WHERE id = ?", callback_data.it)
    if not it:
        await cb.answer("Позицію не знайдено", show_alert=True)
        return
    await _add_sale(callback_data.ap, it["name"], it["price"])
    await _step(cb.message, state, callback_data.ap, Done.ups, edit=True)
    await cb.answer(f"+ {it['name']}")


@router.message(Done.ups, F.text)
async def close_ups_text(m: Message, state: FSMContext):
    mt = re.fullmatch(r"\s*(.*?)[\s;,:–-]*(\d+)\s*(?:грн\.?)?\s*", m.text)
    if not mt:
        await m.answer("Напиши назву і суму, наприклад: <code>укладка 600</code>")
        return
    name = mt[1].strip()[:60] or "Допродаж"
    await _add_sale((await state.get_data())["appt_id"], name[0].upper() + name[1:], int(mt[2]))
    await _step(m, state, (await state.get_data())["appt_id"], Done.ups, edit=False)


@router.callback_query(SaleCB.filter(F.a == "undo"))
async def close_ups_undo(cb: CallbackQuery, callback_data: SaleCB, state: FSMContext):
    last = await db.q1("SELECT id FROM sales WHERE appointment_id = ? ORDER BY id DESC LIMIT 1", callback_data.ap)
    if last:
        await db.ex("DELETE FROM sales WHERE id = ?", last["id"])
    await _step(cb.message, state, callback_data.ap, Done.ups, edit=True)
    await cb.answer("Прибрано")


@router.callback_query(SaleCB.filter(F.a == "next"))
async def close_ups_next(cb: CallbackQuery, callback_data: SaleCB, state: FSMContext):
    await _step(cb.message, state, callback_data.ap, Done.tips, edit=True)
    await cb.answer()


async def _set_tips(msg: Message, state: FSMContext, aid: int, tips: int, edit: bool) -> None:
    await db.ex("UPDATE appointments SET tips = ? WHERE id = ?", tips, aid)
    await state.clear()
    text, kb = await render_appt(await appt(aid))
    text = "✅ <b>Візит закрито</b>\n\n" + text
    if edit:
        await safe_edit(msg, text, kb)
    else:
        await msg.answer(text, reply_markup=kb)


@router.callback_query(SaleCB.filter(F.a == "tip"))
async def close_tips_btn(cb: CallbackQuery, callback_data: SaleCB, state: FSMContext):
    await _set_tips(cb.message, state, callback_data.ap, callback_data.it, edit=True)
    await cb.answer("Збережено ✅")


@router.message(Done.tips, F.text)
async def close_tips_text(m: Message, state: FSMContext):
    tips = to_int(m.text)
    if tips is None:
        await m.answer("Напиши суму чайових числом, наприклад 100, або натисни «Не було»")
        return
    await _set_tips(m, state, (await state.get_data())["appt_id"], tips, edit=False)
