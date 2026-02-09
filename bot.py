from __future__ import annotations

import asyncio
import logging
import os

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from logic import BotError, BybitClient, VolatilityAnalyzer, VolatilityReportService

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
LOGGER = logging.getLogger(__name__)


def build_service() -> VolatilityReportService:
    bybit = BybitClient()
    analyzer = VolatilityAnalyzer()
    return VolatilityReportService(bybit=bybit, analyzer=analyzer)


SERVICE = build_service()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hi! Send a ticker like BTC, ETHUSDT, or PEPE and I'll return a full volatility report.\n\n"
        "Useful ideas for next upgrades:\n"
        "1) Add /chart for volatility + ATR visual snapshots.\n"
        "2) Add /alert to notify when price reaches your DCA percentile levels."
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Usage:\n"
        "• Send a single ticker symbol (BTC, SOLUSDT, XRP).\n"
        "• The bot validates Bybit market, fetches daily candles, and calculates volatility + DCA levels."
    )


async def analyze_ticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    user_text = update.message.text.strip()

    await update.message.chat.send_action(action=ChatAction.TYPING)

    try:
        report = await asyncio.to_thread(SERVICE.generate_report, user_text)
        await update.message.reply_text(report, parse_mode=ParseMode.MARKDOWN)
    except BotError as exc:
        await update.message.reply_text(f"Error: {exc}")
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.exception("Unexpected failure while handling %s", user_text, exc_info=exc)
        await update.message.reply_text(
            "Unexpected error while analyzing ticker. Please retry in a few seconds."
        )


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is required.")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, analyze_ticker)
    )

    LOGGER.info("Bot started")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
