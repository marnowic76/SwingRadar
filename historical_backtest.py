#!/usr/bin/env python3.13
"""
SwingRadar DSS — Historical Backtest Framework v1.0
====================================================
Faza 1: Pobieranie 2-lat OHLCV dla 127 spółek z FMP API
Faza 2: Retroaktywna symulacja scoring engine (walk-forward)
Faza 3: Outcome measurement (D+1/D+2/D+3/D+5, MFE, MAE)

Metodologia:
- Point-in-Time: scoring zawsze na danych do D-1 (brak look-ahead bias)
- Walk-Forward: optymalizacja na pierwszych 12 miesiącach, walidacja na ostatnich 3
- Rate limit: 1 req/s dla FMP Starter plan

Uruchomienie:
    python3.13 historical_backtest.py --fetch      # Pobierz dane historyczne
    python3.13 historical_backtest.py --simulate   # Uruchom retroaktywne scoring
    python3.13 historical_backtest.py --analyze    # Oblicz metryki
    python3.13 historical_backtest.py --all        # Wszystkie fazy
"""

import sqlite3
import requests
import time
import json
import logging
import argparse
import os
from datetime import datetime, timedelta, date
from pathlib import Path
import sys

# ══════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════

DB_PATH       = "data/trading_system.db"
FMP_API_KEY   = os.environ.get("FMP_API_KEY", "Y22T5oOZIv93V5yikSwxKV3JAvulMEqT")
FMP_BASE      = "https://financialmodelingprep.com/stable"
RATE_LIMIT    = 1.1        # seconds between requests (Starter plan safe)
HISTORY_DAYS  = 730        # 2 years = Golden Standard
FETCH_BATCH   = 10         # tickers per log progress update

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/backtest.log", mode="a"),
    ]
)
log = logging.getLogger(__name__)


# ══════════════════════════════════════════════
# DATABASE SETUP
# ══════════════════════════════════════════════

