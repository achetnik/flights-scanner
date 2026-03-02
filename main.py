import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from telegram import Bot, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from database import init_db
from scheduler import FlightScheduler
from bot.handlers import (
    cmd_listjobs,
    cmd_pausejob,
    cmd_resumejob,
    cmd_status,
    cmd_stopjob,
)
from bot.wizard import (
    ASK_AIRLINES,
    ASK_DATE_RANGE,
    ASK_DESTINATIONS,
    ASK_INTERVAL,
    ASK_NAME,
    ASK_ORIGIN,
    ask_airlines,
    ask_date_range,
    ask_destinations,
    ask_interval,
    ask_name,
    cancel,
    confirm_job,
    newjob_start,
)

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "placeholder")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "placeholder")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://localhost")

# Build Telegram application
application = Application.builder().token(BOT_TOKEN).build()

# /newjob conversation
newjob_handler = ConversationHandler(
    entry_points=[CommandHandler("newjob", newjob_start)],
    states={
        ASK_ORIGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_destinations)],
        ASK_DESTINATIONS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_airlines)],
        ASK_AIRLINES: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_date_range)],
        ASK_DATE_RANGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_interval)],
        ASK_INTERVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
        ASK_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_job),
            CommandHandler("skip", confirm_job),
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

application.add_handler(newjob_handler)
application.add_handler(CommandHandler("listjobs", cmd_listjobs))
application.add_handler(CommandHandler("stopjob", cmd_stopjob))
application.add_handler(CommandHandler("pausejob", cmd_pausejob))
application.add_handler(CommandHandler("resumejob", cmd_resumejob))
application.add_handler(CommandHandler("status", cmd_status))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    await application.initialize()
    try:
        await application.bot.set_webhook(f"{WEBHOOK_URL}/webhook")
    except Exception as e:
        logger.warning(f"Could not set webhook (expected in dev): {e}")

    flight_scheduler = FlightScheduler(bot=application.bot, chat_id=CHAT_ID)
    flight_scheduler.start()
    flight_scheduler.load_active_jobs()
    logger.info("Flight scanner started.")
    yield
    # Shutdown
    flight_scheduler.scheduler.shutdown(wait=False)
    await application.shutdown()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return Response(status_code=200)
