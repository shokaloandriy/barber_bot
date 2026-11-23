"""Барбер: графік дня/тижня, дії із записом, закриття візиту з допродажем, блокування часу."""
import re
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db
from cb import ApptCB, BlockSt, DayCB, Done, SaleCB, WeekCB
from handlers import admin_book, booking
from utils import (IsAdmin, appt, btn, dts, e, fdate, find_overlap, k2d, money, now, parse_range_note,
                   remind_flags, safe_edit, sdt, send_client, to_int, today)
from views import kb_book_again, kb_client_appt, render_appt, render_day, render_upsell, render_week

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


async def send_day(m: Message, d) -> None:
    text, kb = await render_day(d)
    await m.answer(text, reply_markup=kb)


async def send_week(m: Message) -> None:
    t = today()
    text, kb = await render_week(t)
    await m.answer(text, reply_markup=kb)


@router.callback_query(DayCB.filter(F.a == "v"))
async def day_view(cb: CallbackQuery, callback_data: DayCB, state: FSMContext):
    await state.clear()
    text, kb = await render_day(k2d(callback_data.day))
    await safe_edit(cb.message, text, kb)
    await cb.answer()


@router.callback_query(WeekCB.filter())
async def week_view(cb: CallbackQuery, callback_data: WeekCB):
    text, kb = await render_week(k2d(callback_data.day))
    await safe_edit(cb.message, text, kb)
    await cb.answer()


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


# ---------- закриття візиту ----------

@router.callback_query(ApptCB.filter(F.a == "done"))
async def appt_done(cb: CallbackQuery, callback_data: ApptCB, state: FSMContext):
    a = await _load(cb, callback_data.id)
    if not a:
        return
    await state.clear()
    await state.set_state(Done.price)
    await state.update_data(appt_id=a["id"], sprice=a["sprice"] or 0)
    kb = InlineKeyboardBuilder()
    kb.row(btn(f"✅ {money(a['sprice'])}", "dp_ok"))
    kb.row(btn("✖️ Скасувати", "x"))
    await cb.message.answer(
        f"💈 Закриваємо візит: <b>{e(a['cname'])}</b>, {e(a['sname'])}\n\n"
        "Скільки взяв за послугу? Натисни кнопку або введи іншу суму числом.",
        reply_markup=kb.as_markup(),
    )
    await cb.answer()


async def _close_visit(msg: Message, state: FSMContext, price: int, edit: bool) -> None:
    aid = (await state.get_data())["appt_id"]
    await db.ex("UPDATE appointments SET status = 'done', price = ?, completed_at = ? WHERE id = ?",
                price, dts(now()), aid)
    await state.clear()
    text, kb = await render_upsell(await appt(aid))
    if edit:
        await safe_edit(msg, text, kb)
    else:
        await msg.answer(text, reply_markup=kb)


@router.callback_query(Done.price, F.data == "dp_ok")
async def done_default_price(cb: CallbackQuery, state: FSMContext):
    await _close_visit(cb.message, state, (await state.get_data())["sprice"], edit=True)
    await cb.answer()


@router.message(Done.price, F.text)
async def done_custom_price(m: Message, state: FSMContext):
    price = to_int(m.text)
    if price is None:
        await m.answer("Введи суму числом, наприклад 450")
        return
    await _close_visit(m, state, price, edit=False)


@router.callback_query(ApptCB.filter(F.a == "ups"))
async def upsell_open(cb: CallbackQuery, callback_data: ApptCB):
    a = await _load(cb, callback_data.id)
    if a:
        text, kb = await render_upsell(a)
        await safe_edit(cb.message, text, kb)
        await cb.answer()


@router.callback_query(SaleCB.filter(F.a == "add"))
async def upsell_add(cb: CallbackQuery, callback_data: SaleCB):
    it = await db.q1("SELECT * FROM upsell_items WHERE id = ?", callback_data.it)
    if not it:
        await cb.answer("Товар не знайдено", show_alert=True)
        return
    await db.ex("INSERT INTO sales(appointment_id, item_name, price, created_at) VALUES(?, ?, ?, ?)",
                callback_data.ap, it["name"], it["price"], dts(now()))
    text, kb = await render_upsell(await appt(callback_data.ap))
    await safe_edit(cb.message, text, kb)
    await cb.answer(f"+ {it['name']}")


@router.callback_query(SaleCB.filter(F.a == "undo"))
async def upsell_undo(cb: CallbackQuery, callback_data: SaleCB):
    last = await db.q1("SELECT id FROM sales WHERE appointment_id = ? ORDER BY id DESC LIMIT 1", callback_data.ap)
    if not last:
        await cb.answer("Нічого прибирати")
        return
    await db.ex("DELETE FROM sales WHERE id = ?", last["id"])
    text, kb = await render_upsell(await appt(callback_data.ap))
    await safe_edit(cb.message, text, kb)
    await cb.answer("Прибрано")


@router.callback_query(SaleCB.filter(F.a == "cus"))
async def upsell_custom(cb: CallbackQuery, callback_data: SaleCB, state: FSMContext):
    await state.clear()
    await state.set_state(Done.custom)
    await state.update_data(appt_id=callback_data.ap)
    await cb.message.answer("Введи назву і ціну, наприклад: <code>Пудра для обʼєму 320</code>")
    await cb.answer()


@router.message(Done.custom, F.text)
async def upsell_custom_input(m: Message, state: FSMContext):
    mt = re.fullmatch(r"\s*(.+?)[\s;,:–-]+(\d+)\s*(?:грн)?\s*", m.text)
    if not mt:
        await m.answer("Формат: <code>Назва 320</code>")
        return
    aid = (await state.get_data())["appt_id"]
    await db.ex("INSERT INTO sales(appointment_id, item_name, price, created_at) VALUES(?, ?, ?, ?)",
                aid, mt[1].strip(), int(mt[2]), dts(now()))
    await state.clear()
    text, kb = await render_upsell(await appt(aid))
    await m.answer(text, reply_markup=kb)


@router.callback_query(SaleCB.filter(F.a == "fin"))
async def upsell_finish(cb: CallbackQuery, callback_data: SaleCB):
    await _refresh(cb, callback_data.ap, prefix="✅ <b>Візит закрито</b>\n\n")
    await cb.answer("Збережено")
