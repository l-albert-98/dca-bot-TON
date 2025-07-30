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

min_qty = 0.1
step_size = 0.1
tick_size = 0.0001
min_notional = 1.0

fixed_investment = 20
profit_total = 0.0

last_min_price = None
trailing_peak_price = None
positions = []

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
        print(f"Ошибка Telegram: {e}")

def place_order(order_type, quantity):
    try:
        quantity = round_step(quantity, step_size)
        if order_type == "BUY":
            return client.order_market_buy(symbol=symbol, quantity=quantity)
        else:
            return client.order_market_sell(symbol=symbol, quantity=quantity)
    except BinanceAPIException as e:
        send_message(f"❌ Ошибка ордера {order_type}: {e}")
        return None

def get_avg_volume():
    candles = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1MINUTE, limit=10)
    volumes = [float(c[5]) for c in candles]
    return sum(volumes) / len(volumes)

def check_connectivity():
    try:
        response = requests.get("https://api.ipify.org", timeout=5)
        ip = response.text.strip()
        client.ping()
        client.get_account()
        print(f"✅ Подключение к Binance установлено. IP: {ip}")
        send_message("🤖 Бот запущен. Стратегия: трейлинг, DCA, объём ≥ 80% от среднего.")
        send_message(f"🌍 Внешний IP Railway: {ip}")
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
        send_message(f"❌ Ошибка подключения к Binance или IP: {e}")

def main():
    global last_min_price, trailing_peak_price, profit_total, positions

    check_connectivity()

    dca_parts = [0.33, 0.33, 0.34]
    dca_index = 0

    while True:
        try:
            price = get_price()
            usdt, ton = get_balances()
            send_message(f"📈 Цена: {price:.5f} | USDT: {usdt:.2f} | TON: {ton:.2f} | Профит: {profit_total:.2f}")

            if not positions:
                avg_volume = get_avg_volume()
                last_candle = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1MINUTE, limit=1)[0]
                current_volume = float(last_candle[5])

                if last_min_price is None or price < last_min_price:
                    last_min_price = price

                if (
                    price >= last_min_price * 1.015 and
                    dca_index < len(dca_parts) and
                    current_volume >= avg_volume * 0.8
                ):
                    invest_amount = min(usdt, fixed_investment * dca_parts[dca_index])
                    if invest_amount >= min_notional:
                        qty = round_step(invest_amount / price, step_size)
                        order = place_order("BUY", qty)
                        if order:
                            commission = invest_amount * 0.001
                            positions.append({"qty": qty, "price": price, "cost": invest_amount, "commission": commission})
                            send_message(f"🔻 Купил TON по {price:.5f}, на {invest_amount:.2f} USDT")
                            trailing_peak_price = price
                            dca_index += 1
                    else:
                        send_message("⚠️ Недостаточно USDT для покупки")
            else:
                if trailing_peak_price is None or price > trailing_peak_price:
                    trailing_peak_price = price

                avg_buy_price = sum(p["price"] * p["qty"] for p in positions) / sum(p["qty"] for p in positions)
                total_qty = sum(p["qty"] for p in positions)
                total_cost = sum(p["cost"] for p in positions)
                total_commission = sum(p["commission"] for p in positions)

                if price <= trailing_peak_price * 0.985 and price > avg_buy_price:
                    revenue = price * total_qty
                    net_profit = revenue - total_cost - total_commission

                    if (price - avg_buy_price) / avg_buy_price >= 0.005:
                        order = place_order("SELL", total_qty)
                        if order:
                            profit_total += net_profit
                            send_message(f"🟡 Продал TON по {price:.5f}")
                            send_message(f"🟢 Прибыль: {net_profit:.2f} USDT")
                            positions = []
                            last_min_price = None
                            trailing_peak_price = None
                            dca_index = 0
                    else:
                        send_message("🔸 Профит < 0.5% — продажа отменена")

        except Exception as e:
            send_message(f"❗ Ошибка в боте: {e}")

        time.sleep(60)

if __name__ == "__main__":
    main()
