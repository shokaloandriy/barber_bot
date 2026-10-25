"""Клієнт: запис, мої записи, перенесення/скасування, номер телефону, нагадування."""
from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db
from cb import MyCB, Reg
from handlers import booking
from keyboards import C_SKIP_PHONE, CLIENT_MENU, CONTACT_KB
from utils import (EMOJI, STATUS_TXT, appt, appt_line, btn, card_short, client_by_tg, dts, e, ensure_client,
                   link_phone, money, norm_phone, notify_admins, now, safe_edit)

router = Router()


# ---------- запис ----------

async def book_entry(msg: Message, state: FSMContext, user) -> None:
    c = await ensure_client(user)
    if not c["phone"]:
        await state.clear()
        await state.set_state(Reg.phone)
        await state.update_data(after="book")
        await msg.answer(
            "Щоб барбер міг звʼязатися з вами, поділіться номером телефону 👇\n"
            "(або просто напишіть його повідомленням)",
            reply_markup=CONTACT_KB,
        )
        return
    last = await db.q1(
        "SELECT service_id FROM appointments WHERE client_id = ? AND status = 'done' ORDER BY start_at DESC LIMIT 1",
        c["id"],
    )
    await booking.start_new(msg, state, "client_new", highlight=last["service_id"] if last else None)


@router.callback_query(F.data == "c:book")
async def book_cb(cb: CallbackQuery, state: FSMContext):
    await book_entry(cb.message, state, cb.from_user)
    await cb.answer()


@router.message(Reg.phone, F.text == C_SKIP_PHONE)
async def phone_skip(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Добре. Без номера записатися не вийде — повертайтесь, коли буде зручно 🙂",
                   reply_markup=CLIENT_MENU)


@router.message(Reg.phone, F.contact | F.text)
async def phone_input(m: Message, state: FSMContext):
    raw = m.contact.phone_number if m.contact else m.text
    if m.contact and m.contact.user_id and m.contact.user_id != m.from_user.id:
        await m.answer("Будь ласка, надішліть саме свій номер 🙏")
        return
    phone = norm_phone(raw)
    if not phone:
        await m.answer("Не схоже на номер телефону. Приклад: 0671234567")
        return
    c = await ensure_client(m.from_user)
    await link_phone(c, phone)
    after = (await state.get_data()).get("after")
    await state.clear()
    await m.answer("Дякую! 👍", reply_markup=CLIENT_MENU)
    if after == "book":
        await book_entry(m, state, m.from_user)


# ---------- мої записи ----------

async def my_list(msg: Message, user, edit: bool = False) -> None:
    c = await client_by_tg(user.id)
    rows = []
    if c:
        rows = await db.q(
            "SELECT a.*, s.name sname FROM appointments a LEFT JOIN services s ON s.id = a.service_id "
            "WHERE a.client_id = ? AND a.status IN ('pending','confirmed') AND a.start_at >= ? ORDER BY a.start_at",
            c["id"], dts(now()),
        )
    kb = InlineKeyboardBuilder()
    if not rows:
        kb.row(btn("✂️ Записатися", "c:book"))
        text = "У вас немає активних записів."
    else:
        lines = ["📋 <b>Ваші записи</b>", ""]
        for a in rows:
            lines.append(f"{EMOJI[a['status']]} {appt_line(a)} · {e(a['sname'])}")
            kb.button(text=f"{appt_line(a)}", callback_data=MyCB(a="v", id=a["id"]))
        lines += ["", "⏳ — чекає підтвердження барбера, 🟢 — підтверджено"]
        kb.adjust(1)
        text = "\n".join(lines)
    if edit:
        await safe_edit(msg, text, kb.as_markup())
    else:
        await msg.answer(text, reply_markup=kb.as_markup())


async def _own(cb: CallbackQuery, aid: int):
    a = await appt(aid)
    if not a or a["ctg"] != cb.from_user.id:
        await cb.answer("Запис не знайдено", show_alert=True)
        return None
    if a["status"] not in ("pending", "confirmed") or a["start_at"] < dts(now()):
        await cb.answer("Цей запис уже неактивний", show_alert=True)
        return None
    return a


@router.callback_query(MyCB.filter(F.a == "list"))
async def my_list_cb(cb: CallbackQuery):
    await my_list(cb.message, cb.from_user, edit=True)
    await cb.answer()