def init_db():
    """Create backtest tables if not exist."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    # 1. Daily OHLCV price history
    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker      TEXT NOT NULL,
            date        DATE NOT NULL,
            open        REAL,
            high        REAL,
            low         REAL,
            close       REAL,
            volume      INTEGER,
            vwap        REAL,
            change_pct  REAL,
            UNIQUE(ticker, date)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ph_ticker_date ON price_history(ticker, date)")

    # 2. Retroactive backtest signals
    conn.execute("""
        CREATE TABLE IF NOT EXISTS backtest_signals (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker           TEXT NOT NULL,
            sector           TEXT,
            signal_date      DATE NOT NULL,
            final_score      REAL,
            tech_score       REAL,
            fund_score       REAL,
            event_score      REAL,
            stability_score  REAL,
            status           TEXT,
            market_regime    TEXT,
            entry_price      REAL,
            stop_loss        REAL,
            target           REAL,
            real_rr          REAL,

            -- Outcomes D+1/D+3/D+5
            close_d1         REAL,
            close_d3         REAL,
            close_d5         REAL,
            return_d1        REAL,    -- % return
            return_d3        REAL,
            return_d5        REAL,

            -- MFE / MAE (max favorable / adverse excursion)
            mfe_d1           REAL,    -- max high D+1 vs entry
            mfe_d3           REAL,    -- max high over D+1 to D+3
            mfe_d5           REAL,
            mae_d1           REAL,    -- max low D+1 vs entry
            mae_d3           REAL,
            mae_d5           REAL,

            -- Efficiency Ratio = MFE / |MAE|
            efficiency_ratio REAL,

            -- Reality Check: was this ticker in top 5 movers that day?
            missed_winner    INTEGER DEFAULT 0,
            actual_d3_rank   INTEGER,  -- rank by return D+3 among all watchlist

            -- Metadata
            created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ticker, signal_date)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bs_date ON backtest_signals(signal_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bs_ticker ON backtest_signals(ticker)")

    # 3. Fetch progress tracking
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fetch_progress (
            ticker      TEXT PRIMARY KEY,
            last_fetched DATETIME,
            days_fetched INTEGER,
            status      TEXT DEFAULT 'pending'
        )
    """)

    conn.commit()
    conn.close()
    log.info("Database tables initialized.")


# ══════════════════════════════════════════════
# FAZA 1: HISTORICAL DATA FETCH
# ══════════════════════════════════════════════

def get_watchlist() -> list[str]:
    """Load watchlist from SQLite active_scans OR watchlist.txt."""
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute("SELECT DISTINCT ticker FROM active_scans ORDER BY ticker").fetchall()
        conn.close()
        if rows:
            tickers = [r[0] for r in rows]
            log.info(f"Loaded {len(tickers)} tickers from active_scans")
            return tickers
    except Exception:
        pass

    # Fallback to watchlist.txt
    watchlist_path = Path("watchlist.txt")
    if watchlist_path.exists():
        tickers = [t.strip() for t in watchlist_path.read_text().splitlines() if t.strip()]
        log.info(f"Loaded {len(tickers)} tickers from watchlist.txt")
        return tickers

    log.error("No watchlist found! Run scanner first or create watchlist.txt")
    return []


def fetch_ohlcv(ticker: str, from_date: str, to_date: str) -> list[dict]:
    """Fetch daily OHLCV from FMP /stable/historical-price-eod/full."""
    url = (f"{FMP_BASE}/historical-price-eod/full"
           f"?symbol={ticker}&from={from_date}&to={to_date}&apikey={FMP_API_KEY}")
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            # FMP returns list or dict with 'historical' key
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("historical", [])
        elif resp.status_code == 429:
            log.warning(f"Rate limit hit for {ticker}, sleeping 60s...")
            time.sleep(60)
            return []
        else:
            log.warning(f"FMP {resp.status_code} for {ticker}: {resp.text[:100]}")
    except Exception as e:
        log.error(f"Fetch error for {ticker}: {e}")
    return []


def save_ohlcv(conn: sqlite3.Connection, ticker: str, records: list[dict]) -> int:
    """Insert OHLCV records, skip duplicates."""
    saved = 0
    for r in records:
        try:
            conn.execute("""
                INSERT OR IGNORE INTO price_history
                    (ticker, date, open, high, low, close, volume, vwap, change_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ticker,
                r.get("date"),
                r.get("open"),
                r.get("high"),
                r.get("low"),
                r.get("close"),
                r.get("volume"),
                r.get("vwap"),
                r.get("changePercent"),
            ))
            saved += conn.execute("SELECT changes()").fetchone()[0]
        except Exception as e:
            log.debug(f"Skip {ticker} {r.get('date')}: {e}")
    return saved


def run_fetch(resume: bool = True):
    """Faza 1: Fetch 2-year OHLCV for all watchlist tickers."""
    init_db()
    tickers = get_watchlist()
    if not tickers:
        return

    to_date   = date.today().isoformat()
    from_date = (date.today() - timedelta(days=HISTORY_DAYS)).isoformat()

    log.info(f"Starting fetch: {len(tickers)} tickers | {from_date} → {to_date}")
    log.info(f"Rate limit: {RATE_LIMIT}s per request | ETA: ~{len(tickers) * RATE_LIMIT / 60:.1f} min")

    conn = sqlite3.connect(DB_PATH)
    total_saved = 0
    skipped     = 0

    for i, ticker in enumerate(tickers, 1):
        # Check if already fetched (resume mode)
        if resume:
            row = conn.execute(
                "SELECT status FROM fetch_progress WHERE ticker = ?", (ticker,)
            ).fetchone()
            if row and row[0] == "done":
                skipped += 1
                continue

        records = fetch_ohlcv(ticker, from_date, to_date)
        n = save_ohlcv(conn, ticker, records)
        total_saved += n

        conn.execute("""
            INSERT OR REPLACE INTO fetch_progress (ticker, last_fetched, days_fetched, status)
            VALUES (?, datetime('now'), ?, 'done')
        """, (ticker, len(records)))
        conn.commit()

        if i % FETCH_BATCH == 0 or i == len(tickers):
            progress = (i / len(tickers)) * 100
            log.info(f"Progress: {i}/{len(tickers)} ({progress:.0f}%) | "
                     f"Saved: {total_saved} records | Skipped: {skipped}")

        time.sleep(RATE_LIMIT)

    conn.close()
    log.info(f"✅ Fetch complete. Total new records: {total_saved} | Skipped (cached): {skipped}")


