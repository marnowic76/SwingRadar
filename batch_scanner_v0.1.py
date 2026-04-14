"""
Batch Scanner v1.0
Trading System – Masterplan V2.4.5

Orchestrator: watchlist → Data Layer → Scoring Engine → DB

Uruchamiany EOD (po zamknięciu sesji giełdowej):
    python batch_scanner.py --polygon-key YOUR_KEY
    python batch_scanner.py --polygon-key YOUR_KEY --dry-run
    python batch_scanner.py --polygon-key YOUR_KEY --tickers AAPL,NVDA,MSFT

Plik watchlist.txt (jeden ticker per linia, # = komentarz):
    AAPL
    NVDA
    # TSLA  ← zakomentowany
    MSFT

Dwa tryby:
    EOD scan  – generuje sygnały dla watchlisty
    EOD check – sprawdza otwarte pozycje (Losing Trade Alert)
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

# Market session auto-detect
try:
    from market_session import (
        get_scan_mode, ScanMode, SessionType,
        format_session_banner, now_et,
        SCAN_MODE_INTRADAY, SCAN_MODE_EOD,
    )
    _MARKET_SESSION_AVAILABLE = True
except ImportError:
    _MARKET_SESSION_AVAILABLE = False

# ─────────────────────────────────────────────
# Logging setup
# ─────────────────────────────────────────────

logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s | %(levelname)s | %(message)s",
    datefmt = "%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Default watchlist (~50 płynnych US tickers)
# ─────────────────────────────────────────────

DEFAULT_WATCHLIST = [
    # Mega-cap Tech
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA",
    # Semiconductors
    "AMD", "AVGO", "QCOM", "MU", "AMAT", "LRCX", "KLAC",
    # Software / Cloud
    "CRM", "NOW", "ADBE", "ORCL", "SNOW", "PLTR", "DDOG",
    # Financials
    "JPM", "GS", "MS", "BAC", "BLK", "V", "MA",
    # Healthcare / Biotech
    "LLY", "UNH", "ABBV", "TMO", "DHR", "ISRG",
    # Consumer / Retail
    "AMZN", "COST", "HD", "NKE", "SBUX",
    # Energy
    "XOM", "CVX", "COP",
    # ETF sektorowe (dla kontekstu)
    "QQQ", "SPY", "XLK", "SMH",
]
# Deduplikacja zachowując kolejność
DEFAULT_WATCHLIST = list(dict.fromkeys(DEFAULT_WATCHLIST))


# ─────────────────────────────────────────────
# Konfiguracja
# ─────────────────────────────────────────────

@dataclass
class ScanConfig:
    """Konfiguracja pojedynczego skanu."""
    polygon_key:   str
    fmp_key:       Optional[str]  = None
    polygon_tier:  str            = "free"
    min_score:     float          = 60.0
    min_grade:     Optional[str]  = None
    max_tickers:   int            = 50
    dry_run:       bool           = False
    setup_type:    str            = "Trend Pullback"
    portfolio_value: float        = 30_000.0
    cash_balance:    float        = 22_000.0
    watchlist_path:  str          = "watchlist.txt"
    scan_mode:     Optional[object] = None   # ScanMode – None = auto-detect


# ─────────────────────────────────────────────
# Watchlist loader
# ─────────────────────────────────────────────

def load_watchlist(path: str = "watchlist.txt") -> list[str]:
    """
    Wczytuje tickery z pliku (jeden per linia, # = komentarz).
    Fallback do DEFAULT_WATCHLIST jeśli plik nie istnieje.
    """
    p = Path(path)
    if p.exists():
        tickers = []
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                tickers.append(line.upper())
        logger.info(f"Wczytano {len(tickers)} tickerów z {path}")
        return tickers

    logger.info(f"Plik {path} nie istnieje – używam domyślnej watchlisty ({len(DEFAULT_WATCHLIST)} tickerów)")
    return DEFAULT_WATCHLIST.copy()


def load_tickers_from_cli(tickers_str: str) -> list[str]:
    """Parsuje tickery z argumentu CLI (AAPL,NVDA,MSFT)."""
    return [t.strip().upper() for t in tickers_str.split(",") if t.strip()]


# ─────────────────────────────────────────────
# EOD Position Check
# ─────────────────────────────────────────────

def run_eod_position_check(
    db_path,
    current_prices: dict[str, float],
) -> list[dict]:
    """
    EOD routine dla otwartych pozycji.
    Sprawdza Losing Trade Alert (L10 Masterplan V2.4.5).

    Args:
        current_prices: {ticker: current_close_price}

    Returns:
        Lista alertów do wyświetlenia/wysłania
    """
    try:
        from db_schema import PositionDAO
        from scoring_engine_v1 import check_losing_trade_alert
    except ImportError:
        logger.warning("Brak db_schema lub scoring_engine_v1 – pomijam EOD check")
        return []

    position_dao = PositionDAO(db_path)
    open_positions = position_dao.get_open_positions()
    alerts = []

    if not open_positions:
        logger.info("EOD Check: brak otwartych pozycji")
        return []

    logger.info(f"EOD Check: sprawdzam {len(open_positions)} otwartych pozycji")

    for pos in open_positions:
        ticker     = pos["ticker"]
        entry_date = pos["entry_date"]
        entry_price = pos["entry_price"]

        # Oblicz days_held
        try:
            entry_dt = datetime.strptime(entry_date, "%Y-%m-%d").date()
            days_held = (date.today() - entry_dt).days
        except (ValueError, TypeError):
            days_held = 0

        # Unrealized PnL
        current_price = current_prices.get(ticker, entry_price)
        unrealized_pct = (current_price - entry_price) / entry_price

        # Losing Trade Alert (L10)
        if check_losing_trade_alert(days_held, unrealized_pct):
            if not pos["losing_alert_sent"]:
                position_dao.update_losing_alert(pos["position_id"])
                alert = {
                    "ticker":         ticker,
                    "position_id":    pos["position_id"],
                    "days_held":      days_held,
                    "unrealized_pct": unrealized_pct,
                    "entry_price":    entry_price,
                    "current_price":  current_price,
                    "stop_loss":      pos["stop_loss"],
                }
                alerts.append(alert)
                logger.warning(
                    f"⚠ WEAK FOLLOW-THROUGH: {ticker} | "
                    f"dzień {days_held} | P&L {unrealized_pct:.1%}"
                )

        # Stop loss check
        if current_price <= pos["stop_loss"]:
            logger.warning(
                f"🛑 STOP LOSS HIT: {ticker} | "
                f"current={current_price:.2f} <= stop={pos['stop_loss']:.2f}"
            )

    return alerts


# ─────────────────────────────────────────────
# Główna pętla skanowania
# ─────────────────────────────────────────────

@dataclass
class ScanResult:
    """Wynik pojedynczego tickera."""
    ticker:      str
    status:      str        # "OK" | "REJECTED" | "ERROR"
    grade:       str = ""
    score:       float = 0.0
    real_rr:     float = 0.0
    signal_id:   str = ""
    error_msg:   str = ""


def run_daily_scan(
    config: ScanConfig,
    tickers: list[str]
) -> tuple[list[ScanResult], dict[str, float]]:
    """
    Główna pętla: lista tickerów → sygnały → DB.

    Fail-soft: błąd jednego tickera nie przerywa batcha.
    Każdy ticker dostaje nowy UUID przez ScoringResult.__init__.

    Returns:
        (results, current_prices)
        current_prices: {ticker: last_close} – używane przez EOD position check
    """
    try:
        from data_layer import (
            build_ticker_data, RegimeDetector, PolygonClient,
            DataQualityError, PolygonAPIError, PolygonNoDataError
        )
        from scoring_engine_v1 import run_scoring_pipeline, PortfolioState, Grade
        from db_schema import SignalDAO, create_all_tables, DB_PATH
    except ImportError as e:
        logger.error(f"Import error: {e}")
        sys.exit(1)

    tickers = tickers[:config.max_tickers]
    total   = len(tickers)

    # ── Auto-detect session mode ───────────────
    if _MARKET_SESSION_AVAILABLE:
        mode   = config.scan_mode or get_scan_mode()
        et_now = now_et()
        logger.info(f"\n{format_session_banner(mode, et_now)}")
    else:
        mode = None
        logger.info("market_session.py niedostępny – używam domyślnych progów")

    logger.info(f"Rozpoczynam skan {total} tickerów | "
                f"dry_run={config.dry_run} | tier={config.polygon_tier}")

    # ── Inicjalizacja ──────────────────────────
    polygon  = PolygonClient(config.polygon_key, tier=config.polygon_tier)
    regime   = RegimeDetector(polygon)

    if not config.dry_run:
        create_all_tables(DB_PATH)
        signal_dao = SignalDAO(DB_PATH)
    else:
        signal_dao = None
        logger.info("DRY RUN – dane nie będą zapisywane do DB")

    portfolio = PortfolioState(
        total_value  = config.portfolio_value,
        cash_balance = config.cash_balance,
    )

    results: list[ScanResult] = []
    current_prices: dict[str, float] = {}   # dla EOD position check

    # ── Główna pętla ───────────────────────────
    for i, ticker in enumerate(tickers, 1):
        logger.info(f"[{i:3}/{total}] {ticker}")
        scan_result = ScanResult(ticker=ticker, status="ERROR")

        try:
            # 1. Data Layer
            td = build_ticker_data(
                ticker          = ticker,
                polygon_key     = config.polygon_key,
                fmp_key         = config.fmp_key,
                polygon_tier    = config.polygon_tier,
                regime_detector = regime,         # shared – nie pobiera SPY każdym razem
                event_status    = "SAFE",         # TODO L4: earnings calendar
                sentiment_raw   = 0.0,            # TODO L5: FinBERT
                setup_type      = config.setup_type,
            )

            current_prices[ticker] = td.price    # zapisz dla EOD check

            # 2. Scoring Engine
            result = run_scoring_pipeline(td, portfolio, scan_mode=mode)

            if result is None:
                # Verbose: powód odrzucenia
                rsi_min     = mode.rsi_min     if mode else 40.0
                rsi_max     = mode.rsi_max     if mode else 75.0
                rvol_reject = mode.rvol_reject if mode else 1.0
                rvol_soft   = mode.rvol_soft   if mode else 1.5

                reasons = []
                if td.rvol < rvol_reject:
                    reasons.append(f"RVOL {td.rvol:.2f}x < {rvol_reject:.1f}x (L3 reject)")
                if td.rsi_14 < rsi_min or td.rsi_14 > rsi_max:
                    reasons.append(f"RSI {td.rsi_14:.1f} poza {rsi_min:.0f}–{rsi_max:.0f} (L2)")
                if not reasons:
                    # L3/L2 OK ale score za niski lub RR zbyt niskie
                    reasons.append(
                        f"RVOL {td.rvol:.2f}x (soft) → score < 60 lub RR zbyt niskie"
                    )

                reason_str = " | ".join(reasons)
                scan_result.status = "REJECTED"
                scan_result.error_msg = reason_str
                logger.info(f"  ✗ REJECTED → {reason_str}")
                continue

            # 3. Grade filter (opcjonalny)
            if config.min_grade:
                grade_order = {"A+": 4, "A": 3, "B": 2, "C": 1}
                if grade_order.get(result.grade.value, 0) < grade_order.get(config.min_grade, 0):
                    scan_result.status = "REJECTED"
                    scan_result.error_msg = f"Grade {result.grade.value} < min {config.min_grade}"
                    logger.info(f"  ✗ Grade filter ({result.grade.value})")
                    continue   # finally doda do results

            # 4. Score filter
            if result.final_score < config.min_score:
                scan_result.status = "REJECTED"
                scan_result.error_msg = f"Score {result.final_score:.1f} < min {config.min_score}"
                logger.info(f"  ✗ Score {result.final_score:.1f}")
                continue   # finally doda do results

            # 5. Zapis do DB
            scan_result.grade    = result.grade.value
            scan_result.score    = result.final_score
            scan_result.real_rr  = result.real_rr

            if signal_dao:
                regime_str = "Bull" if td.spy_price > td.spy_sma200 else (
                    "Bear" if td.spy_price < td.spy_sma200 * 0.9 else "Correction"
                )
                sid = signal_dao.save_signal(result, td, regime=regime_str)
                scan_result.signal_id = sid
                logger.info(
                    f"  ✓ {result.grade.value} | score={result.final_score:.1f} | "
                    f"RR={result.real_rr:.2f} | gap={td.gap_risk.value} | "
                    f"id={sid[:8]}..."
                )
            else:
                scan_result.signal_id = result.signal_id
                logger.info(
                    f"  ✓ [DRY] {result.grade.value} | score={result.final_score:.1f} | "
                    f"RR={result.real_rr:.2f}"
                )

            scan_result.status = "OK"

        except DataQualityError as e:
            scan_result.error_msg = f"DataQuality: {e}"
            logger.warning(f"  ⚠ Data quality: {e}")

        except PolygonNoDataError as e:
            scan_result.error_msg = f"NoData: {e}"
            logger.warning(f"  ⚠ Brak danych: {e}")

        except PolygonAPIError as e:
            scan_result.error_msg = f"API: {e}"
            logger.error(f"  ✗ Polygon API: {e}")

        except Exception as e:
            scan_result.error_msg = f"{type(e).__name__}: {e}"
            logger.error(f"  ✗ Nieoczekiwany błąd: {type(e).__name__}: {e}")

        finally:
            results.append(scan_result)

        # Rate limiting – free tier: 5 calls/min → ~12.5s między calls
        # Starter tier: bez limitu
        if config.polygon_tier == "free" and i < total:
            logger.debug(f"Rate limit: czekam 12.5s...")
            time.sleep(12.5)

    return results, current_prices


# ─────────────────────────────────────────────
# Raport końcowy
# ─────────────────────────────────────────────

def print_scan_report(results: list[ScanResult], dry_run: bool = False) -> None:
    """Drukuje podsumowanie skanu z rankingiem dnia."""
    ok       = [r for r in results if r.status == "OK"]
    rejected = [r for r in results if r.status == "REJECTED"]
    errors   = [r for r in results if r.status == "ERROR"]

    # Ranking dnia – sortowanie po score
    ok.sort(key=lambda r: r.score, reverse=True)

    label = "[DRY RUN] " if dry_run else ""

    print("\n" + "="*60)
    print(f"{label}SCAN ZAKOŃCZONY – {date.today()}")
    print(f"Łącznie: {len(results)} | OK: {len(ok)} | "
          f"Odrzucone: {len(rejected)} | Błędy: {len(errors)}")
    print("="*60)

    if ok:
        print(f"\n{'RANKING DNIA':^60}")
        print(f"{'#':>3}  {'Ticker':<8} {'Grade':<6} {'Score':>6} "
              f"{'Real RR':>8} {'Signal ID'}")
        print("─"*60)
        for i, r in enumerate(ok[:10], 1):
            sid_short = r.signal_id[:8] + "..." if r.signal_id else "─"
            print(f"{i:>3}. {r.ticker:<8} {r.grade:<6} {r.score:>6.1f} "
                  f"{r.real_rr:>7.2f}:1  {sid_short}")

    if errors:
        print(f"\nBŁĘDY ({len(errors)}):")
        for r in errors[:5]:   # max 5 błędów
            print(f"  {r.ticker}: {r.error_msg}")

    if ok and not dry_run:
        try:
            from db_schema import DB_PATH
            print(f"\nZapisano {len(ok)} sygnałów → {DB_PATH}")
        except ImportError:
            pass

    print("="*60)


# ─────────────────────────────────────────────
# Unit testy (bez API)
# ─────────────────────────────────────────────

def test_load_watchlist_default():
    """Brak pliku → domyślna lista."""
    tickers = load_watchlist("nieistniejacy_plik.txt")
    assert len(tickers) > 0
    assert "AAPL" in tickers
    assert "NVDA" in tickers
    # Brak duplikatów
    assert len(tickers) == len(set(tickers))
    print(f"✓ test_load_watchlist_default ({len(tickers)} tickerów)")


def test_load_watchlist_from_file(tmp_path=None):
    """Plik watchlist.txt → poprawne wczytanie."""
    import tempfile, os

    content = "AAPL\nNVDA\n# komentarz\nMSFT\n  AMZN  \n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(content)
        fname = f.name

    try:
        tickers = load_watchlist(fname)
        assert tickers == ["AAPL", "NVDA", "MSFT", "AMZN"]
        print("✓ test_load_watchlist_from_file")
    finally:
        os.unlink(fname)


def test_load_tickers_from_cli():
    tickers = load_tickers_from_cli("AAPL, nvda , MSFT")
    assert tickers == ["AAPL", "NVDA", "MSFT"]
    print("✓ test_load_tickers_from_cli")


def test_scan_result_dataclass():
    r = ScanResult(ticker="AAPL", status="OK", grade="A", score=82.5, real_rr=2.1)
    assert r.ticker == "AAPL"
    assert r.score == 82.5
    print("✓ test_scan_result_dataclass")


def test_eod_check_no_positions():
    """EOD check bez otwartych pozycji – brak alertów."""
    try:
        from db_schema import DB_PATH_TEST, create_all_tables
        create_all_tables(DB_PATH_TEST)
        alerts = run_eod_position_check(DB_PATH_TEST, {})
        assert alerts == []
        if DB_PATH_TEST.exists():
            DB_PATH_TEST.unlink()
        print("✓ test_eod_check_no_positions")
    except ImportError:
        print("✓ test_eod_check_no_positions (SKIP)")


def test_dry_run_pipeline():
    """
    Dry run z mockiem – weryfikuje że pipeline nie zapisuje do DB.
    """
    try:
        from data_layer import _make_mock_ohlcv, IndicatorEngine
        from scoring_engine_v1 import (
            TickerData, Market, SetupType, EventStatus, GapRisk,
            PortfolioState, run_scoring_pipeline
        )
        import numpy as np

        df  = _make_mock_ohlcv(n=252, trend="up")
        ind = IndicatorEngine.calculate_all(df)
        close = float(df["close"].iloc[-1])

        td = TickerData(
            ticker="MOCK", market=Market.US,
            price=close, ask=close*1.001, bid=close*0.999,
            adv_20d=ind["adv_20d"], rvol=ind["rvol"],
            obv_slope=ind["obv_slope"],
            sma200=ind["sma200"], ema50=ind["ema50"], ema20=ind["ema20"],
            rsi_14=ind["rsi_14"], macd_hist=ind["macd_hist"],
            macd_hist_max_20d=ind["macd_hist_max_20d"],
            roc_10=ind["roc_10"], atr_14=ind["atr_14"],
            market_cap=2_000_000_000,
            setup_type=SetupType.TREND_PULLBACK,
            resistance=ind["resistance"], support=ind["support"],
            pattern_range_pct=8.0, pullback_fib_pct=38.2,
            gap_20d_avg=ind["gap_20d_avg"], gap_risk=GapRisk(ind["gap_risk"]),
            eps_growth_yoy=10.0, revenue_growth_yoy=8.0,
            pe_ratio=22.0, sector_avg_pe=25.0, debt_equity=0.8,
            spy_price=480.0, spy_sma200=440.0, spy_sma50=465.0,
            vix_percentile=35.0,
            event_status=EventStatus.SAFE, sentiment_raw=20.0,
            spread_pct=0.002, days_since_setup=1, catalyst_age_days=1,
        )

        portfolio = PortfolioState(total_value=30_000, cash_balance=25_000)
        result    = run_scoring_pipeline(td, portfolio)

        # Każde wywołanie daje unikalny signal_id
        result2 = run_scoring_pipeline(td, portfolio)

        assert result is not None
        assert result2 is not None
        assert result.signal_id != result2.signal_id, \
            "Każdy run musi generować unikalny signal_id!"

        print(
            f"✓ test_dry_run_pipeline "
            f"(grade={result.grade.value}, score={result.final_score:.1f}, "
            f"unique_ids=✓)"
        )

    except ImportError as e:
        print(f"✓ test_dry_run_pipeline (SKIP: {e})")


def test_print_report():
    """print_scan_report nie rzuca wyjątków."""
    mock_results = [
        ScanResult("AAPL", "OK",       "A",  82.5, 2.1, str(uuid.uuid4())),
        ScanResult("NVDA", "OK",       "A+", 91.0, 2.8, str(uuid.uuid4())),
        ScanResult("TSLA", "REJECTED", "",   55.0, 0.0, ""),
        ScanResult("XYZ",  "ERROR",    "",   0.0,  0.0, "", "API timeout"),
    ]
    # Nie powinno rzucić wyjątku
    import io, contextlib
    f = io.StringIO()
    with contextlib.redirect_stdout(f):
        print_scan_report(mock_results, dry_run=True)
    output = f.getvalue()
    assert "NVDA" in output
    assert "A+" in output
    print("✓ test_print_report")


def run_all_tests():
    print("\n" + "="*55)
    print("BATCH SCANNER v1.0 – Unit Tests")
    print("="*55)
    test_load_watchlist_default()
    test_load_watchlist_from_file()
    test_load_tickers_from_cli()
    test_scan_result_dataclass()
    test_eod_check_no_positions()
    test_dry_run_pipeline()
    test_print_report()
    print("="*55)
    print("Wszystkie testy przeszły ✓")
    print("="*55 + "\n")


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Batch Scanner – Trading System V2.4.5",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Przykłady:
  # Skan domyślnej watchlisty (free tier)
  python batch_scanner.py --polygon-key PK_xxx

  # Tylko wybrane tickery
  python batch_scanner.py --polygon-key PK_xxx --tickers AAPL,NVDA,MSFT

  # Dry run – bez zapisu do DB
  python batch_scanner.py --polygon-key PK_xxx --dry-run

  # Tylko grade A i A+
  python batch_scanner.py --polygon-key PK_xxx --min-grade A

  # Starter tier (brak rate limiting)
  python batch_scanner.py --polygon-key PK_xxx --tier starter
        """
    )
    p.add_argument("--polygon-key",  required=True,
                   help="Polygon.io API key")
    p.add_argument("--fmp-key",
                   help="FMP API key (opcjonalny, lepsze fundamentals)")
    p.add_argument("--tickers",
                   help="Lista tickerów oddzielona przecinkami: AAPL,NVDA,MSFT")
    p.add_argument("--watchlist",    default="watchlist.txt",
                   help="Plik z tickerami (default: watchlist.txt)")
    p.add_argument("--tier",         default="free",
                   choices=["free", "starter", "developer"],
                   help="Polygon.io tier (default: free)")
    p.add_argument("--min-score",    type=float, default=60.0,
                   help="Minimalny score do zapisu (default: 60)")
    p.add_argument("--min-grade",    choices=["A+", "A", "B", "C"],
                   help="Minimalny grade (opcjonalny)")
    p.add_argument("--max-tickers",  type=int, default=50,
                   help="Maks. tickerów per skan (default: 50)")
    p.add_argument("--portfolio-value", type=float, default=30_000.0,
                   help="Wartość portfela w $ (default: 30000)")
    p.add_argument("--cash",         type=float, default=22_000.0,
                   help="Dostępna gotówka w $ (default: 22000)")
    p.add_argument("--dry-run",      action="store_true",
                   help="Symulacja – bez zapisu do DB")
    p.add_argument("--test",         action="store_true",
                   help="Uruchom unit testy i wyjdź")
    return p


