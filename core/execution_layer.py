"""
Execution Layer V2.40 - Tarcza ISA & Real Execution Guard
Filtruje uniwersum ZANIM system wyśle kosztowne zapytania API o fundamenty.

ZMIANY V2.40:
- [FIX] Swing target cap: target = min(analyst_median, entry × 1.10)
  Analitycy wyceniają 12M horyzont — dla swing tradingu (2-4 tygodnie)
  cap 10% daje realistyczny RR 2-3 zamiast zawyżonego 6-8.
ZMIANY V2.39:
- [NEW] Micro Float Guard: spółki z floatem < 10M akcji odrzucane automatycznie
  (podatne na manipulację pump&dump, nieodpowiednie dla konta ISA)
ZMIANY V2.36:
- [NEW] calculate_real_rr() używa target_median jako głównego celu:
  Mediana jest odporna na outliers (jeden analityk z ceną 2x nie zaburza wyniku).
  Dodano target_high jako scenariusz optymistyczny w wyniku.
  Fallback: analyst_target jeśli brak mediany.
ZMIANY V2.32:
- [NEW] Earnings Veto: spółki raportujące wyniki w ciągu EARNINGS_VETO_DAYS dni
  są automatycznie odrzucane — binarne ryzyko jest nie do kontrolowania.
  Kalendarz pobierany z FMP /earnings-calendar raz na cykl i cachowany w pamięci.
- [NEW] get_earnings_dates() — pobiera daty wyników dla listy tickerów
- [NEW] has_upcoming_earnings() — sprawdza czy ticker raportuje w oknie ryzyka
"""

import logging
import requests
from datetime import datetime, timezone, timedelta
from typing import List

logger = logging.getLogger(__name__)