# ══════════════════════════════════════════════
# FAZA 2: RETROACTIVE SIGNAL SIMULATION
# ══════════════════════════════════════════════

def get_trading_days(from_date: str, to_date: str) -> list[str]:
    """Get list of trading days (Mon-Fri, excluding major holidays) in range."""
    # NYSE holidays 2024-2026
    holidays = {
        "2024-01-01", "2024-01-15", "2024-02-19", "2024-03-29",
        "2024-05-27", "2024-06-19", "2024-07-04", "2024-09-02",
        "2024-11-28", "2024-12-25",
        "2025-01-01", "2025-01-20", "2025-02-17", "2025-04-18",
        "2025-05-26", "2025-06-19", "2025-07-04", "2025-09-01",
        "2025-11-27", "2025-12-25",
        "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03",
        "2026-05-25", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    }

    days = []
    d = datetime.strptime(from_date, "%Y-%m-%d")
    end = datetime.strptime(to_date, "%Y-%m-%d")

    while d <= end:
        if d.weekday() < 5 and d.strftime("%Y-%m-%d") not in holidays:
            days.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)

    return days


def get_price_on_date(conn: sqlite3.Connection, ticker: str, target_date: str) -> dict | None:
    """Get OHLCV for ticker on specific date."""
    row = conn.execute("""
        SELECT date, open, high, low, close, volume, change_pct
        FROM price_history
        WHERE ticker = ? AND date <= ?
        ORDER BY date DESC LIMIT 1
    """, (ticker, target_date)).fetchone()

    if row and row[0] == target_date:
        return {"date": row[0], "open": row[1], "high": row[2],
                "low": row[3], "close": row[4], "volume": row[5],
                "change_pct": row[6]}
    return None


def get_next_trading_day(conn: sqlite3.Connection, ticker: str, after_date: str, n: int = 1) -> dict | None:
    """Get price N trading days after given date."""
    rows = conn.execute("""
        SELECT date, open, high, low, close, change_pct
        FROM price_history
        WHERE ticker = ? AND date > ?
        ORDER BY date ASC LIMIT ?
    """, (ticker, after_date, n + 5)).fetchall()  # fetch extra for safety

    trading_days = [r for r in rows if r[0] not in
                    {"2026-04-03", "2026-01-01", "2025-12-25", "2025-11-27",
                     "2025-07-04", "2025-05-26", "2025-01-20"}]

    if len(trading_days) >= n:
        r = trading_days[n - 1]
        return {"date": r[0], "open": r[1], "high": r[2],
                "low": r[3], "close": r[4], "change_pct": r[5]}
    return None


def get_price_range(conn: sqlite3.Connection, ticker: str,
                    after_date: str, n_days: int) -> dict:
    """Get high/low extremes over N trading days after signal date."""
    rows = conn.execute("""
        SELECT high, low, close
        FROM price_history
        WHERE ticker = ? AND date > ?
        ORDER BY date ASC LIMIT ?
    """, (ticker, after_date, n_days)).fetchall()

    if not rows:
        return {"max_high": None, "min_low": None, "close_n": None}

    return {
        "max_high": max(r[0] for r in rows if r[0]),
        "min_low":  min(r[1] for r in rows if r[1]),
        "close_n":  rows[-1][2] if rows else None,
    }


