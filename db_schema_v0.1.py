"""
Database Schema v1.0
Trading System – Masterplan V2.4.5

Czyste SQL + Python DAO, zero ORM.
SQLite dla MVP → PostgreSQL przez minimalne zmiany (oznaczone # PG:).

Tabele:
    signals     – immutable log wyniku pipeline (jeden rekord per sygnał)
    sub_scores  – 6 sub-scorów 1:1 z signals (debug + recalibracja wag)
    feedback    – outcome po zamknięciu trade 1:1 z signals (pętla ucząca)
    positions   – otwarte pozycje (mutable, aktualizowane EOD)

Zasady:
    - Nie zapisujemy OHLCV (Polygon jest deterministyczny i tani)
    - signals jest immutable (nigdy nie updatujemy po zapisie)
    - feedback uzupełniany osobno po zamknięciu trade
    - UNIQUE constraints → idempotentność (rerunnowanie bez duplikatów)

Użycie:
    python db_schema.py           → tworzy bazę + uruchamia testy
    python db_schema.py --reset   → usuwa i odtwarza tabele (dev only)
    python db_schema.py --demo    → wstawia przykładowe dane
"""

from __future__ import annotations

import sqlite3
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, date
from pathlib import Path
from typing import Optional


# ─────────────────────────────────────────────
# 1. KONFIGURACJA
# ─────────────────────────────────────────────

DB_PATH      = Path("trading_system.db")
DB_PATH_TEST = Path("trading_system_test.db")   # temp – usuwany po testach


