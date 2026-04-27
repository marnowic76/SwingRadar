"""
SwingRadar V2.44 - Daemon (Główny Robot Skanujący)

ZMIANY V2.44:
- [FIX] Real RR wyliczany przy każdym skanie (nie tylko w oknie decyzyjnym)
  Entry/SL/Target zawsze aktualne. CONFIRMED tylko w oknie 15:30-16:00 UTC.
ZMIANY V2.43:
- [NEW] Market Regime Filter: BULL/BEAR/NEUTRAL na podstawie sector-performance-snapshot
  BEAR: MIN_MEAN_SCORE w StabilityEngine podniesiony do 70 (tylko najsilniejsze sygnały)
  BULL: MIN_MEAN_SCORE obniżony do 55 (więcej szans w rosnącym rynku)
ZMIANY V2.39:
- [NEW] Float data (floatShares, category) pobierany i przekazywany do tech_data
ZMIANY V2.38:
- [FIX] News scan używa _fetch_news() z /news/stock zamiast /stock-news (404)
ZMIANY V2.37:
- [NEW] run_cycle() pobiera price momentum (1D/5D/1M/3M/6M) i przekazuje do tech_data
ZMIANY V2.36:
- [NEW] MarketCalendar zastępuje hardcodowane godziny NYSE:
  * Pobiera godziny otwarcia z /exchange-market-hours (cache 24h)
  * Pobiera święta giełdowe z /holidays-by-exchange (cache 7 dni)
  * Automatyczne DST (ET → UTC), fallback na 13-20 UTC jeśli FMP niedostępny
  * Daemon śpi w Święto Dziękczynienia, Boże Narodzenie, 4 Lipca itd.
ZMIANY V2.33:
- [NEW] ExecutionGuard dostaje klucz API — Earnings Veto działa
- [NEW] load_earnings_calendar() wywoływany na początku każdego cyklu
ZMIANY V2.32:
- [NEW] Przekazuje watchlistę do get_dynamic_universe() — brak duplikatów tickerów
ZMIANY V2.30:
- [NEW] Tryb PRE-MARKET (co 60 min, poza godzinami sesji):
  * Cache warm-up: pobiera dane historyczne i fundamenty dla całej watchlisty
  * News scan: pobiera nagłówki prasowe z FMP /stock-news i zapisuje do bazy
- [NEW] Tabela market_news w bazie (automatyczna migracja przez DatabaseManager)
ZMIANY V2.28:
- [FIX] API key ze zmiennej środowiskowej
- [FIX] Parser sektorów z watchlisty
- [FIX] Okno czasowe NYSE
- [FIX] Kolumna sector w active_scans
"""

import os
import time
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timezone

from core.database import DatabaseManager
from core.fmp_provider import FMPProvider
from core.execution_layer import ExecutionGuard
from core.scoring_engine import ScoringEngine
from core.stability_engine import StabilityEngine
from core.market_calendar import MarketCalendar

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

ALERT_ENDPOINT = "https://www.nex41.io/swingradar/alert.php"
ALERT_SECRET   = "SR_ALERT_2026_nex41"

def send_confirmed_alert(ticker: str, sector: str, stability: float,
                          entry: float, sl: float, target: float, rr: float):
    """Send email alert to opted-in users via PHP endpoint."""
    try:
        import urllib.request, urllib.parse
        data = urllib.parse.urlencode({
            'secret':    ALERT_SECRET,
            'ticker':    ticker,
            'sector':    sector or '',
            'stability': stability,
            'entry':     entry,
            'sl':        sl,
            'target':    target,
            'rr':        rr,
        }).encode('utf-8')
        req = urllib.request.Request(ALERT_ENDPOINT, data=data, method='POST')
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = resp.read().decode('utf-8')
            logger.info(f"Alert sent for {ticker}: {result}")
    except Exception as e:
        logger.warning(f"Alert failed for {ticker}: {e}")

# ================= KONFIGURACJA =================
FMP_API_KEY = os.environ.get("FMP_API_KEY", "")
if not FMP_API_KEY:
    raise EnvironmentError(
        "Brak klucza API! Ustaw zmienną środowiskową FMP_API_KEY przed uruchomieniem."
    )

SCAN_INTERVAL_MINUTES    = 15   # Interwał głównego skanu (sesja)
PREMARKET_INTERVAL_HOURS = 1    # Interwał pre-market warm-up (poza sesją)
# ================================================


