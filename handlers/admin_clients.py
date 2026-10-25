"""Барбер: база клієнтів — пошук, картка, історія, нагадування, експорт."""
import csv
import io
from datetime import timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db
from cb import ApptCB, CEdit, ClientCB, CSearch
from utils import (EMOJI, IsAdmin, btn, client, client_stats, dts, due_clients, e, money, norm_phone, now,
                   safe_edit, sdt, search_clients, to_int, today)
from views import render_client

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


async def home(m: Message, state: FSMContext) -> None:
    await state.clear()
    total = await db.q1("SELECT COUNT(*) n FROM clients")
    in_bot = await db.q1("SELECT COUNT(*) n FROM clients WHERE tg_id IS NOT NULL AND bot_blocked = 0")
    with_phone = await db.q1("SELECT COUNT(*) n FROM clients WHERE phone IS NOT NULL")
    month = await db.q1("SELECT COUNT(*) n FROM clients WHERE created_at >= ?", dts(now() - timedelta(days=30)))
    sources = await db.q(
        "SELECT COALESCE(source, '—') s, COUNT(*) n FROM clients GROUP BY s ORDER BY n DESC LIMIT 6"
    )
    due = await due_clients()
    lines = [
        "👥 <b>База клієнтів</b>", "",
        f"Всього: <b>{total['n']}</b> · у боті: {in_bot['n']} · з телефоном: {with_phone['n']}",
        f"Нових за 30 днів: {month['n']}",
    ]
    if sources:
        lines.append("Джерела: " + ", ".join(f"{e(r['s'])} {r['n']}" for r in sources))
    lines += ["", "🔍 Введи імʼя або номер, щоб знайти клієнта."]
    kb = InlineKeyboardBuilder()
    kb.row(btn(f"📞 Час на стрижку ({len(due)})", "cl_due"))
    kb.row(btn("🆕 Нові клієнти", "cl_new"), btn("📤 Експорт CSV", "cl_csv"))
    await state.set_state(CSearch.q)
    await m.answer("\n".join(lines), reply_markup=kb.as_markup())


@router.message(CSearch.q, F.text)
async def search(m: Message):
    rows = await search_clients(m.text, limit=15)
    if not rows:
        await m.answer("Нікого не знайдено. Спробуй інакше.")
        return
    kb = InlineKeyboardBuilder()
    for c in rows:
        kb.button(text=f"{c['name']} · {c['phone'] or '—'}", callback_data=ClientCB(a="v", id=c["id"]))
    kb.adjust(1)
    await m.answer(f"Знайдено: {len(rows)}", reply_markup=kb.as_markup())


@router.callback_query(ClientCB.filter(F.a == "v"))
async def card(cb: CallbackQuery, callback_data: ClientCB):
    text, kb = await render_client(callback_data.id)
    await safe_edit(cb.message, text, kb)
    await cb.answer()


@router.callback_query(ClientCB.filter(F.a == "hist"))
async def history(cb: CallbackQuery, callback_data: ClientCB):
    rows = await db.q(
        "SELECT a.*, s.name sname FROM appointments a LEFT JOIN services s ON s.id = a.service_id "
        "WHERE a.client_id = ? AND a.status != 'cancelled' ORDER BY a.start_at DESC LIMIT 15", callback_data.id,
    )
    c = await client(callback_data.id)
    lines = [f"🗂 <b>Історія: {e(c['name'])}</b>", ""]
    kb = InlineKeyboardBuilder()
    for a in rows:
        s = sdt(a["start_at"])
        extra = ""
        if a["status"] == "done":
            up = await db.q1("SELECT COALESCE(SUM(price), 0) v FROM sales WHERE appointment_id = ?", a["id"])
            extra = f" · {money((a['price'] or 0) + up['v'] + (a['tips'] or 0))}" \
                + (f" (🛍 {up['v']})" if up["v"] else "") + (f" (💸 {a['tips']})" if a["tips"] else "")
        lines.append(f"{EMOJI[a['status']]} {s:%d.%m.%y %H:%M} · {e(a['sname'])}{extra}")
        kb.button(text=f"{s:%d.%m} {EMOJI[a['status']]}", callback_data=ApptCB(a="v", id=a["id"]))
    if not rows:
        lines.append("Візитів ще не було.")
    kb.adjust(4)
    kb.row(btn("⬅️ Картка", ClientCB(a="v", id=callback_data.id)))
    await safe_edit(cb.message, "\n".join(lines), kb.as_markup())
    await cb.answer()


@router.callback_query(ClientCB.filter(F.a == "tog"))
async def toggle_reminders(cb: CallbackQuery, callback_data: ClientCB):
    await db.ex("UPDATE clients SET reminders_off = 1 - reminders_off WHERE id = ?", callback_data.id)
    text, kb = await render_client(callback_data.id)
    await safe_edit(cb.message, text, kb)
    await cb.answer("Готово")


