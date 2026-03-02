from models import FlightResult
from telegram import Bot
from telegram.constants import ParseMode


def format_flight_message(flight: FlightResult, job_name: str, job_id: int) -> str:
    label = f"{job_name} #{job_id}" if job_name else f"Job #{job_id}"
    dep = flight.departure_date.strftime("%b %d, %Y")
    return (
        f"🚀 *New flight found!* [{label}]\n"
        f"{flight.origin} → {flight.destination} | {flight.airline.title()} {flight.flight_number}\n"
        f"📅 {dep}\n"
        f"💰 €{flight.price_eur:.2f}/person — 2 adults, 10kg bags\n"
        f"[Book now →]({flight.booking_url})"
    )


async def send_flight_alert(
    bot: Bot,
    chat_id: str,
    flight: FlightResult,
    job_name: str,
    job_id: int,
) -> None:
    text = format_flight_message(flight, job_name, job_id)
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )
