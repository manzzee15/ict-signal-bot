"""
ICT Signal Scanner (versi gratis, tanpa TradingView)

Alur: ambil candle forex dari Twelve Data (API gratis) -> hitung skor
confluence ICT (Sweep+Delivery, Momentum, Target, FVG Singular,
Premium/Discount) -> kalau grade cukup tinggi, kirim alert ke Telegram.

Didesain untuk dijalankan berkala (cron / GitHub Actions schedule),
bukan proses yang terus menyala.
"""

import os
import json
import time
import logging

import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

PAIRS = [p.strip() for p in os.getenv("PAIRS", "EUR/USD,GBP/USD").split(",") if p.strip()]
TIMEFRAME = os.getenv("TIMEFRAME", "15min")
SWING_LEN = int(os.getenv("SWING_LEN", "5"))
DISP_MULTIPLIER = float(os.getenv("DISP_MULTIPLIER", "1.2"))
SWEEP_LOOKBACK = int(os.getenv("SWEEP_LOOKBACK", "10"))
FVG_SINGULAR_GAP = int(os.getenv("FVG_SINGULAR_GAP", "10"))
MIN_GRADE = os.getenv("MIN_GRADE", "A")
STATE_FILE = os.getenv("STATE_FILE", "state.json")

GRADE_RANK = {"A+": 5, "A": 4, "B": 3, "C": 2, "D": 1}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ict-scanner")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"


def fetch_candles(pair: str, outputsize: int = 100) -> pd.DataFrame:
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": pair,
        "interval": TIMEFRAME,
        "outputsize": outputsize,
        "apikey": TWELVE_DATA_API_KEY,
        "format": "JSON",
    }
    resp = requests.get(url, params=params, timeout=20)
    data = resp.json()
    if "values" not in data:
        raise RuntimeError(f"Gagal ambil data {pair}: {data}")

    df = pd.DataFrame(data["values"]).rename(columns={"datetime": "time"})
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
    df["time"] = pd.to_datetime(df["time"])
    return df.sort_values("time").reset_index(drop=True)


def pivot_high(series: pd.Series, left: int, right: int) -> pd.Series:
    result = pd.Series(index=series.index, dtype=float)
    for i in range(left, len(series) - right):
        window = series.iloc[i - left:i + right + 1]
        if series.iloc[i] == window.max() and (window == series.iloc[i]).sum() == 1:
            result.iloc[i] = series.iloc[i]
    return result


def pivot_low(series: pd.Series, left: int, right: int) -> pd.Series:
    result = pd.Series(index=series.index, dtype=float)
    for i in range(left, len(series) - right):
        window = series.iloc[i - left:i + right + 1]
        if series.iloc[i] == window.min() and (window == series.iloc[i]).sum() == 1:
            result.iloc[i] = series.iloc[i]
    return result


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.rolling(period).mean()


def grade_from_score(score: int) -> str:
    return {5: "A+", 4: "A", 3: "B", 2: "C"}.get(score, "D")


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def send_telegram(text: str) -> bool:
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(TELEGRAM_API_URL, json=payload, timeout=10)
        if not resp.ok:
            logger.error("Gagal kirim Telegram: %s", resp.text)
        return resp.ok
    except requests.RequestException:
        logger.exception("Error koneksi ke Telegram")
        return False


def format_criteria(c1: bool, c2: bool, c3: bool, c4: bool, c5: bool) -> str:
    items = [
        ("Sweep+Delivery", c1),
        ("Momentum", c2),
        ("Target", c3),
        ("FVG Singular", c4),
        ("Zone", c5),
    ]
    return "\n".join(f"{'✅' if ok else '❌'} {name}" for name, ok in items)


def bars_since(mask: pd.Series, upto: int) -> int:
    sub = mask.iloc[: upto + 1]
    idx = sub[sub].index
    return 9999 if len(idx) == 0 else upto - idx[-1]


def fvg_is_singular(mask: pd.Series, upto: int) -> bool:
    sub = mask.iloc[:upto]
    idx = sub[sub].index
    return True if len(idx) == 0 else (upto - idx[-1]) >= FVG_SINGULAR_GAP


