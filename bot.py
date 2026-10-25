import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat

import db
import scheduler
from config import ADMIN_IDS, BOT_TOKEN
from handlers import admin_book, admin_clients, admin_finance, admin_schedule, admin_settings, booking, client, common


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_routers(
        common.router,          # /start, меню, скасування — мають пріоритет над станами
        booking.router,         # спільний вибір послуги/дати/часу
        admin_book.router,
        admin_schedule.router,
        admin_clients.router,
        admin_finance.router,
        admin_settings.router,
        client.router,
        common.fallback,        # завжди останній
    )
    return dp


async def set_commands(bot: Bot) -> None:
    await bot.set_my_commands([
        BotCommand(command="start", description="Головне меню"),
        BotCommand(command="cancel", description="Скасувати дію"),
    ])
    for uid in ADMIN_IDS:
        try:
            await bot.set_my_commands(
                [BotCommand(command="admin", description="Панель барбера"),
                 BotCommand(command="client", description="Подивитись як клієнт"),
                 BotCommand(command="cancel", description="Скасувати дію")],
                scope=BotCommandScopeChat(chat_id=uid),
            )
        except Exception as err:  # noqa: BLE001 — адмін ще не писав боту
            logging.warning("can't set admin commands for %s: %s", uid, err)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN не задано")
    if not ADMIN_IDS:
        logging.warning("ADMIN_IDS порожній — панель барбера недоступна. Напиши боту /id і додай свій ID.")
    await db.init()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
    dp = build_dispatcher()
    await set_commands(bot)
    task = asyncio.create_task(scheduler.run(bot))
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot)
    finally:
        task.cancel()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
