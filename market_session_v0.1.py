"""
Market Session Detector v1.0
Trading System – Masterplan V2.4.5

Auto-detect trybu skanowania na podstawie czasu UTC i kalendarza NYSE.
Zwraca ScanMode z odpowiednimi progami dla L3 i L2.

Tryby:
    PRE_MARKET   04:00–09:30 ET  →  progi EOD (dane z poprzedniego dnia)
    INTRADAY     09:30–16:00 ET  →  progi intraday (aktywny volume spike)
    AFTER_HOURS  16:00–20:00 ET  →  progi EOD (volume dzienny kompletny)
    CLOSED       20:00–04:00 ET  →  progi EOD (domyślny tryb wieczorny)
    WEEKEND      sob/nie          →  progi EOD

Użycie:
    from market_session import get_scan_mode, ScanMode
    mode = get_scan_mode()
    print(mode.name, mode.rvol_min, mode.rsi_min, mode.rsi_max)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from enum import Enum


# ─────────────────────────────────────────────
# Strefa czasowa ET (Eastern Time)
# NYSE: UTC-5 (EST) lub UTC-4 (EDT w lecie)
# Python nie ma wbudowanego DST – używamy prostej
# aproksymacji: DST aktywne od 2. niedzieli marca
# do 1. niedzieli listopada (reguła US)
# ─────────────────────────────────────────────

def _get_et_offset(dt_utc: datetime) -> int:
    """
    Zwraca offset ET względem UTC w godzinach.
    -4 = EDT (lato), -5 = EST (zima)
    """
    year = dt_utc.year

    # DST start: 2. niedziela marca
    march_1 = datetime(year, 3, 1, tzinfo=timezone.utc)
    # weekday(): 0=poniedziałek, 6=niedziela
    days_to_sunday = (6 - march_1.weekday()) % 7
    dst_start = march_1 + timedelta(days=days_to_sunday + 7)  # +7 = 2. niedziela
    dst_start = dst_start.replace(hour=7)  # 2:00 ET = 7:00 UTC (w EST)

    # DST end: 1. niedziela listopada
    nov_1 = datetime(year, 11, 1, tzinfo=timezone.utc)
    days_to_sunday = (6 - nov_1.weekday()) % 7
    dst_end = nov_1 + timedelta(days=days_to_sunday)  # 1. niedziela
    dst_end = dst_end.replace(hour=6)  # 2:00 ET = 6:00 UTC (w EDT)

    if dst_start <= dt_utc < dst_end:
        return -4  # EDT (lato)
    return -5      # EST (zima)


def utc_to_et(dt_utc: datetime) -> datetime:
    """Konwertuje datetime UTC na Eastern Time."""
    offset = _get_et_offset(dt_utc)
    return dt_utc + timedelta(hours=offset)


def now_et() -> datetime:
    """Zwraca aktualny czas w ET."""
    return utc_to_et(datetime.now(timezone.utc))


# ─────────────────────────────────────────────
# Typy sesji
# ─────────────────────────────────────────────

class SessionType(str, Enum):
    PRE_MARKET  = "PRE_MARKET"    # 04:00–09:30 ET
    INTRADAY    = "INTRADAY"      # 09:30–16:00 ET (giełda otwarta)
    AFTER_HOURS = "AFTER_HOURS"   # 16:00–20:00 ET
    CLOSED      = "CLOSED"        # 20:00–04:00 ET
    WEEKEND     = "WEEKEND"       # sobota / niedziela


# ─────────────────────────────────────────────
# Progi per tryb skanowania
# ─────────────────────────────────────────────

@dataclass(frozen=True)
class ScanMode:
    """
    Zestaw progów skanowania dostosowany do sesji giełdowej.
    Przekazywany do evaluate_liquidity() i TA Filter.
    """
    session:     SessionType

    # L3 – RVOL progi
    rvol_reject:  float   # poniżej → REJECT
    rvol_soft:    float   # poniżej → SOFT_WARNING (powyżej → PASS)

    # L2 – RSI zakres akceptowalny
    rsi_min:      float
    rsi_max:      float

    # Snapshot dostępny? (wymaga paid tier przy intraday)
    use_snapshot: bool

    # Opis dla logów
    description:  str

    @property
    def name(self) -> str:
        return self.session.value


# Definicje trybów
SCAN_MODE_INTRADAY = ScanMode(
    session      = SessionType.INTRADAY,
    rvol_reject  = 1.2,    # aktywna sesja – wymagamy wyraźniejszego volume
    rvol_soft    = 1.5,    # PASS przy ≥ 1.5×
    rsi_min      = 40.0,
    rsi_max      = 75.0,
    use_snapshot = True,   # ask/bid dostępny (paid tier)
    description  = "Intraday scan (NYSE open 09:30–16:00 ET) – strict RVOL",
)

SCAN_MODE_EOD = ScanMode(
    session      = SessionType.AFTER_HOURS,
    rvol_reject  = 0.8,    # EOD – akceptujemy normalny dzienny volume
    rvol_soft    = 1.2,    # PASS przy ≥ 1.2× (lekko powyżej normalnego)
    rsi_min      = 35.0,   # szerszy zakres – szukamy setupów na jutro
    rsi_max      = 78.0,
    use_snapshot = False,  # brak ask/bid po zamknięciu → fallback do close
    description  = "EOD scan (after hours) – relaxed RVOL, full day volume",
)

SCAN_MODE_PRE_MARKET = ScanMode(
    session      = SessionType.PRE_MARKET,
    rvol_reject  = 0.8,    # dane z wczoraj – identycznie jak EOD
    rvol_soft    = 1.2,
    rsi_min      = 35.0,
    rsi_max      = 78.0,
    use_snapshot = False,
    description  = "Pre-market scan (04:00–09:30 ET) – previous day data",
)

SCAN_MODE_CLOSED = ScanMode(
    session      = SessionType.CLOSED,
    rvol_reject  = 0.8,
    rvol_soft    = 1.2,
    rsi_min      = 35.0,
    rsi_max      = 78.0,
    use_snapshot = False,
    description  = "Closed market scan – EOD data from last session",
)

SCAN_MODE_WEEKEND = ScanMode(
    session      = SessionType.WEEKEND,
    rvol_reject  = 0.8,
    rvol_soft    = 1.2,
    rsi_min      = 35.0,
    rsi_max      = 78.0,
    use_snapshot = False,
    description  = "Weekend scan – Friday EOD data",
)


# ─────────────────────────────────────────────
# Główna funkcja detekcji
# ─────────────────────────────────────────────

def detect_session(dt_utc: datetime | None = None) -> SessionType:
    """
    Wykrywa typ sesji NYSE na podstawie czasu UTC.

    Args:
        dt_utc: czas UTC (None = teraz)

    Returns:
        SessionType
    """
    if dt_utc is None:
        dt_utc = datetime.now(timezone.utc)

    et = utc_to_et(dt_utc)

    # Weekend
    if et.weekday() >= 5:  # 5=sobota, 6=niedziela
        return SessionType.WEEKEND

    hour_min = et.hour + et.minute / 60.0

    if 4.0 <= hour_min < 9.5:          # 04:00–09:30 ET
        return SessionType.PRE_MARKET
    elif 9.5 <= hour_min < 16.0:       # 09:30–16:00 ET
        return SessionType.INTRADAY
    elif 16.0 <= hour_min < 20.0:      # 16:00–20:00 ET
        return SessionType.AFTER_HOURS
    else:                               # 20:00–04:00 ET
        return SessionType.CLOSED


def get_scan_mode(dt_utc: datetime | None = None) -> ScanMode:
    """
    Główna funkcja – zwraca ScanMode z progami dostosowanymi do sesji.

    Użycie:
        mode = get_scan_mode()
        # → automatycznie dobiera INTRADAY lub EOD
    """
    session = detect_session(dt_utc)

    mode_map = {
        SessionType.INTRADAY:    SCAN_MODE_INTRADAY,
        SessionType.PRE_MARKET:  SCAN_MODE_PRE_MARKET,
        SessionType.AFTER_HOURS: SCAN_MODE_EOD,
        SessionType.CLOSED:      SCAN_MODE_CLOSED,
        SessionType.WEEKEND:     SCAN_MODE_WEEKEND,
    }

    return mode_map[session]


def format_session_banner(mode: ScanMode, et_time: datetime) -> str:
    """Formatuje banner informacyjny o trybie skanowania."""
    day_names = ["Pon", "Wt", "Śr", "Czw", "Pt", "Sob", "Nd"]
    day = day_names[et_time.weekday()]

    lines = [
        "─" * 55,
        f"SESSION: {mode.session.value:<12} │ {day} {et_time.strftime('%H:%M')} ET",
        f"MODE:    {mode.description}",
        f"RVOL:    reject < {mode.rvol_reject:.1f}× │ soft < {mode.rvol_soft:.1f}× │ pass ≥ {mode.rvol_soft:.1f}×",
        f"RSI:     {mode.rsi_min:.0f} – {mode.rsi_max:.0f}",
        f"SNAPSHOT: {'✓ (ask/bid)' if mode.use_snapshot else '✗ (fallback → close price)'}",
        "─" * 55,
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────
# Unit testy
# ─────────────────────────────────────────────

def _make_utc(weekday: int, hour: int, minute: int = 0) -> datetime:
    """
    Tworzy datetime UTC dla testów.
    weekday: 0=pon (NY) → szukamy najbliższego poniedziałku
    Używamy stałej daty zimowej (EST = UTC-5) żeby uniknąć DST zmienności.
    """
    # 2025-01-06 = poniedziałek, styczeń = zima = EST (UTC-5)
    base = datetime(2025, 1, 6, tzinfo=timezone.utc)
    # przesuń do właściwego dnia tygodnia
    delta_days = (weekday - base.weekday()) % 7
    day = base + timedelta(days=delta_days)
    # zamień godzinę ET na UTC (zimą ET = UTC-5)
    utc_hour = hour + 5
    if utc_hour >= 24:
        day += timedelta(days=1)
        utc_hour -= 24
    return day.replace(hour=utc_hour, minute=minute)


def test_session_intraday():
    # Wtorek 10:00 ET → INTRADAY
    dt = _make_utc(weekday=1, hour=10, minute=0)
    session = detect_session(dt)
    assert session == SessionType.INTRADAY, f"Got {session}"
    print(f"✓ test_session_intraday (10:00 ET → {session.value})")


def test_session_pre_market():
    # Wtorek 07:00 ET → PRE_MARKET
    dt = _make_utc(weekday=1, hour=7, minute=0)
    session = detect_session(dt)
    assert session == SessionType.PRE_MARKET, f"Got {session}"
    print(f"✓ test_session_pre_market (07:00 ET → {session.value})")


def test_session_after_hours():
    # Wtorek 17:30 ET → AFTER_HOURS
    dt = _make_utc(weekday=1, hour=17, minute=30)
    session = detect_session(dt)
    assert session == SessionType.AFTER_HOURS, f"Got {session}"
    print(f"✓ test_session_after_hours (17:30 ET → {session.value})")


def test_session_closed():
    # Wtorek 22:00 ET → CLOSED
    dt = _make_utc(weekday=1, hour=22, minute=0)
    session = detect_session(dt)
    assert session == SessionType.CLOSED, f"Got {session}"
    print(f"✓ test_session_closed (22:00 ET → {session.value})")


def test_session_weekend():
    # Sobota 12:00 ET → WEEKEND
    dt = _make_utc(weekday=5, hour=12, minute=0)
    session = detect_session(dt)
    assert session == SessionType.WEEKEND, f"Got {session}"
    print(f"✓ test_session_weekend (Sobota 12:00 ET → {session.value})")


def test_market_open_boundary():
    # 09:29 ET → PRE_MARKET (tuż przed otwarciem)
    dt = _make_utc(weekday=1, hour=9, minute=29)
    assert detect_session(dt) == SessionType.PRE_MARKET

    # 09:30 ET → INTRADAY (dokładnie otwarcie)
    dt = _make_utc(weekday=1, hour=9, minute=30)
    assert detect_session(dt) == SessionType.INTRADAY
    print("✓ test_market_open_boundary (09:29→PRE, 09:30→INTRADAY)")


def test_market_close_boundary():
    # 15:59 ET → INTRADAY
    dt = _make_utc(weekday=1, hour=15, minute=59)
    assert detect_session(dt) == SessionType.INTRADAY

    # 16:00 ET → AFTER_HOURS
    dt = _make_utc(weekday=1, hour=16, minute=0)
    assert detect_session(dt) == SessionType.AFTER_HOURS
    print("✓ test_market_close_boundary (15:59→INTRADAY, 16:00→AFTER_HOURS)")


def test_scan_mode_rvol_thresholds():
    """Intraday ma wyższe RVOL progi niż EOD."""
    intraday = SCAN_MODE_INTRADAY
    eod      = SCAN_MODE_EOD
    assert intraday.rvol_reject > eod.rvol_reject
    assert intraday.rvol_soft   > eod.rvol_soft
    print(f"✓ test_scan_mode_rvol_thresholds "
          f"(intraday reject={intraday.rvol_reject} > eod reject={eod.rvol_reject})")


def test_scan_mode_rsi_range():
    """EOD ma szerszy zakres RSI niż intraday."""
    assert SCAN_MODE_EOD.rsi_min < SCAN_MODE_INTRADAY.rsi_min
    assert SCAN_MODE_EOD.rsi_max > SCAN_MODE_INTRADAY.rsi_max
    print(f"✓ test_scan_mode_rsi_range "
          f"(EOD: {SCAN_MODE_EOD.rsi_min}–{SCAN_MODE_EOD.rsi_max} | "
          f"INTRADAY: {SCAN_MODE_INTRADAY.rsi_min}–{SCAN_MODE_INTRADAY.rsi_max})")


def test_get_scan_mode_returns_correct_mode():
    # Poniedziałek 14:00 ET → intraday
    dt = _make_utc(weekday=0, hour=14, minute=0)
    mode = get_scan_mode(dt)
    assert mode.session == SessionType.INTRADAY
    assert mode.use_snapshot is True

    # Poniedziałek 20:00 ET → closed
    dt = _make_utc(weekday=0, hour=20, minute=0)
    mode = get_scan_mode(dt)
    assert mode.session == SessionType.CLOSED
    assert mode.use_snapshot is False
    print("✓ test_get_scan_mode_returns_correct_mode")


def test_format_banner():
    dt   = _make_utc(weekday=1, hour=10, minute=0)
    mode = get_scan_mode(dt)
    et   = utc_to_et(dt)
    banner = format_session_banner(mode, et)
    assert "INTRADAY" in banner
    assert "RVOL" in banner
    print("✓ test_format_banner")


def run_all_tests():
    print("\n" + "="*55)
    print("MARKET SESSION DETECTOR v1.0 – Unit Tests")
    print("="*55)
    test_session_intraday()
    test_session_pre_market()
    test_session_after_hours()
    test_session_closed()
    test_session_weekend()
    test_market_open_boundary()
    test_market_close_boundary()
    test_scan_mode_rvol_thresholds()
    test_scan_mode_rsi_range()
    test_get_scan_mode_returns_correct_mode()
    test_format_banner()
    print("="*55)
    print("Wszystkie testy przeszły ✓")
    print("="*55 + "\n")


if __name__ == "__main__":
    run_all_tests()

    # Pokaż aktualny tryb
    print("\nAktualny tryb skanowania:")
    mode   = get_scan_mode()
    et_now = now_et()
    print(format_session_banner(mode, et_now))