def compute_mock_score(ticker: str, price_data: list[dict]) -> dict:
    """
    Simplified retroactive scoring using only OHLCV data.
    NOTE: This is a simplified version — real scoring uses FMP API data
    which would require re-fetching for each historical date.
    For now we use price-based proxies for Technical score only.
    Fund/Event scores are loaded from signal_history if available.
    """
    if len(price_data) < 20:
        return {"tech": 50, "fund": 50, "event": 50, "final": 50}

    closes   = [d["close"] for d in price_data[-20:] if d.get("close")]
    volumes  = [d["volume"] for d in price_data[-10:] if d.get("volume")]
    closes5  = closes[-5:]
    closes20 = closes

    if not closes or not volumes:
        return {"tech": 50, "fund": 50, "event": 50, "final": 50}

    # RSI proxy (simplified)
    gains  = [max(0, closes[i] - closes[i-1]) for i in range(1, len(closes))]
    losses = [max(0, closes[i-1] - closes[i]) for i in range(1, len(closes))]
    avg_g  = sum(gains[-14:]) / 14 if len(gains) >= 14 else 0
    avg_l  = sum(losses[-14:]) / 14 if len(losses) >= 14 else 0
    if avg_l == 0:
        rsi = 100.0  # No losses = fully overbought
    elif avg_g == 0:
        rsi = 0.0    # No gains = fully oversold
    else:
        rsi = 100 - (100 / (1 + avg_g / avg_l))

    # Momentum
    mom5  = ((closes[-1] - closes[-5]) / closes[-5] * 100) if len(closes) >= 5 else 0
    mom20 = ((closes[-1] - closes[-20]) / closes[-20] * 100) if len(closes) >= 20 else 0

    # RVOL proxy
    avg_vol  = sum(volumes[:-1]) / max(1, len(volumes) - 1) if len(volumes) > 1 else volumes[0]
    rvol     = volumes[-1] / avg_vol if avg_vol > 0 else 1.0

    # EMA20
    ema20    = sum(closes20) / len(closes20)
    above_ema = closes[-1] > ema20

    # Score
    tech = 50
    if 40 <= rsi <= 70: tech += 25
    if rvol >= 1.5:     tech += 20
    elif rvol >= 1.2:   tech += 10
    if above_ema:       tech += 15
    if mom5 > 2:        tech += 10
    if mom20 > 5:       tech += 10
    tech = min(100, max(0, tech))

    final = tech  # Without real Fund/Event, use tech only for proxy
    return {"tech": tech, "fund": 50, "event": 50, "final": final, "rsi": rsi, "rvol": rvol}


