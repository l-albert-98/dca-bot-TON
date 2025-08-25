import os
import time
import math
import requests
from typing import Tuple, Optional
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

# ===================== ENV =====================
def get_env_var(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise ValueError(f"{name} not set in environment variables")
    return v

API_KEY          = get_env_var("BINANCE_API_KEY")
API_SECRET       = get_env_var("BINANCE_API_SECRET")
TELEGRAM_TOKEN   = get_env_var("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = get_env_var("TELEGRAM_CHAT_ID")

client = Client(API_KEY, API_SECRET)

# ===================== CONFIG (TON) =====================
SYMBOL = "TONUSDT"
TF_LTF = Client.KLINE_INTERVAL_15MINUTE
TF_HTF = Client.KLINE_INTERVAL_4HOUR

# Режим/тренд
ADX_TREND        = 18
MIN_ADX_TO_TRADE = 16
EMA_FAST         = 50
EMA_SLOW         = 200

# Деньги и риск
BASE_ORDER_USDT        = 20.0
SAFETY_ORDERS          = 5
VOL_MULT               = 1.15
MAX_POS_RISK_PCT       = 1.0
MAX_PORTFOLIO_RISK_PCT = 4.0
REINVEST_PCT           = 1.00   # 100% прибыли в следующий вход

# Профит/стоп/трейлинг (на ATR)
MIN_TP_PCT          = 0.70
TP_ATR_MULT_TREND   = 0.90
TP_ATR_MULT_RANGE   = 0.80
STOP_ATR_MULT_TREND = 1.20
STOP_ATR_MULT_RANGE = 0.60
MIN_NET_PROFIT_PCT  = 0.40
TRAIL_ARM_EXTRA_ATR = 0.25
TRAIL_ATR_MULT      = 0.35
TRAIL_SHARE         = 0.30

# DCA шаги
STEP_K_ATR_TREND = 0.60
STEP_K_ATR_RANGE = 0.60

# Прочее
COMMISSION_RATE  = 0.001       # 0.1% за сторону
INTERVAL_SEC     = 30
COOLDOWN_SEC     = 10 * 60
HEARTBEAT_SEC    = 60 * 60     # раз в час — «я жив» + баланс

# IP-оповещения (Railway)
IP_CHECK_EVERY_SEC = 600
LAST_IP_FILE       = "public_ip.txt"

# ===================== Telegram =====================
def tg(msg: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=5,
        )
    except Exception as e:
        print("Telegram error:", e)

def get_public_ip() -> str:
    return requests.get("https://api.ipify.org", timeout=5).text.strip()

def announce_ip(force=False):
    try:
        ip = get_public_ip()
        old = None
        if os.path.exists(LAST_IP_FILE):
            with open(LAST_IP_FILE, "r", encoding="utf-8") as f:
                old = f.read().strip()
        if force or ip != old:
            with open(LAST_IP_FILE, "w", encoding="utf-8") as f:
                f.write(ip)
            tg(f"🌍 *Public IP (Railway)*: `{ip}`\nДобавь его в Binance → API key → *Restrict access to trusted IPs*.")
    except Exception as e:
        tg(f"⚠️ Ошибка определения IP: {e}")

def check_binance_access() -> bool:
    try:
        client.ping()
        client.get_account()
        return True
    except BinanceAPIException as e:
        if e.code == -2015:
            announce_ip(force=True)
            tg("❌ *Binance -2015*: Invalid API-key, IP, or permissions.\n"
               "• Включи *Spot & Margin trading*\n"
               "• Добавь IP из сообщения выше в whitelist\n"
               "• Проверь, что ключ не Read Only")
        else:
            tg(f"❌ Binance API error: {e}")
        return False

# ===================== Helpers =====================
def round_down_step(value: float, step: float) -> float:
    if step <= 0: return float(value)
    return float((value // step) * step)

def round_up_step(value: float, step: float) -> float:
    if step <= 0: return float(value)
    return math.ceil(value / step) * step

def symbol_filters():
    info = client.get_symbol_info(SYMBOL)
    lot  = next(f for f in info['filters'] if f['filterType'] == 'LOT_SIZE')
    tick = next(f for f in info['filters'] if f['filterType'] == 'PRICE_FILTER')
    min_notional = 0.0
    for f in info['filters']:
        if f['filterType'] in ('MIN_NOTIONAL', 'NOTIONAL'):
            min_notional = float(f.get('minNotional', f.get('notional', '0')))
            break
    return float(lot['stepSize']), float(tick['tickSize']), float(min_notional)

def get_balances() -> Tuple[float, float]:
    q = float(client.get_asset_balance(asset="USDT")["free"])
    b = float(client.get_asset_balance(asset=SYMBOL.replace("USDT",""))["free"])
    return q, b

def get_price() -> float:
    return float(client.get_symbol_ticker(symbol=SYMBOL)["price"])

def klines(interval: str, limit=500):
    d = client.get_klines(symbol=SYMBOL, interval=interval, limit=limit)
    return [(float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5])) for x in d]  # o,h,l,c,v

# ===================== Indicators =====================
def ema(series, period):
    if not series or len(series) < period: return None
    k = 2.0/(period+1)
    e = series[0]
    for v in series[1:]:
        e = v*k + e*(1-k)
    return e

def atr(ohlcv, period=14):
    if len(ohlcv) < period+1: return None
    trs=[]; pc=ohlcv[0][3]
    for _,h,l,c,_ in ohlcv[1:]:
        trs.append(max(h-l, abs(h-pc), abs(l-pc))); pc=c
    a = sum(trs[:period])/period
    for tr in trs[period:]:
        a = (a*(period-1)+tr)/period
    return a

def adx(ohlcv, period=14):
    if len(ohlcv) < period+2: return None
    plus_dm=[]; minus_dm=[]; trs=[]
    for i in range(1,len(ohlcv)):
        _,h,l,c,_ = ohlcv[i]
        _,ph,pl,pc,_ = ohlcv[i-1]
        up=h-ph; dn=pl-l
        plus_dm.append(up if (up>dn and up>0) else 0.0)
        minus_dm.append(dn if (dn>up and dn>0) else 0.0)
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    def w(vals):
        s=sum(vals[:period]); out=[s]
        for v in vals[period:]:
            s = s - s/period + v; out.append(s)
        return out
    trs_sm, plus_sm, minus_sm = w(trs), w(plus_dm), w(minus_dm)
    di_p=[(p/t)*100 if t>0 else 0 for p,t in zip(plus_sm,trs_sm)]
    di_m=[(m/t)*100 if t>0 else 0 for m,t in zip(minus_sm,trs_sm)]
    dx=[(abs(p-m)/(p+m))*100 if (p+m)>0 else 0 for p,m in zip(di_p,di_m)]
    if len(dx) < period: return None
    a=sum(dx[:period])/period
    for v in dx[period:]:
        a=(a*(period-1)+v)/period
    return a

def bollinger(candles, period=20, mult=2.0):
    closes=[c[3] for c in candles]
    if len(closes) < period: return None,None,None
    sma=sum(closes[-period:])/period
    var=sum((x-sma)**2 for x in closes[-period:])/period
    std=math.sqrt(var)
    return sma, sma-mult*std, sma+mult*std

# ===================== Orders =====================
def market_buy_with_budget(quote_usdt: float) -> Optional[dict]:
    """Маркет-бай на сумму quote_usdt (дотягиваем до minNotional)."""
    try:
        lot_step, _, min_notional = symbol_filters()
        price_now = get_price()
        spend = max(quote_usdt, 0.0)
        if min_notional and spend < min_notional:
            spend = min_notional
        qty = round_down_step(spend / price_now, lot_step)
        if qty <= 0: return None
        return client.order_market_buy(symbol=SYMBOL, quantity=qty)
    except BinanceAPIException as e:
        tg(f"❌ Market BUY error: {e}")
        return None

def market_sell_quantity(qty: float) -> Optional[dict]:
    try:
        lot_step, _, _ = symbol_filters()
        q = round_down_step(max(qty, 0.0), lot_step)
        if q <= 0: return None
        return client.order_market_sell(symbol=SYMBOL, quantity=q)
    except BinanceAPIException as e:
        tg(f"❌ Market SELL error: {e}")
        return None

# ===================== State =====================
state = {
    "positions": [],
    "dca_filled": 0,
    "dca_step": None,
    "next_dca_price": None,
    "regime": "flat",
    "bias": "long",
    "adx": 0.0,
    "avg_price": None,
    "total_qty": 0.0,
    "total_cost": 0.0,    # quote потрачено
    "fees": 0.0,          # комиссии (quote)
    "tp_price": None,
    "trail_peak": None,
    "stop_price": None,
    "profit_total": 0.0,  # реализованный net
    "cooldown_until": 0.0,
}

def reset_position():
    for k in ["positions","dca_filled","dca_step","next_dca_price","avg_price",
              "total_qty","total_cost","fees","tp_price","trail_peak","stop_price"]:
        if k=="positions": state[k]=[]
        elif k in ("dca_filled",): state[k]=0
        elif k in ("total_qty","total_cost","fees"): state[k]=0.0
        else: state[k]=None

# ===================== Core logic =====================
def update_regime():
    htf = klines(TF_HTF, limit=400)
    closes = [c[3] for c in htf]
    ema50  = ema(closes[-400:], EMA_FAST)
    ema200 = ema(closes[-400:], EMA_SLOW)
    a = adx(htf, 14) or 0.0
    if ema50 is None or ema200 is None:
        return "flat", "long", 0.0
    bias = "long" if ema50 > ema200 else "short"
    regime = "trend" if a >= ADX_TREND else "range"
    return regime, bias, a

def compute_levels(price_now):
    ltf = klines(TF_LTF, limit=300)
    a   = atr(ltf, 14) or 0.0
    sma, bb_low, bb_up = bollinger(ltf, 20, 2.0)
    closes = [c[3] for c in ltf]
    e20 = ema(closes[-200:], 20)
    e50 = ema(closes[-500:], 50)
    return {"ATR": a, "BB_LOW": bb_low, "BB_UP": bb_up, "EMA20": e20, "EMA50": e50, "PRICE": price_now}

def portfolio_risk_guard():
    usdt, _ = get_balances()
    price = get_price()
    pos_val = state["total_qty"] * price
    acc_val = usdt + pos_val
    _, _, min_notional = symbol_filters()
    max_pos_val = max(acc_val * MAX_POS_RISK_PCT / 100.0, min_notional * 1.05)
    max_portfolio_val = acc_val * MAX_PORTFOLIO_RISK_PCT / 100.0
    return acc_val, max_pos_val, max_portfolio_val, usdt, min_notional

def maybe_enter_long(levels):
    now = time.time()
    if now < state["cooldown_until"]: return
    if state.get("adx", 0.0) < MIN_ADX_TO_TRADE: return

    price = levels["PRICE"]
    if state["regime"] == "trend":
        cond = ((levels["EMA20"] is not None and price <= levels["EMA20"])
                or (levels["BB_LOW"] is not None and price <= levels["BB_LOW"]))
        k = STEP_K_ATR_TREND
        tp_mult, stop_mult = TP_ATR_MULT_TREND, STOP_ATR_MULT_TREND
    else:
        cond = (levels["BB_LOW"] is not None and price <= levels["BB_LOW"])
        k = STEP_K_ATR_RANGE
        tp_mult, stop_mult = TP_ATR_MULT_RANGE, STOP_ATR_MULT_RANGE
    if not cond or not levels["ATR"]: return

    acc_val, max_pos_val, _, usdt, min_notional = portfolio_risk_guard()
    if usdt < min_notional: return

    reinvest_bonus = max(0.0, state["profit_total"]) * REINVEST_PCT
    planned_total  = min(BASE_ORDER_USDT + reinvest_bonus, max_pos_val)
    bo = min(planned_total, usdt)
    if bo < min_notional: bo = min_notional
    if bo <= 0: return

    order = market_buy_with_budget(bo)
    if not order: return

    spent_quote  = float(order.get("cummulativeQuoteQty", 0.0)) or bo
    executed_qty = float(order.get("executedQty", 0.0))
    if executed_qty <= 0: return

    fee = spent_quote * COMMISSION_RATE
    fill_price = spent_quote / executed_qty

    state["positions"].append({"qty": executed_qty, "price": fill_price, "cost": spent_quote, "fee": fee})
    state["total_qty"]  += executed_qty
    state["total_cost"] += spent_quote
    state["fees"]       += fee
    state["avg_price"]   = state["total_cost"]/max(state["total_qty"],1e-9)

    step = max(levels["ATR"] * k, price * 0.002)
    state["dca_step"]       = step
    state["next_dca_price"] = price - step

    tp_abs = max(levels["ATR"] * tp_mult, state["avg_price"] * MIN_TP_PCT/100.0)
    state["tp_price"]   = state["avg_price"] + tp_abs
    state["trail_peak"] = None
    state["stop_price"] = state["avg_price"] - stop_mult * levels["ATR"]

    tg(f"🟢 BUY {SYMBOL} @ {fill_price:.6f} | qty={executed_qty:.0f}\n"
       f"ATR={levels['ATR']:.6f}, step={step:.6f}\n"
       f"avg={state['avg_price']:.6f}, TP={state['tp_price']:.6f}, SL={state['stop_price']:.6f}")

def maybe_dca(levels):
    if state["total_qty"] <= 0 or state["dca_filled"] >= SAFETY_ORDERS: return
    price = levels["PRICE"]
    if state["next_dca_price"] is None or state["dca_step"] is None: return
    if price > state["next_dca_price"]: return

    _, max_pos_val, _, usdt, min_notional = portfolio_risk_guard()
    planned_total = min(state["total_cost"] * VOL_MULT, max_pos_val)
    add_usdt = min(max(planned_total - state["total_cost"], min_notional), usdt)
    if add_usdt < min_notional * 0.99: return

    order = market_buy_with_budget(add_usdt)
    if not order: return

    spent_quote  = float(order.get("cummulativeQuoteQty", 0.0)) or add_usdt
    executed_qty = float(order.get("executedQty", 0.0))
    if executed_qty <= 0: return

    fee = spent_quote * COMMISSION_RATE
    fill_price = spent_quote / executed_qty

    state["positions"].append({"qty": executed_qty, "price": fill_price, "cost": spent_quote, "fee": fee})
    state["total_qty"]  += executed_qty
    state["total_cost"] += spent_quote
    state["fees"]       += fee
    state["avg_price"]   = state["total_cost"]/max(state["total_qty"],1e-9)

    state["dca_filled"]    += 1
    state["next_dca_price"] = price - state["dca_step"]

    tp_mult   = TP_ATR_MULT_TREND if state["regime"] == "trend" else TP_ATR_MULT_RANGE
    stop_mult = STOP_ATR_MULT_TREND if state["regime"] == "trend" else STOP_ATR_MULT_RANGE
    tp_abs  = max(levels["ATR"] * tp_mult, state["avg_price"] * MIN_TP_PCT/100.0)
    state["tp_price"]  = state["avg_price"] + tp_abs
    state["stop_price"]= state["avg_price"] - stop_mult * levels["ATR"]

    tg(f"🟢 DCA {state['dca_filled']}/{SAFETY_ORDERS} @ {fill_price:.6f} | qty={executed_qty:.0f}\n"
       f"avg={state['avg_price']:.6f}, next={state['next_dca_price']:.6f}\n"
       f"TP={state['tp_price']:.6f}, SL={state['stop_price']:.6f}")

def maybe_take_profit_and_trail(levels):
    if state["total_qty"] <= 0: return
    price = levels["PRICE"]
    atrv  = levels["ATR"] or 0.0
    if not atrv: return

    trigger_price = max(state["tp_price"] or 0.0,
                        state["avg_price"] * (1.0 + MIN_NET_PROFIT_PCT/100.0))

    if price >= (trigger_price + TRAIL_ARM_EXTRA_ATR * atrv):
        if state["trail_peak"] is None or price > state["trail_peak"]:
            state["trail_peak"] = price

        dyn_drop = (state["trail_peak"] - (state["tp_price"] or state["trail_peak"])) * TRAIL_SHARE
        drop = max(TRAIL_ATR_MULT * atrv, dyn_drop)

        min_lock = state["avg_price"] * (1.0 + MIN_NET_PROFIT_PCT/100.0)
        new_trail = max(state.get("stop_price", -1e9), state["trail_peak"] - drop, min_lock)
        state["stop_price"] = new_trail

    maybe_stop_out(levels)

def maybe_stop_out(levels):
    if state["total_qty"] <= 0: return
    price = levels["PRICE"]
    if state["stop_price"] and price <= state["stop_price"]:
        sell_all("STOP/TRAIL hit", price)

def regime_flip_exit():
    if state["total_qty"] <= 0: return
    if state["bias"] != "long":
        sell_all("Regime flip", get_price())

def sell_all(reason: str, px_now: float):
    qty = state["total_qty"]
    if qty <= 0: return
    order = market_sell_quantity(qty)
    if not order: return

    revenue = float(order.get("cummulativeQuoteQty", 0.0)) or (px_now * qty)
    exit_fee = revenue * COMMISSION_RATE
    net = revenue - state["total_cost"] - state["fees"] - exit_fee

    state["profit_total"] += net
    tg(f"🟡 {reason}: SELL {SYMBOL} @ ~{px_now:.6f}\n"
       f"PnL: *{net:.2f} USDT* | Total: {state['profit_total']:.2f} USDT\n"
       f"avg={state['avg_price']:.6f}  TP={state['tp_price'] or 0:.6f}  SL={state['stop_price'] or 0:.6f}")

    reset_position()
    state["cooldown_until"] = time.time() + COOLDOWN_SEC

# ===================== Heartbeat (раз в час) =====================
def heartbeat():
    usdt, coin = get_balances()
    price = get_price()
    pos_val = coin * price
    tg(f"⏰ Бот работает. {SYMBOL}={price:.6f}\n"
       f"Свободно: *{usdt:.2f} USDT*, монета: {coin:.0f} (~{pos_val:.2f} USDT)\n"
       f"Текущая позиция qty={state['total_qty']:.0f}, avg={state['avg_price'] or 0:.6f}\n"
       f"PnL total: *{state['profit_total']:.2f} USDT*")

# ===================== Main =====================
def main():
    tg(f"🚀 Smart DCA bot started for *{SYMBOL}* (HTF=4h, LTF=15m)")
    announce_ip(force=True)
    check_binance_access()

    last_ip_check  = time.time()
    last_heartbeat = 0.0

    while True:
        try:
            now = time.time()

            if now - last_ip_check > IP_CHECK_EVERY_SEC:
                announce_ip(force=False)
                last_ip_check = now

            if now - last_heartbeat > HEARTBEAT_SEC:
                heartbeat()
                last_heartbeat = now

            price = get_price()
            regime, bias, adxv = update_regime()
            state["regime"], state["bias"], state["adx"] = regime, bias, adxv
            levels = compute_levels(price)

            if state["total_qty"] <= 0:
                if bias == "long":
                    maybe_enter_long(levels)
            else:
                maybe_dca(levels)
                maybe_take_profit_and_trail(levels)
                regime_flip_exit()

        except (BinanceAPIException, BinanceRequestException) as e:
            tg(f"❗ Binance API error: {e}")
            if getattr(e, "code", None) == -2015:
                announce_ip(force=True)
        except Exception as e:
            tg(f"❗ Bot error: {e}")

        time.sleep(INTERVAL_SEC)

if __name__ == "__main__":
    main()
