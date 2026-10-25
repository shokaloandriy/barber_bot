"""Спільний потік вибору послуги → дати → часу.

flow у state data:
  client_new     — клієнт записується сам (статус pending, барбер підтверджує)
  client_resched — клієнт переносить свій запис (знову pending)
  admin_new      — барбер записує клієнта (одразу confirmed)
  admin_resched  — барбер переносить запис
"""
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db
from cb import Pick, PickDate, PickTime, SvcPick
from keyboards import CLIENT_MENU
from utils import (appt, btn, card_short, client_by_tg, create_appt, d2k, day_hours, dts, e, ensure_client,
                   fdate, find_overlap, free_slots, is_admin, k2d, money, notify_admins, now, parse_day,
                   parse_time, remind_flags, safe_edit, sdt, send_client, today)
from views import kb_client_appt, kb_confirm, render_appt

router = Router()


def _admin_flow(data: dict) -> bool:
    return data.get("flow", "").startswith("admin")


async def _show(msg: Message, text: str, kb, edit: bool) -> None:
    if edit:
        await safe_edit(msg, text, kb)
    else:
        await msg.answer(text, reply_markup=kb)


# ---------- точки входу ----------

async def start_new(msg: Message, state: FSMContext, flow: str, edit: bool = False,
                    highlight: int | None = None, **extra) -> None:
    await state.clear()
    await state.update_data(flow=flow, **extra)
    rows = await db.q("SELECT * FROM services WHERE active = 1 ORDER BY sort, id")
    if not rows:
        await _show(msg, "Послуг ще немає. Барбер має додати їх у ⚙️ Налаштування → ✂️ Послуги.", None, edit)
        return
    kb = InlineKeyboardBuilder()
    for s in rows:
        star = "⭐ " if s["id"] == highlight else ""
        kb.button(text=f"{star}{s['name']} · {s['price']} грн · {s['duration']} хв", callback_data=SvcPick(id=s["id"]))
    kb.adjust(1)
    kb.row(btn("✖️ Скасувати", "x"))
    head = f"👤 <b>{e(extra['client_name'])}</b>\n" if extra.get("client_name") else ""
    await _show(msg, head + "✂️ Оберіть послугу:", kb.as_markup(), edit)


