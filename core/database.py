"""
Database Core V2.30 - SwingRadar DSS
Bezpieczne, współbieżne zarządzanie danymi (SQLite + WAL).

ZMIANY V2.30:
- [NEW] Tabela market_news do przechowywania nagłówków prasowych
- [NEW] Migracja: kolumna sector + tabela market_news dla starych baz
ZMIANY V2.28:
- [FIX] Dodana migracja schematu: _migrate_db() bezpiecznie dodaje brakujące
  kolumny do istniejących baz (np. 'sector' w active_scans).
  Poprzednia wersja używała tylko CREATE TABLE IF NOT EXISTS, przez co
  stare bazy nie otrzymywały nowych kolumn i system działał cicho bez sektora.
"""

import sqlite3
import logging
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self, db_path="data/trading_system.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._migrate_db()

    def _init_db(self):
        """Inicjalizacja bazy w trybie WAL z kompletem tabel."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")

            # 1. Historia sygnałów
            conn.execute("""
                CREATE TABLE IF NOT EXISTS signal_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker      TEXT NOT NULL,
                    final_score REAL,
                    tech_score  REAL,
                    fund_score  REAL,
                    event_score REAL,
                    timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 2. Aktywne skany
            conn.execute("""
                CREATE TABLE IF NOT EXISTS active_scans (
                    ticker          TEXT PRIMARY KEY,
                    status          TEXT,
                    sector          TEXT,
                    stability_score REAL,
                    real_rr         REAL,
                    entry_limit     REAL,
                    stop_loss       REAL,
                    target          REAL,
                    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 3. DNA transakcji (pod Moduł AI)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trade_review (
                    trade_id            TEXT PRIMARY KEY,
                    ticker              TEXT NOT NULL,
                    entry_date          DATETIME DEFAULT CURRENT_TIMESTAMP,
                    exit_date           DATETIME,
                    status              TEXT,
                    entry_price         REAL,
                    exit_price          REAL,
                    pnl_pct             REAL,
                    stability_at_entry  REAL,
                    rvol_at_entry       REAL,
                    market_regime       TEXT
                )
            """)

            # 4. Wiadomości prasowe (Pre-market news scan)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_news (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker       TEXT NOT NULL,
                    headline     TEXT,
                    url          TEXT UNIQUE,
                    source       TEXT,
                    published_at TEXT,
                    fetched_at   DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Indeksy
            conn.execute("CREATE INDEX IF NOT EXISTS idx_signal_ticker_time ON signal_history(ticker, timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_active_status      ON active_scans(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_active_sector      ON active_scans(sector)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_news_ticker        ON market_news(ticker)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_news_published     ON market_news(published_at)")

            logger.info("Baza danych SQLite (WAL) zainicjalizowana.")

    def _migrate_db(self):
        """
        Bezpieczna migracja schematu dla istniejących baz.
        Dodaje brakujące kolumny bez niszczenia danych.
        Każda migracja jest idempotentna (bezpieczna przy wielokrotnym wywołaniu).
        """
        migrations = [
            # (tabela, kolumna, definicja SQL)
            ("active_scans", "sector", "TEXT DEFAULT 'Unknown'"),
        ]

        with sqlite3.connect(self.db_path) as conn:
            for table, column, col_def in migrations:
                # Sprawdzamy czy kolumna już istnieje
                existing = [
                    row[1]
                    for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
                ]
                if column not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
                    logger.info(f"Migracja: Dodano kolumnę '{column}' do tabeli '{table}'.")
                else:
                    logger.debug(f"Migracja: Kolumna '{column}' w '{table}' już istnieje — pomijam.")

    @contextmanager
    def get_connection(self):
        """Bezpieczny menedżer kontekstu do połączeń z auto-commit i rollback."""
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Błąd transakcji SQLite: {e}")
            raise
        finally:
            conn.close()