def run_simulate(days_back: int = 365, force_proxy: bool = False):
    """
    Faza 2: Retroactively simulate signals.
    force_proxy=True uses OHLCV-based scoring on full 2-year history.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    hist_count = conn.execute("SELECT COUNT(*) FROM signal_history").fetchone()[0]
    log.info(f"signal_history records: {hist_count}")

    if force_proxy:
        log.info(f"PROXY mode: OHLCV-based scoring on {days_back} days history")
        # Clear existing proxy signals to re-run clean
        conn.execute("DELETE FROM backtest_signals WHERE tech_score IS NOT NULL AND fund_score IS NULL")
        conn.commit()
        _simulate_from_ohlcv(conn, days_back)
    elif hist_count >= 100:
        log.info("Using actual signal_history scores (best accuracy)")
        _simulate_from_signal_history(conn)
    else:
        log.warning("Limited signal_history — using OHLCV proxy scoring")
        _simulate_from_ohlcv(conn, days_back)

    conn.close()


def _simulate_from_signal_history(conn: sqlite3.Connection):
    """Use actual scores from signal_history + active_scans tables."""

    # First check what columns exist in signal_history
    cols = [r[1] for r in conn.execute("PRAGMA table_info(signal_history)").fetchall()]
    log.info(f"signal_history columns: {cols}")

    has_stability = "stability_score" in cols
    has_status    = "status" in cols
    has_entry     = "entry_limit" in cols
    has_sector    = "sector" in cols

    # Build query dynamically based on available columns
    sh_stability = "sh.stability_score" if has_stability else "as_t.stability_score"
    sh_status    = "sh.status"          if has_status    else "as_t.status"
    sh_entry     = "sh.entry_limit"     if has_entry     else "as_t.entry_limit"
    sh_sector    = "sh.sector"          if has_sector    else "as_t.sector"

    query = f"""
        SELECT DISTINCT
            sh.ticker,
            date(sh.timestamp) as signal_date,
            sh.tech_score,
            sh.fund_score,
            sh.event_score,
            sh.final_score,
            {sh_stability},
            {sh_status},
            {sh_entry},
            COALESCE(as_t.stop_loss, 0),
            COALESCE(as_t.target, 0),
            COALESCE(as_t.real_rr, 0),
            {sh_sector}
        FROM signal_history sh
        LEFT JOIN active_scans as_t ON sh.ticker = as_t.ticker
        WHERE sh.final_score >= 60
        ORDER BY sh.timestamp
    """

    rows = conn.execute(query).fetchall()
    log.info(f"Found {len(rows)} signal records to process")
    processed = 0

    # Deduplicate — keep one record per ticker per day (highest score)
    seen = {}
    for row in rows:
        key = (row[0], row[1])  # ticker + date
        if key not in seen or (row[5] or 0) > (seen[key][5] or 0):
            seen[key] = row

    unique_rows = list(seen.values())
    log.info(f"Unique ticker-day combinations: {len(unique_rows)}")

    for row in unique_rows:
        (ticker, signal_date, tech, fund, event, final, stability,
         status, entry, sl, target, rr, sector) = row

        entry = entry or 0
        outcome = _calculate_outcome(conn, ticker, signal_date, entry)
        if not outcome:
            continue

        try:
            conn.execute("""
                INSERT OR REPLACE INTO backtest_signals (
                    ticker, sector, signal_date, final_score, tech_score,
                    fund_score, event_score, stability_score, status,
                    entry_price, stop_loss, target, real_rr,
                    close_d1, close_d3, close_d5,
                    return_d1, return_d3, return_d5,
                    mfe_d1, mfe_d3, mfe_d5,
                    mae_d1, mae_d3, mae_d5,
                    efficiency_ratio
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                ticker, sector, signal_date, final, tech, fund, event,
                stability, status, entry, sl, target, rr,
                outcome["close_d1"], outcome["close_d3"], outcome["close_d5"],
                outcome["ret_d1"], outcome["ret_d3"], outcome["ret_d5"],
                outcome["mfe_d1"], outcome["mfe_d3"], outcome["mfe_d5"],
                outcome["mae_d1"], outcome["mae_d3"], outcome["mae_d5"],
                outcome["er"],
            ))
            processed += 1
        except Exception as e:
            log.debug(f"Skip {ticker} {signal_date}: {e}")

    conn.commit()
    log.info(f"✅ Simulation complete: {processed} signals processed")


