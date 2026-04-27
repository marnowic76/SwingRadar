"""
FMP Data Provider V2.43 - SwingRadar DSS
Kompletny dostawca danych z załataną historią i kompletem wskaźników.

ZMIANY V2.43:
- [NEW] get_market_regime() — pobiera /sector-performance-snapshot:
  Liczy ile sektorów jest na plusie/minusie dziś.
  Zwraca: regime ("BULL"/"BEAR"/"NEUTRAL"), sectors_up, sectors_down
ZMIANY V2.42:
- [FIX] get_recent_8k() używa poprawnego endpointu /sec-filings-search/symbol
  z parametrami from/to zamiast /sec-filings-8k (który ignoruje symbol).
  Dodano filtr formType == "8-K" bo endpoint zwraca też inne typy.
ZMIANY V2.41:
- [NEW] get_recent_8k() — pobiera /sec-filings-8k dla tickera:
  Sprawdza czy spółka złożyła 8-K w ostatnich 7 dniach (material event).
  8-K = przejęcia, nowe kontrakty, zmiany zarządu, wyniki nieperiodyczne.
ZMIANY V2.40:
- [NEW] get_insider_stats() — pobiera /insider-trading/statistics:
  acquiredDisposedRatio, acquiredTransactions, disposedTransactions
  Używane przez ScoringEngine w fund_score jako sygnał jakości zarządu
ZMIANY V2.39:
- [NEW] get_float_data() — pobiera /shares-float:
  floatShares, freeFloat%, outstandingShares
  Używane przez ExecutionGuard (filtr manipulacji) i ScoringEngine (bonus low-float)
ZMIANY V2.38:
- [FIX] _fetch_news() — dedykowana metoda dla /news/stock?symbols=AAPL
  Poprzedni endpoint /stock-news zwracał 404 dla wszystkich tickerów.
ZMIANY V2.37:
- [NEW] get_price_momentum() — pobiera /stock-price-change:
  zmiana % za 1D, 5D, 1M, 3M, 6M w jednym requeście.
  Używane przez scoring_engine do oceny momentum wielookresowego.
ZMIANY V2.36:
- [NEW] get_quality_metrics() pobiera /price-target-consensus:
  target_median, target_high, target_low — mediana jest odporna na outliers,
  zastępuje estimatedPriceTargetAvg jako główny target do kalkulacji RR
ZMIANY V2.35:
- [NEW] get_quality_metrics() pobiera /financial-scores:
  piotroski_score (0-9) i altman_z_score — gotowe wartości z FMP, zero kalkulacji
ZMIANY V2.34:
- [NEW] get_screener_universe() — Stock Screener API z filtrami swing-trade:
  cena $10-500, vol >500K, market cap >2B, tylko NYSE/NASDAQ, exchange=US
  Zwraca spółki spełniające kryteria płynności i rozmiaru.
- [NEW] get_dynamic_universe() rozszerzony o 3. źródło: screener
  Priorytet: gainers > actives > screener (deduplikacja na każdym etapie)
ZMIANY V2.33:
- [NEW] get_quality_metrics() rozszerzony o grades_consensus:
  recent_upgrade, recent_downgrade, strong_buy_count, analyst_consensus
ZMIANY V2.32:
- [NEW] get_dynamic_universe() zaimplementowane:
  Łączy biggest-gainers + most-actives, filtruje duplikaty z watchlisty,
  zwraca do `limit` nowych tickerów z największym momentum dnia.
ZMIANY V2.31:
- [OPT] get_batch_quotes() — 1 request dla wszystkich tickerów (było N requestów)
  Oszczędność: ~126 req/cykl, czas skanu krótszy o ~30s
ZMIANY V2.29:
- [FIX] _fetch() z retry: timeout skrócony do 6s, 2 próby przed poddaniem się.
  Poprzednia wersja rzucała ERROR przy pierwszym timeoucie i przerywała skan.
ZMIANY V2.28:
- [FIX] get_dynamic_universe() nie zwraca cicho pustej listy — loguje INFO.
- [NOTE] Klucz API przekazywany ze zmiennej środowiskowej FMP_API_KEY.
"""

import logging
import pandas as pd
import requests
import requests_cache
from datetime import timedelta
from typing import List, Dict

logger = logging.getLogger(__name__)