@router.callback_query(MyCB.filter(F.a == "v"))
async def my_view(cb: CallbackQuery, callback_data: MyCB):
    a = await _own(cb, callback_data.id)
    if not a:
        return
    kb = InlineKeyboardBuilder()
    kb.row(btn("🔁 Перенести", MyCB(a="rs", id=a["id"])), btn("❌ Скасувати", MyCB(a="cx", id=a["id"])))
    kb.row(btn("⬅️ Мої записи", MyCB(a="list")))
    text = (f"{EMOJI[a['status']]} <b>{appt_line(a)}</b>\n✂️ {e(a['sname'])} · {money(a['sprice'])}\n"
            f"Статус: {STATUS_TXT[a['status']]}")
    await safe_edit(cb.message, text, kb.as_markup())
    await cb.answer()


@router.callback_query(MyCB.filter(F.a == "cx"))
async def my_cancel_ask(cb: CallbackQuery, callback_data: MyCB):
    a = await _own(cb, callback_data.id)
    if not a:
        return
    kb = InlineKeyboardBuilder()
    kb.row(btn("Так, скасувати", MyCB(a="cxy", id=a["id"])), btn("Ні", MyCB(a="v", id=a["id"])))
    await safe_edit(cb.message, f"Скасувати запис <b>{appt_line(a)}</b>?", kb.as_markup())
    await cb.answer()


@router.callback_query(MyCB.filter(F.a == "cxy"))
async def my_cancel(cb: CallbackQuery, callback_data: MyCB, bot: Bot):
    a = await _own(cb, callback_data.id)
    if not a:
        return
    await db.ex("UPDATE appointments SET status = 'cancelled' WHERE id = ?", a["id"])
    kb = InlineKeyboardBuilder()
    kb.row(btn("✂️ Записатися на інший час", "c:book"))
    await safe_edit(cb.message, "❌ Запис скасовано.", kb.as_markup())
    await notify_admins(bot, "❌ <b>Клієнт скасував запис</b>\n\n" + card_short(a))
    await cb.answer()


@router.callback_query(MyCB.filter(F.a == "rs"))
async def my_resched(cb: CallbackQuery, callback_data: MyCB, state: FSMContext):
    a = await _own(cb, callback_data.id)
    if not a:
        return
    await booking.start_resched(cb.message, state, "client_resched", a, edit=True)
    await cb.answer()


@router.callback_query(MyCB.filter(F.a == "ok"))
async def my_ok(cb: CallbackQuery, callback_data: MyCB):
    await cb.answer("Чекаємо на вас! 💈")
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass


# ---------- нагадування ----------

@router.callback_query(F.data == "c:roff")
async def reminders_off(cb: CallbackQuery):
    await db.ex("UPDATE clients SET reminders_off = 1 WHERE tg_id = ?", cb.from_user.id)
    kb = InlineKeyboardBuilder()
    kb.row(btn("🔔 Увімкнути назад", "c:ron"))
    await safe_edit(cb.message, "🔕 Добре, більше не нагадуватиму про стрижку.", kb.as_markup())
    await cb.answer()


@router.callback_query(F.data == "c:ron")
async def reminders_on(cb: CallbackQuery):
    await db.ex("UPDATE clients SET reminders_off = 0 WHERE tg_id = ?", cb.from_user.id)
    await safe_edit(cb.message, "🔔 Нагадування увімкнено.", None)
    await cb.answer()


# ---------- інфо ----------

async def prices(m: Message) -> None:
    rows = await db.q("SELECT * FROM services WHERE active = 1 ORDER BY sort, id")
    lines = ["💈 <b>Послуги і ціни</b>", ""]
    lines += [f"✂️ {e(s['name'])} — <b>{money(s['price'])}</b> · {s['duration']} хв" for s in rows]
    kb = InlineKeyboardBuilder()
    kb.row(btn("✂️ Записатися", "c:book"))
    await m.answer("\n".join(lines), reply_markup=kb.as_markup())


async def contacts(m: Message) -> None:
    kb = InlineKeyboardBuilder()
    kb.row(btn("✂️ Записатися", "c:book"))
    await m.answer(e(await db.get("info_text")) or "Контакти ще не заповнені.", reply_markup=kb.as_markup())
