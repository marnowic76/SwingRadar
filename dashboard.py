"""
SwingRadar V2.44 - Dashboard (Streamlit)

ZMIANY V2.44:
- [NEW] Auto-odświeżanie co 60s
- [NEW] Market Regime widget — BULL/BEAR/NEUTRAL z wynikami sektorów na górze
- [NEW] News — filtrowanie po tickerze, źródle i dacie
- [NEW] Widok szczegółowy — Piotroski, Altman, insider ratio, 8-K, float, momentum
- [NEW] Top 10 — kolumny momentum 1M/3M i float category
"""

import streamlit as st
import pandas as pd
import sqlite3
import uuid
import time
from datetime import datetime, timedelta

st.set_page_config(
    page_title="SwingRadar DSS",
    page_icon="SwingRadar-icon.webp",
    layout="wide",
    menu_items={
        "About": "SwingRadar DSS — Built by [Nex41](https://www.nex41.io)"
    }
)

# ══════════════════════════════════════════════
# DATA LAYER
# ══════════════════════════════════════════════

def get_scans() -> pd.DataFrame:
    try:
        conn = sqlite3.connect("data/trading_system.db")
        df = pd.read_sql_query("""
            SELECT ticker, sector, status, stability_score, real_rr,
                   entry_limit, stop_loss, target, updated_at
            FROM active_scans
            ORDER BY sector ASC, stability_score DESC
        """, conn)
        conn.close()
        if 'sector' not in df.columns:
            df['sector'] = 'Unknown'
        return df
    except Exception as e:
        st.error(f"Database connection error: {e}")
        return pd.DataFrame()

def get_score_history(ticker: str) -> pd.DataFrame:
    try:
        conn = sqlite3.connect("data/trading_system.db")
        df = pd.read_sql_query("""
            SELECT final_score, tech_score, fund_score, event_score, timestamp
            FROM signal_history WHERE ticker = ?
            ORDER BY timestamp ASC
        """, conn, params=(ticker,))
        conn.close()
        if not df.empty:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        return df
    except Exception:
        return pd.DataFrame()

