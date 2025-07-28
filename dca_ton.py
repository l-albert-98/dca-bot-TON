import os
import time
import requests
from binance.client import Client
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
tick_size = 0.00001
min_notional = 1.0

fixed_investment = 20  # стартовое вложение
profit_total = 0
last_min_price = None
last_max_price = None
position = False
buy_price = None


def round_step(value, step):
    return round(value - (value % step), 8)


def get_price():
    return float(client.get_symbol_ticker(symbol=symbol)["price"])


def get_balances():
    usdt = float(client.get_asset_balance(asset="USDT")["free"])
    ton = float(client.get_asset_balance(asset="TON")["free"])
    return usdt, ton


def send_message(text):
    try:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text)
    except Exception as e:
        print(f"Ошибка отправки в Telegram: {e}")


def place_order(order_type, quantity):
    try:
        quantity = round_step(quantity, step_size)
        if order_type == "BUY":
            return client.order_market_buy(symbol=symbol, quantity=quantity)
        else:
            return client.order_market_sell(symbol=symbol, quantity=quantity)
    except Exception as e:
        send_message(f"❌ Ошибка размещения {order_type}: {e}")
        return None


def main():
    global last_min_price, last_max_price, position, buy_price, profit_total

    send_message("🤖 Бот запущен, стратегия: отскок + реинвест")

    while True:
        try:
            price = get_price()
            usdt, ton = get_balances()
            send_message(f"📊 Цена: {price:.5f}, Баланс USDT: {usdt:.2f}, TON: {ton:.2f}")

            if not position:
                if last_min_price is None or price < last_min_price:
                    last_min_price = price

                if price >= last_min_price * 1.015:  # отскок вверх на 1.5%
                    invest_amount = min(fixed_investment + profit_total, usdt)
                    if invest_amount >= min_notional:
                        qty = round_step(invest_amount / price, step_size)
                        order = place_order("BUY", qty)
                        if order:
                            buy_price = price
                            position = True
                            send_message(f"🟥 Купил TON по {price:.5f}, на {invest_amount:.2f} USDT")
                    else:
                        send_message(f"⚠️ Недостаточно средств для покупки: {usdt:.2f} USDT")
            else:
                if last_max_price is None or price > last_max_price:
                    last_max_price = price

                if price <= last_max_price * 0.985:  # откат от максимума на 1.5%
                    if ton >= min_qty:
                        order = place_order("SELL", ton)
                        if order:
                            revenue = ton * price
                            cost = ton * buy_price
                            profit = revenue - cost
                            profit_total += profit
                            send_message(f"🟨 Продал TON по {price:.5f}, прибыль: {profit:.2f} USDT")
                            position = False
                            last_min_price = None
                            last_max_price = None
                            buy_price = None
                    else:
                        send_message("⚠️ Недостаточно TON для продажи")

        except Exception as e:
            send_message(f"❗ Общая ошибка: {e}")

        time.sleep(60)


if __name__ == "__main__":
    main()
