import os
import time
import json
import threading
import random
import urllib.request
from datetime import datetime, timedelta

import ccxt
import pandas as pd
from ta.trend import PSARIndicator
import logging
from market_simulator import MarketSimulator
from signal_sender import SignalSender

# ========== Прямой REST API (MEXC + Binance fallback) ==========
def _rest_get(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def fetch_ohlcv_mexc(symbol="ETHUSDT", interval="1m", limit=200):
    """OHLCV с MEXC REST API."""
    url = f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    raw = _rest_get(url)
    return [[int(d[0]), float(d[1]), float(d[2]), float(d[3]), float(d[4]), float(d[5])] for d in raw]

def fetch_ohlcv_binance(symbol="ETHUSDT", interval="1m", limit=200):
    """OHLCV с Binance REST API (резерв, если MEXC недоступен)."""
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    raw = _rest_get(url)
    return [[int(d[0]), float(d[1]), float(d[2]), float(d[3]), float(d[4]), float(d[5])] for d in raw]

def fetch_price_mexc(symbol="ETHUSDT"):
    """Текущая цена ETH с MEXC REST API."""
    data = _rest_get(f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}")
    return float(data["price"])

def fetch_price_binance(symbol="ETHUSDT"):
    """Текущая цена ETH с Binance REST API."""
    data = _rest_get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}")
    return float(data["price"])

# ========== Конфигурация ==========
# Ключи MEXC (приоритет) или AscendEx (обратная совместимость)
API_KEY    = os.getenv("MEXC_API_KEY",    os.getenv("ASCENDEX_API_KEY", ""))
API_SECRET = os.getenv("MEXC_SECRET",     os.getenv("ASCENDEX_SECRET",  ""))
RUN_IN_PAPER = True
USE_SIMULATOR = os.getenv("USE_SIMULATOR", "0") == "1"

SYMBOL        = "ETH/USDT:USDT"  # MEXC linear perpetual futures
SYMBOL_SPOT   = "ETH/USDT"       # для публичного OHLCV (не требует ключей)
LEVERAGE = 500  # плечо x500 (может быть изменено через API)
ISOLATED = True  # изолированная маржа
POSITION_PERCENT = 0.10  # 10% от доступного баланса
TIMEFRAMES = {"1m": 1, "5m": 5, "30m": 30}  # Установлены 3 таймфрейма: 1м, 5м, 30м
MIN_TRADE_SECONDS = 120  # минимальная длительность сделки 2 минуты
MIN_RANDOM_TRADE_SECONDS = 480  # минимальная случайная длительность сделки 8 минут
MAX_RANDOM_TRADE_SECONDS = 780  # максимальная случайная длительность сделки 13 минут
PAUSE_BETWEEN_TRADES = 0  # пауза между сделками убрана
START_BANK = 100.0  # стартовый банк (для бумажной торговли / учета)
DASHBOARD_MAX = 100
ALLOWED_LEVERAGES = [100, 200, 300, 400, 500]

# ========== Глобальные переменные состояния ==========
state = {
    "balance": START_BANK,
    "available": START_BANK,
    "in_position": False,
    "position": None,  # dict: {side, entry_price, size_base, entry_time}
    "last_trade_time": None,
    "last_1m_dir": None,
    "one_min_flip_count": 0,
    "skip_next_signal": False,  # пропускать следующий сигнал входа
    "trades": [],  # список последних сделок
    "leverage": LEVERAGE,  # текущее плечо (изменяется через API)
}