@contextmanager
def get_connection(db_path: str | Path = DB_PATH):
    """
    Context manager dla połączenia SQLite.
    Auto-commit przy sukcesie, rollback przy wyjątku.

    # PG: zamień na psycopg2.connect(DSN) lub asyncpg
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─────────────────────────────────────────────
# 2. DDL – DEFINICJE TABEL
# ─────────────────────────────────────────────

SQL_CREATE_SIGNALS = """
CREATE TABLE IF NOT EXISTS signals (

    -- Identyfikacja
    signal_id           TEXT        PRIMARY KEY,
    timestamp           TEXT        NOT NULL,       -- ISO8601 UTC
    ticker              TEXT        NOT NULL,
    market              TEXT        NOT NULL
                                    CHECK (market IN ('US', 'UK')),

    -- Setup
    setup_type          TEXT        NOT NULL,
    final_score         REAL        NOT NULL,
    grade               TEXT        NOT NULL
                                    CHECK (grade IN ('A+', 'A', 'B', 'C')),
    regime              TEXT        NOT NULL
                                    CHECK (regime IN ('Bull', 'Correction', 'Bear', 'Sideways')),
    freshness           REAL        NOT NULL,
    freshness_cat       TEXT        NOT NULL
                                    CHECK (freshness_cat IN ('EARLY', 'OPTIMAL', 'LATE', 'STALE')),
    sentiment_raw       REAL        NOT NULL        DEFAULT 0,

    -- Event & Liquidity
    event_status        TEXT        NOT NULL
                                    CHECK (event_status IN ('SAFE', 'WARN', 'HIGH_RISK', 'BLOCKED')),
    event_penalty       REAL        NOT NULL        DEFAULT 0,
    liquidity_status    TEXT        NOT NULL
                                    CHECK (liquidity_status IN ('PASS', 'SOFT_WARNING')),

    -- Gap & Volatility
    gap_risk            TEXT        NOT NULL
                                    CHECK (gap_risk IN ('LOW', 'MEDIUM', 'HIGH')),
    gap_20d_avg         REAL        NOT NULL,
    atr_pct             REAL        NOT NULL,
    min_acceptable_rr   REAL        NOT NULL,

    -- Execution plan
    entry_suggested     REAL        NOT NULL,
    stop                REAL        NOT NULL,
    target_1            REAL        NOT NULL,
    nominal_rr          REAL        NOT NULL,
    real_rr             REAL        NOT NULL,
    rr_status           TEXT        NOT NULL
                                    CHECK (rr_status IN ('OK', 'POOR_EXECUTION', 'BLOCKED')),
    cost_roundtrip_pct  REAL        NOT NULL,
    breakeven_pct       REAL        NOT NULL,

    -- Sizing
    position_size       REAL        NOT NULL,       -- liczba akcji/jednostek
    risk_pct_applied    REAL        NOT NULL,

    -- Metadata
    scan_date           TEXT        NOT NULL,       -- DATE jako TEXT (YYYY-MM-DD)
    created_at          TEXT        NOT NULL        DEFAULT (datetime('now'))
    -- PG: created_at TIMESTAMPTZ DEFAULT NOW()
);
"""

# Indeks: szybkie query po ticker + dacie (najczęstszy pattern)
SQL_IDX_SIGNALS_TICKER_DATE = """
CREATE INDEX IF NOT EXISTS idx_signals_ticker_date
ON signals (ticker, scan_date DESC);
"""

# Indeks: filtrowanie po grade + score (dla dashboardu)
SQL_IDX_SIGNALS_GRADE_SCORE = """
CREATE INDEX IF NOT EXISTS idx_signals_grade_score
ON signals (grade, final_score DESC);
"""


SQL_CREATE_SUB_SCORES = """
CREATE TABLE IF NOT EXISTS sub_scores (

    -- Klucz obcy do signals
    signal_id           TEXT        PRIMARY KEY
                                    REFERENCES signals(signal_id) ON DELETE CASCADE,

    -- 6 sub-scores (wagi z L6 Masterplan V2.4.5)
    sub_setup           REAL        NOT NULL,       -- waga 30%
    sub_volume          REAL        NOT NULL,       -- waga 20%
    sub_momentum        REAL        NOT NULL,       -- waga 15%
    sub_sentiment       REAL        NOT NULL,       -- waga 15%
    sub_regime          REAL        NOT NULL,       -- waga 10%
    sub_fundamental     REAL        NOT NULL,       -- waga 10%

    -- Raw score przed mnożnikiem reżimu
    raw_score           REAL        NOT NULL,
    regime_multiplier   REAL        NOT NULL,

    -- Surowe wskaźniki techniczne (snapshot w momencie sygnału)
    -- Krytyczne dla debugowania i recalibracji wag po 50 tradach
    rsi_14              REAL,
    macd_hist           REAL,
    roc_10              REAL,
    atr_14              REAL,
    rvol                REAL,
    obv_slope           REAL,
    adv_20d             REAL,

    -- Regime context
    spy_vs_sma200       REAL,                       -- spy_price / spy_sma200
    spy_vs_sma50        REAL,                       -- spy_price / spy_sma50
    vix_percentile      REAL,

    -- Fundamentals snapshot
    eps_growth_yoy      REAL,
    revenue_growth_yoy  REAL,
    pe_ratio            REAL,
    debt_equity         REAL
);
"""


SQL_CREATE_FEEDBACK = """
CREATE TABLE IF NOT EXISTS feedback (

    -- Klucz obcy do signals
    signal_id           TEXT        PRIMARY KEY
                                    REFERENCES signals(signal_id) ON DELETE CASCADE,

    -- Dane wejścia (wypełniane gdy user wchodzi w trade)
    entry_actual        REAL,                       -- rzeczywista cena wejścia
    entry_date          TEXT,                       -- DATE jako TEXT

    -- Dane wyjścia (wypełniane po zamknięciu)
    exit_actual         REAL,
    exit_date           TEXT,
    exit_reason         TEXT
                                    CHECK (exit_reason IN (
                                        'T1', 'STOP_LOSS', 'WEAK_FOLLOWTHROUGH',
                                        'MANUAL', 'NOT_TAKEN', NULL
                                    )),

    -- Wynik
    outcome             TEXT
                                    CHECK (outcome IN (
                                        'WIN', 'LOSS', 'BREAK_EVEN', 'NOT_TAKEN', NULL
                                    )),
    pnl_pct             REAL,                       -- % zysku/straty
    pnl_abs             REAL,                       -- absolutna kwota ($, £)
    days_held           INTEGER,

    -- Metadata
    updated_at          TEXT        DEFAULT (datetime('now'))
    -- PG: updated_at TIMESTAMPTZ DEFAULT NOW()
);
"""

# Indeks: analiza po exit_reason i outcome (dashboard)
SQL_IDX_FEEDBACK_OUTCOME = """
CREATE INDEX IF NOT EXISTS idx_feedback_outcome
ON feedback (outcome, exit_reason);
"""


SQL_CREATE_POSITIONS = """
CREATE TABLE IF NOT EXISTS positions (

    -- Identyfikacja
    position_id         TEXT        PRIMARY KEY,
    signal_id           TEXT        REFERENCES signals(signal_id),
    ticker              TEXT        NOT NULL,
    market              TEXT        NOT NULL
                                    CHECK (market IN ('US', 'UK')),

    -- Dane pozycji
    entry_price         REAL        NOT NULL,
    entry_date          TEXT        NOT NULL,
    shares              REAL        NOT NULL,
    stop_loss           REAL        NOT NULL,
    target_1            REAL        NOT NULL,
    risk_pct            REAL        NOT NULL,
    grade               TEXT        NOT NULL,
    gap_risk            TEXT        NOT NULL,

    -- Status
    status              TEXT        NOT NULL        DEFAULT 'OPEN'
                                    CHECK (status IN ('OPEN', 'CLOSED', 'STOPPED')),

    -- Losing trade alert tracking
    losing_alert_sent   INTEGER     NOT NULL        DEFAULT 0,  -- 0/1 boolean

    -- Zamknięcie (NULL gdy OPEN)
    exit_price          REAL,
    exit_date           TEXT,
    exit_reason         TEXT,
    pnl_pct             REAL,
    pnl_abs             REAL,

    -- Metadata
    created_at          TEXT        NOT NULL        DEFAULT (datetime('now')),
    updated_at          TEXT        NOT NULL        DEFAULT (datetime('now'))
);
"""

# Indeks: szybkie query otwartych pozycji (sprawdzanie każdego EOD)
SQL_IDX_POSITIONS_OPEN = """
CREATE INDEX IF NOT EXISTS idx_positions_open
ON positions (status, ticker)
WHERE status = 'OPEN';
-- PG: partial index WHERE status = 'OPEN' działa identycznie
"""

# Indeks: historia per ticker
SQL_IDX_POSITIONS_TICKER = """
CREATE INDEX IF NOT EXISTS idx_positions_ticker_date
ON positions (ticker, entry_date DESC);
"""


# ─────────────────────────────────────────────
# 3. MIGRACJE
# ─────────────────────────────────────────────

ALL_DDL = [
    SQL_CREATE_SIGNALS,
    SQL_IDX_SIGNALS_TICKER_DATE,
    SQL_IDX_SIGNALS_GRADE_SCORE,
    SQL_CREATE_SUB_SCORES,
    SQL_CREATE_FEEDBACK,
    SQL_IDX_FEEDBACK_OUTCOME,
    SQL_CREATE_POSITIONS,
    SQL_IDX_POSITIONS_OPEN,
    SQL_IDX_POSITIONS_TICKER,
]


def create_all_tables(db_path: str | Path = DB_PATH) -> None:
    """Tworzy wszystkie tabele i indeksy (idempotentne – IF NOT EXISTS)."""
    with get_connection(db_path) as conn:
        for ddl in ALL_DDL:
            conn.execute(ddl)
    print(f"✓ Tabele utworzone: {db_path}")


def drop_all_tables(db_path: str | Path = DB_PATH) -> None:
    """Usuwa wszystkie tabele (DEV ONLY – nieodwracalne)."""
    tables = ["feedback", "sub_scores", "positions", "signals"]
    with get_connection(db_path) as conn:
        for table in tables:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
    print(f"✓ Tabele usunięte: {db_path}")


def reset_database(db_path: str | Path = DB_PATH) -> None:
    """Drop + Create (DEV ONLY)."""
    drop_all_tables(db_path)
    create_all_tables(db_path)
    print(f"✓ Baza zresetowana: {db_path}")


# ─────────────────────────────────────────────
# 4. DAO – DATA ACCESS OBJECTS
# ─────────────────────────────────────────────

class SignalDAO:
    """
    CRUD dla tabeli signals + sub_scores + feedback.
    Jeden save_signal() zapisuje do trzech tabel atomicznie.
    """

    def __init__(self, db_path: str | Path = DB_PATH):
        self.db_path = db_path

    def save_signal(
        self,
        result,       # ScoringResult z scoring_engine_v1
        ticker_data,  # TickerData z data_layer
        regime: str = "Bull",
    ) -> str:
        """
        Zapisuje kompletny sygnał do signals + sub_scores.
        Feedback pozostaje pusty (uzupełniany po zamknięciu trade).

        Returns:
            signal_id (UUID)

        Idempotentne: INSERT OR IGNORE – rerunnowanie bez duplikatów.
        """
        signal_id = result.signal_id
        now       = datetime.now().isoformat()
        today     = date.today().isoformat()

        with get_connection(self.db_path) as conn:

            # ── signals ──────────────────────────
            conn.execute("""
                INSERT OR IGNORE INTO signals (
                    signal_id, timestamp, ticker, market,
                    setup_type, final_score, grade, regime,
                    freshness, freshness_cat, sentiment_raw,
                    event_status, event_penalty, liquidity_status,
                    gap_risk, gap_20d_avg, atr_pct, min_acceptable_rr,
                    entry_suggested, stop, target_1,
                    nominal_rr, real_rr, rr_status,
                    cost_roundtrip_pct, breakeven_pct,
                    position_size, risk_pct_applied,
                    scan_date, created_at
                ) VALUES (
                    ?,?,?,?,  ?,?,?,?,
                    ?,?,?,
                    ?,?,?,
                    ?,?,?,?,
                    ?,?,?,
                    ?,?,?,
                    ?,?,
                    ?,?,
                    ?,?
                )
            """, (
                signal_id, now, result.ticker, result.market.value,

                ticker_data.setup_type.value,
                result.final_score,
                result.grade.value,
                regime,

                result.freshness,
                result.freshness_category.value,
                ticker_data.sentiment_raw,

                ticker_data.event_status.value,
                result.event_penalty,
                result.liquidity_status.value,

                ticker_data.gap_risk.value,
                ticker_data.gap_20d_avg,
                result.atr_pct,
                result.min_acceptable_rr,

                result.entry_suggested,
                result.stop,
                result.target_1,

                result.nominal_rr,
                result.real_rr,
                result.rr_status.value,

                result.cost_roundtrip_pct,
                result.breakeven_move_pct,

                result.position_size,
                result.effective_risk_pct,

                today, now,
            ))

            # ── sub_scores ────────────────────────
            sub = result.sub_scores
            conn.execute("""
                INSERT OR IGNORE INTO sub_scores (
                    signal_id,
                    sub_setup, sub_volume, sub_momentum,
                    sub_sentiment, sub_regime, sub_fundamental,
                    raw_score, regime_multiplier,
                    rsi_14, macd_hist, roc_10, atr_14,
                    rvol, obv_slope, adv_20d,
                    spy_vs_sma200, spy_vs_sma50, vix_percentile,
                    eps_growth_yoy, revenue_growth_yoy, pe_ratio, debt_equity
                ) VALUES (
                    ?,
                    ?,?,?,
                    ?,?,?,
                    ?,?,
                    ?,?,?,?,
                    ?,?,?,
                    ?,?,?,
                    ?,?,?,?
                )
            """, (
                signal_id,
                sub.setup, sub.volume, sub.momentum,
                sub.sentiment, sub.regime, sub.fundamental,
                result.raw_score, result.regime_multiplier,

                ticker_data.rsi_14,
                ticker_data.macd_hist,
                ticker_data.roc_10,
                ticker_data.atr_14,
                ticker_data.rvol,
                ticker_data.obv_slope,
                ticker_data.adv_20d,

                (ticker_data.spy_price / ticker_data.spy_sma200
                 if ticker_data.spy_sma200 else None),
                (ticker_data.spy_price / ticker_data.spy_sma50
                 if ticker_data.spy_sma50 else None),
                ticker_data.vix_percentile,

                ticker_data.eps_growth_yoy,
                ticker_data.revenue_growth_yoy,
                ticker_data.pe_ratio,
                ticker_data.debt_equity,
            ))

            # ── feedback (pusty rekord – wypełniany później) ──
            conn.execute("""
                INSERT OR IGNORE INTO feedback (signal_id)
                VALUES (?)
            """, (signal_id,))

        return signal_id

    def get_signal(self, signal_id: str) -> Optional[sqlite3.Row]:
        """Pobiera jeden sygnał z sub_scores JOIN."""
        with get_connection(self.db_path) as conn:
            return conn.execute("""
                SELECT s.*, ss.*
                FROM signals s
                LEFT JOIN sub_scores ss USING (signal_id)
                WHERE s.signal_id = ?
            """, (signal_id,)).fetchone()

    def get_signals_by_date(
        self,
        scan_date: str,
        grade: Optional[str] = None,
        min_score: float = 60.0,
    ) -> list[sqlite3.Row]:
        """
        Pobiera sygnały z danego dnia.

        Args:
            scan_date: 'YYYY-MM-DD'
            grade:     opcjonalny filtr ('A+', 'A', 'B', 'C')
            min_score: minimalny final_score (default 60)
        """
        query = """
            SELECT s.*, ss.sub_setup, ss.sub_volume, ss.sub_momentum,
                   ss.sub_sentiment, ss.sub_regime, ss.sub_fundamental,
                   ss.rsi_14, ss.rvol, ss.atr_14
            FROM signals s
            LEFT JOIN sub_scores ss USING (signal_id)
            WHERE s.scan_date = ?
              AND s.final_score >= ?
        """
        params: list = [scan_date, min_score]

        if grade:
            query += " AND s.grade = ?"
            params.append(grade)

        query += " ORDER BY s.final_score DESC"

        with get_connection(self.db_path) as conn:
            return conn.execute(query, params).fetchall()

    def get_latest_signals(
        self,
        ticker: str,
        limit: int = 5
    ) -> list[sqlite3.Row]:
        """Ostatnie N sygnałów dla danego tickera."""
        with get_connection(self.db_path) as conn:
            return conn.execute("""
                SELECT s.*, f.outcome, f.pnl_pct, f.exit_reason
                FROM signals s
                LEFT JOIN feedback f USING (signal_id)
                WHERE s.ticker = ?
                ORDER BY s.scan_date DESC
                LIMIT ?
            """, (ticker, limit)).fetchall()


class FeedbackDAO:
    """CRUD dla tabeli feedback – wypełniany po zamknięciu trade."""

    def __init__(self, db_path: str | Path = DB_PATH):
        self.db_path = db_path

    def record_entry(
        self,
        signal_id:    str,
        entry_actual: float,
        entry_date:   Optional[str] = None,
    ) -> None:
        """Zapisuje rzeczywistą cenę wejścia."""
        entry_date = entry_date or date.today().isoformat()
        with get_connection(self.db_path) as conn:
            conn.execute("""
                UPDATE feedback
                SET entry_actual = ?, entry_date = ?,
                    updated_at = datetime('now')
                WHERE signal_id = ?
            """, (entry_actual, entry_date, signal_id))

    def record_exit(
        self,
        signal_id:   str,
        exit_actual: float,
        exit_reason: str,
        outcome:     str,
        pnl_pct:     float,
        pnl_abs:     float,
        days_held:   int,
        exit_date:   Optional[str] = None,
    ) -> None:
        """
        Zapisuje wynik zamkniętego trade.

        Args:
            exit_reason: 'T1'|'STOP_LOSS'|'WEAK_FOLLOWTHROUGH'|'MANUAL'|'NOT_TAKEN'
            outcome:     'WIN'|'LOSS'|'BREAK_EVEN'|'NOT_TAKEN'
            pnl_pct:     % zysku/straty (np. 0.056 = +5.6%)
            pnl_abs:     kwota w $ lub £
        """
        exit_date = exit_date or date.today().isoformat()
        with get_connection(self.db_path) as conn:
            conn.execute("""
                UPDATE feedback
                SET exit_actual = ?, exit_date = ?,
                    exit_reason = ?, outcome = ?,
                    pnl_pct = ?, pnl_abs = ?,
                    days_held = ?,
                    updated_at = datetime('now')
                WHERE signal_id = ?
            """, (
                exit_actual, exit_date,
                exit_reason, outcome,
                pnl_pct, pnl_abs,
                days_held,
                signal_id,
            ))

    def mark_not_taken(self, signal_id: str) -> None:
        """Oznacza sygnał jako NOT_TAKEN (user zdecydował nie wchodzić)."""
        with get_connection(self.db_path) as conn:
            conn.execute("""
                UPDATE feedback
                SET outcome = 'NOT_TAKEN', exit_reason = 'NOT_TAKEN',
                    updated_at = datetime('now')
                WHERE signal_id = ?
            """, (signal_id,))


class PositionDAO:
    """CRUD dla tabeli positions – aktywne zarządzanie pozycjami."""

    def __init__(self, db_path: str | Path = DB_PATH):
        self.db_path = db_path

    def open_position(
        self,
        signal_id:   str,
        ticker:      str,
        market:      str,
        entry_price: float,
        shares:      float,
        stop_loss:   float,
        target_1:    float,
        risk_pct:    float,
        grade:       str,
        gap_risk:    str,
        entry_date:  Optional[str] = None,
    ) -> str:
        """
        Otwiera nową pozycję.
        Returns: position_id (UUID)
        """
        position_id = str(uuid.uuid4())
        entry_date  = entry_date or date.today().isoformat()

        with get_connection(self.db_path) as conn:
            conn.execute("""
                INSERT INTO positions (
                    position_id, signal_id, ticker, market,
                    entry_price, entry_date, shares,
                    stop_loss, target_1,
                    risk_pct, grade, gap_risk,
                    status, losing_alert_sent
                ) VALUES (?,?,?,?,  ?,?,?,  ?,?,  ?,?,?,  ?,?)
            """, (
                position_id, signal_id, ticker, market,
                entry_price, entry_date, shares,
                stop_loss, target_1,
                risk_pct, grade, gap_risk,
                "OPEN", 0,
            ))

        return position_id

    def get_open_positions(self) -> list[sqlite3.Row]:
        """Pobiera wszystkie otwarte pozycje (używane przy EOD check)."""
        with get_connection(self.db_path) as conn:
            return conn.execute("""
                SELECT * FROM positions
                WHERE status = 'OPEN'
                ORDER BY entry_date ASC
            """).fetchall()

    def update_losing_alert(self, position_id: str) -> None:
        """Oznacza że alert Losing Trade został wysłany (nie powtarzaj)."""
        with get_connection(self.db_path) as conn:
            conn.execute("""
                UPDATE positions
                SET losing_alert_sent = 1, updated_at = datetime('now')
                WHERE position_id = ?
            """, (position_id,))

    def close_position(
        self,
        position_id: str,
        exit_price:  float,
        exit_reason: str,
        pnl_pct:     float,
        pnl_abs:     float,
        exit_date:   Optional[str] = None,
    ) -> None:
        """Zamyka pozycję – ustawia status CLOSED lub STOPPED."""
        exit_date = exit_date or date.today().isoformat()
        status    = "STOPPED" if exit_reason == "STOP_LOSS" else "CLOSED"

        with get_connection(self.db_path) as conn:
            conn.execute("""
                UPDATE positions
                SET status = ?, exit_price = ?, exit_date = ?,
                    exit_reason = ?, pnl_pct = ?, pnl_abs = ?,
                    updated_at = datetime('now')
                WHERE position_id = ?
            """, (
                status, exit_price, exit_date,
                exit_reason, pnl_pct, pnl_abs,
                position_id,
            ))


# ─────────────────────────────────────────────
# 5. ANALYTICS QUERIES (L13 dashboard)
# ─────────────────────────────────────────────

class AnalyticsDAO:
    """
    Queries analityczne dla dashboardu L13.
    Uruchamiane po ~50 zamkniętych tradach do recalibracji wag.
    """

    def __init__(self, db_path: str | Path = DB_PATH):
        self.db_path = db_path

    def win_rate_by_grade(self) -> list[sqlite3.Row]:
        """
        Win rate per grade.
        Oczekiwany wynik: A+ > A > B > C
        """
        with get_connection(self.db_path) as conn:
            return conn.execute("""
                SELECT
                    s.grade,
                    COUNT(*) AS total,
                    SUM(CASE WHEN f.outcome = 'WIN' THEN 1 ELSE 0 END) AS wins,
                    ROUND(
                        100.0 * SUM(CASE WHEN f.outcome = 'WIN' THEN 1 ELSE 0 END)
                        / NULLIF(COUNT(*), 0), 1
                    ) AS win_rate_pct,
                    ROUND(AVG(f.pnl_pct) * 100, 2) AS avg_pnl_pct
                FROM signals s
                JOIN feedback f USING (signal_id)
                WHERE f.outcome IN ('WIN', 'LOSS', 'BREAK_EVEN')
                GROUP BY s.grade
                ORDER BY
                    CASE s.grade
                        WHEN 'A+' THEN 1
                        WHEN 'A'  THEN 2
                        WHEN 'B'  THEN 3
                        WHEN 'C'  THEN 4
                    END
            """).fetchall()

    def profit_factor(self) -> sqlite3.Row:
        """
        Profit Factor = suma zysków / suma strat.
        Target: > 1.5
        """
        with get_connection(self.db_path) as conn:
            return conn.execute("""
                SELECT
                    ROUND(
                        SUM(CASE WHEN f.pnl_abs > 0 THEN f.pnl_abs ELSE 0 END) /
                        NULLIF(SUM(CASE WHEN f.pnl_abs < 0 THEN ABS(f.pnl_abs) ELSE 0 END), 0),
                        2
                    ) AS profit_factor,
                    COUNT(*) AS total_closed,
                    ROUND(SUM(f.pnl_abs), 2) AS total_pnl
                FROM feedback f
                WHERE f.outcome IN ('WIN', 'LOSS', 'BREAK_EVEN')
            """).fetchone()

    def win_rate_by_setup(self) -> list[sqlite3.Row]:
        """Win rate per setup type – które setupy działają najlepiej."""
        with get_connection(self.db_path) as conn:
            return conn.execute("""
                SELECT
                    s.setup_type,
                    COUNT(*) AS total,
                    ROUND(
                        100.0 * SUM(CASE WHEN f.outcome = 'WIN' THEN 1 ELSE 0 END)
                        / NULLIF(COUNT(*), 0), 1
                    ) AS win_rate_pct,
                    ROUND(AVG(f.pnl_pct) * 100, 2) AS avg_pnl_pct
                FROM signals s
                JOIN feedback f USING (signal_id)
                WHERE f.outcome IN ('WIN', 'LOSS', 'BREAK_EVEN')
                GROUP BY s.setup_type
                ORDER BY win_rate_pct DESC
            """).fetchall()

    def gap_risk_impact(self) -> list[sqlite3.Row]:
        """Wpływ Gap Risk na wyniki – czy LOW > MEDIUM > HIGH?"""
        with get_connection(self.db_path) as conn:
            return conn.execute("""
                SELECT
                    s.gap_risk,
                    COUNT(*) AS total,
                    ROUND(
                        100.0 * SUM(CASE WHEN f.outcome = 'WIN' THEN 1 ELSE 0 END)
                        / NULLIF(COUNT(*), 0), 1
                    ) AS win_rate_pct,
                    ROUND(AVG(f.pnl_pct) * 100, 2) AS avg_pnl_pct
                FROM signals s
                JOIN feedback f USING (signal_id)
                WHERE f.outcome IN ('WIN', 'LOSS', 'BREAK_EVEN')
                GROUP BY s.gap_risk
                ORDER BY CASE s.gap_risk
                    WHEN 'LOW' THEN 1
                    WHEN 'MEDIUM' THEN 2
                    WHEN 'HIGH' THEN 3
                END
            """).fetchall()

    def exit_reason_distribution(self) -> list[sqlite3.Row]:
        """Ile % zysków pochodzi z T1 vs stop/time/manual."""
        with get_connection(self.db_path) as conn:
            return conn.execute("""
                SELECT
                    f.exit_reason,
                    COUNT(*) AS count,
                    ROUND(AVG(f.pnl_pct) * 100, 2) AS avg_pnl_pct,
                    ROUND(
                        100.0 * COUNT(*) /
                        NULLIF((SELECT COUNT(*) FROM feedback
                                WHERE outcome IS NOT NULL
                                AND outcome != 'NOT_TAKEN'), 0), 1
                    ) AS pct_of_total
                FROM feedback f
                WHERE f.outcome IS NOT NULL
                  AND f.outcome != 'NOT_TAKEN'
                GROUP BY f.exit_reason
                ORDER BY count DESC
            """).fetchall()

    def freshness_impact(self) -> list[sqlite3.Row]:
        """Czy EARLY > OPTIMAL > LATE w win rate?"""
        with get_connection(self.db_path) as conn:
            return conn.execute("""
                SELECT
                    s.freshness_cat,
                    COUNT(*) AS total,
                    ROUND(
                        100.0 * SUM(CASE WHEN f.outcome = 'WIN' THEN 1 ELSE 0 END)
                        / NULLIF(COUNT(*), 0), 1
                    ) AS win_rate_pct
                FROM signals s
                JOIN feedback f USING (signal_id)
                WHERE f.outcome IN ('WIN', 'LOSS', 'BREAK_EVEN')
                GROUP BY s.freshness_cat
                ORDER BY CASE s.freshness_cat
                    WHEN 'EARLY'   THEN 1
                    WHEN 'OPTIMAL' THEN 2
                    WHEN 'LATE'    THEN 3
                    WHEN 'STALE'   THEN 4
                END
            """).fetchall()

    def sub_score_correlation(self) -> list[sqlite3.Row]:
        """
        Korelacja sub-scorów z wynikiem – do recalibracji wag.
        Które sub-score najlepiej przewidują WIN?
        """
        with get_connection(self.db_path) as conn:
            return conn.execute("""
                SELECT
                    ROUND(AVG(CASE WHEN f.outcome='WIN' THEN ss.sub_setup     END), 1) AS setup_win,
                    ROUND(AVG(CASE WHEN f.outcome='WIN' THEN ss.sub_volume    END), 1) AS vol_win,
                    ROUND(AVG(CASE WHEN f.outcome='WIN' THEN ss.sub_momentum  END), 1) AS mom_win,
                    ROUND(AVG(CASE WHEN f.outcome='WIN' THEN ss.sub_sentiment END), 1) AS sent_win,
                    ROUND(AVG(CASE WHEN f.outcome='WIN' THEN ss.sub_regime    END), 1) AS regime_win,
                    ROUND(AVG(CASE WHEN f.outcome='LOSS' THEN ss.sub_setup    END), 1) AS setup_loss,
                    ROUND(AVG(CASE WHEN f.outcome='LOSS' THEN ss.sub_volume   END), 1) AS vol_loss,
                    ROUND(AVG(CASE WHEN f.outcome='LOSS' THEN ss.sub_momentum END), 1) AS mom_loss
                FROM sub_scores ss
                JOIN feedback f USING (signal_id)
                WHERE f.outcome IN ('WIN', 'LOSS')
            """).fetchone()


# ─────────────────────────────────────────────
# 6. UNIT TESTY
# ─────────────────────────────────────────────

def _make_mock_result_and_ticker():
    """
    Tworzy mockowe obiekty ScoringResult i TickerData do testów DB.
    Działa bez wywołań API.
    """
    try:
        from scoring_engine_v1 import (
            ScoringResult, SubScores, TickerData, PortfolioState,
            Market, SetupType, EventStatus, GapRisk,
            LiquidityStatus, EventStatus, FreshnessCategory,
            Grade, RRStatus, run_scoring_pipeline
        )
        from data_layer import _make_mock_ohlcv, IndicatorEngine
        import numpy as np

        df  = _make_mock_ohlcv(n=252, trend="up")
        ind = IndicatorEngine.calculate_all(df)
        close = float(df["close"].iloc[-1])

        td = TickerData(
            ticker="AAPL", market=Market.US,
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
        return result, td

    except ImportError as e:
        print(f"  SKIP (brak zależności: {e})")
        return None, None


def test_create_tables():
    create_all_tables(DB_PATH_TEST)
    with get_connection(DB_PATH_TEST) as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = {t["name"] for t in tables}
        for expected in ("signals", "sub_scores", "feedback", "positions"):
            assert expected in names, f"Brak tabeli: {expected}"
    print("✓ test_create_tables")


def test_save_and_get_signal():
    result, td = _make_mock_result_and_ticker()
    if result is None:
        return

    dao = SignalDAO(DB_PATH_TEST)
    sid = dao.save_signal(result, td, regime="Bull")

    row = dao.get_signal(sid)
    assert row is not None
    assert row["ticker"] == "AAPL"
    assert row["grade"] == result.grade.value
    assert abs(row["final_score"] - result.final_score) < 0.01
    # sub_scores zapisane
    assert row["sub_setup"] is not None
    assert row["rsi_14"] is not None
    print(f"✓ test_save_and_get_signal (grade={row['grade']}, score={row['final_score']:.1f})")


def test_idempotent_insert():
    """INSERT OR IGNORE – dwa zapisy tego samego signal_id nie tworzą duplikatu."""
    result, td = _make_mock_result_and_ticker()
    if result is None:
        return

    dao = SignalDAO(DB_PATH_TEST)
    sid1 = dao.save_signal(result, td)
    sid2 = dao.save_signal(result, td)   # drugi zapis tego samego

    assert sid1 == sid2

    with get_connection(DB_PATH_TEST) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE signal_id = ?", (sid1,)
        ).fetchone()[0]
        assert count == 1, f"Oczekiwano 1 rekord, got {count}"

    print("✓ test_idempotent_insert")


def test_feedback_lifecycle():
    """Pełny cykl: save → record_entry → record_exit."""
    result, td = _make_mock_result_and_ticker()
    if result is None:
        return

    signal_dao   = SignalDAO(DB_PATH_TEST)
    feedback_dao = FeedbackDAO(DB_PATH_TEST)

    sid = signal_dao.save_signal(result, td)

    # Wejście
    feedback_dao.record_entry(sid, entry_actual=185.50, entry_date="2025-01-15")

    # Wyjście
    feedback_dao.record_exit(
        signal_id   = sid,
        exit_actual = 198.00,
        exit_reason = "T1",
        outcome     = "WIN",
        pnl_pct     = 0.067,
        pnl_abs     = 900.0,
        days_held   = 5,
        exit_date   = "2025-01-20",
    )

    with get_connection(DB_PATH_TEST) as conn:
        row = conn.execute(
            "SELECT * FROM feedback WHERE signal_id = ?", (sid,)
        ).fetchone()

    assert row["outcome"] == "WIN"
    assert row["exit_reason"] == "T1"
    assert abs(row["pnl_pct"] - 0.067) < 0.001
    assert row["days_held"] == 5
    print("✓ test_feedback_lifecycle (WIN, T1, 5 dni)")


def test_position_lifecycle():
    """Otwarcie i zamknięcie pozycji."""
    result, td = _make_mock_result_and_ticker()
    if result is None:
        return

    signal_dao   = SignalDAO(DB_PATH_TEST)
    position_dao = PositionDAO(DB_PATH_TEST)

    sid = signal_dao.save_signal(result, td)

    pid = position_dao.open_position(
        signal_id   = sid,
        ticker      = "AAPL",
        market      = "US",
        entry_price = 185.50,
        shares      = 70,
        stop_loss   = 179.00,
        target_1    = 198.00,
        risk_pct    = 0.015,
        grade       = "A",
        gap_risk    = "LOW",
    )

    open_pos = position_dao.get_open_positions()
    assert any(p["position_id"] == pid for p in open_pos)

    # Losing trade alert
    position_dao.update_losing_alert(pid)

    # Zamknięcie
    position_dao.close_position(
        position_id = pid,
        exit_price  = 198.00,
        exit_reason = "T1",
        pnl_pct     = 0.067,
        pnl_abs     = 875.0,
    )

    open_pos_after = position_dao.get_open_positions()
    assert not any(p["position_id"] == pid for p in open_pos_after)
    print("✓ test_position_lifecycle (open → alert → close)")


def test_analytics_queries():
    """Analytics queries działają bez błędów na pustej bazie."""
    analytics = AnalyticsDAO(DB_PATH_TEST)

    # Wszystkie queries powinny zwrócić puste listy/None, nie rzucać wyjątków
    wbg  = analytics.win_rate_by_grade()
    pf   = analytics.profit_factor()
    wbs  = analytics.win_rate_by_setup()
    gri  = analytics.gap_risk_impact()
    erd  = analytics.exit_reason_distribution()
    fi   = analytics.freshness_impact()
    ssc  = analytics.sub_score_correlation()

    assert isinstance(wbg, list)
    assert isinstance(wbs, list)
    print("✓ test_analytics_queries (puste tabele → brak błędów)")


def test_get_signals_by_date():
    """Query po dacie zwraca właściwe rekordy."""
    result, td = _make_mock_result_and_ticker()
    if result is None:
        return

    dao   = SignalDAO(DB_PATH_TEST)
    today = date.today().isoformat()

    dao.save_signal(result, td)

    rows = dao.get_signals_by_date(today, min_score=0.0)
    assert len(rows) >= 1
    assert rows[0]["ticker"] == "AAPL"
    print(f"✓ test_get_signals_by_date ({len(rows)} sygnał(y) dla {today})")


def run_all_tests():
    print("\n" + "="*55)
    print("DATABASE SCHEMA v1.0 – Unit Tests")
    print("="*55)

    # Świeża baza dla każdego przebiegu testów
    if DB_PATH_TEST.exists():
        DB_PATH_TEST.unlink()

    create_all_tables(DB_PATH_TEST)

    test_create_tables()
    test_save_and_get_signal()
    test_idempotent_insert()
    test_feedback_lifecycle()
    test_position_lifecycle()
    test_analytics_queries()
    test_get_signals_by_date()

    # Cleanup
    if DB_PATH_TEST.exists():
        DB_PATH_TEST.unlink()

    print("="*55)
    print("Wszystkie testy przeszły ✓")
    print("="*55 + "\n")


# ─────────────────────────────────────────────
# 7. DEMO – przykładowe dane i analytics
# ─────────────────────────────────────────────

def run_demo():
    """
    Wstawia 3 przykładowe sygnały z pełnym feedback
    i uruchamia queries analityczne.
    """
    print("\n" + "─"*55)
    print("DEMO: Analytics po 3 zamkniętych tradach")
    print("─"*55)

    result, td = _make_mock_result_and_ticker()
    if result is None:
        print("SKIP (brak zależności)")
        return

    demo_db = Path("trading_system_demo.db")
    if demo_db.exists():
        demo_db.unlink()
    create_all_tables(demo_db)

    signal_dao   = SignalDAO(demo_db)
    feedback_dao = FeedbackDAO(demo_db)
    analytics    = AnalyticsDAO(demo_db)

    demo_trades = [
        {"outcome": "WIN",  "exit_reason": "T1",               "pnl_pct": 0.067,  "pnl_abs":  900.0, "days": 5},
        {"outcome": "LOSS", "exit_reason": "STOP_LOSS",         "pnl_pct": -0.034, "pnl_abs": -450.0, "days": 2},
        {"outcome": "WIN",  "exit_reason": "WEAK_FOLLOWTHROUGH","pnl_pct": 0.021,  "pnl_abs":  280.0, "days": 3},
    ]

    for trade in demo_trades:
        import time; time.sleep(0.01)  # unikamy kolizji UUID timestamp
        sid = signal_dao.save_signal(result, td)
        feedback_dao.record_entry(sid, 185.50)
        feedback_dao.record_exit(
            sid,
            exit_actual = 185.50 * (1 + trade["pnl_pct"]),
            exit_reason = trade["exit_reason"],
            outcome     = trade["outcome"],
            pnl_pct     = trade["pnl_pct"],
            pnl_abs     = trade["pnl_abs"],
            days_held   = trade["days"],
        )

    # Analytics
    pf = analytics.profit_factor()
    print(f"\nProfit Factor: {pf['profit_factor']}")
    print(f"Zamkniętych tradów: {pf['total_closed']}")
    print(f"Total PnL: ${pf['total_pnl']:.2f}")

    print("\nWin Rate by Grade:")
    for row in analytics.win_rate_by_grade():
        print(f"  {row['grade']}: {row['win_rate_pct']}% ({row['total']} tradów)")

    print("\nExit Reason Distribution:")
    for row in analytics.exit_reason_distribution():
        print(f"  {row['exit_reason']}: {row['count']} ({row['pct_of_total']}%)")


# ─────────────────────────────────────────────
# 8. MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if "--reset" in args:
        reset_database()
    elif "--demo" in args:
        create_all_tables(DB_PATH_TEST)
        run_all_tests()
        run_demo()
    else:
        create_all_tables()
        run_all_tests()