_PROMPTS = {
    "note": (CEdit.note, "📝 Введи нотатку (як стриже, що любить, побажання). «-» — очистити."),
    "int": (CEdit.interval, "⏱ Через скільки днів після візиту нагадувати цьому клієнту? Число. 0 — стандарт."),
    "ph": (CEdit.phone, "📱 Введи номер телефону клієнта:"),
}


@router.callback_query(ClientCB.filter(F.a.in_(list(_PROMPTS))))
async def edit_prompt(cb: CallbackQuery, callback_data: ClientCB, state: FSMContext):
    st, text = _PROMPTS[callback_data.a]
    await state.clear()
    await state.set_state(st)
    await state.update_data(cid=callback_data.id)
    await cb.message.answer(text)
    await cb.answer()


async def _back_to_card(m: Message, state: FSMContext, cid: int) -> None:
    await state.clear()
    text, kb = await render_client(cid)
    await m.answer(text, reply_markup=kb)


@router.message(CEdit.note, F.text)
async def edit_note(m: Message, state: FSMContext):
    cid = (await state.get_data())["cid"]
    note = None if m.text.strip() == "-" else m.text.strip()[:500]
    await db.ex("UPDATE clients SET note = ? WHERE id = ?", note, cid)
    await _back_to_card(m, state, cid)


@router.message(CEdit.interval, F.text)
async def edit_interval(m: Message, state: FSMContext):
    days = to_int(m.text)
    if days is None or days > 365:
        await m.answer("Введи число днів, наприклад 14")
        return
    cid = (await state.get_data())["cid"]
    await db.ex("UPDATE clients SET remind_days = ? WHERE id = ?", days or None, cid)
    await _back_to_card(m, state, cid)


@router.message(CEdit.phone, F.text)
async def edit_phone(m: Message, state: FSMContext):
    phone = norm_phone(m.text)
    if not phone:
        await m.answer("Не схоже на номер. Приклад: 0671234567")
        return
    cid = (await state.get_data())["cid"]
    await db.ex("UPDATE clients SET phone = ? WHERE id = ?", phone, cid)
    await _back_to_card(m, state, cid)


@router.callback_query(F.data == "cl_due")
async def due_list(cb: CallbackQuery):
    due = await due_clients()
    if not due:
        await cb.answer("Всі клієнти або записані, або ще не «обросли» 👌", show_alert=True)
        return
    lines = ["📞 <b>Кому вже час на стрижку</b>",
             "<i>💬 — бот нагадає сам, 📵 — немає в боті, треба написати/подзвонити</i>", ""]
    kb = InlineKeyboardBuilder()
    for c, last, interval, overdue in due[:40]:
        icon = "💬" if c["tg_id"] and not c["bot_blocked"] and not c["reminders_off"] else "📵"
        lines.append(f"{icon} {e(c['name'])} · {c['phone'] or '—'} · був {last:%d.%m} (+{overdue} дн.)")
        kb.button(text=c["name"][:20], callback_data=ClientCB(a="v", id=c["id"]))
    kb.adjust(3)
    await cb.message.answer("\n".join(lines), reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data == "cl_new")
async def new_list(cb: CallbackQuery):
    rows = await db.q("SELECT * FROM clients ORDER BY created_at DESC LIMIT 30")
    if not rows:
        await cb.answer("Клієнтів ще немає", show_alert=True)
        return
    lines = ["🆕 <b>Останні клієнти</b>", ""]
    kb = InlineKeyboardBuilder()
    for c in rows:
        lines.append(f"{sdt(c['created_at']):%d.%m} · {e(c['name'])} · {c['phone'] or '—'} · {e(c['source'])}")
        kb.button(text=c["name"][:20], callback_data=ClientCB(a="v", id=c["id"]))
    kb.adjust(3)
    await cb.message.answer("\n".join(lines), reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data == "cl_csv")
async def export_csv(cb: CallbackQuery):
    rows = await db.q("SELECT * FROM clients ORDER BY name")
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Імʼя", "Телефон", "Telegram", "Джерело", "Додано", "Візитів", "Неявок",
                "Всього, грн", "Середній чек", "Останній візит", "Наступний запис", "Нотатка"])
    for c in rows:
        st = await client_stats(c["id"])
        w.writerow([
            c["name"], c["phone"] or "", f"@{c['username']}" if c["username"] else ("так" if c["tg_id"] else ""),
            c["source"] or "", c["created_at"][:10], st["visits"], st["no_show"], st["total"], round(st["avg"]),
            st["last"].isoformat() if st["last"] else "", dts(st["next"]) if st["next"] else "", c["note"] or "",
        ])
    data = buf.getvalue().encode("utf-8-sig")  # BOM — щоб Excel коректно відкрив кирилицю
    await cb.message.answer_document(
        BufferedInputFile(data, filename=f"clients_{today():%Y-%m-%d}.csv"),
        caption=f"📤 База клієнтів: {len(rows)} записів",
    )
    await cb.answer()
