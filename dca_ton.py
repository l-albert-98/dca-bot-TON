import os
import time
import requests
from binance.client import Client
from binance.exceptions import BinanceAPIException
from telegram import Bot

# === НАСТРОЙКИ ===
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

client = Client(API_KEY, API_SECRET)
bot = Bot(token=TELEGRAM_TOKEN)

symbol = "TONUSDT"
min_qty = 1.0
step_size = 1.0
min_notional = 1.0
tick_size = 0.00001

fixed_investment = 20  # базовое вложение
profit_total = 0
last_min_price = None
last_max_price = None
position = False
buy_price = None

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
def round_step(value, step):
    return round(value - (value % step), 8)

def get_price():
    try:
        ticker = client.get_symbol_ticker(symbol=symbol)
        return float(ticker["price"])
    except Exception as e:
        send_message(f"❌ Ошибка получения цены: {e}")
        return None

def get_balances():
    try:
        usdt = float(client.get_asset_balance(asset="USDT")["free"])
        ton = float(client.get_asset_balance(asset="TON")["free"])
        return usdt, ton
    except Exception as e:
        send_message(f"❌ Ошибка получения балансов: {e}")
        return 0, 0

def send_message(text):
    try:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text)
    except Exception as e:
        print(f"Ошибка Telegram: {e}")

def log(msg):
    print(msg)
    send_message(msg)

def place_order(order_type, quantity):
    try:
        quantity = round_step(quantity, step_size)
        if order_type == "BUY":
            return client.order_market_buy(symbol=symbol, quantity=quantity)
        else:
            return client.order_market_sell(symbol=symbol, quantity=quantity)
    except BinanceAPIException as e:
        log(f"❌ Ошибка {order_type}: {e}")
        return None

def report_external_ip():
    try:
        ip = requests.get("https://api.ipify.org").text
        log(f"🌐 Внешний IP Railway: {ip}")
    except Exception as e:
        log(f"❌ Не удалось получить внешний IP: {e}")

# === ОСНОВНОЙ ЦИКЛ ===
def main():
    global last_min_price, last_max_price, position, buy_price, profit_total

    log("🤖 Бот запущен: стратегия — отскок + реинвест")
    report_external_ip()

    while True:
        try:
            price = get_price()
            if not price:
                time.sleep(60)
                continue

            usdt, ton = get_balances()
            log(f"📊 Цена: {price:.5f} | USDT: {usdt:.2f} | TON: {ton:.2f} | Профит: {profit_total:.2f}")

            # === ПОКУПКА ===
            if not position:
                if last_min_price is None or price < last_min_price:
                    last_min_price = price

                if price >= last_min_price * 1.015:
                    invest_amount = min(fixed_investment + profit_total, usdt)
                    if invest_amount >= min_notional:
                        qty = invest_amount / price
                        log(f"🛒 Покупка TON на {invest_amount:.2f} USDT (≈ {qty:.2f} TON)")
                        order = place_order("BUY", qty)
                        if order:
                            buy_price = price
                            position = True
                            last_max_price = None
                            log(f"🟥 Куплено по {price:.5f}")
                    else:
                        log(f"⚠️ Недостаточно USDT для покупки: {usdt:.2f}")

            # === ПРОДАЖА ===
            else:
                if last_max_price is None or price > last_max_price:
                    last_max_price = price

                if price <= last_max_price * 0.985:
                    if ton >= min_qty:
                        log(f"💰 Продажа {ton:.2f} TON по {price:.5f}")
                        order = place_order("SELL", ton)
                        if order:
                            revenue = ton * price
                            cost = ton * buy_price
                            profit = revenue - cost
                            profit_total += profit
                            log(f"🟨 Продано по {price:.5f} | 🟢 Прибыль: {profit:.2f} USDT")
                            position = False
                            last_min_price = None
                            buy_price = None
                    else:
                        log("⚠️ Недостаточно TON для продажи")

        except Exception as e:
            log(f"❗ Общая ошибка: {e}")

        time.sleep(60)

if __name__ == "__main__":
    main()