class ExecutionGuard:
    def __init__(self, fmp_api_key: str = ""):
        # 1. Filtry Płynności i Zmienności (Hard Guards)
        self.MIN_PRICE = 5.0
        self.MIN_DOLLAR_VOLUME = 20_000_000

        # Sektory wykluczone (Zabezpieczenie przed binarnym ryzykiem)
        # Sektor veto usunięty (V2.39+) — wszystkie sektory dopuszczone.
        # Ochrona przed binarnym ryzykiem zapewniona przez Earnings Veto (3 dni przed wynikami).
        self.EXCLUDED_SECTORS = []

        # 2. Koszty Realnej Egzekucji na koncie ISA (UK)
        self.STAMP_DUTY_PROXY = 0.005        # 0.5% podatku lub kosztu FX
        self.SLIPPAGE_BUFFER  = 0.003        # 0.3% poślizgu przy wejściu w pozycję
        self.MAX_SPREAD_PROXY = 0.04         # Maksymalny dopuszczalny spread (ATR/Price)
        self.MIN_RR           = 2.0          # Minimalne akceptowalne Real RR

        # 3. Zabezpieczenie Danych (Data Freshness)
        self.MAX_DATA_AGE_SECONDS = 300      # 5 minut maksymalnego opóźnienia decyzji

        # 4. Float Guard
        self.MICRO_FLOAT_VETO = 10_000_000   # < 10M akcji = ryzyko manipulacji

        # 5. Earnings Veto
        self.EARNINGS_VETO_DAYS = 3          # Odrzucamy spółki raportujące w ciągu 3 dni
        self.fmp_api_key = fmp_api_key
        self.base_url    = "https://financialmodelingprep.com/stable"

        # Cache kalendarza wyników (ticker -> data wyników)
        # Odświeżany raz na cykl przez load_earnings_calendar()
        self._earnings_cache: dict[str, str] = {}
        self._earnings_cache_loaded_at: datetime | None = None
        self._EARNINGS_CACHE_TTL_HOURS = 6   # Odświeżamy co 6h

    # ══════════════════════════════════════════
    # EARNINGS CALENDAR
    # ══════════════════════════════════════════

    def load_earnings_calendar(self, tickers: List[str]) -> None:
        """
        Pobiera daty wyników dla podanej listy tickerów z FMP /earnings-calendar.
        Wyniki są cachowane w pamięci na EARNINGS_CACHE_TTL_HOURS godzin.
        Wywołaj raz na początku każdego cyklu skanowania.
        """
        if not self.fmp_api_key:
            logger.debug("Earnings calendar: brak klucza API — pomijam.")
            return

        # Sprawdź czy cache jest aktualny
        now = datetime.now(timezone.utc)
        if self._earnings_cache_loaded_at is not None:
            age_h = (now - self._earnings_cache_loaded_at).total_seconds() / 3600
            if age_h < self._EARNINGS_CACHE_TTL_HOURS:
                logger.debug(f"Earnings cache aktualny ({age_h:.1f}h < {self._EARNINGS_CACHE_TTL_HOURS}h) — pomijam reload.")
                return

        # Okno: dziś + EARNINGS_VETO_DAYS + 1 dzień buforu
        date_from = now.strftime("%Y-%m-%d")
        date_to   = (now + timedelta(days=self.EARNINGS_VETO_DAYS + 1)).strftime("%Y-%m-%d")

        try:
            r = requests.get(
                f"{self.base_url}/earnings-calendar",
                params={
                    "from":    date_from,
                    "to":      date_to,
                    "apikey":  self.fmp_api_key,
                },
                timeout=10
            )
            if r.status_code != 200:
                logger.warning(f"Earnings calendar: status {r.status_code} — pomijam.")
                return

            data = r.json()
            if not isinstance(data, list):
                return

            # Budujemy słownik: ticker -> najbliższa data wyników
            new_cache = {}
            tickers_upper = set(t.upper() for t in tickers)
            for item in data:
                sym  = item.get("symbol", "").upper()
                date = item.get("date", "")
                if sym in tickers_upper and date:
                    # Jeśli ticker ma kilka dat — bierzemy najwcześniejszą
                    if sym not in new_cache or date < new_cache[sym]:
                        new_cache[sym] = date

            self._earnings_cache            = new_cache
            self._earnings_cache_loaded_at  = now

            upcoming = len(new_cache)
            logger.info(
                f"Earnings calendar załadowany: {upcoming} spółek raportuje "
                f"w ciągu {self.EARNINGS_VETO_DAYS} dni ({date_from} — {date_to})."
            )

        except requests.exceptions.RequestException as e:
            logger.warning(f"Earnings calendar błąd: {e} — pomijam veto.")

    def has_upcoming_earnings(self, ticker: str) -> bool:
        """
        Sprawdza czy ticker raportuje wyniki w oknie ryzyka (EARNINGS_VETO_DAYS dni).
        Wymaga wcześniejszego wywołania load_earnings_calendar().
        """
        return ticker.upper() in self._earnings_cache

    # ══════════════════════════════════════════
    # ISTNIEJĄCE METODY (bez zmian)
    # ══════════════════════════════════════════

    def is_data_fresh(self, data_timestamp: datetime) -> bool:
        """Sprawdza, czy system nie podejmuje decyzji na starych danych."""
        now = datetime.now(timezone.utc)
        age_seconds = (now - data_timestamp).total_seconds()
        if age_seconds > self.MAX_DATA_AGE_SECONDS:
            logger.warning(f"Data Freshness Guard: Dane przeterminowane ({age_seconds}s).")
            return False
        return True

    def is_sector_safe(self, sector: str) -> bool:
        """Wszystkie sektory dopuszczone — ochrona przez Earnings Veto."""
        return True

    def filter_universe(self, batch_quotes: dict) -> dict:
        """
        Filtruje rynek na podstawie samych cen z FMP (Layer 1).
        Odrzuca groszowe spółki, brak płynności, luki spadkowe
        oraz spółki raportujące wyniki w ciągu EARNINGS_VETO_DAYS dni.
        """
        playable_universe = {}
        earnings_vetoed   = 0

        for ticker, data in batch_quotes.items():
            price      = data.get("price", 0)
            volume     = data.get("volume", 0)
            change_pct = data.get("changesPercentage", 0) / 100.0

            # 1. Penny Stock Guard
            if price < self.MIN_PRICE:
                continue

            # 2. Fake Liquidity Guard (Dollar Volume)
            if price * volume < self.MIN_DOLLAR_VOLUME:
                continue

            # 3. Asymetryczny Gap Guard — luka spadkowa > 3%
            if change_pct < -0.03:
                continue

            # 4. Micro Float Guard — ryzyko manipulacji
            float_shares = data.get("float_shares")
            if float_shares is not None and float_shares < self.MICRO_FLOAT_VETO:
                logger.debug(f"Float Veto: {ticker} ma {float_shares/1e6:.1f}M akcji — odrzucam.")
                continue

            # 5. Earnings Veto — binarne ryzyko wyników
            if self.has_upcoming_earnings(ticker):
                earnings_date = self._earnings_cache.get(ticker.upper(), "?")
                logger.debug(f"Earnings Veto: {ticker} raportuje {earnings_date} — odrzucam.")
                earnings_vetoed += 1
                continue

            # Przepuszczamy — zapisujemy do grywalnego uniwersum
            playable_universe[ticker] = data
            playable_universe[ticker]["positive_gap_penalty"] = change_pct > 0.03

        log_msg = (
            f"Execution Guard: {len(playable_universe)}/{len(batch_quotes)} "
            f"tickerów przeszło przez L1."
        )
        if earnings_vetoed:
            log_msg += f" ({earnings_vetoed} odrzuconych przez Earnings Veto)"
        logger.info(log_msg)

        return playable_universe

    def calculate_real_rr(
        self,
        raw_price:     float,
        atr:           float,
        analyst_target: float,
        target_median: float = 0.0,
        target_high:   float = 0.0,
    ) -> dict:
        """
        Kalkulacja Real RR z uwzględnieniem poślizgu, podatku ISA i spreadu.

        Hierarchia targetu (od najbardziej do najmniej wiarygodnego):
          1. target_median  — mediana cen docelowych analityków (odporna na outliers)
          2. analyst_target — średnia (fallback gdy brak mediany)

        target_high jest używany wyłącznie informacyjnie w wyniku (scenariusz bull).
        Nie wpływa na kalkulację RR — żeby nie zawyżać oczekiwań.
        """
        # Wybieramy najlepszy dostępny target — mediana > średnia
        best_target = target_median if target_median > 0 else analyst_target

        if not atr or not best_target or raw_price <= 0:
            return {"status": "REJECT", "rr": 0}

        entry_price  = raw_price * (1 + self.SLIPPAGE_BUFFER)
        spread_proxy = atr / entry_price

        if spread_proxy > self.MAX_SPREAD_PROXY:
            return {"status": "REJECT", "rr": 0, "reason": "Spread Too High"}

        raw_sl              = entry_price - (1.5 * atr)
        real_risk_per_share = (entry_price - raw_sl) + (entry_price * self.STAMP_DUTY_PROXY)

        # Swing target cap — min(analyst_median × 0.85, entry × 1.10)
        # Analitycy wyceniają 12M horyzont, swing trade trwa 2-4 tygodnie.
        # Cap 10% od entry daje realistyczny cel i uczciwy RR 2-3.
        analyst_conservative = entry_price + ((best_target - entry_price) * 0.85)
        swing_cap            = entry_price * 1.10
        conservative_target  = min(analyst_conservative, swing_cap)
        reward_per_share     = conservative_target - entry_price

        if real_risk_per_share <= 0:
            return {"status": "REJECT", "rr": 0}

        real_rr = reward_per_share / real_risk_per_share

        result = {
            "rr":           round(real_rr, 2),
            "sl":           round(raw_sl, 2),
            "target":       round(conservative_target, 2),
            "entry_limit":  round(entry_price, 2),
            "target_used":  "median" if target_median > 0 else "avg",
        }
        # Scenariusz bull — tylko informacyjnie, nie wpływa na PASS/REJECT
        if target_high > entry_price:
            bull_target  = min(entry_price + ((target_high - entry_price) * 0.85), entry_price * 1.15)
            bull_rr      = (bull_target - entry_price) / real_risk_per_share
            result["rr_bull"] = round(bull_rr, 2)

        result["status"] = "PASS" if real_rr >= self.MIN_RR else "REJECT"
        return result