def analyze_pair(pair: str, state: dict) -> None:
    df = fetch_candles(pair)
    if len(df) < max(20, SWING_LEN * 2 + 5):
        logger.warning("Data %s terlalu sedikit, skip", pair)
        return

    df["atr"] = atr(df, 14)
    df["swing_high"] = pivot_high(df["high"], SWING_LEN, SWING_LEN)
    df["swing_low"] = pivot_low(df["low"], SWING_LEN, SWING_LEN)
    df["last_swing_high"] = df["swing_high"].ffill()
    df["last_swing_low"] = df["swing_low"].ffill()
    df["eq"] = (df["last_swing_high"] + df["last_swing_low"]) / 2

    df["bull_fvg"] = (df["low"].shift(1) > df["high"].shift(3)) & (df["close"] > df["open"])
    df["bear_fvg"] = (df["high"].shift(1) < df["low"].shift(3)) & (df["close"] < df["open"])
    df["bull_sweep"] = (df["low"] < df["last_swing_low"]) & (df["close"] > df["last_swing_low"])
    df["bear_sweep"] = (df["high"] > df["last_swing_high"]) & (df["close"] < df["last_swing_high"])
    df["bull_disp"] = (df["close"] - df["close"].shift(3)) > (df["atr"] * DISP_MULTIPLIER)
    df["bear_disp"] = (df["close"].shift(3) - df["close"]) > (df["atr"] * DISP_MULTIPLIER)

    i = len(df) - 1  # candle terakhir (dianggap sudah closed dari API)
    row = df.iloc[i]
    results = []

    if bool(row["bull_fvg"]) and i > 0:
        c1 = bars_since(df["bull_sweep"], i - 1) <= SWEEP_LOOKBACK
        c2 = bool(row["bull_disp"])
        c3 = pd.notna(row["last_swing_high"]) and row["last_swing_high"] > row["close"]
        c4 = fvg_is_singular(df["bull_fvg"], i)
        c5 = pd.notna(row["eq"]) and row["close"] < row["eq"]
        score = sum([c1, c2, c3, c4, c5])
        results.append(("LONG Setup", grade_from_score(score), score, (c1, c2, c3, c4, c5)))

    if bool(row["bear_fvg"]) and i > 0:
        c1 = bars_since(df["bear_sweep"], i - 1) <= SWEEP_LOOKBACK
        c2 = bool(row["bear_disp"])
        c3 = pd.notna(row["last_swing_low"]) and row["last_swing_low"] < row["close"]
        c4 = fvg_is_singular(df["bear_fvg"], i)
        c5 = pd.notna(row["eq"]) and row["close"] > row["eq"]
        score = sum([c1, c2, c3, c4, c5])
        results.append(("SHORT Setup", grade_from_score(score), score, (c1, c2, c3, c4, c5)))

    bar_key = str(row["time"])
    pair_state = state.setdefault(pair, {})

    for signal, grade, score, criteria in results:
        if GRADE_RANK[grade] < GRADE_RANK.get(MIN_GRADE, 4):
            continue

        dedupe_key = f"{signal}:{bar_key}"
        if pair_state.get("last_alert_key") == dedupe_key:
            continue  # sudah pernah dikirim untuk candle ini

        emoji = "🟢 LONG" if "LONG" in signal else "🔴 SHORT"
        bar_marker = "🟩" * GRADE_RANK[grade]
        text = (
            f"{emoji} — Grade <b>{grade}</b> {bar_marker}\n"
            f"Pair: <b>{pair}</b> | TF: {TIMEFRAME}\n"
            f"Skor: {score}/5\n"
            f"Harga: {row['close']}\n"
            f"Waktu candle: {row['time']} UTC\n\n"
            f"<b>Checklist:</b>\n{format_criteria(*criteria)}\n\n"
            "<i>Bukan nasihat finansial. Selalu gunakan manajemen risiko.</i>"
        )
        if send_telegram(text):
            pair_state["last_alert_key"] = dedupe_key
            logger.info("Alert terkirim: %s %s grade %s", pair, signal, grade)


def main() -> None:
    if not (TWELVE_DATA_API_KEY and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        raise SystemExit(
            "Isi dulu TWELVE_DATA_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID di .env"
        )

    state = load_state()
    for pair in PAIRS:
        try:
            analyze_pair(pair, state)
        except Exception:
            logger.exception("Gagal proses pair %s", pair)
        time.sleep(1)  # jaga rate limit Twelve Data (8 request/menit di free tier)
    save_state(state)


if __name__ == "__main__":
    main()