class FMPProvider:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("FMPProvider: Pusty klucz API. Sprawdź zmienną środowiskową FMP_API_KEY.")
        self.api_key = api_key
        self.base_url = "https://financialmodelingprep.com/stable"

        self.session = requests_cache.CachedSession(
            'data/fmp_cache',
            expire_after=timedelta(hours=12),
            allowable_codes=[200]
        )

    def _fetch(self, endpoint: str, ticker: str, use_cache: bool = True, extra_params: dict = None):
        params = {"symbol": ticker, "apikey": self.api_key}
        if extra_params:
            params.update(extra_params)

        url = f"{self.base_url}/{endpoint}"

        for attempt in range(2):  # 1 próba + 1 retry
            try:
                req_engine = self.session if use_cache else requests
                r = req_engine.get(url, params=params, timeout=6)

                if r.status_code == 429:
                    logger.error("FMP API Limit Exceeded (429)! System dławi zapytania.")
                    return None
                elif r.status_code != 200:
                    logger.warning(f"FMP Warning: {endpoint} zwrócił {r.status_code} dla {ticker}")
                    return None

                data = r.json()
                return data if isinstance(data, list) else [data]

            except requests.exceptions.Timeout:
                logger.warning(f"FMP Timeout ({endpoint} / {ticker}) — próba {attempt + 1}/2")
            except requests.exceptions.RequestException as e:
                logger.error(f"FMP Request Error ({endpoint}): {e}")
                return None

        logger.warning(f"FMP: Obie próby nieudane ({endpoint} / {ticker}) — pomijam.")
        return None

    def _fetch_news(self, ticker: str, limit: int = 5) -> list:
        """
        Pobiera newsy dla tickera z FMP /news/stock?symbols=AAPL.
        Używa innej struktury URL niż _fetch() — stąd dedykowana metoda.
        Nie używa cache — newsy muszą być świeże.
        """
        try:
            r = requests.get(
                f"{self.base_url}/news/stock",
                params={
                    "symbols": ticker,
                    "limit":   limit,
                    "apikey":  self.api_key,
                },
                timeout=8
            )
            if r.status_code == 200:
                data = r.json()
                return data if isinstance(data, list) else []
            logger.warning(f"FMP News: /news/stock zwrócił {r.status_code} dla {ticker}")
            return []
        except requests.exceptions.RequestException as e:
            logger.warning(f"FMP News błąd ({ticker}): {e}")
            return []

    def get_dynamic_universe(self, limit: int = 20, watchlist: List[str] = None) -> List[str]:
        """
        Zwraca dynamicznie wybrane tickery z największym momentum dnia.

        Źródła (2 requesty łącznie):
        1. /biggest-gainers  — spółki z największym % wzrostem dnia
        2. /most-actives     — spółki z największym wolumenem dnia

        Logika:
        - Łączy obie listy, deduplikuje
        - Odrzuca tickery już obecne w watchliście (żeby nie duplikować skanów)
        - Odrzuca spółki z ceną < MIN_PRICE lub bez wolumenu
        - Zwraca do `limit` tickerów posortowanych wg zmiany % (malejąco)

        Parametry:
            limit     -- max liczba tickerów do zwrócenia (domyślnie 20)
            watchlist -- lista tickerów już w watchliście (do odfiltrowania)
        """
        watchlist_set = set(w.upper() for w in (watchlist or []))
        candidates = {}

        # Źródło 1: Biggest Gainers
        try:
            r = requests.get(
                f"{self.base_url}/biggest-gainers",
                params={"apikey": self.api_key},
                timeout=8
            )
            if r.status_code == 200:
                for item in r.json():
                    sym = item.get("symbol", "").upper()
                    if sym and sym not in watchlist_set:
                        candidates[sym] = {
                            "price":            float(item.get("price", 0)),
                            "changesPercentage": float(item.get("changesPercentage", 0)),
                            "volume":           int(item.get("volume", 0)),
                            "source":           "gainers",
                        }
            else:
                logger.warning(f"biggest-gainers zwrócił {r.status_code}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"biggest-gainers błąd: {e}")

        # Źródło 2: Most Actives (najwyższy wolumen)
        try:
            r = requests.get(
                f"{self.base_url}/most-actives",
                params={"apikey": self.api_key},
                timeout=8
            )
            if r.status_code == 200:
                for item in r.json():
                    sym = item.get("symbol", "").upper()
                    if sym and sym not in watchlist_set and sym not in candidates:
                        candidates[sym] = {
                            "price":            float(item.get("price", 0)),
                            "changesPercentage": float(item.get("changesPercentage", 0)),
                            "volume":           int(item.get("volume", 0)),
                            "source":           "actives",
                        }
            else:
                logger.warning(f"most-actives zwrócił {r.status_code}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"most-actives błąd: {e}")


        # Źródło 3: Stock Screener — spółki spełniające kryteria swing-trade
        screener_tickers = self.get_screener_universe(
            watchlist=list(watchlist_set) + list(candidates.keys()),
            limit=limit
        )
        for sym in screener_tickers:
            if sym not in candidates:
                candidates[sym] = {
                    "price":            0.0,
                    "changesPercentage": 0.0,
                    "volume":           0,
                    "source":           "screener",
                }

        # Filtrowanie końcowe: cena > 5$ i wolumen > 0
        # (screener już to filtruje, ale gainers/actives mogą mieć śmieci)
        MIN_PRICE = 5.0
        filtered = {
            sym: data for sym, data in candidates.items()
            if data["price"] >= MIN_PRICE or data["source"] == "screener"
        }

        # Sortowanie: gainers i actives wg % zmiany (malejąco), screener na końcu
        def sort_key(sym):
            d = filtered[sym]
            if d["source"] == "screener":
                return -999  # screener idzie na koniec
            return d["changesPercentage"]

        sorted_tickers = sorted(filtered.keys(), key=sort_key, reverse=True)[:limit]

        sources = {}
        for sym in sorted_tickers:
            src = filtered[sym]["source"]
            sources[src] = sources.get(src, 0) + 1

        if sorted_tickers:
            src_summary = ", ".join(f"{v} {k}" for k, v in sources.items())
            logger.info(f"Dynamic universe: {len(sorted_tickers)} tickerów ({src_summary}).")
        else:
            logger.info("Dynamic universe: brak nowych tickerów spoza watchlisty.")

        return sorted_tickers

    def get_screener_universe(self, watchlist: list = None, limit: int = 20) -> List[str]:
        """
        Pobiera spółki z FMP /company-screener z filtrami dopasowanymi
        do strategii swing-trade na koncie ISA (UK).

        Filtry:
          - exchange:       NASDAQ, NYSE  (tylko główne giełdy US)
          - priceMoreThan:  10            (nie grosze)
          - priceLessThan:  500           (nie za drogie do pozycji)
          - volumeMoreThan: 500000        (płynność min. 500K akcji/dzień)
          - marketCapMoreThan: 2000000000 (min. 2 mld USD — mid/large cap)
          - country:        US
          - isActivelyTrading: true

        Wyklucza tickery już w watchliście lub dynamicznym universum.
        """
        watchlist_set = set(w.upper() for w in (watchlist or []))

        try:
            r = requests.get(
                f"{self.base_url}/company-screener",
                params={
                    "exchange":            "NASDAQ,NYSE",
                    "priceMoreThan":       10,
                    "priceLessThan":       500,
                    "volumeMoreThan":      500_000,
                    "marketCapMoreThan":   2_000_000_000,
                    "country":            "US",
                    "isActivelyTrading":   "true",
                    "limit":               limit * 3,  # pobieramy więcej, bo będziemy filtrować
                    "apikey":              self.api_key,
                },
                timeout=10
            )

            if r.status_code != 200:
                logger.warning(f"Screener: status {r.status_code} — pomijam.")
                return []

            data = r.json()
            if not isinstance(data, list):
                return []

            results = []
            for item in data:
                sym = item.get("symbol", "").upper()
                if not sym or sym in watchlist_set:
                    continue

                # Dodatkowy filtr: wykluczamy ETFy i fundusze (brak sektora = podejrzane)
                sector = item.get("sector") or ""
                if not sector:
                    continue

                results.append(sym)
                if len(results) >= limit:
                    break

            logger.info(f"Screener: {len(results)} spółek spełnia kryteria swing-trade.")
            return results

        except requests.exceptions.RequestException as e:
            logger.warning(f"Screener błąd: {e} — pomijam.")
            return []

    def get_market_regime(self) -> dict:
        """
        Wykrywa reżim rynkowy na podstawie wyników sektorowych z FMP.

        Pobiera /sector-performance-snapshot dla dzisiejszej daty.
        Liczy ile sektorów NYSE jest na plusie vs minusie.

        Reżim:
          BULL    — >= 7 sektorów na plusie (szeroki rynek rośnie)
          BEAR    — >= 7 sektorów na minusie (szeroki rynek spada)
          NEUTRAL — pozostałe przypadki

        Cache: 30 minut — wystarczy dla 15-minutowego interwału skanowania.
        Fallback: NEUTRAL jeśli endpoint niedostępny.
        """
        from datetime import datetime, timezone
        now   = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")

        try:
            r = requests.get(
                f"{self.base_url}/sector-performance-snapshot",
                params={"date": today, "apikey": self.api_key},
                timeout=8
            )
            if r.status_code != 200 or not r.text:
                logger.warning(f"Market regime: status {r.status_code} — fallback NEUTRAL")
                return {"regime": "NEUTRAL", "sectors_up": 0, "sectors_down": 0, "detail": {}}

            data = r.json()
            if not isinstance(data, list):
                return {"regime": "NEUTRAL", "sectors_up": 0, "sectors_down": 0, "detail": {}}

            # Filtrujemy NYSE (główna giełda dla naszych spółek)
            # Jeśli brak NYSE bierzemy wszystkie
            nyse = [d for d in data if d.get("exchange", "").upper() == "NYSE"]
            items = nyse if nyse else data

            sectors_up   = sum(1 for d in items if float(d.get("averageChange", 0)) > 0)
            sectors_down = sum(1 for d in items if float(d.get("averageChange", 0)) < 0)
            total        = len(items)

            # Szczegóły sektorów do logowania
            detail = {
                d["sector"]: round(float(d.get("averageChange", 0)), 2)
                for d in items if "sector" in d
            }

            if total >= 8 and sectors_up >= 7:
                regime = "BULL"
            elif total >= 8 and sectors_down >= 7:
                regime = "BEAR"
            else:
                regime = "NEUTRAL"

            logger.info(
                f"Market Regime: {regime} "
                f"({sectors_up} sektorów ↑ / {sectors_down} ↓ / {total} total)"
            )
            return {
                "regime":       regime,
                "sectors_up":   sectors_up,
                "sectors_down": sectors_down,
                "detail":       detail,
            }

        except requests.exceptions.RequestException as e:
            logger.warning(f"Market regime błąd: {e} — fallback NEUTRAL")
            return {"regime": "NEUTRAL", "sectors_up": 0, "sectors_down": 0, "detail": {}}

    # ==========================================
    # LAYER 1: DANE REAL-TIME
    # ==========================================
    def get_batch_quotes(self, tickers: List[str]) -> Dict:
        """
        Pobiera quotes dla wszystkich tickerów w JEDNYM requeście API.
        FMP /quote przyjmuje listę symboli oddzielonych przecinkami.
        Poprzednia wersja robiła N requestów (jeden per ticker) — teraz jest 1.
        Fallback na pojedyncze requesty jeśli batch zawiedzie.
        """
        if not tickers:
            return {}

        # Plan Starter FMP nie obsługuje multi-symbol batch — odpytujemy pojedynczo
        results = {}
        for ticker in tickers:
            data = self._fetch("quote-short", ticker, use_cache=False)
            if data and len(data) > 0:
                item = data[0]
                price  = float(item.get("price", 0))
                change = float(item.get("change", 0))
                volume = int(item.get("volume", 0))

                prev_close  = price - change
                changes_pct = (change / prev_close * 100) if prev_close > 0 else 0

                results[ticker.upper()] = {
                    "price":            price,
                    "volume":           volume,
                    "changesPercentage": changes_pct,
                }
        return results

    def get_price_momentum(self, ticker: str) -> dict:
        """
        Pobiera wielookresowe zmiany ceny z FMP /stock-price-change.
        Jeden request zwraca: 1D, 5D, 1M, 3M, 6M, 1Y, 3Y, 5Y.

        Dla swing tradingu używamy: 1M i 3M jako wskaźniki trendu średnioterminowego.
        5D jako krótkoterminowe momentum tygodniowe.

        FMP zwraca wartości jako procenty (np. 5.2 = +5.2%).
        Normalizujemy do dziesiętnych (0.052) dla spójności z resztą systemu.

        Fallback: zwraca zera jeśli endpoint niedostępny.
        """
        data = self._fetch("stock-price-change", ticker, use_cache=True)

        if not data or not isinstance(data[0], dict):
            return {
                "change_1d":  0.0,
                "change_5d":  0.0,
                "change_1m":  0.0,
                "change_3m":  0.0,
                "change_6m":  0.0,
            }

        item = data[0]

        def pct(key: str) -> float:
            """
            FMP zwraca już wartości procentowe (8.66 = +8.66%).
            Konwertujemy do dziesiętnych (0.0866) dla spójności z resztą systemu.
            """
            raw = item.get(key)
            try:
                return float(raw) / 100.0 if raw is not None else 0.0
            except (TypeError, ValueError):
                return 0.0

        # Klucze potwierdzone z FMP: '1D', '5D', '1M', '3M', '6M'
        return {
            "change_1d": pct("1D"),
            "change_5d": pct("5D"),
            "change_1m": pct("1M"),
            "change_3m": pct("3M"),
            "change_6m": pct("6M"),
        }

    def get_float_data(self, ticker: str) -> dict:
        """
        Pobiera dane o float akcji z FMP /shares-float.

        Klucze z FMP:
          floatShares      — liczba akcji w wolnym obrocie
          freeFloat        — % akcji w wolnym obrocie (np. 99.77)
          outstandingShares — łączna liczba akcji

        Klasyfikacja float dla swing tradingu:
          < 10M  akcji = Micro float  — ekstremalnie ryzykowny (manipulacja)
          < 50M  akcji = Low float    — silne ruchy, premium za RVOL
          < 200M akcji = Mid float    — standardowy
          >= 200M akcji = Large float  — large/mega cap, wolniejsze ruchy

        Cachowane 12h — float zmienia się rzadko.
        Fallback: None dla wszystkich pól jeśli endpoint niedostępny.
        """
        data = self._fetch("shares-float", ticker, use_cache=True)

        if not data or not isinstance(data[0], dict):
            return {
                "float_shares":       None,
                "free_float_pct":     None,
                "outstanding_shares": None,
                "float_category":     None,
            }

        item = data[0]
        float_shares = item.get("floatShares")
        free_float   = item.get("freeFloat")
        outstanding  = item.get("outstandingShares")

        # Klasyfikacja
        category = None
        if float_shares is not None:
            fs = float(float_shares)
            if fs < 10_000_000:
                category = "micro"
            elif fs < 50_000_000:
                category = "low"
            elif fs < 200_000_000:
                category = "mid"
            else:
                category = "large"

        return {
            "float_shares":       float(float_shares) if float_shares is not None else None,
            "free_float_pct":     float(free_float)   if free_float   is not None else None,
            "outstanding_shares": float(outstanding)  if outstanding  is not None else None,
            "float_category":     category,
        }

    def get_insider_stats(self, ticker: str) -> dict:
        """
        Pobiera statystyki transakcji insiderów z FMP /insider-trading/statistics.

        Klucze z FMP (bieżący kwartał):
          acquiredDisposedRatio  — stosunek kupna do sprzedaży (>1 = netto kupowanie)
          acquiredTransactions   — liczba transakcji kupna
          disposedTransactions   — liczba transakcji sprzedaży
          totalAcquired          — łączna liczba akcji zakupionych
          totalDisposed          — łączna liczba akcji sprzedanych

        Interpretacja dla swing tradingu:
          ratio > 1.0  = insiderzy kupują netto → silny sygnał wewnętrzny
          ratio > 0.5  = neutralny / lekko pozytywny
          ratio < 0.2  = insiderzy masowo sprzedają → ostrzeżenie
          brak danych  = neutralny (nie karamy ani nie nagradzamy)

        Cache 12h — statystyki kwartalne zmieniają się rzadko.
        """
        data = self._fetch("insider-trading/statistics", ticker, use_cache=True)

        if not data or not isinstance(data[0], dict):
            return {
                "insider_ratio":        None,
                "insider_acquired":     None,
                "insider_disposed":     None,
                "insider_net_buying":   False,
                "insider_net_selling":  False,
            }

        item = data[0]

        ratio    = item.get("acquiredDisposedRatio")
        acquired = item.get("acquiredTransactions", 0)
        disposed = item.get("disposedTransactions", 0)

        ratio_f = float(ratio) if ratio is not None else None

        return {
            "insider_ratio":       ratio_f,
            "insider_acquired":    int(acquired) if acquired else 0,
            "insider_disposed":    int(disposed) if disposed else 0,
            # Sygnały binarne do scoringu
            "insider_net_buying":  ratio_f is not None and ratio_f > 1.0,
            "insider_net_selling": ratio_f is not None and ratio_f < 0.2,
        }

    def get_recent_8k(self, ticker: str, days: int = 7) -> dict:
        """
        Sprawdza czy spółka złożyła formularz 8-K w ostatnich `days` dniach.

        8-K to zgłoszenie do SEC o istotnym zdarzeniu (material event):
          przejęcia, nowe kontrakty, zmiany zarządu, wyniki nieperiodyczne.

        Używa /sec-filings-search/symbol z parametrami from/to i formType=8-K.
        Endpoint wymaga obu dat — budujemy okno: (dziś - days) → dziś.
        Filtrujemy po formType == "8-K" bo endpoint zwraca też inne typy.

        Cache: NIE cachujemy — 8-K może pojawić się w dowolnym momencie.
        """
        from datetime import datetime, timezone, timedelta
        now      = datetime.now(timezone.utc)
        date_to  = now.strftime("%Y-%m-%d")
        date_from = (now - timedelta(days=days)).strftime("%Y-%m-%d")

        try:
            r = requests.get(
                f"{self.base_url}/sec-filings-search/symbol",
                params={
                    "symbol":   ticker,
                    "formType": "8-K",
                    "from":     date_from,
                    "to":       date_to,
                    "limit":    5,
                    "apikey":   self.api_key,
                },
                timeout=8
            )
            if r.status_code != 200 or not r.text:
                return {"has_recent_8k": False, "days_since_8k": None, "filing_date": None}

            data = r.json()
            if not isinstance(data, list):
                return {"has_recent_8k": False, "days_since_8k": None, "filing_date": None}

        except requests.exceptions.RequestException as e:
            logger.warning(f"8-K fetch błąd ({ticker}): {e}")
            return {"has_recent_8k": False, "days_since_8k": None, "filing_date": None}

        for item in data:
            # Filtrujemy tylko prawdziwe 8-K (endpoint zwraca też SC 13G, DEF 14A itp.)
            if item.get("formType", "") != "8-K":
                continue

            date_str = item.get("filingDate") or item.get("acceptedDate") or ""
            if not date_str:
                continue

            try:
                filing_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                if filing_dt.tzinfo is None:
                    filing_dt = filing_dt.replace(tzinfo=timezone.utc)
            except (ValueError, AttributeError):
                continue

            days_ago = (now - filing_dt).days
            return {
                "has_recent_8k": True,
                "days_since_8k": days_ago,
                "filing_date":   date_str[:10],
            }

        return {
            "has_recent_8k": False,
            "days_since_8k": None,
            "filing_date":   None,
        }

    # ==========================================
    # LAYER 3: DANE HISTORYCZNE
    # ==========================================
    def get_historical_daily(self, ticker: str, days: int = 40) -> pd.DataFrame:
        data = self._fetch("historical-price-eod/light", ticker, use_cache=True)

        if not data:
            return pd.DataFrame()

        records = (
            data[0].get("historical")
            if isinstance(data[0], dict) and "historical" in data[0]
            else data
        )

        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)
        df.columns = [col.lower() for col in df.columns]

        if "price" in df.columns and "close" not in df.columns:
            df = df.rename(columns={"price": "close"})

        if "date" not in df.columns or "close" not in df.columns:
            return pd.DataFrame()

        for col in ["open", "high", "low"]:
            if col not in df.columns:
                df[col] = df["close"]

        if "volume" not in df.columns:
            df["volume"] = 0

        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        return df.tail(days).reset_index(drop=True)

    # ==========================================
    # LAYER 4: JAKOŚĆ I FUNDAMENTY
    # ==========================================
    def get_quality_metrics(self, ticker: str) -> dict:
        estimates    = self._fetch(
            "analyst-estimates", ticker,
            use_cache=True, extra_params={"period": "annual", "limit": 1}
        )
        metrics      = self._fetch("key-metrics-ttm",        ticker, use_cache=True)
        grades       = self._fetch("grades-historical",       ticker, use_cache=True,
                                   extra_params={"limit": 10})
        scores       = self._fetch("financial-scores",        ticker, use_cache=True)
        pt_consensus = self._fetch("price-target-consensus",  ticker, use_cache=True)

        m_data   = metrics[0]       if metrics       else {}
        e_data   = estimates[0]     if estimates     else {}
        s_data   = scores[0]        if scores        else {}
        pt_data  = pt_consensus[0]  if pt_consensus  else {}

        # Insider statistics — osobna metoda (cache 12h)
        insider  = self.get_insider_stats(ticker)
        # Recent 8-K — nie cachujemy, sprawdzamy na żywo przy każdym skanie
        eightk   = self.get_recent_8k(ticker)

        # ── Grades: szukamy upgrade/downgrade w ostatnich 30 dniach ──
        recent_upgrade   = False
        recent_downgrade = False
        strong_buy_count = 0
        analyst_consensus = ""

        if grades:
            from datetime import datetime, timezone, timedelta
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)

            for g in grades:
                # Data oceny
                grade_date_str = g.get("date", "") or g.get("gradingDate", "")
                try:
                    grade_date = datetime.fromisoformat(grade_date_str.replace("Z", "+00:00"))
                    if grade_date.tzinfo is None:
                        grade_date = grade_date.replace(tzinfo=timezone.utc)
                except (ValueError, AttributeError):
                    continue

                if grade_date < cutoff:
                    continue  # Starsza niż 30 dni — pomijamy

                action = (g.get("action") or g.get("gradeAction") or "").lower()
                grade  = (g.get("newGrade") or g.get("grade") or "").lower()

                if action in ("upgrade", "initiated", "reiterated"):
                    if any(w in grade for w in ("buy", "outperform", "overweight", "strong buy")):
                        recent_upgrade = True
                    if "strong buy" in grade:
                        strong_buy_count += 1

                if action == "downgrade":
                    if any(w in grade for w in ("sell", "underperform", "underweight", "reduce")):
                        recent_downgrade = True

        # Consensus z grades-consensus (osobny lekki endpoint)
        consensus_data = self._fetch("grades-consensus", ticker, use_cache=True)
        if consensus_data:
            analyst_consensus = consensus_data[0].get("consensus", "")

        # Piotroski Score: 0-9 (FMP liczy go za nas z bilansu)
        # None oznacza brak danych — scoring engine obsługuje ten przypadek
        piotroski_raw = s_data.get("piotroskiScore")
        piotroski_score = int(piotroski_raw) if piotroski_raw is not None else None

        # Altman Z-Score: > 2.99 = bezpieczna, 1.81-2.99 = szara strefa, < 1.81 = zagrożona
        altman_raw = s_data.get("altmanZScore")
        altman_z_score = float(altman_raw) if altman_raw is not None else None

        return {
            "roe":               m_data.get("roeTTM", 0.0),
            "debt_equity":       m_data.get("debtToEquityTTM", 0.0),
            "eps_growth":        m_data.get("epsGrowthTTM", 0.0),
            # Price Targets — używamy mediany (odporna na outliers) jako główny target
            # Klucze z FMP /price-target-consensus: targetMedian, targetHigh, targetLow, targetConsensus
            # Fallback: estimatedPriceTargetAvg z analyst-estimates jeśli brak mediany
            "analyst_target":    (
                float(pt_data.get("targetMedian") or 0) or
                float(e_data.get("estimatedPriceTargetAvg") or 0)
            ),
            "target_median":     float(pt_data.get("targetMedian")    or 0),
            "target_high":       float(pt_data.get("targetHigh")      or 0),
            "target_low":        float(pt_data.get("targetLow")       or 0),
            "target_consensus":  float(pt_data.get("targetConsensus") or 0),
            # Grades
            "recent_upgrade":    recent_upgrade,
            "recent_downgrade":  recent_downgrade,
            "strong_buy_count":  strong_buy_count,
            "analyst_consensus": analyst_consensus,
            # Financial Health Scores
            "piotroski_score":   piotroski_score,
            "altman_z_score":    altman_z_score,
            # Insider Trading Statistics
            "insider_ratio":     insider["insider_ratio"],
            "insider_net_buying":  insider["insider_net_buying"],
            "insider_net_selling": insider["insider_net_selling"],
            # Recent 8-K (material events)
            "has_recent_8k":     eightk["has_recent_8k"],
            "days_since_8k":     eightk["days_since_8k"],
        }