async def start_resched(msg: Message, state: FSMContext, flow: str, a, edit: bool = True) -> None:
    s, en = sdt(a["start_at"]), sdt(a["end_at"])
    await state.clear()
    await state.update_data(
        flow=flow, appt_id=a["id"], service_id=a["service_id"], sname=a["sname"],
        price=a["sprice"], duration=int((en - s).total_seconds() // 60),
    )
    await show_dates(msg, state, edit=edit)


@router.callback_query(SvcPick.filter())
async def on_service(cb: CallbackQuery, callback_data: SvcPick, state: FSMContext):
    data = await state.get_data()
    if "flow" not in data:
        if is_admin(cb.from_user.id):
            await cb.answer("Почни запис заново через ➕ Запис", show_alert=True)
            return
        data = {"flow": "client_new"}
    s = await db.q1("SELECT * FROM services WHERE id = ? AND active = 1", callback_data.id)
    if not s:
        await cb.answer("Ця послуга вже недоступна", show_alert=True)
        return
    data.update(service_id=s["id"], duration=s["duration"], price=s["price"], sname=s["name"])
    await state.set_data(data)
    if data.get("date"):
        await show_times(cb.message, state, edit=True)
    else:
        await show_dates(cb.message, state, edit=True)
    await cb.answer()


# ---------- дата ----------

async def show_dates(msg: Message, state: FSMContext, edit: bool = True) -> None:
    data = await state.get_data()
    admin = _admin_flow(data)
    days = await db.get_int("booking_days", 14)
    lead = 0 if admin else await db.get_int("min_lead_min", 60)
    kb = InlineKeyboardBuilder()
    found = 0
    for i in range(days):
        d = today() + timedelta(days=i)
        if admin:
            label = fdate(d) + ("" if await day_hours(d) else " 💤")
            kb.button(text=label, callback_data=PickDate(day=d2k(d)))
            found += 1
        elif await free_slots(d, data["duration"], data.get("appt_id"), lead):
            kb.button(text=fdate(d), callback_data=PickDate(day=d2k(d)))
            found += 1
    kb.adjust(3)
    if admin:
        kb.row(btn("✍️ Інша дата", "pd_manual"))
    kb.row(btn("✖️ Скасувати", "x"))
    text = f"✂️ <b>{e(data['sname'])}</b> · {data['duration']} хв\n\n"
    if found:
        text += "📅 Оберіть дату:"
    else:
        text += (f"😔 На найближчі {days} днів вільних вікон немає.\n"
                 "Напишіть барберу напряму — контакти в меню «📍 Контакти».")
    await state.set_state(Pick.date)
    await _show(msg, text, kb.as_markup(), edit)


@router.callback_query(Pick.date, PickDate.filter())
async def on_date(cb: CallbackQuery, callback_data: PickDate, state: FSMContext):
    await state.update_data(date=callback_data.day)
    await show_times(cb.message, state, edit=True)
    await cb.answer()


@router.callback_query(Pick.date, F.data == "pd_manual")
async def on_manual_date(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Pick.manual_date)
    await cb.message.answer("Введи дату у форматі ДД.ММ (наприклад, 31.10):")
    await cb.answer()


@router.message(Pick.manual_date, F.text)
async def on_manual_date_text(m: Message, state: FSMContext):
    d = parse_day(m.text)
    if not d:
        await m.answer("Не зрозумів дату. Формат: 31.10 або 31.10.2026")
        return
    await state.update_data(date=d2k(d))
    await show_times(m, state, edit=False)


@router.callback_query(StateFilter(Pick.time, Pick.confirm, Pick.manual_time), F.data == "pd_back")
async def on_back_to_dates(cb: CallbackQuery, state: FSMContext):
    await show_dates(cb.message, state, edit=True)
    await cb.answer()


# ---------- час ----------

async def show_times(msg: Message, state: FSMContext, edit: bool = True) -> None:
    data = await state.get_data()
    admin = _admin_flow(data)
    d = k2d(data["date"])
    lead = 0 if admin else await db.get_int("min_lead_min", 60)
    slots = await free_slots(d, data["duration"], data.get("appt_id"), lead)
    hours = await day_hours(d)
    kb = InlineKeyboardBuilder()
    for s in slots:
        kb.button(text=s, callback_data=PickTime(t=s.replace(":", "")))
    kb.adjust(4)
    if admin:
        kb.row(btn("✍️ Свій час", "pt_manual"))
    kb.row(btn("⬅️ Інша дата", "pd_back"), btn("✖️ Скасувати", "x"))
    text = f"✂️ <b>{e(data['sname'])}</b> · {fdate(d)}\n"
    if hours:
        text += f"🕘 Робочі години: {hours[0]:%H:%M}–{hours[1]:%H:%M}\n\n"
    else:
        text += "💤 Цей день — вихідний.\n\n"
    if slots:
        text += "🕐 Оберіть час:"
    elif admin:
        text += "Вільних слотів немає — можна вказати свій час."
    else:
        text += "На цей день вільного часу вже немає. Оберіть іншу дату."
    await state.set_state(Pick.time)
    await _show(msg, text, kb.as_markup(), edit)


@router.callback_query(Pick.time, PickTime.filter())
async def on_time(cb: CallbackQuery, callback_data: PickTime, state: FSMContext, bot: Bot):
    t = callback_data.t
    await state.update_data(time=f"{t[:2]}:{t[2:]}")
    await _proceed(cb.message, state, cb.from_user, bot, edit=True)
    await cb.answer()


@router.callback_query(Pick.time, F.data == "pt_manual")
async def on_manual_time(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Pick.manual_time)
    await cb.message.answer("Введи час початку, наприклад 18:30:")
    await cb.answer()


@router.message(Pick.manual_time, F.text)
async def on_manual_time_text(m: Message, state: FSMContext, bot: Bot):
    t = parse_time(m.text)
    if not t:
        await m.answer("Не зрозумів час. Формат: 18:30")
        return
    await state.update_data(time=t.strftime("%H:%M"))
    await _proceed(m, state, m.from_user, bot, edit=False)


@router.callback_query(Pick.confirm, F.data == "pt_back")
async def on_back_to_times(cb: CallbackQuery, state: FSMContext):
    await show_times(cb.message, state, edit=True)
    await cb.answer()


# ---------- підтвердження і збереження ----------

def _bounds(data: dict) -> tuple[datetime, datetime]:
    start = datetime.combine(k2d(data["date"]), parse_time(data["time"]))
    return start, start + timedelta(minutes=data["duration"])


async def _conflict_msg(msg: Message, state: FSMContext, data: dict, conflict) -> None:
    if _admin_flow(data):
        who = "блок" if conflict["status"] == "block" else (conflict["cname"] or "")
        s, en = sdt(conflict["start_at"]), sdt(conflict["end_at"])
        await msg.answer(f"⚠️ Перетин із записом {s:%H:%M}–{en:%H:%M} {e(who)}. Обери інший час.")
    else:
        await msg.answer("⚠️ Цей час щойно зайняли. Оберіть інший:")
    await show_times(msg, state, edit=False)


async def _proceed(msg: Message, state: FSMContext, user, bot: Bot, edit: bool) -> None:
    data = await state.get_data()
    start, end = _bounds(data)
    conflict = await find_overlap(start, end, data.get("appt_id"))
    if conflict:
        await _conflict_msg(msg, state, data, conflict)
        return
    if _admin_flow(data):
        await _finalize(msg, state, user, bot)
        return
    lead = await db.get_int("min_lead_min", 60)
    if start < now() + timedelta(minutes=lead):
        await msg.answer("⏱ На цей час уже пізно записатися. Оберіть інший:")
        await show_times(msg, state, edit=False)
        return
    resched = data["flow"] == "client_resched"
    text = (("🔁 <b>Перенесення запису</b>\n\n" if resched else "<b>Перевірте запис:</b>\n\n")
            + f"✂️ {e(data['sname'])}\n📅 {fdate(start.date())}, {start:%H:%M}–{end:%H:%M}\n"
            + f"💵 {money(data.get('price'))}")
    kb = InlineKeyboardBuilder()
    kb.row(btn("✅ Підтвердити", "bk_ok"))
    kb.row(btn("⬅️ Змінити час", "pt_back"), btn("✖️ Скасувати", "x"))
    await state.set_state(Pick.confirm)
    await _show(msg, text, kb.as_markup(), edit)


@router.callback_query(Pick.confirm, F.data == "bk_ok")
async def on_confirm(cb: CallbackQuery, state: FSMContext, bot: Bot):
    await cb.message.edit_reply_markup(reply_markup=None)
    await _finalize(cb.message, state, cb.from_user, bot)
    await cb.answer()


async def _finalize(msg: Message, state: FSMContext, user, bot: Bot) -> None:
    data = await state.get_data()
    flow = data["flow"]
    start, end = _bounds(data)
    conflict = await find_overlap(start, end, data.get("appt_id"))
    if conflict:
        await _conflict_msg(msg, state, data, conflict)
        return
    when = f"{fdate(start.date())}, {start:%H:%M}–{end:%H:%M}"

    if flow == "client_new":
        c = await client_by_tg(user.id) or await ensure_client(user)
        aid = await create_appt(c["id"], data["service_id"], start, end, "pending", "client")
        await state.clear()
        await msg.answer(
            f"📨 <b>Заявку надіслано!</b>\n\n✂️ {e(data['sname'])}\n📅 {when}\n\n"
            "Барбер підтвердить запис — я одразу напишу вам 👌",
            reply_markup=CLIENT_MENU,
        )
        await notify_admins(bot, "🆕 <b>Нова заявка</b>\n\n" + card_short(await appt(aid)), kb_confirm(aid))

    elif flow == "client_resched":
        a = await appt(data["appt_id"])
        if not a or a["ctg"] != user.id or a["status"] not in ("pending", "confirmed"):
            await state.clear()
            await msg.answer("Цей запис уже неактивний.", reply_markup=CLIENT_MENU)
            return
        old = a["start_at"]
        r24, r2 = remind_flags(start)
        await db.ex(
            "UPDATE appointments SET start_at = ?, end_at = ?, status = 'pending', reminded_24 = ?, reminded_2 = ? "
            "WHERE id = ?", dts(start), dts(end), r24, r2, a["id"],
        )
        await state.clear()
        await msg.answer(f"🔁 Запит на перенесення надіслано.\n📅 Новий час: {when}\n\nЧекаємо підтвердження барбера.",
                         reply_markup=CLIENT_MENU)
        old_dt = sdt(old)
        await notify_admins(
            bot,
            f"🔁 <b>Клієнт переносить запис</b>\nБуло: {fdate(old_dt.date())}, {old_dt:%H:%M}\n\n"
            + card_short(await appt(a["id"])),
            kb_confirm(a["id"]),
        )

    elif flow == "admin_new":
        aid = await create_appt(data["client_id"], data["service_id"], start, end, "confirmed", "admin")
        await state.clear()
        a = await appt(aid)
        text, kb = await render_appt(a)
        await msg.answer("✅ <b>Записано!</b>\n\n" + text, reply_markup=kb)
        await send_client(bot, a["ctg"], f"✅ Вас записано до барбера:\n\n✂️ {e(a['sname'])}\n📅 {when}",
                          kb_client_appt(aid))

    elif flow == "admin_resched":
        a = await appt(data["appt_id"])
        if not a:
            await state.clear()
            await msg.answer("Запис не знайдено.")
            return
        old_dt = sdt(a["start_at"])
        status = "confirmed" if a["status"] in ("pending", "confirmed") else a["status"]
        r24, r2 = remind_flags(start)
        await db.ex(
            "UPDATE appointments SET start_at = ?, end_at = ?, status = ?, reminded_24 = ?, reminded_2 = ? "
            "WHERE id = ?", dts(start), dts(end), status, r24, r2, a["id"],
        )
        await state.clear()
        a = await appt(a["id"])
        text, kb = await render_appt(a)
        await msg.answer("🔁 <b>Перенесено</b>\n\n" + text, reply_markup=kb)
        await send_client(
            bot, a["ctg"],
            f"🔁 Ваш запис перенесено.\nБуло: {fdate(old_dt.date())}, {old_dt:%H:%M}\n"
            f"Тепер: <b>{when}</b>\n✂️ {e(a['sname'])}",
            kb_client_appt(a["id"]),
        )
