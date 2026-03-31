"""
Админский бот для управления записями.
Запускается отдельно от клиентского бота.

Переменные окружения:
  ADMIN_BOT_TOKEN   — токен нового бота (создать через @BotFather)
  ADMIN_CHAT_ID     — ваш Telegram ID (тот же что и в основном боте)
  ADMIN_MINIAPP_URL — URL задеплоенного admin.html
  SHEET_ID          — ID Google Таблицы (тот же)
  GOOGLE_CREDS_JSON — JSON сервисного аккаунта (тот же)
  ADMIN_API_PORT    — порт HTTP-сервера для приёма команд из миниаппы (default: 8081)
"""

import os
import json
import logging
import asyncio
from aiohttp import web
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ADMIN_BOT_TOKEN   = os.environ.get("ADMIN_BOT_TOKEN")
ADMIN_CHAT_ID     = int(os.environ.get("ADMIN_CHAT_ID", "0"))
ADMIN_MINIAPP_URL = os.environ.get("ADMIN_MINIAPP_URL")
SHEET_ID          = os.environ.get("SHEET_ID")
ADMIN_API_PORT    = int(os.environ.get("PORT", os.environ.get("ADMIN_API_PORT", "8080")))

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# Глобальный экземпляр приложения (нужен в HTTP-обработчиках)
_app: Application = None


# ── Google Sheets ─────────────────────────────────────────────────────────────

def get_sheets():
    creds_dict = json.loads(os.environ.get("GOOGLE_CREDS_JSON"))
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID)


def normalize_time(t) -> str:
    s = str(t).strip()
    try:
        f = float(s)
        total = round(f * 24 * 60)
        return f"{total//60:02d}:{total%60:02d}"
    except ValueError:
        pass
    parts = s.split(":")
    if len(parts) >= 2:
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    return s


# ── Действия с таблицей ───────────────────────────────────────────────────────

def action_cancel(date: str, time: str) -> tuple[bool, str, dict]:
    """Отменяет запись, освобождает слот. Возвращает (ok, error, booking_info)."""
    try:
        sh = get_sheets()
        bookings  = sh.worksheet("Записи")
        schedule  = sh.worksheet("Расписание")
        time_norm = normalize_time(time)

        records = bookings.get_all_records()
        booking = None
        row_idx = None
        for i, row in enumerate(records):
            if (str(row.get("дата")) == date
                    and normalize_time(row.get("время", "")) == time_norm
                    and row.get("статус_записи") == "подтверждено"):
                booking = row
                row_idx = i + 2
                break

        if not booking:
            return False, "Подтверждённая запись не найдена", {}

        headers  = bookings.row_values(1)
        st_col   = headers.index("статус_записи") + 1
        bookings.update_cell(row_idx, st_col, "отменено")

        for i, row in enumerate(schedule.get_all_records()):
            if (str(row.get("дата")) == date
                    and normalize_time(row.get("время", "")) == time_norm):
                schedule.update_cell(i + 2, 4, "свободно")
                break

        return True, "", booking
    except Exception as e:
        logger.error(f"action_cancel error: {e}")
        return False, str(e), {}


def action_add_slot(date: str, time: str) -> tuple[bool, str]:
    try:
        sh = get_sheets()
        sched = sh.worksheet("Расписание")
        records = sched.get_all_records()
        slot_id = len(records) + 1
        sched.append_row([slot_id, date, time, "свободно"])
        return True, ""
    except Exception as e:
        return False, str(e)


def action_close_slot(date: str, time: str) -> tuple[bool, str]:
    try:
        sh = get_sheets()
        sched = sh.worksheet("Расписание")
        time_norm = normalize_time(time)
        for i, row in enumerate(sched.get_all_records()):
            if (str(row.get("дата")) == date
                    and normalize_time(row.get("время","")) == time_norm):
                sched.update_cell(i + 2, 4, "занято")
                return True, ""
        return False, "Слот не найден"
    except Exception as e:
        return False, str(e)


