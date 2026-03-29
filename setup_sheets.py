"""
Запусти этот скрипт один раз чтобы создать нужную структуру в Google Sheets.
Использование: python setup_sheets.py
"""
import os, json
import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

SHEET_ID = os.environ.get("SHEET_ID")
creds_dict = json.loads(os.environ.get("GOOGLE_CREDS_JSON"))
creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
client = gspread.authorize(creds)
sh = client.open_by_key(SHEET_ID)

# Лист 1: Клиенты
try:
    ws = sh.worksheet("Клиенты")
    print("Лист 'Клиенты' уже существует")
except:
    ws = sh.add_worksheet("Клиенты", rows=500, cols=10)
    ws.append_row(["telegram_id", "имя", "username", "статус", "дата_регистрации", "визитов", "заметки"])
    ws.format("A1:G1", {"textFormat": {"bold": True}})
    print("Лист 'Клиенты' создан")

# Лист 2: Расписание
try:
    ws2 = sh.worksheet("Расписание")
    print("Лист 'Расписание' уже существует")
except:
    ws2 = sh.add_worksheet("Расписание", rows=500, cols=6)
    ws2.append_row(["id", "дата", "время", "статус"])
    ws2.format("A1:D1", {"textFormat": {"bold": True}})
    # Добавим несколько примеров слотов
    from datetime import datetime, timedelta
    today = datetime.now()
    sample_slots = []
    for i in range(1, 15):
        d = today + timedelta(days=i)
        if d.weekday() < 5:  # пн-пт
            for t in ["10:00", "12:00", "14:00", "16:00"]:
                sample_slots.append([len(sample_slots)+1, d.strftime("%d.%m.%Y"), t, "свободно"])
    for slot in sample_slots:
        ws2.append_row(slot)
    print(f"Лист 'Расписание' создан, добавлено {len(sample_slots)} слотов")

# Лист 3: Записи
try:
    ws3 = sh.worksheet("Записи")
    print("Лист 'Записи' уже существует")
except:
    ws3 = sh.add_worksheet("Записи", rows=1000, cols=10)
    ws3.append_row(["id", "telegram_id", "имя_клиента", "услуга", "дата", "время", "цена", "статус_записи", "создано"])
    ws3.format("A1:I1", {"textFormat": {"bold": True}})
    print("Лист 'Записи' создан")

print("\nГотово! Структура Google Sheets настроена.")
