import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))
MINIAPP_URL = os.environ.get("MINIAPP_URL")
SHEET_ID = os.environ.get("SHEET_ID")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def get_sheets():
    creds_json = os.environ.get("GOOGLE_CREDS_JSON")
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SHEET_ID)
    return spreadsheet

def get_client_info(telegram_id: int):
    try:
        sh = get_sheets()
        clients_sheet = sh.worksheet("Клиенты")
        records = clients_sheet.get_all_records()
        for row in records:
            if str(row.get("telegram_id")) == str(telegram_id):
                return row
        return None
    except Exception as e:
        logger.error(f"Error getting client info: {e}")
        return None

def register_client(telegram_id: int, name: str, username: str):
    try:
        sh = get_sheets()
        clients_sheet = sh.worksheet("Клиенты")
        records = clients_sheet.get_all_records()
        for row in records:
            if str(row.get("telegram_id")) == str(telegram_id):
                return row
        new_row = [
            telegram_id,
            name,
            username or "",
            "новый",
            datetime.now().strftime("%d.%m.%Y"),
            0,
            ""
        ]
        clients_sheet.append_row(new_row)
        return {
            "telegram_id": telegram_id,
            "имя": name,
            "username": username or "",
            "статус": "новый",
            "дата_регистрации": datetime.now().strftime("%d.%m.%Y"),
            "визитов": 0,
            "заметки": ""
        }
    except Exception as e:
        logger.error(f"Error registering client: {e}")
        return None

def get_available_slots():
    try:
        sh = get_sheets()
        schedule_sheet = sh.worksheet("Расписание")
        records = schedule_sheet.get_all_records()
        slots = []
        today = datetime.now().date()
        for row in records:
            if row.get("статус") == "свободно":
                try:
                    slot_date = datetime.strptime(row["дата"], "%d.%m.%Y").date()
                    if slot_date >= today:
                        slots.append({
                            "id": row.get("id"),
                            "date": row["дата"],
                            "time": row["время"],
                            "status": row["статус"]
                        })
                except:
                    continue
        return slots
    except Exception as e:
        logger.error(f"Error getting slots: {e}")
        return []

def get_prices_for_status(status: str):
    prices = {
        "новый": {
            "Классический массаж 60 мин": 4000,
            "Классический массаж 90 мин": 5500,
            "Массаж лица": 3000,
        },
        "постоянный": {
            "Классический массаж 60 мин": 3500,
            "Классический массаж 90 мин": 4800,
            "Массаж лица": 2500,
        },
        "vip": {
            "Классический массаж 60 мин": 3000,
            "Классический массаж 90 мин": 4200,
            "Массаж лица": 2000,
        }
    }
    return prices.get(status.lower(), prices["новый"])

