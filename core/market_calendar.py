"""
Market Calendar V1.0 - SwingRadar DSS
Zastępuje hardcodowane godziny NYSE dynamicznymi danymi z FMP.

Pobiera z FMP:
  /exchange-market-hours?exchange=NYSE  — godziny otwarcia/zamknięcia
  /holidays-by-exchange?exchange=NYSE   — kalendarz świąt giełdowych

Cache: godziny = 24h, święta = 7 dni (rzadko się zmieniają).
Fallback: jeśli FMP niedostępny, używa bezpiecznych wartości hardcodowanych.
"""

import logging
import requests
from datetime import datetime, timezone, date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class MarketCalendar:
    """
    Inteligentny kalendarz giełdowy oparty na danych FMP.
    Odpowiada na pytanie: czy NYSE jest teraz otwarta?
    """

    # Fallback hardcode — używane gdy FMP niedostępny
    _FALLBACK_OPEN_UTC  = 13   # 13:30 UTC = 09:30 ET
    _FALLBACK_CLOSE_UTC = 20   # 20:00 UTC = 16:00 ET

    def __init__(self, api_key: str):
        self.api_key  = api_key
        self.base_url = "https://financialmodelingprep.com/stable"

        # Cache godzin otwarcia (odświeżany co 24h)
        self._open_hour_utc:  int = self._FALLBACK_OPEN_UTC
        self._close_hour_utc: int = self._FALLBACK_CLOSE_UTC
        self._hours_loaded_at: Optional[datetime] = None
        self._fmp_is_open: bool = False  # isMarketOpen z FMP

        # Cache świąt giełdowych (odświeżany co 7 dni)
        self._holidays: set[str] = set()   # daty jako "YYYY-MM-DD"
        self._holidays_loaded_at: Optional[datetime] = None
        self._HOLIDAYS_TTL_DAYS = 7
        self._HOURS_TTL_HOURS   = 24

    # ══════════════════════════════════════════
    # ŁADOWANIE DANYCH Z FMP
    # ══════════════════════════════════════════

    def _load_market_hours(self) -> None:
        """
        Pobiera godziny otwarcia/zamknięcia NYSE z FMP.

        FMP zwraca format: "09:30 AM -04:00" — parsujemy godzinę i offset UTC.
        Wynik: ustawia self._open_hour_utc i self._close_hour_utc.
        Bonus: FMP zwraca też isMarketOpen — zapisujemy do szybkiego sprawdzenia.
        Fallback: zachowuje poprzednie wartości jeśli request zawiedzie.
        """
        now = datetime.now(timezone.utc)
        if self._hours_loaded_at:
            age_h = (now - self._hours_loaded_at).total_seconds() / 3600
            if age_h < self._HOURS_TTL_HOURS:
                return

        try:
            r = requests.get(
                f"{self.base_url}/exchange-market-hours",
                params={"exchange": "NYSE", "apikey": self.api_key},
                timeout=8
            )
            if r.status_code != 200:
                logger.warning(f"MarketCalendar: exchange-market-hours status {r.status_code} — fallback.")
                return

            data = r.json()
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("exchange", "").upper() == "NYSE":
                    open_str  = item.get("openingHour", "")   # "09:30 AM -04:00"
                    close_str = item.get("closingHour", "")   # "04:00 PM -04:00"

                    if open_str and close_str:
                        open_utc  = self._parse_fmp_time_to_utc(open_str)
                        close_utc = self._parse_fmp_time_to_utc(close_str)

                        if open_utc is not None and close_utc is not None:
                            self._open_hour_utc   = open_utc
                            self._close_hour_utc  = close_utc
                            self._hours_loaded_at = now
                            self._fmp_is_open     = item.get("isMarketOpen", False)
                            logger.info(
                                f"MarketCalendar: NYSE {open_str} – {close_str} "
                                f"= {open_utc}:00–{close_utc}:00 UTC | "
                                f"isMarketOpen={self._fmp_is_open}"
                            )
                            return

            logger.warning("MarketCalendar: Nie znaleziono NYSE w odpowiedzi — fallback.")

        except requests.exceptions.RequestException as e:
            logger.warning(f"MarketCalendar: Błąd pobierania godzin: {e} — fallback.")

    @staticmethod
    def _parse_fmp_time_to_utc(time_str: str) -> Optional[int]:
        """
        Parsuje format FMP: "09:30 AM -04:00" → godzina UTC jako int.
        Przykłady:
          "09:30 AM -04:00" → 9 + 4 = 13 UTC
          "04:00 PM -04:00" → 16 + 4 = 20 UTC
        """
        try:
            # Rozdzielamy: ["09:30", "AM", "-04:00"]
            parts = time_str.strip().split()
            if len(parts) < 3:
                return None

            hour_min = parts[0]   # "09:30"
            ampm     = parts[1]   # "AM" / "PM"
            offset   = parts[2]   # "-04:00" / "-05:00"

            hour = int(hour_min.split(":")[0])

            # Konwersja 12h → 24h
            if ampm.upper() == "PM" and hour != 12:
                hour += 12
            elif ampm.upper() == "AM" and hour == 12:
                hour = 0

            # Offset UTC: "-04:00" → +4 godziny do UTC
            offset_sign = 1 if offset.startswith("-") else -1
            offset_hour = int(offset.replace("+", "").replace("-", "").split(":")[0])
            utc_hour = hour + (offset_sign * offset_hour)

            return utc_hour

        except (ValueError, IndexError):
            return None

    def _load_holidays(self) -> None:
        """
        Pobiera kalendarz świąt NYSE z FMP na bieżący i następny rok.
        Wynik: ustawia self._holidays jako set dat "YYYY-MM-DD".
        """
        now = datetime.now(timezone.utc)
        if self._holidays_loaded_at:
            age_d = (now - self._holidays_loaded_at).total_seconds() / 86400
            if age_d < self._HOLIDAYS_TTL_DAYS:
                return

        try:
            r = requests.get(
                f"{self.base_url}/holidays-by-exchange",
                params={"exchange": "NYSE", "apikey": self.api_key},
                timeout=8
            )
            if r.status_code != 200:
                logger.warning(f"MarketCalendar: holidays status {r.status_code} — brak kalendarza świąt.")
                return

            data = r.json()
            items = data if isinstance(data, list) else [data]

            new_holidays = set()
            for item in items:
                # FMP zwraca: {exchange, date, name, isClosed, adjOpenTime, adjCloseTime}
                # Bierzemy tylko dni gdzie isClosed=True (nie skrócone sesje)
                is_closed = item.get("isClosed", True)
                holiday_date = item.get("date", "")
                if holiday_date and len(str(holiday_date)) >= 10 and is_closed:
                    new_holidays.add(str(holiday_date)[:10])

            self._holidays = new_holidays
            self._holidays_loaded_at = now

            logger.info(f"MarketCalendar: Załadowano {len(self._holidays)} świąt NYSE.")

        except requests.exceptions.RequestException as e:
            logger.warning(f"MarketCalendar: Błąd pobierania świąt: {e} — pomijam.")

    # ══════════════════════════════════════════
    # LOGIKA POMOCNICZA
    # ══════════════════════════════════════════

    @staticmethod
    def _is_dst_active() -> bool:
        """
        Przybliżone sprawdzenie czy USA jest w DST (letni czas).
        DST w USA: drugi niedziela marca → pierwsza niedziela listopada.
        """
        now = datetime.now(timezone.utc)
        year = now.year

        # Drugi niedziela marca
        march_1 = date(year, 3, 1)
        days_to_sun = (6 - march_1.weekday()) % 7  # dni do pierwszej niedzieli
        dst_start = march_1 + timedelta(days=days_to_sun + 7)  # +7 = druga niedziela

        # Pierwsza niedziela listopada
        nov_1 = date(year, 11, 1)
        days_to_sun = (6 - nov_1.weekday()) % 7
        dst_end = nov_1 + timedelta(days=days_to_sun)

        today = now.date()
        return dst_start <= today < dst_end

    def _is_holiday(self, check_date: date) -> bool:
        """Sprawdza czy podana data jest świętem giełdowym."""
        return check_date.strftime("%Y-%m-%d") in self._holidays

    # ══════════════════════════════════════════
    # PUBLICZNE API
    # ══════════════════════════════════════════

    def refresh(self) -> None:
        """
        Odświeża dane z FMP (godziny + święta).
        Wywołaj raz przy starcie daemona i raz dziennie.
        """
        self._load_market_hours()
        self._load_holidays()

    def is_trading_window(self) -> bool:
        """
        Czy NYSE jest teraz otwarta?
        Uwzględnia: weekendy, święta giełdowe, godziny sesji z FMP.
        """
        self.refresh()  # lazy refresh — nic nie robi jeśli cache aktualny

        now = datetime.now(timezone.utc)

        # Weekend
        if now.weekday() >= 5:
            return False

        # Święto giełdowe
        if self._is_holiday(now.date()):
            logger.info(f"MarketCalendar: Dziś święto NYSE ({now.date()}) — sesja zamknięta.")
            return False

        # Godziny sesji (z buforem 30 min przed otwarciem)
        open_with_buffer = self._open_hour_utc
        return open_with_buffer <= now.hour < self._close_hour_utc

    def is_premarket_window(self) -> bool:
        """
        Czy jesteśmy w oknie pre-market (przed otwarciem, dzień roboczy, nie święto)?
        Używane do cache warm-up i news scan.
        """
        self.refresh()

        now = datetime.now(timezone.utc)

        if now.weekday() >= 5:
            return False

        if self._is_holiday(now.date()):
            return False

        # Pre-market: od 6:00 UTC (2:00 ET) do otwarcia
        return 6 <= now.hour < self._open_hour_utc

    def is_decision_window(self) -> bool:
        """
        Okno decyzyjne: 17:30-19:00 PL (lato) = 15:30-17:00 UTC.
        1.5h na przegląd Top 10, konsultację wykresów i decyzję.
        NYSE zamknięte o 20:00 UTC — zostaje jeszcze 3h sesji po oknie.
        """
        now = datetime.now(timezone.utc)
        # 15:30-17:00 UTC = 17:30-19:00 PL (CEST)
        if now.hour == 15 and now.minute >= 30:
            return True
        if now.hour == 16:
            return True
        return False

    def next_open_info(self) -> str:
        """Zwraca czytelny opis kiedy następne otwarcie — do logów."""
        now = datetime.now(timezone.utc)
        if self.is_trading_window():
            return "Sesja trwa."

        # Znajdź następny dzień roboczy bez święta
        check = now.date() + timedelta(days=1)
        for _ in range(10):
            if check.weekday() < 5 and not self._is_holiday(check):
                return f"Następna sesja: {check} o {self._open_hour_utc}:00 UTC"
            check += timedelta(days=1)
        return "Nie można określić następnej sesji."