class SwingRadarDaemon:
    def __init__(self):
        self.db = DatabaseManager()
        self.fmp = FMPProvider(FMP_API_KEY)
        self.guard = ExecutionGuard(fmp_api_key=FMP_API_KEY)
        self.scorer = ScoringEngine()
        self.stability = StabilityEngine()
        self.watchlist_path = "watchlist.txt"
        self._last_premarket_run: datetime | None = None
        self.calendar = MarketCalendar(api_key=FMP_API_KEY)

    # ══════════════════════════════════════════
    # WATCHLIST
    # ══════════════════════════════════════════

    def _load_watchlist(self) -> tuple[list, dict]:
        tickers = []
        sector_map = {}
        current_sector = "Uncategorized"

        try:
            with open(self.watchlist_path, "r", encoding="utf-8") as f:
                for line in f:
                    clean_line = line.strip()
                    if not clean_line:
                        continue
                    if clean_line.startswith("#"):
                        comment_text = clean_line.lstrip("#").strip().strip("─").strip()
                        if comment_text:
                            current_sector = comment_text
                        continue
                    ticker = clean_line.upper()
                    tickers.append(ticker)
                    sector_map[ticker] = current_sector

            logger.info(f"Wczytano {len(tickers)} tickerów ({len(set(sector_map.values()))} sektorów).")

        except FileNotFoundError:
            logger.error(f"Nie znaleziono {self.watchlist_path}! Używam listy awaryjnej.")
            fallback = ["AAPL", "MSFT", "NVDA"]
            return fallback, {t: "Fallback" for t in fallback}

        seen = set()
        unique = []
        for t in tickers:
            if t not in seen:
                seen.add(t)
                unique.append(t)
        return unique, sector_map

    # ══════════════════════════════════════════
    # WSKAŹNIKI TECHNICZNE
    # ══════════════════════════════════════════

    def _calculate_indicators(self, df: pd.DataFrame) -> dict:
        if len(df) < 20:
            return {}

        df = df.copy()
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()

        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        high_low   = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close  = np.abs(df['low']  - df['close'].shift())
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr']  = true_range.rolling(14).mean()

        df['vol_sma20'] = df['volume'].rolling(20).mean()
        df['rvol']      = df['volume'] / df['vol_sma20']

        latest = df.iloc[-1]
        return {
            "rsi":   float(latest.get('rsi',   50)),
            "ema20": float(latest.get('ema20',  0)),
            "atr":   float(latest.get('atr',    0)),
            "rvol":  float(latest.get('rvol', 1.0)),
        }

    # ══════════════════════════════════════════
    # OKNA CZASOWE
    # ══════════════════════════════════════════

    def is_trading_window(self) -> bool:
        """Deleguje do MarketCalendar — uwzględnia święta i aktualne godziny NYSE."""
        return self.calendar.is_trading_window()

    def is_decision_window(self) -> bool:
        """Deleguje do MarketCalendar."""
        return self.calendar.is_decision_window()



    def is_premarket_due(self) -> bool:
        """Czy minęła co najmniej 1 godzina od ostatniego pre-market runu?"""
        if self.is_trading_window():
            return False
        if not self.calendar.is_premarket_window():
            return False
        if self._last_premarket_run is None:
            return True
        now = datetime.now(timezone.utc)
        elapsed = (now - self._last_premarket_run).total_seconds() / 3600
        return elapsed >= PREMARKET_INTERVAL_HOURS

    # ══════════════════════════════════════════
    # PRE-MARKET: CACHE WARM-UP
    # ══════════════════════════════════════════

    def run_premarket_warmup(self, tickers: list):
        """
        Pobiera dane historyczne i fundamenty dla całej watchlisty
        i zapisuje je do cache FMP (requests_cache).
        Nie liczy score — tylko "rozgrzewa" cache przed sesją.
        """
        logger.info(f"=== PRE-MARKET CACHE WARM-UP ({len(tickers)} tickerów) ===")
        ok, fail = 0, 0
        for ticker in tickers:
            try:
                hist = self.fmp.get_historical_daily(ticker)
                metrics = self.fmp.get_quality_metrics(ticker)
                if not hist.empty and metrics:
                    ok += 1
                else:
                    fail += 1
            except Exception as e:
                logger.warning(f"Warm-up błąd ({ticker}): {e}")
                fail += 1
        logger.info(f"Cache warm-up zakończony: {ok} OK / {fail} błędów.")

    # ══════════════════════════════════════════
    # PRE-MARKET: NEWS SCAN
    # ══════════════════════════════════════════

    def run_news_scan(self, tickers: list):
        """
        Pobiera nagłówki prasowe z FMP /stock-news dla watchlisty
        i zapisuje nowe artykuły do tabeli market_news w bazie.
        """
        logger.info(f"=== PRE-MARKET NEWS SCAN ({len(tickers)} tickerów) ===")
        new_articles = 0

        with self.db.get_connection() as conn:
            for ticker in tickers:
                # Poprawny endpoint FMP: /news/stock?symbols=AAPL
                # (nie /stock-news który zwraca 404)
                news = self.fmp._fetch_news(ticker, limit=5)
                if not news:
                    continue

                for item in news:
                    article_url = item.get("url", "")
                    if not article_url:
                        continue

                    # Sprawdzamy czy artykuł już jest w bazie (deduplicacja po URL)
                    exists = conn.execute(
                        "SELECT 1 FROM market_news WHERE url = ?", (article_url,)
                    ).fetchone()
                    if exists:
                        continue

                    conn.execute("""
                        INSERT INTO market_news (ticker, headline, url, source, published_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        ticker,
                        item.get("title", "")[:500],
                        article_url[:1000],
                        item.get("site", "")[:100],
                        item.get("publishedDate", ""),
                    ))
                    new_articles += 1

        logger.info(f"News scan zakończony: {new_articles} nowych artykułów zapisanych.")

    # ══════════════════════════════════════════
    # GŁÓWNY CYKL SKANOWANIA (SESJA)
    # ══════════════════════════════════════════

    def run_cycle(self):
        logger.info("=== START CYKLU SKANOWANIA ===")

        # Market Regime — raz na cykl, dostosowuje progi scoringu
        regime_data = self.fmp.get_market_regime()
        regime      = regime_data["regime"]

        # Dynamiczne progi StabilityEngine na podstawie reżimu rynkowego
        if regime == "BEAR":
            self.stability.MIN_MEAN_SCORE = 70.0   # Tylko najsilniejsze sygnały
            logger.info("Market Regime BEAR — podnoszę próg stabilności do 70")
        elif regime == "BULL":
            self.stability.MIN_MEAN_SCORE = 55.0   # Więcej szans w rosnącym rynku
            logger.info("Market Regime BULL — obniżam próg stabilności do 55")
        else:
            self.stability.MIN_MEAN_SCORE = 60.0   # Domyślny próg
            logger.info("Market Regime NEUTRAL — standardowy próg stabilności 60")

        base_universe, sector_map = self._load_watchlist()
        dynamic_tickers = self.fmp.get_dynamic_universe(limit=20, watchlist=base_universe)
        for t in dynamic_tickers:
            if t not in sector_map:
                sector_map[t] = "Dynamic"
        universe = list(set(base_universe + dynamic_tickers))

        # Załaduj kalendarz wyników przed filtrowaniem (Earnings Veto)
        self.guard.load_earnings_calendar(universe)

        quotes = self.fmp.get_batch_quotes(universe)
        playable_universe = self.guard.filter_universe(quotes)

        with self.db.get_connection() as conn:
            for ticker, q_data in playable_universe.items():
                hist_df = self.fmp.get_historical_daily(ticker)
                metrics = self.fmp.get_quality_metrics(ticker)

                if hist_df.empty:
                    continue

                indicators = self._calculate_indicators(hist_df)
                if not indicators:
                    logger.warning(f"{ticker}: Za mało danych historycznych.")
                    continue

                # Pobieramy momentum wielookresowe (1D/5D/1M/3M/6M) — 1 request, cache 12h
                momentum   = self.fmp.get_price_momentum(ticker)
                # Pobieramy float — cache 12h, rzadko się zmienia
                float_data = self.fmp.get_float_data(ticker)
                tech_data  = {**q_data, **indicators, **momentum, **float_data}
                sector    = sector_map.get(ticker, "Unknown")

                score_result = self.scorer.get_composite_score(ticker, tech_data, metrics)
                final_score  = score_result["final_score"]

                conn.execute("""
                    INSERT INTO signal_history (ticker, final_score, tech_score, fund_score, event_score)
                    VALUES (?, ?, ?, ?, ?)
                """, (ticker, final_score, score_result["tech_score"],
                      score_result["fund_score"], score_result["event_score"]))

                rows = conn.execute("""
                    SELECT final_score FROM signal_history
                    WHERE ticker = ? ORDER BY timestamp DESC LIMIT 4
                """, (ticker,)).fetchall()
                history_scores = [r["final_score"] for r in reversed(rows)]

                state           = self.stability.evaluate_signal_state(final_score, history_scores)
                stability_score = self.stability.calculate_stability(history_scores)

                real_rr = entry_limit = sl = target = 0.0

                # Wyliczamy RR przy każdym skanie dla CANDIDATE i CONFIRMED
                # Dzięki temu Entry/SL/Target są zawsze aktualne na dashboardzie
                if state in ("CANDIDATE", "CONFIRMED") and tech_data.get("price", 0) > 0:
                    rr_check = self.guard.calculate_real_rr(
                        raw_price=tech_data.get("price", 0),
                        atr=tech_data.get("atr", 0),
                        analyst_target=metrics.get("analyst_target", 0),
                        target_median=metrics.get("target_median", 0.0),
                        target_high=metrics.get("target_high", 0.0),
                    )
                    if rr_check["status"] == "PASS":
                        real_rr     = rr_check["rr"]
                        entry_limit = rr_check["entry_limit"]
                        sl          = rr_check["sl"]
                        target      = rr_check["target"]

                # CONFIRMED tylko w oknie decyzyjnym 15:30-16:00 UTC
                # (2h po otwarciu NYSE — wolumen miarodajny, jeszcze czas na ruch)
                if state == "CANDIDATE" and self.is_decision_window():
                    if tech_data.get("rvol", 0) > 1.2 and real_rr > 0:
                        state = "CONFIRMED"
                        logger.info(
                            f"!!! CONFIRMED: {ticker} | {sector} | RR: {real_rr:.2f} !!!"
                        )
                        # Send email alert to opted-in users
                        send_confirmed_alert(
                            ticker, sector, stability_score,
                            entry_limit, sl, target, real_rr
                        )

                conn.execute("""
                    INSERT INTO active_scans
                        (ticker, status, sector, stability_score, real_rr, entry_limit, stop_loss, target, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(ticker) DO UPDATE SET
                        status=excluded.status, sector=excluded.sector,
                        stability_score=excluded.stability_score,
                        -- Zachowaj Entry/SL/Target/RR jeśli już ustawione i nowe są zerowe
                        -- (poza oknem decyzyjnym nie nadpisujemy poziomów cenowych)
                        real_rr     = CASE WHEN excluded.real_rr > 0
                                           THEN excluded.real_rr
                                           ELSE active_scans.real_rr END,
                        entry_limit = CASE WHEN excluded.entry_limit > 0
                                           THEN excluded.entry_limit
                                           ELSE active_scans.entry_limit END,
                        stop_loss   = CASE WHEN excluded.stop_loss > 0
                                           THEN excluded.stop_loss
                                           ELSE active_scans.stop_loss END,
                        target      = CASE WHEN excluded.target > 0
                                           THEN excluded.target
                                           ELSE active_scans.target END,
                        updated_at  = CURRENT_TIMESTAMP
                """, (ticker, state, sector, stability_score, real_rr, entry_limit, sl, target))

        logger.info("=== KONIEC CYKLU SKANOWANIA ===")


# ══════════════════════════════════════════════
# GŁÓWNA PĘTLA
# ══════════════════════════════════════════════

if __name__ == "__main__":
    logger.info("Uruchamianie Daemona SwingRadar V2.44...")
    daemon = SwingRadarDaemon()

    while True:
        try:
            if daemon.is_trading_window():
                daemon.run_cycle()
            elif daemon.is_premarket_due():
                # Poza sesją — tryb pre-market co 60 minut
                tickers, _ = daemon._load_watchlist()
                daemon.run_premarket_warmup(tickers)
                daemon.run_news_scan(tickers)
                daemon._last_premarket_run = datetime.now(timezone.utc)
                logger.info("Pre-market run zakończony. Następny za ~60 minut.")
            else:
                logger.info(f"Rynek zamknięty. {daemon.calendar.next_open_info()}")

        except Exception as e:
            logger.error(f"Krytyczny błąd w pętli: {e}", exc_info=True)

        logger.info(f"Oczekiwanie {SCAN_INTERVAL_MINUTES} minut...")
        time.sleep(SCAN_INTERVAL_MINUTES * 60)