class TradingBot:
    def __init__(self, telegram_notifier=None):
        self.notifier = telegram_notifier
        self.signal_sender = SignalSender()
        
        if USE_SIMULATOR:
            logging.info("Initializing market simulator")
            self.simulator = MarketSimulator(initial_price=3000, volatility=0.02)
            self.exchange = None
            self.public_exchange = None
        else:
            logging.info("Initializing MEXC exchange connection")
            self.simulator = None

            # Публичный клиент MEXC — для OHLCV/цены (без ключей)
            self.public_exchange = ccxt.mexc({
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
            })

            # Торговый клиент MEXC — для ордеров (нужны ключи)
            self.exchange = ccxt.mexc({
                "apiKey": API_KEY,
                "secret": API_SECRET,
                "enableRateLimit": True,
                "options": {"defaultType": "swap"},
            })

            if API_KEY and API_SECRET:
                try:
                    lev = state.get("leverage", LEVERAGE)
                    if ISOLATED:
                        self.exchange.set_margin_mode('isolated', SYMBOL)
                    self.exchange.set_leverage(lev, SYMBOL)
                except Exception as e:
                    logging.error(f"Failed to configure MEXC exchange: {e}")
        
        self.load_state_from_file()
        
    def save_state_to_file(self):
        try:
            with open("goldantilopaeth500_state.json", "w") as f:
                json.dump(state, f, default=str, indent=2)
        except Exception as e:
            logging.error(f"Save error: {e}")

    def load_state_from_file(self):
        try:
            with open("goldantilopaeth500_state.json", "r") as f:
                data = json.load(f)
                state.update(data)
            # Если позиция открыта, но entry_time слишком старый (> 2 часов) — сбрасываем
            if state.get("in_position") and state.get("position"):
                entry_time_str = state["position"].get("entry_time", "")
                try:
                    entry_dt = datetime.fromisoformat(entry_time_str)
                    age_hours = (datetime.utcnow() - entry_dt).total_seconds() / 3600
                    if age_hours > 2:
                        logging.warning(f"Stale position detected (age: {age_hours:.1f}h), resetting.")
                        state["in_position"] = False
                        state["position"] = None
                        # Возвращаем маржу обратно в available
                        state["available"] = state["balance"]
                except Exception:
                    state["in_position"] = False
                    state["position"] = None
                    state["available"] = state["balance"]
        except:
            pass

    def now(self):
        return datetime.utcnow()

    def fetch_ohlcv_tf(self, tf: str, limit=200):
        try:
            if USE_SIMULATOR and self.simulator:
                ohlcv = self.simulator.fetch_ohlcv(tf, limit=limit)
            else:
                ohlcv = None
                # 1) MEXC REST API
                try:
                    ohlcv = fetch_ohlcv_mexc("ETHUSDT", interval=tf, limit=limit)
                    logging.debug(f"MEXC REST OHLCV {tf}: {len(ohlcv)} candles")
                except Exception as e1:
                    logging.warning(f"MEXC REST OHLCV {tf} failed: {e1}")
                    # 2) Binance REST API (резерв)
                    try:
                        ohlcv = fetch_ohlcv_binance("ETHUSDT", interval=tf, limit=limit)
                        logging.info(f"Binance REST OHLCV {tf}: {len(ohlcv)} candles")
                    except Exception as e2:
                        logging.warning(f"Binance REST OHLCV {tf} failed: {e2}")
                        # 3) ccxt.mexc (последний резерв)
                        try:
                            exc = self.public_exchange if self.public_exchange else self.exchange
                            ohlcv = exc.fetch_ohlcv(SYMBOL_SPOT, timeframe=tf, limit=limit)
                        except Exception as e3:
                            logging.error(f"All OHLCV sources failed for {tf}: {e3}")

            if not ohlcv or len(ohlcv) < 5:
                return None

            df = pd.DataFrame(ohlcv)
            df.columns = ["timestamp", "open", "high", "low", "close", "volume"]
            df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
            return df
        except Exception as e:
            logging.error(f"fetch_ohlcv_tf {tf} error: {e}")
            return None

    def compute_psar(self, df: pd.DataFrame):
        if df is None or len(df) < 5:
            return None
        try:
            psar_ind = PSARIndicator(high=df["high"].astype(float), low=df["low"].astype(float), close=df["close"].astype(float), step=0.05, max_step=0.5)
            return psar_ind.psar()
        except Exception as e:
            logging.error(f"PSAR compute error: {e}")
            return None

    def get_direction_from_psar(self, df: pd.DataFrame):
        psar = self.compute_psar(df)
        if psar is None or len(psar) == 0:
            return None
        last_psar = psar.iloc[-1]
        last_close = float(df["close"].iloc[-1])
        if pd.isna(last_psar):
            return None
        return "long" if last_close > last_psar else "short"

    def get_current_directions(self):
        directions = {}
        for tf in TIMEFRAMES.keys():
            df = self.fetch_ohlcv_tf(tf)
            directions[tf] = self.get_direction_from_psar(df) if df is not None else None
        return directions

    def compute_order_size_usdt(self, balance, price):
        lev = state.get("leverage", LEVERAGE)
        notional = balance * POSITION_PERCENT * lev
        base_amount = notional / price
        return base_amount, notional

    def place_market_order(self, side: str, amount_base: float):
        if RUN_IN_PAPER or not API_KEY:
            price = self.get_current_price()
            entry_time = self.now()
            notional = amount_base * price
            lev = state.get("leverage", LEVERAGE)
            margin = notional / lev
            open_fee = notional * 0.0003
            state["available"] -= (margin + open_fee)
            state["available"] = max(0.0, state["available"])
            state["balance"] -= open_fee
            state["balance"] = max(0.0, state["balance"])
            
            if "telegram_trade_counter" not in state:
                state["telegram_trade_counter"] = 1
            else:
                state["telegram_trade_counter"] += 1
            
            state["in_position"] = True
            state["position"] = {
                "side": "long" if side == "buy" else "short",
                "entry_price": price,
                "size_base": amount_base,
                "notional": notional,
                "margin": margin,
                "entry_time": entry_time.isoformat(),
                "trade_number": state["telegram_trade_counter"]
            }
            
            if self.notifier:
                self.notifier.send_position_opened(state["position"], price, state["position"]["trade_number"], state["balance"])
            
            if side == "buy": self.signal_sender.send_open_long()
            else: self.signal_sender.send_open_short()
            
            return state["position"]
        else:
            try:
                order = self.exchange.create_market_buy_order(SYMBOL, amount_base) if side == "buy" else self.exchange.create_market_sell_order(SYMBOL, amount_base)
                price = self.get_price_from_order(order)
                entry_time = self.now()
                notional = amount_base * price
                lev = state.get("leverage", LEVERAGE)
                margin = notional / lev
                open_fee = notional * 0.0003
                state["available"] -= (margin + open_fee)
                state["balance"] -= open_fee
                state["in_position"] = True
                state["position"] = {
                    "side": "long" if side == "buy" else "short",
                    "entry_price": price,
                    "size_base": amount_base,
                    "notional": notional,
                    "margin": margin,
                    "entry_time": entry_time.isoformat()
                }
                if side == "buy": self.signal_sender.send_open_long()
                else: self.signal_sender.send_open_short()
                return state["position"]
            except Exception as e:
                logging.error(f"Order error: {e}")
                return None

    def get_price_from_order(self, order):
        if not order: return self.get_current_price()
        for field in ['average', 'price']:
            if order.get(field): return float(order[field])
        info = order.get('info', {})
        for field in ['avgPrice', 'price']:
            if info.get(field): return float(info[field])
        return self.get_current_price()

    def close_position(self, close_reason="unknown"):
        if not state["in_position"]: return None
        side = state["position"]["side"]
        size = state["position"]["size_base"]
        
        if RUN_IN_PAPER or not API_KEY:
            price = self.get_current_price()
            entry_price = state["position"]["entry_price"]
            close_notional = size * price
            pnl = (price - entry_price) * size if side == "long" else (entry_price - price) * size
            close_fee = close_notional * 0.0003
            pnl -= close_fee

            state["available"] += state["position"]["margin"] + pnl
            state["available"] = max(0.0, state["available"])
            state["balance"] = state["available"]
            
            trade = {
                "time": self.now().isoformat(),
                "side": side,
                "entry_price": entry_price,
                "exit_price": price,
                "size_base": size,
                "pnl": pnl,
                "duration": self.calculate_duration(state["position"]["entry_time"]),
                "close_reason": close_reason
            }
            
            if self.notifier:
                self.notifier.send_position_closed(trade, state["position"].get("trade_number", 1), state["balance"])
            
            self.append_trade(trade)
            state["in_position"] = False
            state["position"] = None
            self.save_state_to_file()
            return trade
        else:
            try:
                order = self.exchange.create_market_sell_order(SYMBOL, size) if side == "long" else self.exchange.create_market_buy_order(SYMBOL, size)
                exit_price = self.get_price_from_order(order)
                entry_price = state["position"]["entry_price"]
                close_notional = size * exit_price
                pnl = (exit_price - entry_price) * size if side == "long" else (entry_price - exit_price) * size
                pnl -= close_notional * 0.0003
                state["available"] += state["position"]["margin"] + pnl
                state["available"] = max(0.0, state["available"])
                state["balance"] = state["available"]
                trade = {
                    "time": self.now().isoformat(),
                    "side": side,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl": pnl,
                    "duration": self.calculate_duration(state["position"]["entry_time"]),
                    "close_reason": close_reason
                }
                self.append_trade(trade)
                state["in_position"] = False
                state["position"] = None
                self.save_state_to_file()
                return trade
            except Exception as e:
                logging.error(f"Close error: {e}")
                return None

    def calculate_duration(self, entry_time_str):
        try:
            duration = self.now() - datetime.fromisoformat(entry_time_str.replace('Z', '+00:00'))
            m, s = divmod(int(duration.total_seconds()), 60)
            return f"{m}м {s}с" if m > 0 else f"{s}с"
        except: return "N/A"

    def append_trade(self, trade):
        state["trades"].insert(0, trade)
        state["trades"] = state["trades"][:DASHBOARD_MAX]

    def get_current_price(self):
        try:
            if USE_SIMULATOR:
                return self.simulator.get_current_price()
            # 1) MEXC REST
            try:
                return fetch_price_mexc("ETHUSDT")
            except Exception as e1:
                logging.warning(f"MEXC REST price failed: {e1}")
                # 2) Binance REST
                try:
                    return fetch_price_binance("ETHUSDT")
                except Exception as e2:
                    logging.warning(f"Binance REST price failed: {e2}")
                    # 3) ccxt
                    exc = self.public_exchange if self.public_exchange else self.exchange
                    try:
                        ticker = exc.fetch_ticker(SYMBOL_SPOT)
                    except Exception:
                        ticker = exc.fetch_ticker("ETH/USDT:USDT")
                    return float(ticker["last"])
        except Exception:
            return 3000.0

    def strategy_loop(self, should_continue=lambda: True):
        while should_continue():
            try:
                dirs = self.get_current_directions()
                state["sar_directions"] = dirs
                if any(d is None for d in dirs.values()):
                    time.sleep(5)
                    continue

                d1, d5, d30 = dirs["1m"], dirs["5m"], dirs["30m"]
                logging.info(f"[{self.now()}] SAR: 1m={d1}, 5m={d5}, 30m={d30}")

                if state["in_position"]:
                    if d1 != state["position"]["side"]:
                        self.close_position(close_reason="sar_reversal")
                        state["skip_next_signal"] = True
                        self.save_state_to_file()
                else:
                    if state["last_1m_dir"] and state["last_1m_dir"] != d1:
                        state["skip_next_signal"] = False
                    state["last_1m_dir"] = d1
                    
                    if d1 and d1 == d5 == d30 and not state["skip_next_signal"]:
                        price = self.get_current_price()
                        size, _ = self.compute_order_size_usdt(state["balance"], price)
                        self.place_market_order("buy" if d1 == "long" else "sell", size)
                        self.save_state_to_file()
                
                time.sleep(5)
            except Exception as e:
                logging.error(f"Strategy loop error: {e}")
                time.sleep(5)