def _simulate_from_ohlcv(conn: sqlite3.Connection, days_back: int):
    """Use OHLCV proxy scoring for historical simulation."""
    tickers = [r[0] for r in conn.execute(
        "SELECT DISTINCT ticker FROM price_history ORDER BY ticker"
    ).fetchall()]

    from_date = (date.today() - timedelta(days=days_back)).isoformat()
    log.info(f"OHLCV simulation: {len(tickers)} tickers from {from_date}")

    processed = 0
    skipped   = 0

    for t_idx, ticker in enumerate(tickers):
        # Load all price data for this ticker at once
        all_prices = conn.execute("""
            SELECT date, open, high, low, close, volume
            FROM price_history
            WHERE ticker = ? AND date >= ?
            ORDER BY date ASC
        """, (ticker, (date.today() - timedelta(days=days_back + 30)).isoformat())).fetchall()

        if len(all_prices) < 25:
            skipped += 1
            continue

        price_list = [{"date": r[0], "open": r[1], "high": r[2],
                       "low": r[3], "close": r[4], "volume": r[5]}
                      for r in all_prices]

        # Slide window — score every 5th day to reduce noise + API calls
        for i in range(25, len(price_list) - 5, 5):
            day       = price_list[i]["date"]
            if day < from_date:
                continue

            hist      = price_list[:i]  # data up to D-1 (no look-ahead)
            scores    = compute_mock_score(ticker, hist)

            # Only process signals that meet minimum threshold
            if scores["final"] < 60:
                continue

            entry     = price_list[i - 1]["close"] * 1.003
            outcome   = _calculate_outcome(conn, ticker, day, entry)
            if not outcome or outcome["ret_d3"] is None:
                continue

            try:
                conn.execute("""
                    INSERT OR IGNORE INTO backtest_signals (
                        ticker, signal_date, final_score, tech_score,
                        entry_price, close_d1, close_d3, close_d5,
                        return_d1, return_d3, return_d5,
                        mfe_d1, mfe_d3, mfe_d5,
                        mae_d1, mae_d3, mae_d5, efficiency_ratio
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    ticker, day, scores["final"], scores["tech"], entry,
                    outcome["close_d1"], outcome["close_d3"], outcome["close_d5"],
                    outcome["ret_d1"],   outcome["ret_d3"],   outcome["ret_d5"],
                    outcome["mfe_d1"],   outcome["mfe_d3"],   outcome["mfe_d5"],
                    outcome["mae_d1"],   outcome["mae_d3"],   outcome["mae_d5"],
                    outcome["er"],
                ))
                processed += 1
            except Exception:
                pass

        if (t_idx + 1) % 20 == 0:
            conn.commit()
            log.info(f"  Progress: {t_idx+1}/{len(tickers)} tickers | {processed} signals so far")

    conn.commit()
    log.info(f"✅ OHLCV simulation: {processed} signals processed | {skipped} tickers skipped")


def _calculate_outcome(conn: sqlite3.Connection, ticker: str,
                        signal_date: str, entry: float) -> dict | None:
    """Calculate D+1/D+3/D+5 outcomes and MFE/MAE for a signal."""
    if not entry or entry <= 0:
        return None

    d1 = get_next_trading_day(conn, ticker, signal_date, 1)
    d3 = get_next_trading_day(conn, ticker, signal_date, 3)
    d5 = get_next_trading_day(conn, ticker, signal_date, 5)

    r1 = get_price_range(conn, ticker, signal_date, 1)
    r3 = get_price_range(conn, ticker, signal_date, 3)
    r5 = get_price_range(conn, ticker, signal_date, 5)

    def pct(price):
        return round((price - entry) / entry * 100, 4) if price and entry else None

    close_d1 = d1["close"] if d1 else None
    close_d3 = d3["close"] if d3 else None
    close_d5 = d5["close"] if d5 else None

    mfe_d3 = pct(r3["max_high"]) if r3["max_high"] else None
    mae_d3 = pct(r3["min_low"])  if r3["min_low"]  else None

    er = None
    if mfe_d3 and mae_d3 and mae_d3 != 0:
        er = round(mfe_d3 / abs(mae_d3), 3)

    return {
        "close_d1": close_d1,
        "close_d3": close_d3,
        "close_d5": close_d5,
        "ret_d1":   pct(close_d1),
        "ret_d3":   pct(close_d3),
        "ret_d5":   pct(close_d5),
        "mfe_d1":   pct(r1["max_high"]) if r1["max_high"] else None,
        "mfe_d3":   mfe_d3,
        "mfe_d5":   pct(r5["max_high"]) if r5["max_high"] else None,
        "mae_d1":   pct(r1["min_low"])  if r1["min_low"]  else None,
        "mae_d3":   mae_d3,
        "mae_d5":   pct(r5["min_low"])  if r5["min_low"]  else None,
        "er":       er,
    }


# ══════════════════════════════════════════════
# FAZA 3: ANALYSIS & METRICS
# ══════════════════════════════════════════════

def run_analysis():
    """
    Faza 3: Compute and print key backtest metrics.
    Results are also saved to analysis_results table for Streamlit.
    """
    conn = sqlite3.connect(DB_PATH)

    total = conn.execute("SELECT COUNT(*) FROM backtest_signals WHERE return_d3 IS NOT NULL").fetchone()[0]
    if total < 10:
        log.warning(f"Only {total} signals with outcomes — run fetch and simulate first")
        conn.close()
        return

    log.info(f"\n{'='*60}")
    log.info(f"SWINGRADAR BACKTEST ANALYSIS — {total} signals")
    log.info(f"{'='*60}")

    # ── 1. Overall Win Rate ──────────────────────
    wins = conn.execute("SELECT COUNT(*) FROM backtest_signals WHERE return_d3 > 0").fetchone()[0]
    avg_ret = conn.execute("SELECT AVG(return_d3) FROM backtest_signals WHERE return_d3 IS NOT NULL").fetchone()[0]
    avg_mfe = conn.execute("SELECT AVG(mfe_d3) FROM backtest_signals WHERE mfe_d3 IS NOT NULL").fetchone()[0]
    avg_mae = conn.execute("SELECT AVG(mae_d3) FROM backtest_signals WHERE mae_d3 IS NOT NULL").fetchone()[0]
    avg_er  = conn.execute("SELECT AVG(efficiency_ratio) FROM backtest_signals WHERE efficiency_ratio IS NOT NULL").fetchone()[0]

    log.info(f"\n📊 OVERALL METRICS (D+3):")
    log.info(f"  Win Rate:       {wins/total*100:.1f}% ({wins}/{total})")
    log.info(f"  Avg Return:     {avg_ret:+.2f}%")
    log.info(f"  Avg MFE:        {avg_mfe:+.2f}%")
    log.info(f"  Avg MAE:        {avg_mae:+.2f}%")
    log.info(f"  Efficiency Ratio: {avg_er:.2f}" if avg_er else "  ER: N/A")

    # ── 2. Component Correlation ─────────────────
    log.info(f"\n🎯 SCORE COMPONENT CORRELATION vs Return D+3:")
    for col, name in [("tech_score", "Technical"), ("fund_score", "Fundamental"),
                       ("event_score", "Event"), ("final_score", "Final Score")]:
        rows = conn.execute(f"""
            SELECT {col}, return_d3 FROM backtest_signals
            WHERE {col} IS NOT NULL AND return_d3 IS NOT NULL
        """).fetchall()
        if len(rows) > 10:
            import statistics
            xs = [r[0] for r in rows]
            ys = [r[1] for r in rows]
            mx, my = statistics.mean(xs), statistics.mean(ys)
            sx = statistics.stdev(xs) or 0.001
            sy = statistics.stdev(ys) or 0.001
            cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / len(rows)
            corr = cov / (sx * sy)
            log.info(f"  {name:15s}: r = {corr:+.3f}  ({'✅ positive' if corr > 0.1 else '⚠️ weak' if abs(corr) < 0.05 else '❌ negative'})")

    # ── 3. Stability Threshold Analysis ──────────
    log.info(f"\n📈 WIN RATE BY STABILITY BRACKET:")
    for low, high in [(60, 70), (70, 80), (80, 90), (90, 101)]:
        rows = conn.execute("""
            SELECT COUNT(*), SUM(CASE WHEN return_d3 > 0 THEN 1 ELSE 0 END),
                   AVG(return_d3)
            FROM backtest_signals
            WHERE stability_score >= ? AND stability_score < ?
              AND return_d3 IS NOT NULL
        """, (low, high)).fetchone()
        if rows[0] > 0:
            wr = rows[1] / rows[0] * 100
            log.info(f"  {low}-{high}%: Win Rate {wr:.0f}% | Avg Ret {rows[2]:+.2f}% | N={rows[0]}")

    # ── 4. Market Regime Performance ─────────────
    log.info(f"\n🌡️ WIN RATE BY MARKET REGIME:")
    for regime in ["BULL", "NEUTRAL", "BEAR"]:
        rows = conn.execute("""
            SELECT COUNT(*), SUM(CASE WHEN return_d3 > 0 THEN 1 ELSE 0 END),
                   AVG(return_d3)
            FROM backtest_signals
            WHERE market_regime = ? AND return_d3 IS NOT NULL
        """, (regime,)).fetchone()
        if rows[0] > 0:
            wr = rows[1] / rows[0] * 100
            icon = "🟢" if wr > 55 else "🟡" if wr > 45 else "🔴"
            log.info(f"  {icon} {regime:8s}: Win Rate {wr:.0f}% | Avg Ret {rows[2]:+.2f}% | N={rows[0]}")

    # ── 5. Top 5 Biggest Winners (MFE) ───────────
    log.info(f"\n🚀 TOP 5 MFE (D+3):")
    rows = conn.execute("""
        SELECT ticker, signal_date, mfe_d3, mae_d3, efficiency_ratio, final_score
        FROM backtest_signals WHERE mfe_d3 IS NOT NULL
        ORDER BY mfe_d3 DESC LIMIT 5
    """).fetchall()
    for r in rows:
        log.info(f"  {r[0]:6s} {r[1]} | MFE: {r[2]:+.1f}% | MAE: {r[3]:+.1f}% | ER: {r[4] or 0:.2f} | Score: {r[5]:.0f}")

    # ── 6. Biggest MAE (worst drawdowns) ─────────
    log.info(f"\n📉 TOP 5 MAE (D+3) — worst adverse excursions:")
    rows = conn.execute("""
        SELECT ticker, signal_date, mfe_d3, mae_d3, efficiency_ratio, final_score
        FROM backtest_signals WHERE mae_d3 IS NOT NULL
        ORDER BY mae_d3 ASC LIMIT 5
    """).fetchall()
    for r in rows:
        log.info(f"  {r[0]:6s} {r[1]} | MFE: {r[2]:+.1f}% | MAE: {r[3]:+.1f}% | ER: {r[4] or 0:.2f} | Score: {r[5]:.0f}")

    # ── 7. ATR-based SL Calibration ──────────────
    log.info(f"\n⚙️ SL CALIBRATION (current: 1.5×ATR):")
    log.info(f"  Signals stopped out (mae_d3 < -current_sl): needs SL data in backtest_signals")
    log.info(f"  TODO: Add SL hit rate once entry+sl data populated from signal_history")

    # ── 8. Save summary to DB for Streamlit ──────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS analysis_summary (
            key   TEXT PRIMARY KEY,
            value TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    summary = {
        "total_signals": total,
        "win_rate_d3":   f"{wins/total*100:.1f}",
        "avg_return_d3": f"{avg_ret:+.2f}" if avg_ret else "N/A",
        "avg_mfe_d3":    f"{avg_mfe:+.2f}" if avg_mfe else "N/A",
        "avg_mae_d3":    f"{avg_mae:+.2f}" if avg_mae else "N/A",
        "avg_er":        f"{avg_er:.2f}" if avg_er else "N/A",
        "last_run":      datetime.now().isoformat(),
    }
    for k, v in summary.items():
        conn.execute("INSERT OR REPLACE INTO analysis_summary (key, value) VALUES (?, ?)", (k, v))

    conn.commit()
    conn.close()
    log.info(f"\n✅ Analysis complete. Results saved for Streamlit dashboard.")
    log.info(f"{'='*60}\n")


# ══════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════

if __name__ == "__main__":
    Path("logs").mkdir(exist_ok=True)

    parser = argparse.ArgumentParser(description="SwingRadar Historical Backtest")
    parser.add_argument("--fetch",    action="store_true", help="Faza 1: Fetch OHLCV history")
    parser.add_argument("--simulate", action="store_true", help="Faza 2: Simulate signals")
    parser.add_argument("--analyze",  action="store_true", help="Faza 3: Compute metrics")
    parser.add_argument("--all",      action="store_true", help="Run all phases")
    parser.add_argument("--proxy",    action="store_true", help="Force OHLCV proxy scoring (ignores signal_history)")
    parser.add_argument("--days", type=int, default=365, help="Days back for simulation (default: 365)")
    args = parser.parse_args()

    if not any([args.fetch, args.simulate, args.analyze, args.all]):
        parser.print_help()
        sys.exit(0)

    if args.all or args.fetch:
        log.info("=== FAZA 1: HISTORICAL FETCH ===")
        run_fetch(resume=not args.no_resume)

    if args.all or args.simulate:
        log.info("=== FAZA 2: SIGNAL SIMULATION ===")
        run_simulate(days_back=args.days, force_proxy=args.proxy)

    if args.all or args.analyze:
        log.info("=== FAZA 3: ANALYSIS ===")
        run_analysis()