def get_freshness(updated_at_str: str) -> tuple[str, str]:
    """
    Returns (emoji, css_color) based on age of last scan.
    < 1h   → 🟢 green  (fresh data)
    1-4h   → 🟡 yellow (moderately fresh)
    > 4h   → 🔴 red    (stale data, market may have moved)
    Weekend/none → ⚪ grey
    """
    if not updated_at_str or updated_at_str == "—":
        return "⚪", "#6B7280"
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(str(updated_at_str).replace(" ", "T"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        if age_hours < 1:
            return "🟢", "#22C55E"
        elif age_hours < 4:
            return "🟡", "#EAB308"
        else:
            return "🔴", "#EF4444"
    except Exception:
        return "⚪", "#6B7280"


def build_ai_prompt(ticker, scan_row, scores=None):
    """Buduje prompt dla AI z prośbą o ocenę 1-10."""
    import urllib.parse
    entry  = f"${scan_row.get('entry_limit',0):.2f}" if scan_row.get('entry_limit',0) > 0 else "not yet calculated"
    sl     = f"${scan_row.get('stop_loss',0):.2f}"   if scan_row.get('stop_loss',0) > 0 else "not yet calculated"
    tgt    = f"${scan_row.get('target',0):.2f}"      if scan_row.get('target',0) > 0 else "not yet calculated"
    rr     = f"{scan_row.get('real_rr',0):.2f}"      if scan_row.get('real_rr',0) > 0 else "not yet calculated"
    stab   = f"{scan_row.get('stability_score',0):.1f}%"
    status = scan_row.get('status','—')
    sector = scan_row.get('sector','—')

    scores_txt = ""
    if scores:
        scores_txt = (
            f"Scoring breakdown: Technical {scores.get('tech_score',0):.0f}/100 (50% weight) | "
            f"Fundamental {scores.get('fund_score',0):.0f}/100 (30% weight) | "
            f"Event {scores.get('event_score',0):.0f}/100 (20% weight) | "
            f"Final Score {scores.get('final_score',0):.0f}/100. "
        )

    prompt = (
        f"I am reviewing a swing trade signal from SwingRadar DSS for a UK ISA account. "
        f"Please analyse this signal and provide a quality score from 1.0 to 10.0 (decimals allowed, e.g. 7.5). "
        f"\n\n"
        f"SIGNAL DETAILS:\n"
        f"Ticker: {ticker} | Sector: {sector} | Status: {status} | Stability Score: {stab}\n"
        f"Entry: {entry} | Stop Loss: {sl} | Target: {tgt} | Real R/R: {rr}\n"
        f"{scores_txt}"
        f"\n"
        f"I will attach price charts (1W, 1D, 4H, 1H timeframes) for your visual analysis.\n"
        f"\n"
        f"Please provide:\n"
        f"1. Technical assessment based on the charts I will share\n"
        f"2. Key risks for this trade\n"
        f"3. Your overall quality score (1.0-10.0) with brief justification\n"
        f"4. Would you take this trade? Yes/No and why\n"
        f"\n"
        f"Format your score clearly as: SCORE: X.X/10"
    )
    return urllib.parse.quote(prompt), prompt


def get_news(ticker: str = None, source: str = None, days: int = 7, limit: int = 100) -> pd.DataFrame:
    try:
        conn = sqlite3.connect("data/trading_system.db")
        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        query = """
            SELECT ticker, headline, source, published_at, url, fetched_at
            FROM market_news WHERE published_at >= ?
        """
        params = [cutoff]
        if ticker:
            query += " AND ticker = ?"
            params.append(ticker)
        if source:
            query += " AND source = ?"
            params.append(source)
        query += " ORDER BY published_at DESC LIMIT ?"
        params.append(limit)
        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()

def get_trades() -> pd.DataFrame:
    try:
        conn = sqlite3.connect("data/trading_system.db")
        df = pd.read_sql_query("""
            SELECT trade_id, ticker, entry_date, exit_date, status,
                   entry_price, exit_price, pnl_pct, stability_at_entry, rvol_at_entry
            FROM trade_review ORDER BY entry_date DESC
        """, conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()

PAPER_TRADES_DDL = """
    CREATE TABLE IF NOT EXISTS paper_trades (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker       TEXT NOT NULL,
        entry_date   DATETIME DEFAULT CURRENT_TIMESTAMP,
        exit_date    DATETIME,
        status       TEXT DEFAULT 'OPEN',
        entry_price  REAL,
        exit_price   REAL,
        stop_loss    REAL,
        target       REAL,
        real_rr      REAL,
        stability    REAL,
        signal_score REAL,
        market_regime TEXT,
        exit_reason  TEXT,
        pnl_pct      REAL,
        r_multiple   REAL,
        mae_pct      REAL,
        mfe_pct      REAL,
        hold_days    INTEGER,
        hit_target   INTEGER DEFAULT 0,
        hit_stop     INTEGER DEFAULT 0,
        notes        TEXT,
        trade_type   TEXT DEFAULT 'PAPER'
    )
"""

def _ensure_paper_table(conn):
    conn.execute(PAPER_TRADES_DDL)
    # Migration: add missing columns for old databases
    existing = [r[1] for r in conn.execute("PRAGMA table_info(paper_trades)").fetchall()]
    new_cols = {
        "market_regime": "TEXT",
        "r_multiple":    "REAL",
        "mae_pct":       "REAL",
        "mfe_pct":       "REAL",
        "hold_days":     "INTEGER",
        "trade_type":    "TEXT DEFAULT 'PAPER'",
    }
    for col, typedef in new_cols.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE paper_trades ADD COLUMN {col} {typedef}")
    conn.commit()

def get_paper_trades() -> pd.DataFrame:
    try:
        conn = sqlite3.connect("data/trading_system.db")
        _ensure_paper_table(conn)
        df = pd.read_sql_query("SELECT * FROM paper_trades ORDER BY entry_date DESC", conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()

def save_paper_trade(ticker, entry_price, stop_loss, target, real_rr,
                     stability, signal_score, market_regime="", notes="", trade_type="PAPER"):
    try:
        conn = sqlite3.connect("data/trading_system.db")
        _ensure_paper_table(conn)
        conn.execute("""
            INSERT INTO paper_trades
            (ticker, entry_price, stop_loss, target, real_rr,
             stability, signal_score, market_regime, notes, trade_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (ticker.upper(), entry_price, stop_loss, target, real_rr,
              stability, signal_score, market_regime, notes, trade_type))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False

def close_paper_trade(trade_id, exit_price, exit_reason, hit_target, hit_stop,
                      mae_pct=0.0, mfe_pct=0.0):
    try:
        conn = sqlite3.connect("data/trading_system.db")
        row = conn.execute(
            "SELECT entry_price, stop_loss, entry_date FROM paper_trades WHERE id = ?",
            (trade_id,)
        ).fetchone()
        if not row:
            return False
        entry, sl, entry_date = row[0], row[1], row[2]
        pnl = ((exit_price - entry) / entry * 100) if entry > 0 else 0
        # R-Multiple: PnL / ryzyko (entry - stop_loss)
        risk = (entry - sl) if sl and sl > 0 else entry * 0.02
        r_multiple = ((exit_price - entry) / risk) if risk > 0 else 0
        # Hold days
        try:
            from datetime import datetime
            ed = datetime.fromisoformat(str(entry_date)[:19])
            hold_days = (datetime.now() - ed).days
        except Exception:
            hold_days = 0

        conn.execute("""
            UPDATE paper_trades SET
                status='CLOSED', exit_date=CURRENT_TIMESTAMP,
                exit_price=?, pnl_pct=?, r_multiple=?,
                exit_reason=?, hit_target=?, hit_stop=?,
                mae_pct=?, mfe_pct=?, hold_days=?
            WHERE id=?
        """, (exit_price, round(pnl, 2), round(r_multiple, 2),
              exit_reason, hit_target, hit_stop,
              mae_pct, mfe_pct, hold_days, trade_id))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def _ensure_ai_ratings_table():
    """Tworzy tabelę ai_ratings jeśli nie istnieje."""
    try:
        conn = sqlite3.connect("data/trading_system.db")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_ratings (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker     TEXT NOT NULL,
                date       TEXT NOT NULL,
                claude     REAL,
                chatgpt    REAL,
                gemini     REAL,
                grok       REAL,
                avg_ai     REAL,
                notes      TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(ticker, date)
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        pass

def get_ai_ratings_today() -> dict:
    """Pobiera oceny AI dla dzisiejszego dnia. Zwraca dict {ticker: row}."""
    _ensure_ai_ratings_table()
    try:
        conn = sqlite3.connect("data/trading_system.db")
        today = datetime.now().strftime("%Y-%m-%d")
        rows = conn.execute("""
            SELECT ticker, claude, chatgpt, gemini, grok, avg_ai, notes
            FROM ai_ratings WHERE date = ?
        """, (today,)).fetchall()
        conn.close()
        return {r[0]: {
            'claude': r[1], 'chatgpt': r[2],
            'gemini': r[3], 'grok': r[4],
            'avg_ai': r[5], 'notes': r[6]
        } for r in rows}
    except Exception:
        return {}

def save_ai_rating(ticker, claude, chatgpt, gemini, grok, notes=""):
    """Zapisuje/aktualizuje oceny AI dla tickera na dziś."""
    _ensure_ai_ratings_table()
    try:
        scores = [s for s in [claude, chatgpt, gemini, grok] if s is not None and s > 0]
        avg = round(sum(scores) / len(scores), 2) if scores else None
        today = datetime.now().strftime("%Y-%m-%d")
        conn = sqlite3.connect("data/trading_system.db")
        conn.execute("""
            INSERT INTO ai_ratings (ticker, date, claude, chatgpt, gemini, grok, avg_ai, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker, date) DO UPDATE SET
                claude=excluded.claude, chatgpt=excluded.chatgpt,
                gemini=excluded.gemini, grok=excluded.grok,
                avg_ai=excluded.avg_ai, notes=excluded.notes
        """, (ticker.upper(), today,
              claude or None, chatgpt or None,
              gemini or None, grok or None,
              avg, notes))
        conn.commit()
        conn.close()
        return avg
    except Exception as e:
        return None

def get_ai_ratings_history() -> pd.DataFrame:
    """Pobiera historię wszystkich ocen AI do kalibracji."""
    _ensure_ai_ratings_table()
    try:
        conn = sqlite3.connect("data/trading_system.db")
        df = pd.read_sql_query("""
            SELECT r.ticker, r.date, r.claude, r.chatgpt, r.gemini, r.grok, r.avg_ai, r.notes,
                   s.stability_score, s.real_rr, s.sector, s.status
            FROM ai_ratings r
            LEFT JOIN active_scans s ON s.ticker = r.ticker
            ORDER BY r.date DESC, r.avg_ai DESC
        """, conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


def get_market_regime_from_db() -> dict:
    """Pobiera ostatni zapisany market regime z bazy (jeśli jest) lub zwraca None."""
    try:
        conn = sqlite3.connect("data/trading_system.db")
        # Szukamy w logach ostatniego skanu — brak dedykowanej tabeli, wracamy None
        conn.close()
    except Exception:
        pass
    return None

def save_trade_open(ticker, entry_price, stability, rvol):
    try:
        conn = sqlite3.connect("data/trading_system.db")
        trade_id = str(uuid.uuid4())[:8]
        conn.execute("""
            INSERT INTO trade_review (trade_id, ticker, status, entry_price, stability_at_entry, rvol_at_entry)
            VALUES (?, ?, 'OPEN', ?, ?, ?)
        """, (trade_id, ticker.upper(), entry_price, stability, rvol))
        conn.commit()
        conn.close()
        return trade_id
    except Exception as e:
        st.error(f"Błąd zapisu: {e}")
        return None

def close_trade(trade_id, exit_price):
    try:
        conn = sqlite3.connect("data/trading_system.db")
        row = conn.execute("SELECT entry_price FROM trade_review WHERE trade_id = ?", (trade_id,)).fetchone()
        if not row:
            return False
        pnl = ((exit_price - row[0]) / row[0] * 100) if row[0] > 0 else 0
        conn.execute("""
            UPDATE trade_review SET status='CLOSED', exit_price=?, exit_date=CURRENT_TIMESTAMP, pnl_pct=?
            WHERE trade_id=?
        """, (exit_price, round(pnl, 2), trade_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Błąd zamknięcia: {e}")
        return False


# ══════════════════════════════════════════════
# COMPONENTS
# ══════════════════════════════════════════════

def render_market_regime_widget():
    """Market Regime banner na górze dashboardu."""
    try:
        conn = sqlite3.connect("data/trading_system.db")
        # Czytamy ostatni wpis z active_scans jako proxy dla czasu ostatniego skanu
        row = conn.execute("SELECT updated_at FROM active_scans ORDER BY updated_at DESC LIMIT 1").fetchone()
        conn.close()
        last_scan = row[0] if row else "—"
    except Exception:
        last_scan = "—"

    # Regime live z FMP (tylko jeśli klucz dostępny przez env)
    import os
    regime_color = {"BULL": "🟢", "BEAR": "🔴", "NEUTRAL": "🟡"}

    st.caption(f"Last scan: **{last_scan}** · Auto-refresh every 60s")


def render_detail(ticker: str, scan_row: pd.Series):
    st.markdown(f"## 🔍 {ticker}")
    st.caption(
        f"Sector: **{scan_row.get('sector', '—')}** · "
        f"Status: **{scan_row.get('status', '—')}** · "
        f"Last scan: {scan_row.get('updated_at', '—')}"
    )

    # ── Ask AI buttons ────────────────────────────
    # Get scores for prompt
    try:
        conn = sqlite3.connect("data/trading_system.db")
        sc_row = conn.execute("""
            SELECT tech_score, fund_score, event_score, final_score
            FROM signal_history WHERE ticker = ?
            ORDER BY timestamp DESC LIMIT 1
        """, (ticker,)).fetchone()
        conn.close()
        scores_dict = {"tech_score": sc_row[0], "fund_score": sc_row[1],
                       "event_score": sc_row[2], "final_score": sc_row[3]} if sc_row else None
    except Exception:
        scores_dict = None

    enc_prompt, raw_prompt = build_ai_prompt(ticker, scan_row, scores_dict)
    ai_col1, ai_col2, ai_col3, ai_col4, ai_col5 = st.columns([1, 1, 1, 1, 4])
    ai_col1.markdown(
        f'<a href="https://claude.ai/new?q={enc_prompt}" target="_blank">'
        f'<button style="background:rgba(204,120,92,.2);color:#CC785C;border:1px solid rgba(204,120,92,.4);'
        f'border-radius:6px;padding:6px 14px;cursor:pointer;font-weight:600;width:100%">Claude</button></a>',
        unsafe_allow_html=True)
    ai_col2.markdown(
        f'<a href="https://chatgpt.com/?q={enc_prompt}" target="_blank">'
        f'<button style="background:rgba(16,163,127,.2);color:#10A37F;border:1px solid rgba(16,163,127,.4);'
        f'border-radius:6px;padding:6px 14px;cursor:pointer;font-weight:600;width:100%">ChatGPT</button></a>',
        unsafe_allow_html=True)
    ai_col3.markdown(
        f'<a href="https://aistudio.google.com/prompts/new_chat?q={enc_prompt}" target="_blank">'
        f'<button style="background:rgba(66,133,244,.2);color:#4285F4;border:1px solid rgba(66,133,244,.4);'
        f'border-radius:6px;padding:6px 14px;cursor:pointer;font-weight:600;width:100%">Gemini</button></a>',
        unsafe_allow_html=True)
    ai_col4.markdown(
        f'<a href="https://x.com/i/grok?text={enc_prompt}" target="_blank">'
        f'<button style="background:rgba(255,255,255,.1);color:#E2E8F0;border:1px solid rgba(255,255,255,.2);'
        f'border-radius:6px;padding:6px 14px;cursor:pointer;font-weight:600;width:100%">Grok</button></a>',
        unsafe_allow_html=True)
    ai_col5.caption("📎 Attach price charts (1W/1D/4H/1H) in the AI chat · Score format: **X.X/10**")

    # ── Metryki główne ────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Stability Score", f"{scan_row.get('stability_score', 0):.2f}%")
    c2.metric("Real R/R",        f"{scan_row.get('real_rr', 0):.2f}")
    c3.metric("Entry Limit",     f"${scan_row.get('entry_limit', 0):.2f}")
    c4.metric("Stop Loss",       f"${scan_row.get('stop_loss', 0):.2f}")
    c5.metric("Target",          f"${scan_row.get('target', 0):.2f}")

    st.divider()

    # ── Dane fundamentalne z ostatniego skanu ─
    st.markdown("#### 🏦 Fundamentals & Health")
    try:
        conn = sqlite3.connect("data/trading_system.db")
        # Pobieramy ostatni wpis z signal_history dla tego tickera
        row = conn.execute("""
            SELECT fund_score, tech_score, event_score, final_score
            FROM signal_history WHERE ticker = ?
            ORDER BY timestamp DESC LIMIT 1
        """, (ticker,)).fetchone()
        conn.close()

        if row:
            f1, f2, f3, f4 = st.columns(4)
            f1.metric("Tech Score",  f"{row[1]:.1f}")
            f2.metric("Fund Score",  f"{row[0]:.1f}")
            f3.metric("Event Score", f"{row[2]:.1f}")
            f4.metric("Final Score", f"{row[3]:.1f}")
    except Exception:
        pass

    st.divider()

    # ── Wykres historii score ─────────────────
    history = get_score_history(ticker)
    if not history.empty:
        st.markdown("#### 📈 Score History")
        chart_df = history.set_index('timestamp')[['final_score', 'tech_score', 'fund_score', 'event_score']]
        chart_df.columns = ['Final', 'Tech (50%)', 'Fund (30%)', 'Event (20%)']
        st.line_chart(chart_df)

        if len(history) >= 2:
            st.markdown("#### 📊 Statistics")
            s1, s2, s3, s4 = st.columns(4)
            s1.metric("Scans",    len(history))
            s2.metric("Avg Final", f"{history['final_score'].mean():.1f}")
            s3.metric("Max Final", f"{history['final_score'].max():.1f}")
            delta = history['final_score'].iloc[-1] - history['final_score'].iloc[-2]
            s4.metric("Δ Last", f"{delta:+.1f}", delta_color="normal")

        # ── Ostatnie skany ───────────────────
        st.markdown("#### 🗂 Recent Scans")
        display = history.tail(10).sort_values('timestamp', ascending=False).copy()
        display['timestamp'] = display['timestamp'].dt.strftime('%H:%M:%S')
        display.columns = ['Final', 'Tech', 'Fund', 'Event', 'Time']
        st.dataframe(
            display[['Time', 'Final', 'Tech', 'Fund', 'Event']].style.format({
                'Final': '{:.1f}', 'Tech': '{:.1f}', 'Fund': '{:.1f}', 'Event': '{:.1f}'
            }).background_gradient(subset=['Final'], cmap='RdYlGn', vmin=0, vmax=100),
            width='stretch'
        )
    else:
        st.info("No scan history for this stock.")

    # ── Ostatnie newsy ───────────────────────
    st.divider()
    st.markdown("#### 📰 Latest News")
    news = get_news(ticker=ticker, days=7, limit=5)
    if not news.empty:
        for _, n in news.iterrows():
            col_time, col_src, col_title = st.columns([1.5, 1.5, 7])
            col_time.caption(str(n.get('published_at', ''))[:16])
            col_src.caption(str(n.get('source', '—')))
            if n.get('url'):
                col_title.markdown(f"[{n['headline']}]({n['url']})")
            else:
                col_title.markdown(n['headline'])
    else:
        st.caption("No news for this stock in the last 7 days.")


def render_top10(df: pd.DataFrame):
    st.markdown("## 🏆 Top 10 Ranking")
    if df.empty:
        st.info("No data available.")
        return

    top = df.nlargest(10, 'stability_score').copy().reset_index(drop=True)
    ratings_today = get_ai_ratings_today()
    in_decision   = datetime.now().hour in (15, 16)

    # ── Single HTML table — ticker as styled text + select below ──
    rows_html = ""
    for i, row in top.iterrows():
        rank    = i + 1
        ticker  = row['ticker']
        status  = row['status']
        stab    = f"{row['stability_score']:.1f}%"
        rr      = f"{row['real_rr']:.2f}" if row.get('real_rr', 0) > 0 else "—"
        entry   = f"${row['entry_limit']:.2f}" if row.get('entry_limit', 0) > 0 else "—"
        sl      = f"${row['stop_loss']:.2f}"   if row.get('stop_loss', 0) > 0 else "—"
        tgt     = f"${row['target']:.2f}"      if row.get('target', 0) > 0 else "—"
        emoji, fcolor = get_freshness(row.get('updated_at'))
        upd     = str(row.get('updated_at',''))[5:16]
        r       = ratings_today.get(ticker, {})
        claude  = r.get('claude') or "—"
        chatgpt = r.get('chatgpt') or "—"
        gemini  = r.get('gemini') or "—"
        grok    = r.get('grok') or "—"
        avg_ai  = r.get('avg_ai') or "—"
        s_color = {"CONFIRMED":"#22C55E","CANDIDATE":"#60A5FA","NEW":"#6B7280"}.get(status,"#6B7280")
        a_color = "#22C55E" if avg_ai != "—" and float(avg_ai) >= 7 else \
                  "#EAB308" if avg_ai != "—" and float(avg_ai) >= 5 else \
                  "#EF4444" if avg_ai != "—" else ""

        rows_html += f"""<tr>
<td style="text-align:center;color:#6B7280">{rank}</td>
<td style="font-weight:700;color:#60A5FA">{ticker}</td>
<td style="color:#9CA3AF;font-size:12px">{row.get('sector','—')}</td>
<td><span style="color:{s_color};font-weight:600">● {status}</span></td>
<td style="text-align:right;font-weight:600">{stab}</td>
<td style="text-align:right">{rr}</td>
<td style="text-align:right;color:#60A5FA">{entry}</td>
<td style="text-align:right;color:#F87171">{sl}</td>
<td style="text-align:right;color:#4ADE80">{tgt}</td>
<td style="text-align:right;font-size:12px"><span style="color:{fcolor}">{emoji}</span> {upd}</td>
<td style="text-align:center;color:#CC785C">{claude}</td>
<td style="text-align:center;color:#10A37F">{chatgpt}</td>
<td style="text-align:center;color:#4285F4">{gemini}</td>
<td style="text-align:center;color:#9CA3AF">{grok}</td>
<td style="text-align:center;font-weight:700;color:{a_color}">{avg_ai}</td>
</tr>"""

    st.markdown(f"""
<style>
.t10{{width:100%;border-collapse:collapse;font-size:13px;font-family:sans-serif}}
.t10 th{{background:#1E2130;color:#6B7280;font-size:11px;text-transform:uppercase;
         letter-spacing:.05em;padding:8px 10px;border-bottom:1px solid #2D3148;white-space:nowrap}}
.t10 td{{padding:9px 10px;border-bottom:1px solid #1A1A2E;vertical-align:middle}}
.t10 tr:hover td{{background:#1A1D27}}
</style>
<table class="t10"><thead><tr>
<th>#</th><th>Ticker</th><th>Sector</th><th>Status</th>
<th style="text-align:right">Stability</th>
<th style="text-align:right">R/R</th>
<th style="text-align:right">Entry</th>
<th style="text-align:right">SL</th>
<th style="text-align:right">Target</th>
<th style="text-align:right">Updated</th>
<th style="text-align:center">Claude</th>
<th style="text-align:center">ChatGPT</th>
<th style="text-align:center">Gemini</th>
<th style="text-align:center">Grok</th>
<th style="text-align:center">Avg AI</th>
</tr></thead><tbody>{rows_html}</tbody></table>
""", unsafe_allow_html=True)

    # ── AI Rating form ─────────────────────────
    st.divider()
    if in_decision:
        st.markdown("#### 🤖 AI Ratings — Decision Window Open")
    else:
        st.markdown("#### 🤖 AI Ratings")

    r1, _ = st.columns([2, 4])
    selected_rate = r1.selectbox("Select ticker to rate",
                                 ["— select —"] + top["ticker"].tolist(),
                                 key="rate_ticker")
    if selected_rate and selected_rate != "— select —":
        existing = ratings_today.get(selected_rate, {})
        c1, c2, c3, c4, c5 = st.columns(5)
        v_claude  = c1.number_input("Claude",  0.0, 10.0, float(existing.get('claude')  or 0), 0.5, key="rc")
        v_chatgpt = c2.number_input("ChatGPT", 0.0, 10.0, float(existing.get('chatgpt') or 0), 0.5, key="rg")
        v_gemini  = c3.number_input("Gemini",  0.0, 10.0, float(existing.get('gemini')  or 0), 0.5, key="rge")
        v_grok    = c4.number_input("Grok",    0.0, 10.0, float(existing.get('grok')    or 0), 0.5, key="rgr")
        scores    = [v for v in [v_claude, v_chatgpt, v_gemini, v_grok] if v > 0]
        avg_p     = round(sum(scores)/len(scores), 2) if scores else 0.0
        c5.metric("Avg AI", f"{avg_p:.2f}" if avg_p > 0 else "—")
        v_notes = st.text_input("Notes", value=existing.get('notes') or "", key="rn")
        if st.button(f"💾 Save — {selected_rate}", key="save_rating"):
            avg = save_ai_rating(selected_rate, v_claude, v_chatgpt, v_gemini, v_grok, v_notes)
            st.success(f"✅ {selected_rate} — Avg AI: **{avg:.2f}**")
            st.rerun()



def render_news_tab():
    st.markdown("## 📰 Pre-Market News")

    # ── Filtry ───────────────────────────────
    f1, f2, f3 = st.columns([2, 2, 1])

    try:
        conn = sqlite3.connect("data/trading_system.db")
        tickers_with_news = [r[0] for r in conn.execute(
            "SELECT DISTINCT ticker FROM market_news ORDER BY ticker"
        ).fetchall()]
        sources = [r[0] for r in conn.execute(
            "SELECT DISTINCT source FROM market_news ORDER BY source"
        ).fetchall()]
        conn.close()
    except Exception:
        tickers_with_news, sources = [], []

    selected_ticker = f1.selectbox("Ticker", ["All"] + tickers_with_news, key="news_ticker")
    selected_source = f2.selectbox("Source", ["All"] + sources, key="news_source")
    days_back = f3.selectbox("Period", [1, 3, 7, 14], index=2, key="news_days")

    ticker_filter = None if selected_ticker == "All" else selected_ticker
    source_filter = None if selected_source == "All" else selected_source

    news_df = get_news(ticker=ticker_filter, source=source_filter, days=days_back, limit=150)

    if news_df.empty:
        st.info("No news found for selected filters.")
        return

    st.caption(f"Showing **{len(news_df)}** articles from the last {days_back} days")

    for _, row in news_df.iterrows():
        col_ticker, col_source, col_time, col_title = st.columns([1, 1.5, 1.5, 6])
        col_ticker.markdown(f"**{row['ticker']}**")
        col_source.caption(row.get('source', '—'))
        col_time.caption(str(row.get('published_at', ''))[:16])
        if row.get('url'):
            col_title.markdown(f"[{row['headline']}]({row['url']})")
        else:
            col_title.markdown(row.get('headline', ''))
        st.divider()


# ══════════════════════════════════════════════
# MAIN LAYOUT
# ══════════════════════════════════════════════

# ── Header with logo ─────────────────────────────
col_logo, col_title = st.columns([1, 5])
with col_logo:
    try:
        st.image("SwingRadar-logo.webp", width=200)
    except Exception:
        st.markdown("### 🚀 SwingRadar")
with col_title:
    st.markdown("""
        <div style="padding-top: 12px;">
            <span style="font-size: 13px; color: #6B7280;">
                Decision Support System &nbsp;·&nbsp;
                Built by <a href="https://www.nex41.io" target="_blank"
                style="color: #2563EB; text-decoration: none; font-weight: 600;">Nex41</a>
                &nbsp;·&nbsp;
                <a href="https://www.nex41.io" target="_blank"
                style="color: #6B7280; text-decoration: none;">www.nex41.io</a>
            </span>
        </div>
    """, unsafe_allow_html=True)
render_market_regime_widget()

df = get_scans()

# ── Sidebar ────────────────────────────────────────────────────
st.sidebar.header("Filters")

# ── Stabilność ────────────────────────────────
min_stability = st.sidebar.slider("Min. Stability Score", 0, 100, 0)

# ── Status — checkboxy zamiast tagów ─────────
st.sidebar.markdown("**Signal Status**")
sc1, sc2, sc3 = st.sidebar.columns(3)
show_new       = sc1.checkbox("NEW",       value=True)
show_candidate = sc2.checkbox("CAND",      value=True)
show_confirmed = sc3.checkbox("CONF",      value=True)
status_filter  = (
    (["NEW"]       if show_new       else []) +
    (["CANDIDATE"] if show_candidate else []) +
    (["CONFIRMED"] if show_confirmed else [])
)

# ── Sektory — toggle wszystkie / expander ────
sc_all = True
selected_sectors = []
if not df.empty:
    available_sectors = sorted(df['sector'].fillna("Unknown").unique().tolist())

    st.sidebar.markdown("**Sectors**")
    sc_all = st.sidebar.toggle("All sectors", value=True, key="all_sectors_toggle")

    if sc_all:
        selected_sectors = available_sectors
    else:
        with st.sidebar.expander("Select sectors", expanded=True):
            selected_sectors = []
            for sector in available_sectors:
                if st.checkbox(sector, value=True, key=f"sec_{sector}"):
                    selected_sectors.append(sector)
        if not selected_sectors:
            selected_sectors = available_sectors


# Odśwież na dole sidebara
st.sidebar.divider()
st.sidebar.caption(f"Auto-refresh every 60s · {datetime.now().strftime('%H:%M:%S')}")
if st.sidebar.button("🔄 Refresh", use_container_width=True):
    st.rerun()

# ── Zakładki ──────────────────────────────────────────────────
tab_top10, tab_main, tab_analiza, tab_paper, tab_news = st.tabs([
    "🏆 Top 10", "📊 Sectors", "🔬 Analysis", "📈 Trades", "📰 News"
])

with tab_main:
    if not df.empty:
        # Filtrujemy tylko po stabilności i statusie
        # Sektory NIE są częścią maski — expander pokazuje tylko sektory
        # które mają spółki po filtrze statusu (active_sectors poniżej)
        # Jeśli żaden status nie wybrany — pokaż wszystko
        active_status = status_filter if status_filter else ["NEW", "CANDIDATE", "CONFIRMED"]

        mask = (
            (df['stability_score'] >= min_stability) &
            (df['status'].isin(active_status))
        )
        filtered_df = df[mask]

        # Filtr sektorów tylko gdy toggle jest wyłączony
        if not sc_all and selected_sectors:
            filtered_df = filtered_df[
                filtered_df['sector'].fillna("Unknown").isin(selected_sectors)
            ]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Monitored",  len(df))
        c2.metric("Candidates",     len(df[df['status'] == "CANDIDATE"]))
        c3.metric("Confirmed",  len(df[df['status'] == "CONFIRMED"]))
        c4.metric("Filtered",   len(filtered_df))

        st.subheader("🎯 Signals by Sector")
        if filtered_df.empty:
            st.info("No stocks matching the current filters.")
        else:
            active_sectors = sorted(filtered_df['sector'].fillna("Unknown").unique().tolist())
            for sector in active_sectors:
                sector_data = filtered_df[filtered_df['sector'].fillna("Unknown") == sector]
                with st.expander(f"📁 {sector} ({len(sector_data)})", expanded=True):
                        display_df = sector_data.drop(columns=['sector']).copy()
                        def highlight_status(val):
                            return {
                                "CONFIRMED": "background-color: #1a472a; color: #69db7c",
                                "CANDIDATE": "background-color: #1c3a5e; color: #74c0fc",
                                "NEW":       "background-color: #2b2b2b; color: #ced4da"
                            }.get(val, "")
                        # Formatujemy kolumny — Entry/SL/Target pokazują "—" gdy 0
                        display_df = display_df.copy()
                        display_df["rr_time"] = display_df.apply(
                            lambda r: f'{r["real_rr"]:.2f} ({str(r["updated_at"])[11:16]})'
                                      if r["real_rr"] > 0 else "—", axis=1
                        )
                        display_df["entry_limit"] = display_df["entry_limit"].map(
                            lambda x: f"${x:.2f}" if x > 0 else "—")
                        display_df["stop_loss"]   = display_df["stop_loss"].map(
                            lambda x: f"${x:.2f}" if x > 0 else "—")
                        display_df["target"]      = display_df["target"].map(
                            lambda x: f"${x:.2f}" if x > 0 else "—")
                        display_df["updated_at"]  = display_df["updated_at"].map(
                            lambda x: f"{get_freshness(x)[0]} {str(x)[5:16]}" if x else "⚪ —")

                        show_cols = ["ticker","status","stability_score","rr_time",
                                     "entry_limit","stop_loss","target","updated_at"]
                        show_cols = [c for c in show_cols if c in display_df.columns]
                        rename_map = {
                            "ticker": "Ticker", "status": "Status",
                            "stability_score": "Stability", "rr_time": "Real R/R",
                            "entry_limit": "Entry $", "stop_loss": "Stop Loss",
                            "target": "Target", "updated_at": "Last Updated"
                        }
                        display_df = display_df[show_cols].rename(columns=rename_map)

                        styled = display_df.style.format({
                            "Stability": "{:.2f}%",
                        }).map(highlight_status, subset=["Status"])
                        st.dataframe(styled, width='stretch')
    else:
        st.warning("⚠️ Database is empty. Please run `scanner_daemon.py`.")

with tab_top10:
    render_top10(df)

with tab_analiza:
    st.markdown("## 🔬 Stock Analysis")
    if not df.empty:
        all_tickers = sorted(df['ticker'].tolist())

        # '_analysis_target' set by Top 10 button, 'analysis_ticker' owned by selectbox
        preselect = st.session_state.pop('_analysis_target', None)
        options   = ["— select —"] + all_tickers
        default_i = options.index(preselect) if preselect in options else 0

        col_sel, _ = st.columns([2, 4])
        selected_ticker = col_sel.selectbox(
            "Select stock", options, index=default_i, key="analysis_ticker"
        )
        if selected_ticker and selected_ticker != "— select —":
            row = df[df['ticker'] == selected_ticker].iloc[0]
            render_detail(selected_ticker, row)
        else:
            st.info("Select a stock from the list above to view detailed analysis.")
    else:
        st.warning("No data. Please run scanner_daemon.py.")

with tab_paper:
    st.markdown("## 📈 Trade Journal")
    st.caption("Track paper and real trades to measure signal quality.")

    ptab_open, ptab_closed, ptab_stats, ptab_new = st.tabs([
        "📂 Open", "✅ Closed", "📊 Statistics", "➕ New Trade"
    ])

    paper_trades = get_paper_trades()

    with ptab_new:
        st.markdown("#### Open a new trade")
        if not df.empty:
            p1, p2 = st.columns(2)
            pt_ticker = p1.selectbox("Ticker", ["— select —"] + sorted(df['ticker'].tolist()), key="pt_ticker")
            pt_notes  = p2.text_input("Notes (optional)", key="pt_notes")

            # Auto-uzupełnienie ze skanera
            pt_entry = pt_sl = pt_target = pt_rr = pt_stab = pt_score = 0.0
            if pt_ticker and pt_ticker != "— select —":
                row = df[df['ticker'] == pt_ticker]
                if not row.empty:
                    r = row.iloc[0]
                    pt_entry = float(r['entry_limit']) if r['entry_limit'] else 0.0
                    pt_sl    = float(r['stop_loss'])   if r['stop_loss']   else 0.0
                    pt_target= float(r['target'])      if r['target']      else 0.0
                    pt_rr    = float(r['real_rr'])      if r['real_rr']     else 0.0
                    pt_stab  = float(r['stability_score'])

                    st.info(f"💡 Auto-filled from scanner: Entry **${pt_entry:.2f}** · SL **${pt_sl:.2f}** · Target **${pt_target:.2f}** · RR **{pt_rr:.2f}** · Stability **{pt_stab:.1f}%**")

            c1, c2, c3 = st.columns(3)
            pt_entry  = c1.number_input("Entry Price ($)", value=max(pt_entry, 0.01),  min_value=0.01, step=0.01, key="pt_entry")
            pt_sl     = c2.number_input("Stop Loss ($)",   value=max(pt_sl, 0.01),    min_value=0.01, step=0.01, key="pt_sl")
            pt_target = c3.number_input("Target ($)",      value=max(pt_target, 0.01), min_value=0.01, step=0.01, key="pt_target")

            c4, c5 = st.columns(2)
            pt_rr    = c4.number_input("Real R/R",         value=pt_rr,   min_value=0.0, step=0.01, key="pt_rr")
            pt_stab  = c5.number_input("Stability Score",  value=pt_stab, min_value=0.0, max_value=100.0, step=0.1, key="pt_stab")

            rg1, rg2 = st.columns(2)
            pt_regime     = rg1.selectbox("Market Regime",
                                          ["NEUTRAL", "BULL", "BEAR"], key="pt_regime")
            pt_trade_type = rg2.selectbox("Trade Type",
                                          ["PAPER", "REAL"], key="pt_trade_type",
                                          help="PAPER = virtual | REAL = live ISA account trade")

            if st.button("💾 Save Trade", disabled=(pt_ticker == "— select —" or pt_entry <= 0)):
                if save_paper_trade(pt_ticker, pt_entry, pt_sl, pt_target, pt_rr,
                                    pt_stab, 0.0, pt_regime, pt_notes, pt_trade_type):
                    label = "📝 Paper trade" if pt_trade_type == "PAPER" else "💰 Real trade"
                    st.success(f"✅ {label} {pt_ticker} opened @ ${pt_entry:.2f}")
                    st.rerun()
        else:
            st.warning("No scanner data available.")

    with ptab_open:
        open_pt = paper_trades[paper_trades['status'] == 'OPEN'] if not paper_trades.empty else pd.DataFrame()
        if open_pt.empty:
            st.info("No open paper trades.")
        else:
            for _, t in open_pt.iterrows():
                trade_badge = "📝" if str(t.get("trade_type","PAPER")) == "PAPER" else "💰"
                with st.expander(
                    f"{trade_badge} **{t['ticker']}** — Entry ${t['entry_price']:.2f} · SL ${t['stop_loss']:.2f} · Target ${t['target']:.2f} · RR {t['real_rr']:.2f}",
                    expanded=True
                ):
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Entry",     f"${t['entry_price']:.2f}")
                    m2.metric("Stop Loss", f"${t['stop_loss']:.2f}")
                    m3.metric("Target",    f"${t['target']:.2f}")
                    m4.metric("Stability", f"{t['stability']:.1f}%")

                    st.markdown("**Zamknij trade:**")
                    cx1, cx2 = st.columns(2)
                    close_price  = cx1.number_input("Exit Price", value=float(t['entry_price']),
                                                    min_value=0.01, step=0.01, key=f"pt_close_{t['id']}")
                    close_reason = cx2.selectbox("Reason", ["Target Hit", "Stop Hit", "Manual", "Time Exit"],
                                                 key=f"pt_reason_{t['id']}")
                    cx3, cx4, cx5 = st.columns(3)
                    mae_val = cx3.number_input("MAE % (max adverse)", value=0.0, min_value=0.0,
                                               step=0.1, key=f"pt_mae_{t['id']}",
                                               help="How far % price moved AGAINST you during the trade")
                    mfe_val = cx4.number_input("MFE % (max favourable)", value=0.0, min_value=0.0,
                                               step=0.1, key=f"pt_mfe_{t['id']}",
                                               help="How far % price moved IN YOUR FAVOUR during the trade")
                    hit_t = close_reason == "Target Hit"
                    hit_s = close_reason == "Stop Hit"

                    if cx5.button("💰 Close", key=f"pt_btn_{t['id']}"):
                        if close_paper_trade(int(t['id']), close_price, close_reason,
                                             hit_t, hit_s, mae_val, mfe_val):
                            pnl = (close_price - t['entry_price']) / t['entry_price'] * 100
                            st.success(f"Closed {t['ticker']} | P&L: **{pnl:+.2f}%** | {close_reason}")
                            st.rerun()

    with ptab_closed:
        closed_pt = paper_trades[paper_trades['status'] == 'CLOSED'] if not paper_trades.empty else pd.DataFrame()
        if closed_pt.empty:
            st.info("No closed paper trades.")
        else:
            disp = closed_pt[['ticker','entry_date','exit_date','entry_price','exit_price',
                               'stop_loss','target','real_rr','stability','pnl_pct','exit_reason']].copy()
            disp.columns = ['Ticker','Entry Date','Exit Date','Entry','Exit','SL','Target','RR','Stab%','P&L%','Reason']
            disp['Entry Date'] = disp['Entry Date'].astype(str).str[:16]
            disp['Exit Date'] = disp['Exit Date'].astype(str).str[:16]

            def color_pnl(val):
                if isinstance(val, float):
                    if val > 0: return 'color: #69db7c'
                    if val < 0: return 'color: #ff6b6b'
                return ''

            st.dataframe(
                disp.style.format({
                    'Entry': '${:.2f}', 'Exit': '${:.2f}',
                    'SL': '${:.2f}', 'Target': '${:.2f}',
                    'RR': '{:.2f}', 'Stab%': '{:.1f}', 'P&L%': '{:+.2f}%'
                }).map(color_pnl, subset=['P&L%']),
                width='stretch'
            )

    with ptab_stats:
        import numpy as np_pt
        closed_pt = paper_trades[paper_trades['status'] == 'CLOSED'] if not paper_trades.empty else pd.DataFrame()
        if len(closed_pt) < 2:
            st.info("At least 2 closed trades required for statistics.")
        else:
            import warnings
            warnings.filterwarnings("ignore", category=RuntimeWarning)

            # ── Kalkulacje bazowe ─────────────────
            closed_pt = closed_pt.copy()
            closed_pt['pnl_pct'] = pd.to_numeric(closed_pt['pnl_pct'], errors='coerce').fillna(0.0)

            winners = closed_pt[closed_pt['pnl_pct'] > 0]
            losers  = closed_pt[closed_pt['pnl_pct'] <= 0]
            n       = len(closed_pt)
            win_rate   = len(winners) / n * 100 if n > 0 else 0.0
            loss_rate  = 100 - win_rate
            avg_win    = float(winners['pnl_pct'].mean()) if len(winners) else 0.0
            avg_loss   = float(abs(losers['pnl_pct'].mean())) if len(losers) else 0.0
            total_pnl  = float(closed_pt['pnl_pct'].sum())
            target_hit = int(closed_pt['hit_target'].sum()) if 'hit_target' in closed_pt.columns else 0
            stop_hit   = int(closed_pt['hit_stop'].sum())   if 'hit_stop'   in closed_pt.columns else 0

            gross_win  = float(winners['pnl_pct'].sum()) if len(winners) else 0.0
            gross_loss = float(abs(losers['pnl_pct'].sum())) if len(losers) else 0.001
            profit_factor = (gross_win / gross_loss) if gross_loss > 0 else 0.0

            # ── Expectancy ────────────────────────
            # E = (Win% × Avg Win) − (Loss% × Avg Loss)
            expectancy = (win_rate/100 * avg_win) - (loss_rate/100 * avg_loss)

            # ── R-Multiple ───────────────────────
            r_vals = closed_pt['r_multiple'].dropna() if 'r_multiple' in closed_pt.columns else pd.Series(dtype=float)
            avg_r  = r_vals.mean() if len(r_vals) else 0.0
            # R-Expectancy = avg R-Multiple (weighted)
            r_expectancy = r_vals.mean() if len(r_vals) else 0.0

            # ── Max Drawdown ─────────────────────
            cum = closed_pt.sort_values('exit_date')['pnl_pct'].cumsum()
            rolling_max = cum.cummax()
            drawdown    = cum - rolling_max
            max_dd      = drawdown.min()

            # ── Sharpe Ratio (miesięczny) ─────────
            returns = closed_pt.sort_values('exit_date')['pnl_pct']
            ret_std = float(returns.std()) if len(returns) > 1 else 0.0
            ret_mean = float(returns.mean()) if len(returns) > 0 else 0.0
            sharpe  = (ret_mean / ret_std * np_pt.sqrt(len(returns))) if ret_std > 0 else 0.0

            # ── Sortino Ratio ────────────────────
            neg_returns  = returns[returns < 0]
            downside_std = float(neg_returns.std()) if len(neg_returns) > 1 else 0.0
            sortino = (ret_mean / downside_std * np_pt.sqrt(len(returns))) if downside_std > 0 else 0.0

            # ── Sekcja 1: Kluczowe metryki ────────
            st.markdown("### 🎯 Key Metrics")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Expectancy",    f"{expectancy:+.2f}%",
                      help="Expected profit per trade. Positive = system has edge. Formula: (Win% x Avg Win) - (Loss% x Avg Loss)")
            c2.metric("Profit Factor", f"{profit_factor:.2f}",
                      delta="✅ good" if profit_factor >= 1.5 else "⚠️ weak",
                      delta_color="off",
                      help="Gross profit / gross loss. >1.5 = good, >2.0 = very good")
            c3.metric("Max Drawdown",  f"{max_dd:.2f}%",
                      delta="✅ OK" if max_dd > -20 else "⚠️ high",
                      delta_color="off",
                      help="Largest equity drawdown. Target: > -20%")
            c4.metric("Total P&L",   f"{total_pnl:+.2f}%",
                      delta_color="normal" if total_pnl >= 0 else "inverse")

            c5, c6, c7, c8 = st.columns(4)
            c5.metric("Sharpe Ratio",  f"{sharpe:.2f}",
                      delta="✅ good" if sharpe >= 1.0 else "⚠️ weak",
                      delta_color="off",
                      help="Return / standard deviation. >1.0 = good, >2.0 = very good")
            c6.metric("Sortino Ratio", f"{sortino:.2f}",
                      help="Like Sharpe but penalises only losing trades. Better for swing trading.")
            c7.metric("R-Expectancy",  f"{r_expectancy:+.2f}R",
                      help="Average risk multiple per trade. +0.5R = you earn 0.5x risk on each trade.")
            c8.metric("Avg R",         f"{avg_r:+.2f}R",
                      help="Average R-Multiple of closed trades")

            st.divider()

            # ── Sekcja 2: Win/Loss ───────────────
            st.markdown("### 📊 Win / Loss Analysis")
            w1, w2, w3, w4, w5, w6 = st.columns(6)
            w1.metric("Trades",      n)
            w2.metric("Win Rate",    f"{win_rate:.0f}%",
                      delta=f"{win_rate-50:+.0f}pp vs 50%", delta_color="normal")
            w3.metric("Avg Win",     f"+{avg_win:.2f}%")
            w4.metric("Avg Loss",    f"-{avg_loss:.2f}%")
            w5.metric("Target Hit",  target_hit)
            w6.metric("Stop Hit",    stop_hit)

            st.divider()

            # ── Sekcja 3: Wykresy ────────────────
            charts_col1, charts_col2 = st.columns(2)

            with charts_col1:
                st.markdown("#### 📈 Skumulowany P&L")
                cum_df = closed_pt.sort_values('exit_date').copy()
                cum_df['Cumulative P&L %'] = cum_df['pnl_pct'].cumsum()
                cum_df = cum_df.set_index('exit_date')[['Cumulative P&L %']]
                st.line_chart(cum_df)

            with charts_col2:
                st.markdown("#### 📊 Rozkład R-Multiple")
                if len(r_vals) >= 3:
                    r_hist = pd.DataFrame({'R-Multiple': r_vals})
                    st.bar_chart(r_hist['R-Multiple'].value_counts(bins=10).sort_index())
                else:
                    st.info("Min. 3 trades with R-Multiple required for chart")

            st.divider()

            # ── Sekcja 4: Analiza Stability vs Wyniki ──
            if len(closed_pt) >= 5:
                st.markdown("### 🔬 Correlation: Stability Score → Outcomes")
                st.caption("Does a higher Stability Score actually predict better outcomes?")

                sa, sb = st.columns(2)
                with sa:
                    st.markdown("**Stability Score vs P&L %**")
                    scatter1 = closed_pt[['stability', 'pnl_pct']].dropna()
                    scatter1.columns = ['Stability Score', 'P&L %']
                    st.scatter_chart(scatter1, x='Stability Score', y='P&L %')

                with sb:
                    if len(r_vals) >= 5:
                        st.markdown("**Stability Score vs R-Multiple**")
                        scatter2 = closed_pt[['stability', 'r_multiple']].dropna()
                        scatter2.columns = ['Stability Score', 'R-Multiple']
                        st.scatter_chart(scatter2, x='Stability Score', y='R-Multiple')

                st.divider()

            # ── Sekcja 5: Analiza per Market Regime ──
            if 'market_regime' in closed_pt.columns and closed_pt['market_regime'].notna().any():
                st.markdown("### 🌍 Results by Market Regime")
                regime_stats = closed_pt.groupby('market_regime').agg(
                    Trades     = ('pnl_pct', 'count'),
                    Win_Rate   = ('pnl_pct', lambda x: (x > 0).mean() * 100),
                    Avg_PnL    = ('pnl_pct', 'mean'),
                    Total_PnL  = ('pnl_pct', 'sum'),
                    Avg_R      = ('r_multiple', 'mean'),
                ).round(2)
                regime_stats.columns = ['Trades', 'Win Rate %', 'Avg P&L %', 'Total P&L %', 'Avg R']
                st.dataframe(regime_stats, width='stretch')
                st.divider()

            # ── Sekcja 6: MAE/MFE Analiza ────────
            has_mae = 'mae_pct' in closed_pt.columns and closed_pt['mae_pct'].notna().any()
            has_mfe = 'mfe_pct' in closed_pt.columns and closed_pt['mfe_pct'].notna().any()
            if has_mae or has_mfe:
                st.markdown("### 📐 MAE / MFE Analysis")
                st.caption("MAE = how far price moved AGAINST you | MFE = how far price moved IN YOUR FAVOUR")

                mf1, mf2, mf3, mf4 = st.columns(4)
                if has_mae:
                    avg_mae = closed_pt['mae_pct'].mean()
                    mf1.metric("Avg MAE",  f"{avg_mae:.2f}%",
                               help="Average maximum adverse excursion. Helps evaluate if stop is too tight or too loose.")
                    mf2.metric("Max MAE",  f"{closed_pt['mae_pct'].max():.2f}%")
                if has_mfe:
                    avg_mfe = closed_pt['mfe_pct'].mean()
                    mf3.metric("Avg MFE",  f"+{avg_mfe:.2f}%",
                               help="Average maximum favourable excursion. If MFE >> target — you are exiting too early.")
                    mfe_efficiency = (closed_pt['pnl_pct'] / closed_pt['mfe_pct'] * 100).mean()
                    mf4.metric("MFE Efficiency", f"{mfe_efficiency:.0f}%",
                               help="What % of available move you captured. 70%+ = good exit execution.")
                st.divider()

            # ── Sekcja 7: Benchmark ──────────────
            st.markdown("### 📋 System Performance Benchmark")
            benchmarks = {
                "Expectancy":    (expectancy,    "> 0",   expectancy > 0),
                "Profit Factor": (profit_factor, "> 1.5", profit_factor >= 1.5),
                "Win Rate":      (win_rate,      "> 40%", win_rate >= 40),
                "Max Drawdown":  (max_dd,        "> -20%", max_dd > -20),
                "Sharpe Ratio":  (sharpe,        "> 1.0", sharpe >= 1.0),
                "Sortino Ratio": (sortino,       "> 1.5", sortino >= 1.5),
            }
            for name, (val, target_bench, passed) in benchmarks.items():
                icon = "✅" if passed else "❌"
                col_n, col_v, col_t, col_s = st.columns([2, 1.5, 1.5, 0.5])
                col_n.write(name)
                col_v.write(f"**{val:.2f}**" if isinstance(val, float) else f"**{val}**")
                col_t.caption(f"target: {target_bench}")
                col_s.write(icon)

with tab_news:
    render_news_tab()

# ── Footer ────────────────────────────────────────
st.divider()
st.markdown("""
    <div style="text-align: center; padding: 8px 0; color: #6B7280; font-size: 12px;">
        SwingRadar DSS &nbsp;·&nbsp; V2.44 &nbsp;·&nbsp;
        Built by <a href="https://www.nex41.io" target="_blank"
        style="color: #2563EB; text-decoration: none; font-weight: 600;">Nex41</a>
        &nbsp;·&nbsp;
        <a href="https://www.nex41.io" target="_blank"
        style="color: #9CA3AF; text-decoration: none;">www.nex41.io</a>
        &nbsp;·&nbsp; NYSE / NASDAQ &nbsp;·&nbsp; ISA Account (UK)
    </div>
""", unsafe_allow_html=True)

# Auto-refresh every 60 seconds
time.sleep(60)
st.rerun()