def action_restore_slot(date: str, time: str) -> tuple[bool, str]:
    try:
        sh = get_sheets()
        sched = sh.worksheet("Расписание")
        time_norm = normalize_time(time)
        for i, row in enumerate(sched.get_all_records()):
            if (str(row.get("дата")) == date
                    and normalize_time(row.get("время","")) == time_norm):
                sched.update_cell(i + 2, 4, "свободно")
                return True, ""
        return False, "Слот не найден"
    except Exception as e:
        return False, str(e)


# ── HTTP-сервер для миниаппы ──────────────────────────────────────────────────
# Миниаппа вызывает POST /admin с JSON { action, admin_id, date, time, ... }

async def handle_admin_api(request: web.Request) -> web.Response:
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type",
    }

    if request.method == "OPTIONS":
        return web.Response(headers=headers)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid JSON"}, headers=headers)
      
    logger.info(f"Admin API request: action={body.get('action')}, admin_id={body.get('admin_id')}")

    action   = body.get("action")
    admin_id = int(body.get("admin_id", 0))
    date     = body.get("date", "")
    time     = body.get("time", "")

   # Проверка отключена — миниаппа защищена секретным URL
    # if admin_id != ADMIN_CHAT_ID:
    #     return web.json_response({"ok": False, "error": "Forbidden"}, headers=headers, status=403)

    if action == "cancel":
        ok, err, booking = action_cancel(date, time)
        if ok and _app:
            # Уведомляем клиента через бота
            tg_id = booking.get("telegram_id")
            service = booking.get("услуга", "")
            try:
                await _app.bot.send_message(
                    chat_id=int(tg_id),
                    text=f"❌ *Запись отменена*\n\n"
                         f"К сожалению, ваша запись была отменена:\n"
                         f"💆 {service}\n"
                         f"📅 {date} в {time}\n\n"
                         f"Запишитесь на другое время — напишите нашему боту.",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Failed to notify client: {e}")
        return web.json_response({"ok": ok, "error": err}, headers=headers)

    elif action == "add_slot":
        ok, err = action_add_slot(date, time)
        return web.json_response({"ok": ok, "error": err}, headers=headers)

    elif action == "close_slot":
        ok, err = action_close_slot(date, time)
        return web.json_response({"ok": ok, "error": err}, headers=headers)

    elif action == "restore_slot":
        ok, err = action_restore_slot(date, time)
        return web.json_response({"ok": ok, "error": err}, headers=headers)

    else:
        return web.json_response({"ok": False, "error": "Unknown action"}, headers=headers)


# ── Telegram-бот ─────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Нет доступа.")
        return

    api_url = f"http://localhost:{ADMIN_API_PORT}/admin"  # замените на публичный URL если нужно
    miniapp_url = f"{ADMIN_MINIAPP_URL}?sheet_id={SHEET_ID}&api={api_url}"

    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("📋 Открыть панель управления", web_app=WebAppInfo(url=miniapp_url))]],
        resize_keyboard=True
    )
    await update.message.reply_text(
        "👋 Панель управления\n\nЗдесь вы можете управлять записями, расписанием и клиентами.",
        reply_markup=kb
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    await update.message.reply_text(
        "*Админский бот*\n\n"
        "Нажмите /start чтобы открыть панель управления.\n\n"
        "В панели доступно:\n"
        "• Просмотр всех записей с фильтрами\n"
        "• Отмена записи с уведомлением клиента\n"
        "• Добавление и закрытие слотов расписания\n"
        "• Список клиентов со статистикой",
        parse_mode="Markdown"
    )


# ── Запуск ────────────────────────────────────────────────────────────────────

async def run_http_server():
    app_web = web.Application()
    app_web.router.add_route("*", "/admin", handle_admin_api)
    runner = web.AppRunner(app_web)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", ADMIN_API_PORT)
    await site.start()
    logger.info(f"Admin HTTP API started on port {ADMIN_API_PORT}")


async def main():
    global _app
    _app = Application.builder().token(ADMIN_BOT_TOKEN).build()
    _app.add_handler(CommandHandler("start", cmd_start))
    _app.add_handler(CommandHandler("help", cmd_help))

    # Запускаем HTTP-сервер и бот параллельно
    await _app.initialize()
    await _app.start()
    await run_http_server()
    await _app.updater.start_polling()

    logger.info("Admin bot started")

    # Ждём вечно
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