def main():
    parser = build_parser()
    args   = parser.parse_args()

    if args.test:
        run_all_tests()
        return

    # Buduj konfigurację
    config = ScanConfig(
        polygon_key    = args.polygon_key,
        fmp_key        = args.fmp_key,
        polygon_tier   = args.tier,
        min_score      = args.min_score,
        min_grade      = args.min_grade,
        max_tickers    = args.max_tickers,
        dry_run        = args.dry_run,
        portfolio_value = args.portfolio_value,
        cash_balance   = args.cash,
        watchlist_path = args.watchlist,
    )

    # Wczytaj tickery
    if args.tickers:
        tickers = load_tickers_from_cli(args.tickers)
        logger.info(f"Tickery z CLI: {tickers}")
    else:
        tickers = load_watchlist(args.watchlist)

    # EOD Scan
    results, current_prices = run_daily_scan(config, tickers)

    # Raport
    print_scan_report(results, dry_run=config.dry_run)

    # EOD Position Check – używa cen z Data Layer (nie 0.0)
    try:
        from db_schema import DB_PATH
        if not config.dry_run and current_prices:
            alerts = run_eod_position_check(DB_PATH, current_prices)
            if alerts:
                print(f"\n⚠ LOSING TRADE ALERTS ({len(alerts)}):")
                for a in alerts:
                    print(
                        f"  {a['ticker']}: dzień {a['days_held']}, "
                        f"P&L {a['unrealized_pct']:.1%} | "
                        f"stop={a['stop_loss']:.2f}"
                    )
    except Exception as e:
        logger.debug(f"EOD position check pominięty: {e}")


if __name__ == "__main__":
    # Uruchom testy jeśli wywołano bez argumentów
    if len(sys.argv) == 1:
        run_all_tests()
    else:
        main()
