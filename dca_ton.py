import time
import requests
from binance.client import Client
from binance.exceptions import BinanceAPIException
from telegram import Bot
import os

# === НАСТРОЙКИ ===
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

client = Client(API_KEY, API_SECRET)
bot = Bot(token=TELEGRAM_TOKEN)

symbol = "TONUSDT"
buy_price = None
sell_price = None

# === Торговые параметры ===
min_qty = 1.0
step_size = 1.0
min_notional = 1.0
tick_size = 0.00001

def round_step(value, step):
    return round(value - (value % step), 8)

def get_price():
    try:
        ticker = client.get_symbol_ticker(symbol=symbol)
        return float(ticker["price"])
    except Exception as e:
        log(f"❌ Ошибка получения цены: {e}")
        return None

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

def send_message(text, color="gray"):
    emojis = {"red": "🔻", "yellow": "🟡", "green": "🟢", "gray": "⚙️"}
    prefix = emojis.get(color, "⚙️") + " "
    try:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=prefix + text)
    except Exception as e:
        print(f"Ошибка Telegram: {e}")

def log(msg):
    print(msg)
    send_message(msg)

def report_external_ip():
    try:
        ip = requests.get("https://api.ipify.org").text
        log(f"🌐 Внешний IP Railway: {ip}")
    except Exception as e:
        log(f"❌ Не получил IP: {e}")

def check_api_access():
    try:
        account_info = client.get_account()
        log("✅ Доступ к аккаунту есть")
    except Exception as e:
        log(f"❌ Проблема с API: {e}")
    report_external_ip()

def main():
    global buy_price, sell_price
    log("🤖 Бот для TON запущен")
    check_api_access()

    while True:
        try:
            price = get_price()
            if price is None:
                time.sleep(10)
                continue

            log(f"📊 Текущая цена {symbol}: {price:.5f}")

            usdt_balance = float(client.get_asset_balance(asset="USDT")["free"])
            ton_balance = float(client.get_asset_balance(asset="TON")["free"])

            log(f"💰 Баланс USDT: {usdt_balance:.2f}")
            log(f"🪙 Баланс TON: {ton_balance:.2f}")

            # === Покупка ===
            if buy_price is None or price < buy_price * 0.985:
                if usdt_balance >= min_notional:
                    qty = usdt_balance / price
                    log(f"🛒 Попытка купить TON на {usdt_balance:.2f} USDT (кол-во: {qty:.2f})")
                    result = place_order("BUY", qty)
                    if result:
                        buy_price = price
                        sell_price = price * 1.02
                        log(f"🔻 Купил TON по {price:.5f}, выставил продажу по {sell_price:.5f}")
                    else:
                        log("❌ Покупка не удалась")
                else:
                    log(f"⚠️ Недостаточно USDT для покупки. Нужно ≥ {min_notional}, сейчас {usdt_balance:.2f}")

            # === Продажа ===
            elif sell_price and price > sell_price:
                if ton_balance >= min_qty:
                    log(f"💰 Попытка продать {ton_balance:.2f} TON по цене {price:.5f}")
                    result = place_order("SELL", ton_balance)
                    if result:
                        profit = ton_balance * (price - buy_price)
                        log(f"🟡 Продал TON по {price:.5f}")
                        log(f"🟢 Прибыль: {profit:.2f} USDT")
                        buy_price = None
                        sell_price = None
                    else:
                        log("❌ Продажа не удалась")
                else:
                    log(f"⚠️ Недостаточно TON для продажи. Нужно ≥ {min_qty}, сейчас {ton_balance:.2f}")

        except Exception as e:
            log(f"❌ Общая ошибка: {e}")

        time.sleep(60)


if __name__ == "__main__":
    main()
