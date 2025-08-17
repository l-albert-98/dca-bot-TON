import os
import time
import math
import requests
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

# ==========================
# ENV
# ==========================
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

# ==========================
# CONFIG (TON)
# ==========================
SYMBOL = "TONUSDT"                     # <<< Пара
TF_LTF = Client.KLINE_INTERVAL_15MINUTE
TF_HTF = Client.KLINE_INTERVAL_4HOUR

# фильтры тренда
ADX_TREND = 18
EMA_FAST  = 50
EMA_SLOW  = 200

# DCA / риск
BASE_ORDER_USDT        = 25.0          # базовая покупка под TON
SAFETY_ORDERS          = 5
VOL_MULT               = 1.15
STEP_K_ATR_TREND       = 0.60
STEP_K_ATR_RANGE       = 0.30
MAX_POS_RISK_PCT       = 1.0
MAX_PORTFOLIO_RISK_PCT = 4.0

# TP / трейлинг / стоп
MIN_TP_PCT        = 0.30
TP_ATR_MULT_TREND = 0.80
TP_ATR_MULT_RANGE = 0.50
TRAIL_ATR_MULT    = 0.70
STOP_ATR_MULT     = 1.80
SLIP_TOLERANCE_PCT= 0.10

# прочее
INTERVAL_SEC   = 30
COMMISSION_RATE= 0.001
SPAM_STATUS_EVERY_SEC = 300  # сводка раз в 5 мин

# ==========================
# UTILS / TELEGRAM
# ==========================
def tg(msg: str):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}
        requests.post(url, data=data, timeout=5)
    except Exception as e:
        print("Telegram error:", e)

def round_step(value: float, step: float) -> float:
    if step <= 0:
        return float(value)
    return float((value // step) * step)

def symbol_filters():
    info = client.get_symbol_info(SYMBOL)
    lot  = next(f for f in info['filters'] if f['filterType'] == 'LOT_SIZE')
    tick = next(f for f in info['filters'] if f['filterType'] == 'PRICE_FILTER')
    # у бинанса бывает MIN_NOTIONAL или NOTIONAL
    mn = 0.0
    for f in info['filters']:
        if f['filterType'] in ('MIN_NOTIONAL', 'NOTIONAL'):
            mn = float(f.get('minNotional', f.get('notional', '0')))
            break
    return float(lot['stepSize']), float(tick['tickSize']), float(mn)

def get_price() -> float:
    return float(client.get_symbol_ticker(symbol=SYMBOL)["price"])

def get_balances():
    quote = "USDT"
    base  = SYMBOL.replace("USDT","")
    q = float(client.get_asset_balance(asset=quote)["free"])
    b = float(client.get_asset_balance(asset=base)["free"])
    return q, b

def klines(interval: str, limit=500):
    d = client.get_klines(symbol=SYMBOL, interval=interval, limit=limit)
    # возвращаем (o,h,l,c,v)
    return [(float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5])) for x in d]

# ==========================
# INDICATORS (без сторонних пакетов)
# ==========================
def ema(series, period):
    if len(series) == 0:
        return None
    k = 2.0/(period+1)
    e = series[0]
    for v in series[1:]:
        e = v*k + e*(1-k)
    return e

def atr(ohlcv, period=14):
    if len(ohlcv) < period+1:
        return None
    trs = []
    prev_close = ohlcv[0][3]
    for _,h,l,c,_ in ohlcv[1:]:
        tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        trs.append(tr)
        prev_close = c
    atr_val = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr_val = (atr_val*(period-1) + tr)/period
    return atr_val

def adx(ohlcv, period=14):
    if len(ohlcv) < period+2:
        return None
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, len(ohlcv)):
        _, h, l, _, _ = ohlcv[i]
        _, ph, pl, pc, _ = ohlcv[i-1]
        up   = h - ph
        down = pl - l
        plus_dm.append(up if (up>down and up>0) else 0.0)
        minus_dm.append(down if (down>up and down>0) else 0.0)
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)

    def wilder(vals):
        s = sum(vals[:period])
        out = [s]
        for v in vals[period:]:
            s = s - (s/period) + v
            out.append(s)
        return out

    trs_sm   = wilder(trs)
    plus_sm  = wilder(plus_dm)
    minus_sm = wilder(minus_dm)

    di_plus  = [ (p/t)*100 if t>0 else 0 for p,t in zip(plus_sm, trs_sm) ]
    di_minus = [ (m/t)*100 if t>0 else 0 for m,t in zip(minus_sm, trs_sm) ]
    dx = [ (abs(p-m)/(p+m))*100 if (p+m)>0 else 0 for p,m in zip(di_plus, di_minus) ]

    if len(dx) < period: 
        return None
    adx_val = sum(dx[:period]) / period
    for v in dx[period:]:
        adx_val = (adx_val*(period-1) + v)/period
    return adx_val

def bollinger(candles, period=20, mult=2.0):
    closes = [c[3] for c in candles]
    if len(closes) < period:
        return None, None, None
    sma = sum(closes[-period:]) / period
    var = sum((x - sma)**2 for x in closes[-period:]) / period
    std = math.sqrt(var)
    return sma, sma - mult*std, sma + mult*std

# ==========================
# ORDERS
# ==========================
def place_market(side, qty):
    try:
        lot_step, _, min_notional = symbol_filters()
        price_now = get_price()
        qty = max(qty, 0.0)
        qty = round_step(qty, lot_step)

        # проверка минимума нотиона
        if min_notional and qty * price_now < min_notional:
            min_qty = round_step(min_notional / price_now, lot_step)
            if min_qty * price_now < min_notional:
                tg(f"❌ Ордер меньше minNotional ({min_notional}). qty={qty}")
                return None
            qty = min_qty  # увеличим до минимума

        if qty <= 0:
            return None

        if side == "BUY":
            return client.order_market_buy(symbol=SYMBOL, quantity=qty)
        else:
            return client.order_market_sell(symbol=SYMBOL, quantity=qty)
    except BinanceAPIException as e:
        tg(f"❌ Market {side} error: {e}")
        return None

# ==========================
# STATE
# ==========================
state = {
    "positions": [],
    "dca_filled": 0,
    "dca_step": None,
    "next_dca_price": None,
    "regime": "flat",
    "bias": "long",
    "avg_price": None,
    "total_qty": 0.0,
    "total_cost": 0.0,
    "fees": 0.0,
    "tp_price": None,
    "trail_peak": None,
    "stop_price": None,
    "profit_total": 0.0
}

def reset_position():
    state["positions"].clear()
    state["dca_filled"] = 0
    state["dca_step"] = None
    state["next_dca_price"] = None
    state["avg_price"] = None
    state["total_qty"] = 0.0
    state["total_cost"] = 0.0
    state["fees"] = 0.0
    state["tp_price"] = None
    state["trail_peak"] = None
    state["stop_price"] = None

# ==========================
# CORE
# ==========================
def portfolio_risk_guard():
    usdt, base = get_balances()
    price = get_price()
    pos_val = state["total_qty"] * price
    acc_val = usdt + pos_val
    max_pos_val = acc_val * MAX_POS_RISK_PCT / 100.0
    max_portfolio_val = acc_val * MAX_PORTFOLIO_RISK_PCT / 100.0
    return acc_val, max_pos_val, max_portfolio_val, usdt

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
    return {"ATR": a, "BB
