"""
Data Layer v1.0
Trading System – Masterplan V2.4.5

Struktura:
    1. PolygonClient      – surowe dane z API (OHLCV, snapshot, fundamentals)
    2. IndicatorEngine    – feature engineering (RSI, MACD, OBV slope, ATR, ROC)
    3. RegimeDetector     – SPY/VIX dla regime score
    4. DataCleaner        – walidacja i czyszczenie (reguły z L1)
    5. build_ticker_data  – główna funkcja → TickerData (gotowe do pipeline)
    6. Unit testy         – mockowane, bez wywołań API

Użycie:
    from data_layer import build_ticker_data
    td = build_ticker_data("AAPL", api_key="YOUR_KEY")
    result = run_scoring_pipeline(td, portfolio)

Polygon.io tier:
    Free tier: 5 calls/min, EOD data
    Starter ($29/mo): unlimited calls, real-time
    MVP działa na free tier (EOD scanning po zamknięciu sesji)
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from typing import Optional

import numpy as np
import pandas as pd
import requests

# Import typów z Scoring Engine
# (zakładamy że scoring_engine_v1.py jest w tym samym katalogu)
try:
    from scoring_engine_v1 import (
        TickerData, Market, SetupType, EventStatus, GapRisk
    )
except ImportError:
    # Fallback dla testów izolowanych
    pass

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 1. POLYGON CLIENT
# ─────────────────────────────────────────────

class PolygonClient:
    """
    Klient Polygon.io API.
    Obsługuje rate limiting, retry i podstawową obsługę błędów.

    Endpoints używane:
        /v2/aggs/ticker/{ticker}/range/1/day/...  → OHLCV
        /v2/snapshot/locale/us/markets/stocks/tickers/{ticker} → snapshot
        /vX/reference/financials/{ticker}          → fundamentals
        /v2/aggs/ticker/SPY/range/1/day/...        → SPY dla regime
        /v2/aggs/ticker/VXX/range/1/day/...        → VIX proxy
    """

    BASE_URL = "https://api.massive.com"   # Polygon.io rebranded → Massive.com (Oct 2025)
    RATE_LIMIT_DELAY = 12.5   # sekund między calls (free tier: 5/min)

    def __init__(self, api_key: str, tier: str = "free"):
        self.api_key = api_key
        self.tier = tier
        self._last_call = 0.0

        # Starter+ tier: bez rate limiting
        if tier != "free":
            self.RATE_LIMIT_DELAY = 0.0

    def _get(self, endpoint: str, params: dict = {}) -> dict:
        """
        Bazowy GET z rate limiting + fallback auth (Massive compatible)
        """
        # Rate limiting
        if self.RATE_LIMIT_DELAY > 0:
            elapsed = time.time() - self._last_call
            if elapsed < self.RATE_LIMIT_DELAY:
                time.sleep(self.RATE_LIMIT_DELAY - elapsed)

        url = f"{self.BASE_URL}{endpoint}"

        # ── TRY 1: apiKey w query ─────────────────
        params_with_key = params.copy()
        params_with_key["apiKey"] = self.api_key

        try:
            resp = requests.get(url, params=params_with_key, timeout=10)
            self._last_call = time.time()

            if resp.status_code == 200:
                return resp.json()

            # ── TRY 2: fallback → Authorization header ──
            if resp.status_code in (401, 403):
                logger.warning("Auth failed with apiKey param → retry with Bearer header")

                headers = {
                    "Authorization": f"Bearer {self.api_key}"
                }

                resp = requests.get(url, headers=headers, params=params, timeout=10)

                if resp.status_code == 200:
                    return resp.json()

            # ── Rate limit handling ─────────────────
            if resp.status_code == 429:
                wait = 60
                logger.warning(f"Rate limit 429, czekam {wait}s...")
                time.sleep(wait)
                return self._get(endpoint, params)

            raise PolygonAPIError(
                f"HTTP {resp.status_code} dla {endpoint}: {resp.text[:200]}"
            )

        except requests.Timeout:
            raise PolygonAPIError(f"Timeout dla {endpoint}")
    
    def get_ohlcv(
        self,
        ticker: str,
        days: int = 252,
        end_date: Optional[date] = None
    ) -> pd.DataFrame:
        """
        Pobiera daily OHLCV + volume za ostatnie N dni.

        Returns:
            DataFrame z kolumnami: date, open, high, low, close, volume
            Posortowany rosnąco po dacie.
        """
        if end_date is None:
            end_date = date.today()

        start_date = end_date - timedelta(days=days + 100)  # bufor na weekendy/święta

        endpoint = f"/v2/aggs/ticker/{ticker}/range/1/day/{start_date}/{end_date}"
        params = {
            "adjusted": "true",
            "sort": "asc",
            "limit": 500,
        }

        data = self._get(endpoint, params)

        if data.get("resultsCount", 0) == 0 or not data.get("results"):
            raise PolygonNoDataError(f"Brak danych OHLCV dla {ticker}")

        rows = []
        for bar in data["results"]:
            rows.append({
                "date":   datetime.fromtimestamp(bar["t"] / 1000).date(),
                "open":   bar["o"],
                "high":   bar["h"],
                "low":    bar["l"],
                "close":  bar["c"],
                "volume": bar["v"],
            })

        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        # Zachowaj tylko ostatnie N sesji
        df = df.tail(days).reset_index(drop=True)

        return df

    def get_snapshot(self, ticker: str) -> dict:
        """
        Pobiera aktualny snapshot tickera:
        ask, bid, last price, today's volume, market cap.

        Returns:
            dict z kluczami: ask, bid, price, volume_today, market_cap
        """
        endpoint = f"/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}"
        data = self._get(endpoint)

        ticker_data = data.get("ticker", {})
        if not ticker_data:
            raise PolygonNoDataError(f"Brak snapshot dla {ticker}")

        day   = ticker_data.get("day", {})
        last  = ticker_data.get("lastQuote", {})
        prev  = ticker_data.get("prevDay", {})

        return {
            "ask":          last.get("P", day.get("c", 0)),   # ask price
            "bid":          last.get("p", day.get("c", 0)),   # bid price
            "price":        day.get("c") or prev.get("c", 0), # close
            "volume_today": day.get("v", 0),
            "vwap":         day.get("vw", 0),
        }

    def get_fundamentals(self, ticker: str) -> dict:
        """
        Pobiera podstawowe fundamentals z Polygon reference API.

        Returns:
            dict z kluczami: market_cap, pe_ratio, eps, revenue
        Note:
            Polygon free tier ma ograniczone fundamentals.
            Fallback: Financial Modeling Prep API (patrz FMPClient).
        """
        endpoint = f"/vX/reference/financials"
        params = {
            "ticker": ticker,
            "limit":  4,    # ostatnie 4 kwartały
            "sort":   "period_of_report_date",
            "order":  "desc",
        }

        try:
            data = self._get(endpoint, params)
            results = data.get("results", [])

            if not results:
                return self._empty_fundamentals()

            latest = results[0].get("financials", {})
            income = latest.get("income_statement", {})
            balance = latest.get("balance_sheet", {})

            # EPS i Revenue YoY growth (porównaj Q vs Q rok temu)
            eps_growth = 0.0
            rev_growth = 0.0

            if len(results) >= 5:  # 4 kwartały + rok temu
                curr_eps = income.get("basic_earnings_per_share", {}).get("value", 0)
                prev_eps = (results[4].get("financials", {})
                            .get("income_statement", {})
                            .get("basic_earnings_per_share", {})
                            .get("value", 0))
                if prev_eps and prev_eps != 0:
                    eps_growth = ((curr_eps - prev_eps) / abs(prev_eps)) * 100

                curr_rev = income.get("revenues", {}).get("value", 0)
                prev_rev = (results[4].get("financials", {})
                            .get("income_statement", {})
                            .get("revenues", {})
                            .get("value", 0))
                if prev_rev and prev_rev != 0:
                    rev_growth = ((curr_rev - prev_rev) / abs(prev_rev)) * 100

            # Debt/Equity
            total_debt   = balance.get("long_term_debt", {}).get("value", 0)
            total_equity = balance.get("equity", {}).get("value", 1)
            de_ratio = total_debt / total_equity if total_equity != 0 else 0

            return {
                "eps_growth_yoy":     eps_growth,
                "revenue_growth_yoy": rev_growth,
                "debt_equity":        de_ratio,
                "pe_ratio":           0.0,       # P/E wymaga market cap + EPS
                "market_cap":         0.0,       # z osobnego endpointu
            }

        except (PolygonAPIError, PolygonNoDataError):
            return self._empty_fundamentals()

    def get_ticker_details(self, ticker: str) -> dict:
        """
        Pobiera market cap i podstawowe informacje o spółce.
        """
        endpoint = f"/v3/reference/tickers/{ticker}"
        data = self._get(endpoint)
        result = data.get("results", {})

        return {
            "market_cap":    result.get("market_cap", 0),
            "name":          result.get("name", ticker),
            "sector":        result.get("sic_description", "Unknown"),
            "exchange":      result.get("primary_exchange", "NASDAQ"),
        }

    def _empty_fundamentals(self) -> dict:
        """Fallback gdy brak danych fundamentalnych."""
        return {
            "eps_growth_yoy":     0.0,
            "revenue_growth_yoy": 0.0,
            "debt_equity":        0.0,
            "pe_ratio":           15.0,  # neutral assumption
            "market_cap":         0.0,
        }


# ─────────────────────────────────────────────
# 2. FMP CLIENT (fallback dla fundamentals)
# ─────────────────────────────────────────────

class FMPClient:
    """
    Financial Modeling Prep – lepsze fundamentals niż Polygon free tier.
    Free tier: 250 calls/dzień.
    https://financialmodelingprep.com/developer/docs
    """

    BASE_URL = "https://financialmodelingprep.com/api/v3"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def _get(self, endpoint: str, params: dict = {}) -> list | dict:
        url = f"{self.BASE_URL}{endpoint}"
        params["apikey"] = self.api_key
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            raise FMPAPIError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def get_key_metrics(self, ticker: str) -> dict:
        """
        Pobiera P/E ratio, EPS growth, Revenue growth, Debt/Equity.

        Returns:
            dict gotowy do wstawienia w TickerData
        """
        try:
            # TTM metrics
            data = self._get(f"/key-metrics-ttm/{ticker}")
            if not data:
                return self._empty()

            m = data[0] if isinstance(data, list) else data

            # Historyczne dla YoY growth
            hist = self._get(f"/income-statement/{ticker}", {"limit": 2, "period": "annual"})

            eps_growth = 0.0
            rev_growth = 0.0

            if hist and len(hist) >= 2:
                curr, prev = hist[0], hist[1]
                if prev.get("eps", 0) != 0:
                    eps_growth = ((curr.get("eps", 0) - prev.get("eps", 0))
                                  / abs(prev.get("eps", 1))) * 100
                if prev.get("revenue", 0) != 0:
                    rev_growth = ((curr.get("revenue", 0) - prev.get("revenue", 0))
                                  / abs(prev.get("revenue", 1))) * 100

            return {
                "eps_growth_yoy":     round(eps_growth, 2),
                "revenue_growth_yoy": round(rev_growth, 2),
                "pe_ratio":           m.get("peRatioTTM", 15.0) or 15.0,
                "debt_equity":        m.get("debtToEquityTTM", 0.5) or 0.5,
            }

        except Exception as e:
            logger.warning(f"FMP fundamentals failed for {ticker}: {e}")
            return self._empty()

    def _empty(self) -> dict:
        return {
            "eps_growth_yoy":     0.0,
            "revenue_growth_yoy": 0.0,
            "pe_ratio":           15.0,
            "debt_equity":        0.5,
        }


# ─────────────────────────────────────────────
# 3. INDICATOR ENGINE
# ─────────────────────────────────────────────

class IndicatorEngine:
    """
    Feature engineering – wszystkie wskaźniki techniczne potrzebne przez pipeline.
    Operuje na DataFrame z kolumnami: open, high, low, close, volume.
    Czyste numpy/pandas, zero zewnętrznych bibliotek TA.
    """

    @staticmethod
    def ema(series: pd.Series, period: int) -> pd.Series:
        """Exponential Moving Average."""
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def sma(series: pd.Series, period: int) -> pd.Series:
        """Simple Moving Average."""
        return series.rolling(window=period).mean()

    @staticmethod
    def rsi(close: pd.Series, period: int = 14) -> pd.Series:
        """
        RSI (Relative Strength Index).
        Używa Wilder's smoothing (EMA z alpha=1/period).
        """
        delta = close.diff()
        gain  = delta.clip(lower=0)
        loss  = (-delta).clip(lower=0)

        avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()

        rs  = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50)

    @staticmethod
    def macd(
        close: pd.Series,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """
        MACD (Moving Average Convergence/Divergence).

        Returns:
            (macd_line, signal_line, histogram)
        """
        ema_fast   = close.ewm(span=fast,   adjust=False).mean()
        ema_slow   = close.ewm(span=slow,   adjust=False).mean()
        macd_line  = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram  = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def atr(
        high: pd.Series,
        low:  pd.Series,
        close: pd.Series,
        period: int = 14
    ) -> pd.Series:
        """
        ATR (Average True Range).
        True Range = max(H-L, |H-Cprev|, |L-Cprev|)
        """
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low  - prev_close).abs(),
        ], axis=1).max(axis=1)

        return tr.ewm(alpha=1/period, adjust=False).mean()

    @staticmethod
    def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
        """On-Balance Volume."""
        direction = np.sign(close.diff()).fillna(0)
        return (direction * volume).cumsum()

    @staticmethod
    def obv_slope_normalized(
        close:  pd.Series,
        volume: pd.Series,
        window: int = 10
    ) -> float:
        """
        Normalized OBV slope.

        Regresja liniowa OBV na ostatnie N sesji.
        Normalizacja: slope / (avg_volume * avg_price) → tanh → [-1, +1]

        Returns:
            float: -1.0 (silny outflow) do +1.0 (silny inflow)
        """
        obv_series = IndicatorEngine.obv(close, volume)
        recent_obv = obv_series.tail(window).values

        if len(recent_obv) < window:
            return 0.0

        x = np.arange(len(recent_obv), dtype=float)
        # Liniowa regresja: y = ax + b → slope = a
        slope = np.polyfit(x, recent_obv, 1)[0]

        # Normalizacja względem typowej wartości OBV
        avg_volume = volume.tail(window).mean()
        avg_price  = close.tail(window).mean()
        normalizer = avg_volume * avg_price

        if normalizer == 0:
            return 0.0

        normalized = slope / normalizer

        # tanh → [-1, +1], scaling_constant = 3.0 (z V2.4.2)
        return float(np.tanh(normalized * 3.0))

    @staticmethod
    def roc(close: pd.Series, period: int = 10) -> float:
        """
        Rate of Change (%).
        ROC = (close_today - close_N_days_ago) / close_N_days_ago * 100
        """
        if len(close) < period + 1:
            return 0.0
        past  = close.iloc[-(period+1)]
        today = close.iloc[-1]
        if past == 0:
            return 0.0
        return float((today - past) / past * 100)

    @staticmethod
    def adv(volume: pd.Series, period: int = 20) -> float:
        """Average Daily Volume (20 dni)."""
        return float(volume.tail(period).mean())

    @staticmethod
    def rvol(volume: pd.Series, period: int = 20) -> float:
        """
        Relative Volume – dzisiejszy volume vs ADV.
        Używa ostatniej wartości jako 'dzisiaj'.
        """
        avg = volume.tail(period + 1).iloc[:-1].mean()
        if avg == 0:
            return 1.0
        return float(volume.iloc[-1] / avg)

    @staticmethod
    def gap_metrics(
        open_prices: pd.Series,
        close_prices: pd.Series,
        period: int = 20
    ) -> tuple[float, str]:
        """
        Oblicza gap_20d_avg i gap_risk.
        gap = abs(open - prev_close) / prev_close

        Returns:
            (gap_20d_avg, gap_risk)  gdzie gap_risk: 'LOW'|'MEDIUM'|'HIGH'
        """
        prev_close = close_prices.shift(1)
        gaps = (open_prices - prev_close).abs() / prev_close.replace(0, np.nan)
        gap_avg = float(gaps.tail(period).mean())

        if gap_avg > 0.030:
            risk = "HIGH"
        elif gap_avg > 0.015:
            risk = "MEDIUM"
        else:
            risk = "LOW"

        return gap_avg, risk

    @staticmethod
    def bid_ask_spread(ask: float, bid: float) -> float:
        """Bid-ask spread jako % mid-price."""
        mid = (ask + bid) / 2
        if mid == 0:
            return 0.0
        return (ask - bid) / mid

    @staticmethod
    def swing_high(close: pd.Series, period: int = 20) -> float:
        """Najwyższe zamknięcie (resistance) z ostatnich N sesji."""
        return float(close.tail(period).max())

    @staticmethod
    def swing_low(close: pd.Series, period: int = 20) -> float:
        """Najniższe zamknięcie (support) z ostatnich N sesji."""
        return float(close.tail(period).min())

    @classmethod
    def calculate_all(cls, df: pd.DataFrame) -> dict:
        """
        Oblicza wszystkie wskaźniki na raz.
        Wejście: DataFrame z kolumnami open, high, low, close, volume
        Wyjście: dict z gotowymi wartościami dla TickerData
        """
        close  = df["close"]
        high   = df["high"]
        low    = df["low"]
        volume = df["volume"]
        open_p = df["open"]

        # Moving Averages
        sma200 = cls.sma(close, 200)
        ema50  = cls.ema(close, 50)
        ema20  = cls.ema(close, 20)

        # Momentum
        rsi_series  = cls.rsi(close, 14)
        _, _, macd_hist_series = cls.macd(close)
        atr_series  = cls.atr(high, low, close, 14)

        # Ostatnie wartości (aktualne)
        last_close  = float(close.iloc[-1])
        last_sma200 = float(sma200.iloc[-1])
        last_ema50  = float(ema50.iloc[-1])
        last_ema20  = float(ema20.iloc[-1])
        last_rsi    = float(rsi_series.iloc[-1])
        last_macd_h = float(macd_hist_series.iloc[-1])
        last_atr    = float(atr_series.iloc[-1])

        # MACD max (ostatnie 20 sesji) – z ochroną przed ZeroDivisionError (fix Gemini)
        macd_hist_max = float(macd_hist_series.tail(20).abs().max())
        if macd_hist_max == 0:
            macd_hist_max = 1.0  # fallback – nie powoduje dzielenia przez 0

        # Volume metrics
        adv_20d     = cls.adv(volume, 20)
        rvol_val    = cls.rvol(volume, 20)

        # OBV slope
        obv_slope   = cls.obv_slope_normalized(close, volume, 10)

        # ROC
        roc_10      = cls.roc(close, 10)

        # Gap metrics
        gap_avg, gap_risk = cls.gap_metrics(open_p, close, 20)

        # Support / Resistance
        resistance  = cls.swing_high(close, 20)
        support     = cls.swing_low(close, 20)

        return {
            # Prices
            "price":              last_close,
            "sma200":             last_sma200,
            "ema50":              last_ema50,
            "ema20":              last_ema20,

            # Momentum
            "rsi_14":             last_rsi,
            "macd_hist":          last_macd_h,
            "macd_hist_max_20d":  macd_hist_max,
            "roc_10":             roc_10,
            "atr_14":             last_atr,

            # Volume
            "adv_20d":            adv_20d,
            "rvol":               rvol_val,
            "obv_slope":          obv_slope,

            # Gap
            "gap_20d_avg":        gap_avg,
            "gap_risk":           gap_risk,

            # Structure
            "resistance":         resistance,
            "support":            support,
        }


# ─────────────────────────────────────────────
# 4. REGIME DETECTOR
# ─────────────────────────────────────────────

class RegimeDetector:
    """
    Pobiera dane SPY i VIX dla Regime Score (L6.5).
    SPY: proxy dla S&P 500
    VXX: proxy dla VIX (dostępny w Polygon jako ETF)
    """

    def __init__(self, client: PolygonClient):
        self.client = client
        self._cache: dict = {}
        self._cache_date: Optional[date] = None

    def get_regime_data(self) -> dict:
        """
        Zwraca dane reżimu rynkowego.
        Cache'owane na jeden dzień (dane EOD nie zmieniają się w ciągu dnia).

        Returns:
            dict: spy_price, spy_sma200, spy_sma50, vix_percentile
        """
        today = date.today()

        if self._cache_date == today and self._cache:
            return self._cache

        try:
            spy_df = self.client.get_ohlcv("SPY", days=252)
            ind    = IndicatorEngine.calculate_all(spy_df)

            spy_price  = ind["price"]
            spy_sma200 = ind["sma200"]
            spy_sma50  = float(IndicatorEngine.sma(spy_df["close"], 50).iloc[-1])

            # VIX percentile przez VXX (proxy)
            vix_pct = self._get_vix_percentile(spy_df)

            self._cache = {
                "spy_price":      spy_price,
                "spy_sma200":     spy_sma200,
                "spy_sma50":      spy_sma50,
                "vix_percentile": vix_pct,
            }
            self._cache_date = today
            return self._cache

        except Exception as e:
            logger.warning(f"Regime data failed, using defaults: {e}")
            return {
                "spy_price":      400.0,
                "spy_sma200":     380.0,
                "spy_sma50":      395.0,
                "vix_percentile": 50.0,
            }

    def _get_vix_percentile(self, spy_df: pd.DataFrame) -> float:
        """
        Przybliżony VIX percentile na podstawie zmienności SPY.
        Rzeczywisty VIX wymaga osobnego feed'u (CBOE).

        Proxy: 20d realized volatility SPY → percentyl vs 252d historii.
        """
        returns  = spy_df["close"].pct_change().dropna()
        vol_20d  = returns.rolling(20).std() * np.sqrt(252) * 100
        current  = float(vol_20d.iloc[-1])
        history  = vol_20d.dropna()

        percentile = float((history < current).mean() * 100)
        return round(percentile, 1)


# ─────────────────────────────────────────────
# 5. DATA CLEANER
# ─────────────────────────────────────────────

class DataCleaner:
    """
    Walidacja i czyszczenie danych – reguły z L1 Masterplan V2.4.5.
    Rzuca wyjątek DataQualityError jeśli dane nie nadają się do pipeline.
    """

    @staticmethod
    def validate_ohlcv(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
        """
        Sprawdza jakość danych OHLCV.
        Reguły z L1:
            - brak danych > 3 dni w ostatnich 20 sesjach → odrzuć
            - volume = 0 przez > 2 kolejne dni → odrzuć
            - gap > 50% → sprawdź (potencjalny stock split)
        """
        if len(df) < 50:
            raise DataQualityError(
                f"{ticker}: Za mało danych ({len(df)} sesji, min 50)"
            )

        # Brak danych (NaN) w ostatnich 20 sesjach
        recent = df.tail(20)
        nan_count = recent["close"].isna().sum()
        if nan_count > 3:
            raise DataQualityError(
                f"{ticker}: {nan_count} brakujących dni w ostatnich 20 sesjach"
            )

        # Volume = 0 przez > 2 kolejne dni
        zero_vol = (df["volume"] == 0)
        consec_zero = zero_vol.groupby(
            (zero_vol != zero_vol.shift()).cumsum()
        ).cumsum()
        if consec_zero.max() > 2:
            raise DataQualityError(
                f"{ticker}: Volume = 0 przez więcej niż 2 kolejne dni"
            )

        # Gap > 50% – flaga (nie odrzucamy automatycznie)
        prev_close = df["close"].shift(1)
        gaps = ((df["open"] - prev_close) / prev_close.replace(0, np.nan)).abs()
        large_gaps = gaps[gaps > 0.50]
        if len(large_gaps) > 0:
            logger.warning(
                f"{ticker}: {len(large_gaps)} gap(ów) > 50% – sprawdź stock split"
            )

        # Wypełnij pozostałe NaN forward fill (maks 1 dzień)
        df = df.ffill(limit=1)
        df = df.dropna()

        return df

    @staticmethod
    def validate_indicators(indicators: dict, ticker: str) -> None:
        """
        Sprawdza czy obliczone wskaźniki są w sensownych zakresach.
        Chroni przed przekazaniem NaN/Inf do pipeline.
        """
        checks = {
            "rsi_14":    (0, 100),
            "adv_20d":   (0, 1e12),
            "rvol":      (0, 100),
            "atr_14":    (0, 1e6),
        }

        for field, (lo, hi) in checks.items():
            val = indicators.get(field, 0)
            if not np.isfinite(val):
                raise DataQualityError(
                    f"{ticker}: {field} = {val} (NaN lub Inf)"
                )
            if not (lo <= val <= hi):
                logger.warning(
                    f"{ticker}: {field} = {val:.2f} poza oczekiwanym zakresem [{lo}, {hi}]"
                )


# ─────────────────────────────────────────────
# 6. GŁÓWNA FUNKCJA – build_ticker_data
# ─────────────────────────────────────────────

def build_ticker_data(
    ticker:          str,
    polygon_key:     str,
    fmp_key:         Optional[str] = None,
    polygon_tier:    str = "free",
    regime_detector: Optional[RegimeDetector] = None,
    event_status:    str = "SAFE",
    sentiment_raw:   float = 0.0,
    setup_type:      str = "Trend Pullback",
    pattern_range_pct: float = 8.0,
    pullback_fib_pct:  float = 38.2,
    sector_avg_pe:   float = 25.0,
    market:          str = "US",
) -> "TickerData":
    """
    Główna funkcja Data Layer.
    Pobiera dane → liczy wskaźniki → buduje TickerData gotowe do pipeline.

    Args:
        ticker:          Symbol tickera (np. "AAPL")
        polygon_key:     Klucz API Polygon.io
        fmp_key:         Klucz API FMP (opcjonalny, lepsze fundamentals)
        polygon_tier:    "free" | "starter" | "developer"
        regime_detector: Przekaż istniejący aby uniknąć powtórnego pobierania SPY
        event_status:    SAFE|WARN|HIGH_RISK|BLOCKED (z zewnętrznego kalendarza zdarzeń)
        sentiment_raw:   Wynik FinBERT -100…+100 (z zewnętrznego modelu)
        setup_type:      Typ setupu z L2 TA Filter
        pattern_range_pct: Tightness of pattern (%) z L2
        pullback_fib_pct:  Głębokość pullbacku Fibonacci z L2
        sector_avg_pe:   Średnie P/E sektora (do porównania)
        market:          "US" | "UK"

    Returns:
        TickerData gotowy do run_scoring_pipeline()

    Raises:
        DataQualityError:  Dane nie spełniają kryteriów jakości L1
        PolygonAuthError:  Błąd autoryzacji API
        PolygonAPIError:   Błąd API Polygon
    """
    polygon = PolygonClient(polygon_key, tier=polygon_tier)

    # ── 1. OHLCV ──────────────────────────────
    logger.info(f"Pobieranie OHLCV: {ticker}")
    df = polygon.get_ohlcv(ticker, days=252)
    df = DataCleaner.validate_ohlcv(df, ticker)

    # ── 2. Snapshot (ask/bid/volume dziś) ─────
    # Snapshot NIE dostępny w free tier → fallback do close price
    logger.info(f"Snapshot pominięty (free tier): {ticker}")

    last_close = float(df["close"].iloc[-1])

    ask   = last_close
    bid   = last_close
    price = last_close

    # ── 3. Feature engineering ────────────────
    logger.info(f"Obliczanie wskaźników: {ticker}")
    ind = IndicatorEngine.calculate_all(df)
    DataCleaner.validate_indicators(ind, ticker)

    # ── 4. Fundamentals ───────────────────────
    if fmp_key:
        fmp = FMPClient(fmp_key)
        fundamentals = fmp.get_key_metrics(ticker)
    else:
        fundamentals = polygon.get_fundamentals(ticker)

    # Market cap z Polygon details
    details   = polygon.get_ticker_details(ticker)
    market_cap = details.get("market_cap", 0) or 1_000_000_000  # fallback 1B

    # ── 5. Regime data ────────────────────────
    if regime_detector is None:
        regime_detector = RegimeDetector(polygon)

    regime = regime_detector.get_regime_data()

    # ── 6. Spread ─────────────────────────────
    spread_pct = IndicatorEngine.bid_ask_spread(ask, bid)

    # ── 7. Zbuduj TickerData ──────────────────
    td = TickerData(
        ticker  = ticker,
        market  = Market.US if market == "US" else Market.UK,

        # Ceny
        price   = price,
        ask     = ask,
        bid     = bid,

        # Volume
        adv_20d = ind["adv_20d"],
        rvol    = ind["rvol"],
        obv_slope = ind["obv_slope"],

        # Wskaźniki techniczne
        sma200  = ind["sma200"],
        ema50   = ind["ema50"],
        ema20   = ind["ema20"],
        rsi_14  = ind["rsi_14"],
        macd_hist = ind["macd_hist"],
        macd_hist_max_20d = ind["macd_hist_max_20d"],
        roc_10  = ind["roc_10"],
        atr_14  = ind["atr_14"],
        market_cap = market_cap,

        # Setup (z L2 TA Filter – przekazywane z zewnątrz)
        setup_type        = SetupType(setup_type),
        resistance        = ind["resistance"],
        support           = ind["support"],
        pattern_range_pct = pattern_range_pct,
        pullback_fib_pct  = pullback_fib_pct,

        # Gap metrics (obliczone w L1 – raz)
        gap_20d_avg = ind["gap_20d_avg"],
        gap_risk    = GapRisk(ind["gap_risk"]),

        # Fundamentals
        eps_growth_yoy     = fundamentals.get("eps_growth_yoy", 0.0),
        revenue_growth_yoy = fundamentals.get("revenue_growth_yoy", 0.0),
        pe_ratio           = fundamentals.get("pe_ratio", 15.0),
        sector_avg_pe      = sector_avg_pe,
        debt_equity        = fundamentals.get("debt_equity", 0.5),

        # Regime
        spy_price      = regime["spy_price"],
        spy_sma200     = regime["spy_sma200"],
        spy_sma50      = regime["spy_sma50"],
        vix_percentile = regime["vix_percentile"],

        # Event & Sentiment (z zewnętrznych źródeł)
        event_status  = EventStatus(event_status),
        sentiment_raw = sentiment_raw,

        # Spread
        spread_pct = spread_pct,

        # Timing (domyślnie 0 – do ustawienia przez TA Filter)
        days_since_setup   = 0,
        catalyst_age_days  = 0,
    )

    logger.info(
        f"{ticker}: RSI={td.rsi_14:.1f} | RVOL={td.rvol:.2f}x | "
        f"Gap={td.gap_risk.value} | ATR={td.atr_14:.2f}"
    )

    return td


# ─────────────────────────────────────────────
# 7. WYJĄTKI
# ─────────────────────────────────────────────

class PolygonAPIError(Exception):
    """Błąd odpowiedzi API Polygon."""
    pass

class PolygonAuthError(PolygonAPIError):
    """Błąd autoryzacji (403)."""
    pass

class PolygonNoDataError(PolygonAPIError):
    """Brak danych dla tickera."""
    pass

class FMPAPIError(Exception):
    """Błąd FMP API."""
    pass

class DataQualityError(Exception):
    """Dane nie spełniają kryteriów jakości L1."""
    pass


# ─────────────────────────────────────────────
# 8. UNIT TESTY (bez wywołań API – pełny mock)
# ─────────────────────────────────────────────

def _make_mock_ohlcv(n: int = 252, trend: str = "up") -> pd.DataFrame:
    """
    Generuje syntetyczne dane OHLCV do testów.
    trend: "up" | "down" | "sideways"
    """
    np.random.seed(42)
    # business days – może dać więcej niż n wierszy, przycinamy do n
    dates_raw = pd.date_range(end=pd.Timestamp.today(), periods=n * 2, freq="B")
    dates = dates_raw[-n:]   # ostatnie n dni roboczych

    noise  = np.random.randn(n) * 2

    if trend == "up":
        close = 100 + np.linspace(0, 80, n) + noise
    elif trend == "down":
        close = 180 - np.linspace(0, 80, n) + noise
    else:
        close = 140 + noise

    close  = np.maximum(close, 5)  # min $5
    high   = close * (1 + np.abs(np.random.randn(n)) * 0.01)
    low    = close * (1 - np.abs(np.random.randn(n)) * 0.01)
    open_p = close * (1 + np.random.randn(n) * 0.005)
    volume = np.abs(np.random.randn(n) * 2_000_000 + 10_000_000)
    # Ostatni dzień: wyższy volume → RVOL > 1.5 (wymagane przez L3)
    volume[-1] = volume[-2:].mean() * 2.0

    return pd.DataFrame({
        "date":   dates,
        "open":   open_p,
        "high":   high,
        "low":    low,
        "close":  close,
        "volume": volume,
    })


def test_ema():
    df = _make_mock_ohlcv()
    ema20 = IndicatorEngine.ema(df["close"], 20)
    assert len(ema20) == len(df)
    assert not ema20.isna().all()
    print("✓ test_ema")


def test_rsi_range():
    df  = _make_mock_ohlcv()
    rsi = IndicatorEngine.rsi(df["close"], 14)
    assert rsi.min() >= 0
    assert rsi.max() <= 100
    # Ostatnia wartość powinna być w rozsądnym zakresie
    assert 20 <= float(rsi.iloc[-1]) <= 80
    print(f"✓ test_rsi_range (last RSI={rsi.iloc[-1]:.1f})")


def test_macd_histogram():
    df = _make_mock_ohlcv()
    _, _, hist = IndicatorEngine.macd(df["close"])
    assert len(hist) == len(df)
    assert not hist.isna().all()
    # Max abs powinno być > 0 dla normalnych danych
    assert hist.abs().max() > 0
    print(f"✓ test_macd_histogram (max_abs={hist.abs().max():.4f})")


def test_macd_zero_protection():
    """Ochrona przed ZeroDivisionError gdy macd_hist_max = 0."""
    df = _make_mock_ohlcv(n=100, trend="sideways")
    # Wymuszamy zerowy histogram
    ind = IndicatorEngine.calculate_all(df)
    # macd_hist_max_20d nigdy nie powinno być 0 (fallback = 1.0)
    assert ind["macd_hist_max_20d"] > 0
    print(f"✓ test_macd_zero_protection (max={ind['macd_hist_max_20d']:.6f})")


def test_atr_positive():
    df  = _make_mock_ohlcv()
    atr = IndicatorEngine.atr(df["high"], df["low"], df["close"])
    assert (atr.dropna() > 0).all()
    print(f"✓ test_atr_positive (last ATR={atr.iloc[-1]:.2f})")


def test_obv_slope_range():
    df    = _make_mock_ohlcv(trend="up")
    slope = IndicatorEngine.obv_slope_normalized(df["close"], df["volume"])
    assert -1.0 <= slope <= 1.0
    # Uptrend powinien dać pozytywny slope
    assert slope > 0, f"Uptrend powinien dać dodatni OBV slope, got {slope:.3f}"
    print(f"✓ test_obv_slope_range (slope={slope:.3f})")


def test_gap_metrics():
    df              = _make_mock_ohlcv()
    gap_avg, risk   = IndicatorEngine.gap_metrics(df["open"], df["close"])
    assert gap_avg >= 0
    assert risk in ("LOW", "MEDIUM", "HIGH")
    print(f"✓ test_gap_metrics (avg={gap_avg:.4f}, risk={risk})")


def test_roc():
    df  = _make_mock_ohlcv(trend="up")
    roc = IndicatorEngine.roc(df["close"], 10)
    # Uptrend → ROC powinien być pozytywny
    assert roc > 0, f"Uptrend powinien dać pozytywny ROC, got {roc:.2f}"
    print(f"✓ test_roc (roc={roc:.2f}%)")


def test_calculate_all_keys():
    """Sprawdza że calculate_all zwraca wszystkie pola potrzebne przez TickerData."""
    df  = _make_mock_ohlcv()
    ind = IndicatorEngine.calculate_all(df)

    required_keys = [
        "price", "sma200", "ema50", "ema20",
        "rsi_14", "macd_hist", "macd_hist_max_20d", "roc_10", "atr_14",
        "adv_20d", "rvol", "obv_slope",
        "gap_20d_avg", "gap_risk",
        "resistance", "support",
    ]

    for key in required_keys:
        assert key in ind, f"Brakuje klucza: {key}"
        val = ind[key]
        if isinstance(val, float):
            assert np.isfinite(val), f"{key} = {val} (nie jest finite)"

    print(f"✓ test_calculate_all_keys ({len(required_keys)} kluczy OK)")


def test_data_cleaner_valid():
    df     = _make_mock_ohlcv(n=100)
    result = DataCleaner.validate_ohlcv(df, "TEST")
    assert len(result) > 0
    print("✓ test_data_cleaner_valid")


def test_data_cleaner_too_short():
    df = _make_mock_ohlcv(n=30)
    try:
        DataCleaner.validate_ohlcv(df, "TEST")
        assert False, "Powinno rzucić DataQualityError"
    except DataQualityError as e:
        print(f"✓ test_data_cleaner_too_short ({e})")


def test_data_cleaner_nan():
    df = _make_mock_ohlcv(n=100)
    # Wprowadź 5 NaN w ostatnich 20 sesjach
    df.loc[df.index[-5:], "close"] = np.nan
    try:
        DataCleaner.validate_ohlcv(df, "TEST")
        assert False, "Powinno rzucić DataQualityError"
    except DataQualityError as e:
        print(f"✓ test_data_cleaner_nan ({e})")


def test_bid_ask_spread():
    spread = IndicatorEngine.bid_ask_spread(ask=100.10, bid=99.90)
    assert abs(spread - 0.002) < 0.0001   # ~0.2%
    print(f"✓ test_bid_ask_spread (spread={spread:.4f})")


def test_full_pipeline_with_mock_data():
    """
    Integracyjny test bez API: mock OHLCV → IndicatorEngine → TickerData → pipeline.
    Weryfikuje że Data Layer poprawnie buduje TickerData dla Scoring Engine.
    """
    try:
        from scoring_engine_v1 import (
            TickerData, Market, SetupType, EventStatus, GapRisk,
            PortfolioState, run_scoring_pipeline
        )
    except ImportError:
        print("✓ test_full_pipeline_with_mock_data (SKIP – scoring_engine_v1 niedostępny)")
        return

    df  = _make_mock_ohlcv(n=252, trend="up")
    ind = IndicatorEngine.calculate_all(df)

    close = float(df["close"].iloc[-1])

    td = TickerData(
        ticker    = "MOCK",
        market    = Market.US,
        price     = close,
        ask       = close * 1.001,
        bid       = close * 0.999,
        adv_20d   = ind["adv_20d"],
        rvol      = ind["rvol"],
        obv_slope = ind["obv_slope"],
        sma200    = ind["sma200"],
        ema50     = ind["ema50"],
        ema20     = ind["ema20"],
        rsi_14    = ind["rsi_14"],
        macd_hist = ind["macd_hist"],
        macd_hist_max_20d = ind["macd_hist_max_20d"],
        roc_10    = ind["roc_10"],
        atr_14    = ind["atr_14"],
        market_cap = 2_000_000_000,
        setup_type = SetupType.TREND_PULLBACK,
        resistance = ind["resistance"],
        support    = ind["support"],
        pattern_range_pct = 8.0,
        pullback_fib_pct  = 38.2,
        gap_20d_avg = ind["gap_20d_avg"],
        gap_risk    = GapRisk(ind["gap_risk"]),
        eps_growth_yoy     = 10.0,
        revenue_growth_yoy = 8.0,
        pe_ratio    = 22.0,
        sector_avg_pe = 25.0,
        debt_equity = 0.8,
        spy_price   = 480.0,
        spy_sma200  = 440.0,
        spy_sma50   = 465.0,
        vix_percentile = 35.0,
        event_status  = EventStatus.SAFE,
        sentiment_raw = 20.0,
        spread_pct    = 0.002,
        days_since_setup  = 1,
        catalyst_age_days = 1,
    )

    portfolio = PortfolioState(total_value=30_000, cash_balance=25_000)
    result    = run_scoring_pipeline(td, portfolio)

    assert result is not None, "Pipeline nie powinien odrzucić mockowego tickera"
    assert result.final_score > 0
    assert result.position_size >= 0
    print(
        f"✓ test_full_pipeline_with_mock_data "
        f"(grade={result.grade.value}, score={result.final_score:.1f}, "
        f"rsi={td.rsi_14:.1f}, rvol={td.rvol:.2f}x)"
    )


def run_all_tests():
    print("\n" + "="*55)
    print("DATA LAYER v1.0 – Unit Tests")
    print("="*55)
    test_ema()
    test_rsi_range()
    test_macd_histogram()
    test_macd_zero_protection()
    test_atr_positive()
    test_obv_slope_range()
    test_gap_metrics()
    test_roc()
    test_calculate_all_keys()
    test_data_cleaner_valid()
    test_data_cleaner_too_short()
    test_data_cleaner_nan()
    test_bid_ask_spread()
    test_full_pipeline_with_mock_data()
    print("="*55)
    print("Wszystkie testy przeszły ✓")
    print("="*55 + "\n")


# ─────────────────────────────────────────────
# 9. PRZYKŁAD UŻYCIA (wymaga kluczy API)
# ─────────────────────────────────────────────

USAGE_EXAMPLE = '''
# Przykład użycia z prawdziwymi kluczami API:

from data_layer import build_ticker_data, RegimeDetector, PolygonClient
from scoring_engine_v1 import PortfolioState, run_scoring_pipeline

POLYGON_KEY = "twoj_klucz_polygon"
FMP_KEY     = "twoj_klucz_fmp"   # opcjonalny

# Jeden shared RegimeDetector dla wszystkich tickerów (cache SPY)
polygon  = PolygonClient(POLYGON_KEY, tier="free")
regime   = RegimeDetector(polygon)

# Portfel
portfolio = PortfolioState(
    total_value=30_000,
    cash_balance=22_000,
    open_positions=[]
)

# Przetwórz listę tickerów
tickers = ["AAPL", "NVDA", "MSFT", "AMZN", "META"]
results = []

for ticker in tickers:
    try:
        td = build_ticker_data(
            ticker          = ticker,
            polygon_key     = POLYGON_KEY,
            fmp_key         = FMP_KEY,
            regime_detector = regime,       # reuse – nie pobiera SPY każdym razem
            event_status    = "SAFE",       # TODO: podłącz kalendarz eventów (L4)
            sentiment_raw   = 0.0,          # TODO: podłącz FinBERT (L5)
            setup_type      = "Trend Pullback",  # TODO: podłącz TA Filter (L2)
        )
        result = run_scoring_pipeline(td, portfolio)
        if result:
            results.append(result)
            print(f"{ticker}: {result.grade.value} ({result.final_score:.1f})")
        else:
            print(f"{ticker}: ODRZUCONY")
    except Exception as e:
        print(f"{ticker}: BŁĄD – {e}")

# Sortuj po score malejąco
results.sort(key=lambda r: r.final_score, reverse=True)
print("\\nTop sygnały:")
for r in results[:3]:
    print(f"  {r.ticker}: {r.grade.value} {r.final_score:.1f} | RR {r.real_rr:.2f} | {r.position_size:.0f} akcji")
'''


if __name__ == "__main__":
    run_all_tests()
    print(USAGE_EXAMPLE)
