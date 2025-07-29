import os
import time
import requests
from binance.client import Client
from binance.exceptions import BinanceAPIException

# === НАСТРОЙКИ ===
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

client = Client(API_KEY, API_SECRET)

symbol = "TONUSDT"
min_qty = 1.0
step_size = 1.0
tick_size = 0.00001
min_notional = 1.0

fixed_investment = 20
profit_total = 0
last_min_price = None
last_max_price = None
position = False
buy_price = None

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
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
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
        requests.post(url, data=data)
    except Exception as e:
        print(f"Ошибка отправки в Telegram: {e}")

def place_order(order_type, quantity):
    try:
        quantity = round_step(quantity, step_size)
        if order_type == "BUY":
            return client.order_market_buy(symbol=symbol, quantity=quantity)
        else:
            return client.order_market_sell(symbol=symbol, quantity=quantity)
    except BinanceAPIException as e:
        send_message(f"❌ Ошибка размещения {order_type}: {e}")
        return None

def get_public_ip():
    try:
        ip = requests.get("https://api.ipify.org").text
        send_message(f"🌐 Внешний IP Railway: {ip}")
    except Exception as e:
        send_message(f"❌ Ошибка получения IP: {e}")

# === ОСНОВНОЙ ЦИКЛ ===
def main():
    global last_min_price, last_max_price, position, buy_price, profit_total

    send_message("🤖 Бот запущен: стратегия — TON отскок 1.5% + защита от минуса")
    get_public_ip()

    while True:
        try:
            price = get_price()
            usdt, ton = get_balances()
            send_message(f"📈 Цена: {price:.5f} | USDT: {usdt:.2f} | TON: {ton:.2f} | Профит: {profit_total:.2f}")

            if not position:
                if last_min_price is None or price < last_min_price:
                    last_min_price = price

                if last_min_price and price >= last_min_price * 1.015:
                    invest_amount = min(fixed_investment + profit_total, usdt)
                    if invest_amount >= min_notional:
                        qty = round_step(invest_amount / price, step_size)
                        order = place_order("BUY", qty)
                        if order:
                            buy_price = price
                            position = True
                            last_max_price = price
                            send_message(f"🔻 Купил TON по {price:.5f}, на {invest_amount:.2f} USDT")
                    else:
                        send_message(f"⚠️ Недостаточно USDT: {usdt:.2f}")
            else:
                if last_max_price is None or price > last_max_price:
                    last_max_price = price

                if last_max_price and price <= last_max_price * 0.985 and price >= buy_price:
                    if ton >= min_qty:
                        order = place_order("SELL", ton)
                        if order:
                            revenue = ton * price
                            cost = ton * buy_price
                            profit = revenue - cost
                            profit_total += profit
                            send_message(f"🟡 Продал TON по {price:.5f}")
                            send_message(f"🟢 Прибыль: {profit:.2f} USDT")
                            position = False
                            last_min_price = None
                            last_max_price = None
                            buy_price = None
                    else:
                        send_message("⚠️ Недостаточно TON для продажи")
        except Exception as e:
            send_message(f"❗ Общая ошибка: {e}")

        time.sleep(60)

# === СТАРТ ===
if __name__ == "__main__":
    main()
