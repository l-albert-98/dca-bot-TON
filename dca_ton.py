import os
import time
import json
import requests
from binance.client import Client
from binance.exceptions import BinanceAPIException

# === ПОЛУЧЕНИЕ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ===
def get_env_var(name):
    value = os.getenv(name)
    if not value:
        raise ValueError(f"{name} not set in environment variables")
    return value

# === НАСТРОЙКИ ===
API_KEY = get_env_var("BINANCE_API_KEY")
API_SECRET = get_env_var("BINANCE_API_SECRET")
TELEGRAM_TOKEN = get_env_var("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = get_env_var("TELEGRAM_CHAT_ID")

SYMBOL = "TONUSDT"
FIXED_INVESTMENT = 20
INTERVAL = 60
DCA_PARTS = [0.33, 0.33, 0.34]
MIN_PROFIT_PERCENT = 0.5
COMMISSION_RATE = 0.001

client = Client(API_KEY, API_SECRET)

positions = []
profit_total = 0.0
last_min_price = None
trailing_peak_price = None

def round_step(value, step):
    return round(value - (value % step), 8)

def get_price():
    return float(client.get_symbol_ticker(symbol=SYMBOL)["price"])

def get_balances():
    quote_asset = SYMBOL[-4:]  # USDT
    base_asset = SYMBOL[:-4]  # TON
    quote_balance = float(client.get_asset_balance(asset=quote_asset)["free"])
    base_balance = float(client.get_asset_balance(asset=base_asset)["free"])
    return quote_balance, base_balance

def send_message(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
        requests.post(url, data=data)
    except Exception as e:
        print(f"Ошибка Telegram: {e}")

def place_order(order_type, quantity):
    try:
        info = client.get_symbol_info(SYMBOL)
        step_size = float([f for f in info['filters'] if f['filterType'] == 'LOT_SIZE'][0]['stepSize'])
        quantity = round_step(quantity, step_size)
        if order_type == "BUY":
            return client.order_market_buy(symbol=SYMBOL, quantity=quantity)
        else:
            return client.order_market_sell(symbol=SYMBOL, quantity=quantity)
    except BinanceAPIException as e:
        send_message(f"❌ Ошибка ордера {order_type}: {e}")
        return None

def get_avg_volume():
    candles = client.get_klines(symbol=SYMBOL, interval=Client.KLINE_INTERVAL_1MINUTE, limit=10)
    volumes = [float(c[5]) for c in candles]
    return sum(volumes) / len(volumes)

def check_connectivity():
    try:
        response = requests.get("https://api.ipify.org", timeout=5)
        ip = response.text.strip()
        send_message(f"🌍 Railway IP для Binance: `{ip}`\n\n⚠️ Если в Binance включено ограничение по IP, обязательно добавь этот IP в whitelist.")
        client.ping()
        client.get_account()
    except Exception as e:
        send_message(f"❌ Ошибка подключения: {e}")

def main():
    global last_min_price, trailing_peak_price, profit_total, positions
    dca_index = 0

    check_connectivity()
    send_message(f"🚀 Бот запущен для {SYMBOL}. DCA активен. Бюджет: {FIXED_INVESTMENT} USDT")

    while True:
        try:
            price = get_price()
            usdt, asset = get_balances()

            send_message(f"📉 Цена: {price:.5f} | USDT: {usdt:.2f} | {SYMBOL[:-4]}: {asset:.2f} | Профит: {profit_total:.2f}")

            if not positions:
                avg_volume = get_avg_volume()
                last_candle = client.get_klines(symbol=SYMBOL, interval=Client.KLINE_INTERVAL_1MINUTE, limit=1)[0]
                current_volume = float(last_candle[5])

                if last_min_price is None or price < last_min_price:
                    last_min_price = price

                if (
                    price >= last_min_price * 1.015 and
                    dca_index < len(DCA_PARTS) and
                    current_volume >= avg_volume * 0.8
                ):
                    time.sleep(5)
                    new_price = get_price()
                    if new_price > price:
                        invest_amount = min(usdt, FIXED_INVESTMENT * DCA_PARTS[dca_index])
                        order_qty = invest_amount / new_price
                        order = place_order("BUY", order_qty)
                        if order:
                            commission = invest_amount * COMMISSION_RATE
                            positions.append({"qty": order_qty, "price": new_price, "cost": invest_amount, "commission": commission})
                            send_message(f"🟢 Купил {SYMBOL} по {new_price:.5f}, на {invest_amount:.2f} USDT")
                            trailing_peak_price = new_price
                            dca_index += 1
            else:
                if trailing_peak_price is None or price > trailing_peak_price:
                    trailing_peak_price = price

                avg_buy_price = sum(p["price"] * p["qty"] for p in positions) / sum(p["qty"] for p in positions)
                total_qty = sum(p["qty"] for p in positions)
                total_cost = sum(p["cost"] for p in positions)
                total_commission = sum(p["commission"] for p in positions)

                expected_profit_price = avg_buy_price * (1 + (MIN_PROFIT_PERCENT + COMMISSION_RATE * 2) / 100)

                if price <= trailing_peak_price * 0.985 and price >= expected_profit_price:
                    revenue = price * total_qty
                    net_profit = revenue - total_cost - total_commission

                    order = place_order("SELL", total_qty)
                    if order:
                        profit_total += net_profit
                        send_message(f"🟡 Продал {SYMBOL} по {price:.5f}\n🟢 Прибыль: {net_profit:.2f} USDT")
                        positions = []
                        last_min_price = None
                        trailing_peak_price = None
                        dca_index = 0
                else:
                    send_message("🔸 Условия для продажи не выполнены")

        except Exception as e:
            send_message(f"❗ Ошибка в боте: {e}")

        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