def save_booking(telegram_id: int, client_name: str, service: str, date: str, time: str, price: int):
    try:
        sh = get_sheets()
        bookings_sheet = sh.worksheet("Записи")
        schedule_sheet = sh.worksheet("Расписание")

        booking_id = f"BK{datetime.now().strftime('%d%m%H%M%S')}"
        bookings_sheet.append_row([
            booking_id,
            telegram_id,
            client_name,
            service,
            date,
            time,
            price,
            "подтверждено",
            datetime.now().strftime("%d.%m.%Y %H:%M")
        ])

        records = schedule_sheet.get_all_records()
        for i, row in enumerate(records):
            if row["дата"] == date and row["время"] == time and row["статус"] == "свободно":
                schedule_sheet.update_cell(i + 2, 4, "занято")
                break

        return booking_id
    except Exception as e:
        logger.error(f"Error saving booking: {e}")
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    client = get_client_info(user.id)
    if not client:
        client = register_client(user.id, user.full_name, user.username)

    status = client.get("статус", "новый") if client else "новый"
    prices = get_prices_for_status(status)

    keyboard = [[
        InlineKeyboardButton(
            "📅 Записаться",
            web_app=WebAppInfo(url=f"{MINIAPP_URL}?tid={user.id}&status={status}")
        )
    ], [
        InlineKeyboardButton("📋 Мои записи", callback_data="my_bookings"),
        InlineKeyboardButton("💆 Услуги", callback_data="services")
    ]]

    prices_text = "\n".join([f"• {k} — {v:,} дин.".replace(",", " ") for k, v in prices.items()])

    await update.message.reply_text(
        f"Привет, {user.first_name}! 👋\n\n"
        f"Я помогу вам записаться на массаж к Наталии.\n\n"
        f"*Актуальные цены:*\n{prices_text}\n\n"
        f"Нажмите кнопку ниже чтобы выбрать удобное время:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def handle_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = json.loads(update.effective_message.web_app_data.data)

    client = get_client_info(user.id)
    status = client.get("статус", "новый") if client else "новый"
    prices = get_prices_for_status(status)

    service = data.get("service")
    date = data.get("date")
    time = data.get("time")
    price = prices.get(service, 0)

    booking_id = save_booking(user.id, user.full_name, service, date, time, price)

    await update.message.reply_text(
        f"✅ *Запись подтверждена!*\n\n"
        f"📋 Номер: `{booking_id}`\n"
        f"💆 Услуга: {service}\n"
        f"📅 Дата: {date}\n"
        f"🕐 Время: {time}\n"
        f"💰 Стоимость: {price:,} дин.\n\n"
        f"За день до визита придёт напоминание.",
        parse_mode="Markdown"
    )

    if ADMIN_CHAT_ID:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"🆕 *Новая запись!*\n\n"
                 f"👤 {user.full_name} (@{user.username or 'нет'})\n"
                 f"🏷 Статус: {status}\n"
                 f"💆 {service}\n"
                 f"📅 {date} в {time}\n"
                 f"💰 {price:,} дин.\n"
                 f"🔖 #{booking_id}",
            parse_mode="Markdown"
        )

async def my_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user

    try:
        sh = get_sheets()
        bookings_sheet = sh.worksheet("Записи")
        records = bookings_sheet.get_all_records()
        user_bookings = [r for r in records if str(r.get("telegram_id")) == str(user.id)]

        if not user_bookings:
            await query.edit_message_text("У вас пока нет записей.\n\nНажмите /start чтобы записаться.")
            return

        text = "*Ваши записи:*\n\n"
        for b in user_bookings[-5:]:
            status_icon = "✅" if b.get("статус_записи") == "подтверждено" else "❌"
            text += f"{status_icon} {b['дата']} {b['время']} — {b['услуга']}\n"

        await query.edit_message_text(text, parse_mode="Markdown")
    except Exception as e:
        await query.edit_message_text("Не удалось загрузить записи. Попробуйте позже.")

async def services_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user

    client = get_client_info(user.id)
    status = client.get("статус", "новый") if client else "новый"
    prices = get_prices_for_status(status)

    text = "*Услуги и цены:*\n\n"
    durations = {
        "Классический массаж 60 мин": "60 мин",
        "Классический массаж 90 мин": "90 мин",
        "Массаж лица": "45 мин",
    }
    for service, price in prices.items():
        dur = durations.get(service, "")
        text += f"💆 *{service}*\n⏱ {dur} · 💰 {price:,} дин.\n\n".replace(",", " ")

    keyboard = [[InlineKeyboardButton(
        "📅 Записаться",
        web_app=WebAppInfo(url=f"{MINIAPP_URL}?tid={user.id}&status={status}")
    )]]
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


# ── ADMIN команды ──────────────────────────────────────────────

async def admin_check(update: Update) -> bool:
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Нет доступа.")
        return False
    return True

