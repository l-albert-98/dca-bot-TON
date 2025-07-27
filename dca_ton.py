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

# === Жестко заданные параметры торговли для TON ===
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
        print(f"Ошибка получения цены: {e}")
        return None


def place_order(order_type, quantity):
    try:
        quantity = round_step(quantity, step_size)
        if order_type == "BUY":
            order = client.order_market_buy(symbol=symbol, quantity=quantity)
        else:
            order = client.order_market_sell(symbol=symbol, quantity=quantity)
        return order
    except BinanceAPIException as e:
        print(f"Ошибка при размещении {order_type} ордера: {e}")
        return None


def send_message(text, color="gray"):
    emojis = {"red": "🔻", "yellow": "🟡", "green": "🟢", "gray": "⚙️"}
    prefix = emojis.get(color, "") + " "
    try:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=prefix + text)
    except Exception as e:
        print(f"Ошибка отправки сообщения: {e}")


def report_external_ip():
    try:
        ip = requests.get("https://api.ipify.org").text
        send_message(f"Внешний IP Railway: {ip}", color="gray")
    except Exception as e:
        print(f"Не удалось получить IP: {e}")


def check_api_access():
    try:
        account_info = client.get_account()
        print("✅ Доступ к аккаунту есть")
        send_message("✅ API-ключ работает", color="green")
    except Exception as e:
        print(f"❌ Ошибка API: {e}")
        send_message(f"❌ Проблема с API: {e}", color="red")
    try:
    ip = requests.get("https://api.ipify.org").text
    print(f"🌐 Внешний IP-адрес Railway: {ip}")
    send_message(f"🌐 Внешний IP Railway: {ip}", color="gray")
except Exception as e:
    print(f"❌ Не удалось получить внешний IP: {e}")
    send_message(f"❌ Не получил IP: {e}", color="red")


def main():
    global buy_price, sell_price
    print("Бот для TON запущен")
    report_external_ip()
    check_api_access()

    while True:
        try:
            price = get_price()
            if price is None:
                time.sleep(10)
                continue

            print(f"Текущая цена {symbol}: {price:.5f}")

            balance = client.get_asset_balance(asset="USDT")
            usdt_balance = float(balance["free"])

            ton_balance = float(client.get_asset_balance(asset="TON")["free"])

            if buy_price is None or price < buy_price * 0.985:
                if usdt_balance >= min_notional:
                    qty = usdt_balance / price
                    result = place_order("BUY", qty)
                    if result:
                        buy_price = price
                        sell_price = price * 1.02
                        send_message(f"Купил TON по {price:.5f}", color="red")
                else:
                    print("Недостаточно USDT для покупки")

            elif sell_price and price > sell_price:
                if ton_balance >= min_qty:
                    result = place_order("SELL", ton_balance)
                    if result:
                        send_message(f"Продал TON по {price:.5f}", color="yellow")
                        profit = ton_balance * price - ton_balance * buy_price
                        send_message(f"Прибыль: {profit:.2f} USDT", color="green")
                        buy_price = None
                        sell_price = None
                else:
                    print("Недостаточно TON для продажи")

        except Exception as e:
            print(f"Общая ошибка: {e}")

        time.sleep(60)


if __name__ == "__main__":
    main()
