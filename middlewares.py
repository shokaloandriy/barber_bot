"""Обовʼязковий номер телефону: клієнт без номера не може користуватися ботом, поки його не надасть."""
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject

from cb import Reg
from keyboards import CONTACT_KB
from utils import client_by_tg, is_admin

PHONE_PROMPT = (
    "📱 Щоб записуватися, потрібен ваш номер телефону — барбер зможе звʼязатися, якщо щось зміниться.\n\n"
    "Натисніть кнопку <b>«📱 Поділитися номером»</b> внизу або просто напишіть номер повідомленням."
)

# Команди, які працюють і без номера
_FREE_COMMANDS = ("/start", "/id")


async def ask_phone(state: FSMContext, answer, after: str | None = None) -> None:
    await state.clear()
    await state.set_state(Reg.phone)
    if after:
        await state.update_data(after=after)
    await answer(PHONE_PROMPT, reply_markup=CONTACT_KB)


class PhoneRequired(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        state: FSMContext | None = data.get("state")
        if not user or not state or is_admin(user.id):
            return await handler(event, data)
        # у стані «введіть номер» пропускаємо лише повідомлення — їх обробить client.phone_input
        if isinstance(event, Message) and await state.get_state() == Reg.phone.state:
            return await handler(event, data)
        if isinstance(event, Message) and event.text and event.text.split()[0].split("@")[0] in _FREE_COMMANDS:
            return await handler(event, data)

        c = await client_by_tg(user.id)
        if c and c["phone"]:
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            await event.answer("Спершу вкажіть номер телефону 📱", show_alert=True)
            if event.message:
                await ask_phone(state, event.message.answer)
            return None
        if isinstance(event, Message):
            await ask_phone(state, event.answer)
        return None