async def admin_slots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_check(update):
        return
    slots = get_available_slots()
    if not slots:
        await update.message.reply_text("Свободных слотов нет.")
        return
    text = "*Свободные слоты:*\n\n"
    for s in slots[:20]:
        text += f"• {s['date']} {s['time']}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def admin_clients(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_check(update):
        return
    try:
        sh = get_sheets()
        clients_sheet = sh.worksheet("Клиенты")
        records = clients_sheet.get_all_records()
        text = f"*Клиентов всего: {len(records)}*\n\n"
        for c in records[-10:]:
            text += f"👤 {c.get('имя')} · {c.get('статус')} · визитов: {c.get('визитов', 0)}\n"
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def admin_set_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_check(update):
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "Использование: /setstatus @username статус\n"
            "Статусы: новый, постоянный, vip"
        )
        return
    username = context.args[0].lstrip("@")
    new_status = context.args[1].lower()
    if new_status not in ["новый", "постоянный", "vip"]:
        await update.message.reply_text("Статус должен быть: новый, постоянный или vip")
        return
    try:
        sh = get_sheets()
        clients_sheet = sh.worksheet("Клиенты")
        records = clients_sheet.get_all_records()
        for i, row in enumerate(records):
            if row.get("username", "").lower() == username.lower():
                clients_sheet.update_cell(i + 2, 4, new_status)
                await update.message.reply_text(f"✅ Статус @{username} изменён на *{new_status}*", parse_mode="Markdown")
                return
        await update.message.reply_text(f"Клиент @{username} не найден.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def admin_add_slot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_check(update):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /addslot 15.04.2026 10:00")
        return
    date_str = context.args[0]
    time_str = context.args[1]
    try:
        datetime.strptime(date_str, "%d.%m.%Y")
        sh = get_sheets()
        schedule_sheet = sh.worksheet("Расписание")
        records = schedule_sheet.get_all_records()
        slot_id = len(records) + 1
        schedule_sheet.append_row([slot_id, date_str, time_str, "свободно"])
        await update.message.reply_text(f"✅ Слот добавлен: {date_str} в {time_str}")
    except ValueError:
        await update.message.reply_text("Неверный формат даты. Используйте: ДД.ММ.ГГГГ ЧЧ:ММ")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def admin_close_slot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_check(update):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /closeslot 15.04.2026 10:00")
        return
    date_str = context.args[0]
    time_str = context.args[1]
    try:
        sh = get_sheets()
        schedule_sheet = sh.worksheet("Расписание")
        records = schedule_sheet.get_all_records()
        for i, row in enumerate(records):
            if row["дата"] == date_str and row["время"] == time_str:
                schedule_sheet.update_cell(i + 2, 4, "закрыто")
                await update.message.reply_text(f"✅ Слот закрыт: {date_str} в {time_str}")
                return
        await update.message.reply_text("Слот не найден.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_check(update):
        return
    await update.message.reply_text(
        "*Команды мастера:*\n\n"
        "/slots — свободные слоты\n"
        "/clients — список клиентов\n"
        "/addslot 15.04.2026 10:00 — добавить слот\n"
        "/closeslot 15.04.2026 10:00 — закрыть слот\n"
        "/setstatus @username постоянный — изменить статус клиента\n\n"
        "_Статусы: новый, постоянный, vip_",
        parse_mode="Markdown"
    )

async def send_reminders(context: ContextTypes.DEFAULT_TYPE):
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y")
    try:
        sh = get_sheets()
        bookings_sheet = sh.worksheet("Записи")
        records = bookings_sheet.get_all_records()
        for booking in records:
            if booking.get("дата") == tomorrow and booking.get("статус_записи") == "подтверждено":
                try:
                    await context.bot.send_message(
                        chat_id=int(booking["telegram_id"]),
                        text=f"⏰ *Напоминание*\n\n"
                             f"Завтра у вас запись к Наталии:\n"
                             f"💆 {booking['услуга']}\n"
                             f"🕐 {booking['время']}\n\n"
                             f"Ждём вас! Если планы изменились — напишите боту.",
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.error(f"Failed to send reminder to {booking['telegram_id']}: {e}")
    except Exception as e:
        logger.error(f"Error in send_reminders: {e}")


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", admin_help))
    app.add_handler(CommandHandler("slots", admin_slots))
    app.add_handler(CommandHandler("clients", admin_clients))
    app.add_handler(CommandHandler("setstatus", admin_set_status))
    app.add_handler(CommandHandler("addslot", admin_add_slot))
    app.add_handler(CommandHandler("closeslot", admin_close_slot))
    app.add_handler(CallbackQueryHandler(my_bookings, pattern="my_bookings"))
    app.add_handler(CallbackQueryHandler(services_info, pattern="services"))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_webapp_data))

    job_queue = app.job_queue
    job_queue.run_daily(send_reminders, time=datetime.strptime("09:00", "%H:%M").time())

    logger.info("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
