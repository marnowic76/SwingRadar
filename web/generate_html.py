"""
SwingRadar HTML Generator V1.0
Generuje statyczny dashboard HTML z bazy SQLite i uploaduje na serwer FTP.

Uruchamiaj co 15 minut przez cron:
  */15 * * * * cd /Users/marek/Git/swing-radar && python3.13 generate_html.py >> logs/html_gen.log 2>&1

FTP Config w pliku .env lub zmienne środowiskowe:
  FTP_HOST, FTP_USER, FTP_PASS, FTP_PATH
"""

import sqlite3
import os
import ftplib
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ══════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════
DB_PATH      = "data/trading_system.db"
OUTPUT_HTML  = "web/dashboard.html"
FTP_HOST     = os.environ.get("FTP_HOST", "serwer82250.lh.pl")
FTP_USER     = os.environ.get("FTP_USER", "")
FTP_PASS     = os.environ.get("FTP_PASS", "")
FTP_PATH     = os.environ.get("FTP_PATH", "/public_html/swingRadar/")
FTP_ENABLED  = bool(FTP_USER and FTP_PASS)

# ══════════════════════════════════════════════
# DATA HELPERS
# ══════════════════════════════════════════════

def get_scans():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT ticker, sector, status, stability_score, real_rr,
                   entry_limit, stop_loss, target, updated_at
            FROM active_scans
            ORDER BY stability_score DESC
        """).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"DB error: {e}")
        return []

def get_top10(scans):
    candidates = [s for s in scans if s['status'] in ('CANDIDATE', 'CONFIRMED')]
    return sorted(candidates, key=lambda x: x['stability_score'], reverse=True)[:10]

def get_news(limit=50):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cutoff = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
        rows = conn.execute("""
            SELECT ticker, headline, source, published_at, url
            FROM market_news WHERE published_at >= ?
            ORDER BY published_at DESC LIMIT ?
        """, (cutoff, limit)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []

def get_stock_details():
    """
    Pobiera ostatnie scores i newsy dla każdej spółki.
    Zwraca dict: {ticker: {scores, news}}
    Ograniczamy do CANDIDATE i CONFIRMED żeby HTML nie był za duży.
    """
    details = {}
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row

        # Last scores per ticker from signal_history
        scores_rows = conn.execute("""
            SELECT ticker, tech_score, fund_score, event_score, final_score, timestamp
            FROM signal_history
            WHERE (ticker, timestamp) IN (
                SELECT ticker, MAX(timestamp) FROM signal_history GROUP BY ticker
            )
        """).fetchall()
        scores = {r['ticker']: dict(r) for r in scores_rows}

        # Last 5 news per ticker
        news_rows = conn.execute("""
            SELECT ticker, headline, source, published_at, url
            FROM market_news
            WHERE published_at >= date('now', '-7 days')
            ORDER BY published_at DESC
        """).fetchall()

        news_by_ticker = {}
        for r in news_rows:
            t = r['ticker']
            if t not in news_by_ticker:
                news_by_ticker[t] = []
            if len(news_by_ticker[t]) < 5:
                news_by_ticker[t].append(dict(r))

        conn.close()

        for ticker, sc in scores.items():
            details[ticker] = {
                'scores': sc,
                'news':   news_by_ticker.get(ticker, [])
            }

    except Exception as e:
        print(f"Stock details error: {e}")

    return details


def is_decision_window_now():
    """15:30-17:00 UTC = 17:30-19:00 PL"""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    if now.hour == 15 and now.minute >= 30:
        return True
    if now.hour == 16:
        return True
    return False


def ftp_makedirs(ftp, path):
    parts = [p for p in path.strip("/").split("/") if p]
    current = ""
    for part in parts:
        current += "/" + part
        try:
            ftp.mkd(current)
        except Exception:
            pass

def upload_ftp(local_file, ftp_path, assets):
    print(f"Uploading to FTP: {FTP_HOST}{ftp_path}")
    try:
        ftp = ftplib.FTP(FTP_HOST)
        ftp.login(FTP_USER, FTP_PASS)
        ftp_makedirs(ftp, ftp_path)
        ftp.cwd(ftp_path)
        with open(local_file, 'rb') as f:
            ftp.storbinary('STOR dashboard.html', f)
        print(f"  ✅ dashboard.html uploaded")
        for asset in assets:
            if Path(asset).exists():
                with open(asset, 'rb') as f:
                    ftp.storbinary(f'STOR {Path(asset).name}', f)
                print(f"  ✅ {Path(asset).name} uploaded")
            else:
                print(f"  ⚠️  Not found: {asset}")
        ftp.quit()
        print("FTP upload complete.")
    except Exception as e:
        print(f"FTP error: {e}")


def get_ai_ratings():
    """Pobiera dzisiejsze średnie oceny AI."""
    try:
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT ticker, avg_ai FROM ai_ratings WHERE date = ? AND avg_ai IS NOT NULL",
            (today,)
        ).fetchall()
        conn.close()
        return {r['ticker']: round(float(r['avg_ai']), 2) for r in rows}
    except Exception:
        return {}


def get_regime():
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("""
            SELECT updated_at FROM active_scans
            ORDER BY updated_at DESC LIMIT 1
        """).fetchone()
        conn.close()
        return fmt_bst(row[0]) if row else "—"
    except Exception:
        return "—"


def get_regime_data() -> dict:
    """Returns latest market regime with sector counts."""
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("""
            SELECT regime, sectors_up, sectors_dn, updated_at
            FROM market_regime_log
            ORDER BY id DESC LIMIT 1
        """).fetchone()
        conn.close()
        if row:
            return {
                "regime":      row[0],
                "sectors_up":  row[1] or 0,
                "sectors_dn":  row[2] or 0,
                "updated_at":  fmt_bst(row[3]),
            }
    except Exception:
        pass
    return {"regime": "NEUTRAL", "sectors_up": 0, "sectors_dn": 0, "updated_at": "—"}

def freshness_class(updated_at):
    if not updated_at:
        return "stale", "⚪"
    try:
        dt = datetime.fromisoformat(str(updated_at).replace(" ", "T"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        if age_h < 1:   return "fresh",    "🟢"
        elif age_h < 4: return "moderate", "🟡"
        else:           return "stale",    "🔴"
    except Exception:
        return "stale", "⚪"

def fmt_price(val):
    return f"${val:.2f}" if val and val > 0 else "—"

def fmt_rr(val, updated_at):
    if not val or val <= 0:
        return "—"
    t = str(updated_at)[11:16] if updated_at else ""
    return f"{val:.2f} <span class='rr-time'>({t})</span>"

def fmt_stability(val):
    if not val or val <= 0:
        return "—"
    return f"{val:.1f}%"

def fmt_bst(utc_str):
    """Convert UTC datetime string to BST display (MM-DD HH:MM BST)."""
    if not utc_str:
        return "—"
    try:
        from datetime import datetime, timezone, timedelta
        dt = datetime.fromisoformat(str(utc_str).replace(" ", "T"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        bst = dt + timedelta(hours=1)
        return bst.strftime("%m-%d %H:%M BST")
    except Exception:
        return str(utc_str)[5:16]


def ai_prompt(s, sc=None):
    """Buduje URL do AI z gotowym promptem dla danej spółki."""
    entry = fmt_price(s['entry_limit'])
    sl    = fmt_price(s['stop_loss'])
    tgt   = fmt_price(s['target'])
    rr    = f"{s['real_rr']:.2f}" if s.get('real_rr') and s['real_rr'] > 0 else "—"
    stab  = fmt_stability(s['stability_score'])

    scores_txt = ""
    if sc:
        scores_txt = (f"Scores: Tech {sc.get('tech_score',0):.0f} | "
                      f"Fund {sc.get('fund_score',0):.0f} | "
                      f"Event {sc.get('event_score',0):.0f} | "
                      f"Final {sc.get('final_score',0):.0f}. ")

    prompt = (
        f"SwingRadar DSS signal for {s['ticker']} ({s.get('sector','')}) "
        f"on NYSE/NASDAQ for UK ISA account. "
        f"Status: {s['status']}. Stability: {stab}. "
        f"Entry: {entry} | Stop Loss: {sl} | Target: {tgt} | Real R/R: {rr}. "
        f"{scores_txt}"
        f"Please analyse this swing trade setup: "
        f"1) Technical assessment 2) Key risks 3) Your recommendation. "
        f"Consider current market conditions."
    )
    import urllib.parse
    enc = urllib.parse.quote(prompt)
    # Escape for safe JS string embedding
    prompt_js = prompt.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"').replace("\n", "\\n")
    return {
        'claude':  f"https://claude.ai/new?q={enc}",
        'chatgpt': f"https://chatgpt.com/?q={enc}",
        'gemini':  f"https://gemini.google.com/app",
        'grok':    f"https://x.com/i/grok?text={enc}",
        'prompt':  prompt_js,
    }


def sectors_grouped(scans):
    sectors = {}
    for s in scans:
        sec = s['sector'] or 'Unknown'
        sectors.setdefault(sec, []).append(s)
    return dict(sorted(sectors.items()))

def status_badge(status):
    colors = {
        'CONFIRMED': ('badge-confirmed', '🟢'),
        'CANDIDATE': ('badge-candidate', '🔵'),
        'NEW':       ('badge-new',       '⚫'),
    }
    cls, icon = colors.get(status, ('badge-new', '⚪'))
    return f'<span class="badge {cls}">{icon} {status}</span>'

# ══════════════════════════════════════════════
# HTML BUILDER
# ══════════════════════════════════════════════

def build_html(scans, top10, news, last_scan, details=None, ai_ratings=None, in_decision=False, regime_data=None):
    from datetime import timedelta
    now_utc = datetime.now(timezone.utc)
    now_bst = now_utc + timedelta(hours=1)
    now = now_bst.strftime("%Y-%m-%d %H:%M")
    total      = len(scans)
    candidates = len([s for s in scans if s['status'] == 'CANDIDATE'])
    confirmed  = len([s for s in scans if s['status'] == 'CONFIRMED'])

    # ── Top 10 rows ──────────────────────────
    top10_rows = ""
    for i, s in enumerate(top10, 1):
        fc, fi = freshness_class(s['updated_at'])
        ticker = s['ticker']
        d  = (details or {}).get(ticker, {})
        sc = d.get('scores', {})
        ai = ai_prompt(s, sc)
        ai_score = (ai_ratings or {}).get(ticker, '—')
        top10_rows += f"""
        <tr>
            <td class="num">{i}</td>
            <td><strong>{ticker}</strong></td>
            <td class="sector">{s['sector'] or '—'}</td>
            <td>{status_badge(s['status'])}</td>
            <td class="num">{fmt_stability(s['stability_score'])}</td>
            <td class="num">{fmt_rr(s['real_rr'], s['updated_at'])}</td>
            <td class="num">{fmt_price(s['entry_limit'])}</td>
            <td class="num">{fmt_price(s['stop_loss'])}</td>
            <td class="num">{fmt_price(s['target'])}</td>
            <td class="num freshness-{fc}">{fi} {fmt_bst(s['updated_at'])}</td>
            <td class="num ai-score">{ai_score}</td>
            <td class="ai-btns">{
    '<a href="' + ai['claude'] + '" target="_blank" class="ai-btn ai-claude" title="Ask Claude">C</a>'
    + '<a href="' + ai['chatgpt'] + '" target="_blank" class="ai-btn ai-chatgpt" title="Ask ChatGPT">G</a>'
    + '<a href="javascript:void(0)" onclick="copyAndOpenGemini(this)" data-prompt="' + ai['prompt'].replace('"', '&quot;') + '" class="ai-btn ai-gemini" title="Ask Gemini (copies prompt)">Ge</a>'
    + '<a href="' + ai['grok'] + '" target="_blank" class="ai-btn ai-grok" title="Ask Grok">X</a>'
    + '<button onclick="copyPrompt(&quot;' + ticker + '&quot;)" class="ai-btn ai-copy" title="Copy full prompt to clipboard">&#128203;</button>'
}</td>
        </tr>"""

    # ── Sector tables ────────────────────────
    sector_html = ""
    grouped = sectors_grouped(scans)
    for sector, stocks in grouped.items():
        rows = ""
        for s in stocks:
            fc, fi = freshness_class(s['updated_at'])
            rows += f"""
            <tr>
                <td><strong>{s['ticker']}</strong></td>
                <td>{status_badge(s['status'])}</td>
                <td class="num">{fmt_stability(s['stability_score'])}</td>
                <td class="num">{fmt_rr(s['real_rr'], s['updated_at'])}</td>
                <td class="num">{fmt_price(s['entry_limit'])}</td>
                <td class="num">{fmt_price(s['stop_loss'])}</td>
                <td class="num">{fmt_price(s['target'])}</td>
                <td class="num freshness-{fc}">{fi} {fmt_bst(s['updated_at'])}</td>
            </tr>"""
        sector_html += f"""
        <div class="sector-block">
            <div class="sector-header" onclick="toggleSector(this)">
                📁 {sector} <span class="sector-count">({len(stocks)})</span>
                <span class="toggle-icon">▼</span>
            </div>
            <div class="sector-body"><div class="table-wrap">
                <table>
                    <thead><tr>
                        <th>Ticker</th><th>Status</th><th>Stability</th>
                        <th>Real R/R</th><th>Entry $</th><th>Stop Loss</th>
                        <th>Target</th><th>Last Updated</th>
                    </tr></thead>
                    <tbody>{rows}</tbody>
                </table></div>
            </div>
        </div>"""

    # ── News rows ────────────────────────────
    news_rows = ""
    for n in news:
        title = n['headline'] or ''
        url   = n['url'] or ''
        link  = f'<a href="{url}" target="_blank">{title}</a>' if url else title
        news_rows += f"""
        <tr>
            <td><strong>{n['ticker']}</strong></td>
            <td class="source">{n['source'] or '—'}</td>
            <td class="time">{fmt_bst(n['published_at'])}</td>
            <td class="headline">{link}</td>
        </tr>"""

    if not news_rows:
        news_rows = '<tr><td colspan="4" class="empty">No news in the last 3 days.</td></tr>'

    # ── Analysis Cards ──────────────────────
    details = details or {}
    analysis_cards = ""
    for s in scans:
        ticker  = s['ticker']
        d       = details.get(ticker, {})
        sc      = d.get('scores', {})
        ticker_news = d.get('news', [])
        fc, fi  = freshness_class(s['updated_at'])

        # Score bars
        def score_bar(label, val, color):
            val = val or 0
            pct = min(100, max(0, val))
            return f"""
            <div style="margin-bottom:10px">
                <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:4px">
                    <span style="color:#9CA3AF">{label}</span>
                    <span style="font-weight:600">{val:.0f}</span>
                </div>
                <div style="background:#252836;border-radius:4px;height:6px">
                    <div style="background:{color};width:{pct}%;height:6px;border-radius:4px;transition:width .3s"></div>
                </div>
            </div>"""

        scores_html = ""
        if sc:
            scores_html = f"""
            <div style="padding:16px 0;border-top:1px solid #2D3148;border-bottom:1px solid #2D3148;margin:12px 0">
                {score_bar('Technical (50%)', sc.get('tech_score'), '#2563EB')}
                {score_bar('Fundamental (30%)', sc.get('fund_score'), '#8B5CF6')}
                {score_bar('Event (20%)', sc.get('event_score'), '#F59E0B')}
                {score_bar('Final Score', sc.get('final_score'), '#22C55E')}
            </div>"""

        # Price levels
        has_levels = s['entry_limit'] and s['entry_limit'] > 0
        levels_html = ""
        if has_levels:
            levels_html = f"""
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:12px 0">
                <div style="background:#252836;border-radius:8px;padding:10px;text-align:center">
                    <div style="font-size:11px;color:#6B7280;margin-bottom:4px">ENTRY</div>
                    <div style="font-weight:700;color:#60A5FA">{fmt_price(s['entry_limit'])}</div>
                </div>
                <div style="background:#252836;border-radius:8px;padding:10px;text-align:center">
                    <div style="font-size:11px;color:#6B7280;margin-bottom:4px">STOP</div>
                    <div style="font-weight:700;color:#F87171">{fmt_price(s['stop_loss'])}</div>
                </div>
                <div style="background:#252836;border-radius:8px;padding:10px;text-align:center">
                    <div style="font-size:11px;color:#6B7280;margin-bottom:4px">TARGET</div>
                    <div style="font-weight:700;color:#4ADE80">{fmt_price(s['target'])}</div>
                </div>
            </div>"""

        # News
        news_html = ""
        if ticker_news:
            news_items = ""
            for n in ticker_news:
                url   = n.get('url', '')
                title = n.get('headline', '')
                src   = n.get('source', '')
                t     = fmt_bst(n.get('published_at', ''))
                link  = f'<a href="{url}" target="_blank" style="color:#E2E8F0;text-decoration:none">{title}</a>' if url else title
                news_items += f"""
                <div style="padding:8px 0;border-bottom:1px solid #1E2130">
                    <div style="font-size:13px;line-height:1.4;margin-bottom:4px">{link}</div>
                    <div style="font-size:11px;color:#6B7280">{src} · {t}</div>
                </div>"""
            news_html = f"""
            <div style="margin-top:12px">
                <div style="font-size:12px;font-weight:600;color:#9CA3AF;text-transform:uppercase;
                            letter-spacing:.05em;margin-bottom:8px">Latest News</div>
                {news_items}
            </div>"""

        analysis_cards += f"""
        <div class="acard" data-ticker="{ticker.lower()}">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">
                <div>
                    <span style="font-size:20px;font-weight:700">{ticker}</span>
                    <span style="font-size:12px;color:#6B7280;margin-left:8px">{s.get('sector','')}</span>
                </div>
                <div style="display:flex;align-items:center;gap:8px">
                    {status_badge(s['status'])}
                    <span style="font-size:12px;font-weight:600">{fmt_stability(s['stability_score'])}</span>
                </div>
            </div>
            {f'<div style="font-size:13px;color:#9CA3AF;margin-bottom:4px">Real R/R: <strong style=\"color:#E2E8F0\">{s["real_rr"]:.2f}</strong> &nbsp;·&nbsp; Updated: <span class=\"freshness-{fc}\">{fi} {fmt_bst(s["updated_at"])}</span></div>' if s.get("real_rr") and s["real_rr"] > 0 else ""}
            {scores_html}
            {levels_html}
            {news_html}
        </div>"""

    # ── Market Regime Widget ─────────────────
    regime_data = regime_data or {"regime": "NEUTRAL", "sectors_up": 0, "sectors_dn": 0, "updated_at": "—"}
    r           = regime_data["regime"]
    sectors_up  = regime_data["sectors_up"]
    sectors_dn  = regime_data["sectors_dn"]
    r_color     = {"BULL": "#22C55E", "BEAR": "#EF4444", "NEUTRAL": "#EAB308"}.get(r, "#EAB308")
    r_bg        = {"BULL": "rgba(34,197,94,.06)", "BEAR": "rgba(239,68,68,.06)", "NEUTRAL": "rgba(234,179,8,.06)"}.get(r, "rgba(234,179,8,.06)")
    r_border    = {"BULL": "rgba(34,197,94,.2)", "BEAR": "rgba(239,68,68,.2)", "NEUTRAL": "rgba(234,179,8,.2)"}.get(r, "rgba(234,179,8,.2)")
    r_icon      = {"BULL": "📈", "BEAR": "📉", "NEUTRAL": "〰️"}.get(r, "〰️")
    r_desc      = {
        "BULL":    "7+ sectors advancing. More candidates qualify.",
        "BEAR":    "7+ sectors declining. Only strongest signals pass.",
        "NEUTRAL": "Mixed market. Standard thresholds apply.",
    }.get(r, "")
    r_threshold = {"BULL": "55", "BEAR": "70", "NEUTRAL": "60"}.get(r, "60")

    sector_bar = ""
    if sectors_up or sectors_dn:
        total_sectors = 11
        up_pct   = int((sectors_up / total_sectors) * 100)
        dn_pct   = int((sectors_dn / total_sectors) * 100)
        nt_pct   = 100 - up_pct - dn_pct
        sector_bar = f"""
        <div style="margin-top:10px">
            <div style="font-size:11px;color:#6B7280;margin-bottom:5px">Sector breakdown ({total_sectors} S&P 500 sectors)</div>
            <div style="display:flex;border-radius:4px;overflow:hidden;height:8px;gap:1px">
                <div style="width:{up_pct}%;background:#22C55E;border-radius:4px 0 0 4px"></div>
                <div style="width:{nt_pct}%;background:#374151"></div>
                <div style="width:{dn_pct}%;background:#EF4444;border-radius:0 4px 4px 0"></div>
            </div>
            <div style="display:flex;gap:16px;margin-top:5px;font-size:11px">
                <span style="color:#22C55E">▲ {sectors_up} advancing</span>
                <span style="color:#6B7280">— {total_sectors - sectors_up - sectors_dn} neutral</span>
                <span style="color:#EF4444">▼ {sectors_dn} declining</span>
            </div>
        </div>"""

    regime_html = f"""<div style="background:{r_bg};border:1px solid {r_border};border-radius:10px;
        padding:14px 20px;margin-bottom:16px;display:flex;align-items:center;
        justify-content:space-between;flex-wrap:wrap;gap:12px">
        <div style="display:flex;align-items:center;gap:12px">
            <span style="font-size:28px">{r_icon}</span>
            <div>
                <div style="font-size:12px;color:#6B7280;margin-bottom:2px">Market Regime</div>
                <div style="font-size:20px;font-weight:700;color:{r_color}">{r}</div>
                <div style="font-size:12px;color:#9CA3AF;margin-top:2px">{r_desc}</div>
                {sector_bar}
            </div>
        </div>
        <div style="text-align:right">
            <div style="font-size:11px;color:#6B7280;margin-bottom:4px">Min Stability threshold</div>
            <div style="font-size:22px;font-weight:700;color:{r_color}">{r_threshold}%</div>
            <div style="font-size:11px;color:#6B7280;margin-top:2px">Updated: {regime_data["updated_at"]}</div>
        </div>
    </div>"""

    # ── Build signalsData for JS copyPrompt ──
    reg_script = ""
    for s in top10:
        t  = s['ticker']
        d  = (details or {}).get(t, {})
        sc = d.get('scores', {})
        # Escape strings for safe JS embedding
        sector = (s.get("sector","") or "").replace("\\", "").replace('"', '').replace("'", "")
        status = (s.get("status","") or "").replace("\\", "").replace('"', '').replace("'", "")
        reg_script += (
            f'signalsData["{t}"]={{'
            f'"sector":"{sector}",'
            f'"status":"{status}",'
            f'"stability_score":{float(s.get("stability_score") or 0)},'
            f'"real_rr":{float(s.get("real_rr") or 0)},'
            f'"entry_limit":{float(s.get("entry_limit") or 0)},'
            f'"stop_loss":{float(s.get("stop_loss") or 0)},'
            f'"target":{float(s.get("target") or 0)},'
            f'"tech_score":{float(sc.get("tech_score") or 0)},'
            f'"fund_score":{float(sc.get("fund_score") or 0)},'
            f'"event_score":{float(sc.get("event_score") or 0)},'
            f'"final_score":{float(sc.get("final_score") or 0)}'
            f'}};\n'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="900">
    <title>SwingRadar DSS</title>
    <link rel="icon" type="image/x-icon" href="favicon.ico">
    <link rel="apple-touch-icon" href="apple-touch-icon.png">
    <style>
        :root {{
            --bg:      #0F1117;
            --bg2:     #1A1D27;
            --bg3:     #252836;
            --border:  #2D3148;
            --text:    #E2E8F0;
            --muted:   #6B7280;
            --blue:    #2563EB;
            --green:   #22C55E;
            --yellow:  #EAB308;
            --red:     #EF4444;
            --purple:  #8B5CF6;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: var(--bg);
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            font-size: 14px;
            line-height: 1.5;
        }}

        /* ── NAV ── */
        .navbar {{
            background: var(--bg2);
            border-bottom: 1px solid var(--border);
            padding: 12px 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            position: sticky;
            top: 0;
            z-index: 100;
        }}
        .navbar-left {{
            display: flex;
            align-items: center;
            gap: 16px;
        }}
        .navbar img.logo {{
            height: 36px;
        }}
        .navbar-meta {{
            font-size: 12px;
            color: var(--muted);
        }}
        .navbar-meta a {{
            color: var(--blue);
            text-decoration: none;
            font-weight: 600;
        }}
        .navbar-right {{
            display: flex;
            gap: 8px;
            align-items: center;
            font-size: 12px;
            color: var(--muted);
        }}
        .last-scan {{
            background: var(--bg3);
            padding: 4px 10px;
            border-radius: 6px;
            border: 1px solid var(--border);
        }}

        /* ── TABS ── */
        .tabs {{
            display: flex;
            gap: 4px;
            padding: 16px 24px 0;
            border-bottom: 1px solid var(--border);
        }}
        .tab {{
            padding: 8px 18px;
            cursor: pointer;
            border-radius: 8px 8px 0 0;
            color: var(--muted);
            font-weight: 500;
            border: 1px solid transparent;
            border-bottom: none;
            transition: all 0.15s;
        }}
        .tab:hover {{ color: var(--text); background: var(--bg3); }}
        .tab.active {{
            color: var(--text);
            background: var(--bg2);
            border-color: var(--border);
            border-bottom-color: var(--bg2);
            margin-bottom: -1px;
        }}

        /* ── CONTENT ── */
        .content {{ padding: 24px; }}
        .tab-panel {{ display: none !important; }}
        .tab-panel.active {{ display: block !important; }}

        /* ── STATS ROW ── */
        .stats-row {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
            margin-bottom: 24px;
        }}
        .stat-card {{
            background: var(--bg2);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 16px 20px;
        }}
        .stat-label {{ font-size: 12px; color: var(--muted); margin-bottom: 4px; }}
        .stat-value {{ font-size: 28px; font-weight: 700; color: var(--text); }}

        /* ── TABLES ── */
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }}
        th {{
            background: var(--bg3);
            color: var(--muted);
            font-weight: 600;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            padding: 10px 12px;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }}
        td {{
            padding: 10px 12px;
            border-bottom: 1px solid var(--border);
            vertical-align: middle;
        }}
        tr:last-child td {{ border-bottom: none; }}
        tr:hover td {{ background: var(--bg3); }}
        td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
        td.sector {{ color: var(--muted); font-size: 12px; }}
        td.time {{ color: var(--muted); font-size: 12px; white-space: nowrap; }}
        td.source {{ color: var(--muted); font-size: 12px; }}
        td.headline a {{ color: var(--text); text-decoration: none; }}
        td.headline a:hover {{ color: var(--blue); }}
        td.empty {{ text-align: center; color: var(--muted); padding: 24px; }}
        .rr-time {{ color: var(--muted); font-size: 11px; }}

        /* ── BADGES ── */
        .badge {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
            white-space: nowrap;
        }}
        .badge-confirmed {{ background: rgba(34,197,94,0.15); color: var(--green); }}
        .badge-candidate {{ background: rgba(37,99,235,0.15); color: #60A5FA; }}
        .badge-new        {{ background: rgba(107,114,128,0.15); color: var(--muted); }}

        /* ── FRESHNESS ── */
        .freshness-fresh    {{ color: var(--green); }}
        .freshness-moderate {{ color: var(--yellow); }}
        .freshness-stale    {{ color: var(--red); }}

        /* ── SECTOR BLOCKS ── */
        .sector-block {{
            background: var(--bg2);
            border: 1px solid var(--border);
            border-radius: 10px;
            margin-bottom: 12px;
            overflow: hidden;
        }}
        .sector-header {{
            padding: 12px 16px;
            font-weight: 600;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: space-between;
            user-select: none;
        }}
        .sector-header:hover {{ background: var(--bg3); }}
        .sector-count {{ color: var(--muted); font-weight: 400; margin-left: 6px; }}
        .toggle-icon {{ color: var(--muted); font-size: 10px; }}
        .sector-body {{ overflow-x: auto; }}
        .sector-body.collapsed {{ display: none; }}

        /* ── TOP10 TABLE ── */
        .top10-wrap {{
            background: var(--bg2);
            border: 1px solid var(--border);
            border-radius: 10px;
            overflow: hidden;
            margin-bottom: 24px;
        }}

        /* ── NEWS ── */
        .news-wrap {{
            background: var(--bg2);
            border: 1px solid var(--border);
            border-radius: 10px;
            overflow: hidden;
        }}

        /* ── FOOTER ── */
        footer {{
            text-align: center;
            padding: 20px;
            color: var(--muted);
            font-size: 12px;
            border-top: 1px solid var(--border);
            margin-top: 40px;
        }}
        footer a {{ color: var(--blue); text-decoration: none; font-weight: 600; }}

        /* ── ANALYSIS CARDS ── */
        .acard {{
            background: var(--bg2);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 12px;
        }}
        .acard.hidden {{ display: none; }}
        .analysis-search input:focus {{ border-color: var(--blue); }}

        /* ── AI BUTTONS ── */
        .ai-btns {{ display: flex; gap: 4px; justify-content: center; flex-wrap: wrap; }}
        .ai-btn {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 28px;
            height: 22px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 700;
            text-decoration: none;
            transition: opacity .15s;
        }}
        .ai-btn:hover {{ opacity: .75; }}
        .ai-claude  {{ background: rgba(204,120,92,.2);  color: #CC785C; border: 1px solid rgba(204,120,92,.4); }}
        .ai-chatgpt {{ background: rgba(16,163,127,.2);  color: #10A37F; border: 1px solid rgba(16,163,127,.4); }}
        .ai-gemini  {{ background: rgba(66,133,244,.2);  color: #4285F4; border: 1px solid rgba(66,133,244,.4); }}
        .ai-grok    {{ background: rgba(255,255,255,.1); color: #E2E8F0; border: 1px solid rgba(255,255,255,.2); }}
        .ai-all     {{ background: rgba(139,92,246,.2);  color: #A78BFA; border: 1px solid rgba(139,92,246,.4); width: 32px; }}
        .ai-copy    {{ background: rgba(107,114,128,.15); color: #9CA3AF; border: 1px solid rgba(107,114,128,.3); cursor:pointer; font-size:12px; }}
        .ai-score   {{ font-weight: 700; color: #A78BFA; }}

        /* ── TABLE SCROLL ── */
        .table-wrap {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}

        /* ── MOBILE INFO BAR ── */
        .mobile-info-bar {{
            display: none;
            background: var(--bg2);
            border-bottom: 1px solid var(--border);
            padding: 8px 12px;
            font-size: 12px;
            color: var(--muted);
            text-align: center;
        }}
        @media (max-width: 768px) {{
            .mobile-info-bar {{ display: block; }}
        }}

        /* ── HAMBURGER ── */
        .hamburger {{
            display: none;
            flex-direction: column;
            gap: 5px;
            background: none;
            border: none;
            cursor: pointer;
            padding: 6px;
            margin-left: 8px;
        }}
        .hamburger span {{
            display: block;
            width: 22px;
            height: 2px;
            background: var(--text);
            border-radius: 2px;
            transition: .2s;
        }}

        /* ── MOBILE MENU ── */
        .mobile-menu {{
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,.85);
            z-index: 200;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }}
        .mobile-menu.open {{ display: flex; }}
        .mobile-tab {{
            padding: 14px 16px;
            background: var(--bg2);
            border: 1px solid var(--border);
            border-radius: 10px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            color: var(--text);
        }}
        .mobile-tab:hover {{ background: var(--bg3); }}

        /* ── MARKET STATUS BANNER ── */
        .mkt-banner {{
            margin: 0 12px;
            border-radius: 0;
            padding: 14px 48px 14px 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            position: relative;
            flex-wrap: wrap;
            border-left: none;
            border-right: none;
            border-top: none;
        }}
        .mkt-close-btn {{
            position: absolute;
            top: 8px;
            right: 8px;
            background: none;
            border: none;
            color: #4B5563;
            font-size: 16px;
            cursor: pointer;
            padding: 4px 6px;
            border-radius: 4px;
            line-height: 1;
        }}
        .mkt-close-btn:hover {{ color: #9CA3AF; background: rgba(255,255,255,.05); }}
        .mkt-banner.open   {{ background: rgba(34,197,94,.08);  border: 1px solid rgba(34,197,94,.25); }}
        .mkt-banner.closed {{ background: rgba(234,179,8,.08);  border: 1px solid rgba(234,179,8,.25); }}
        .mkt-banner.pre    {{ background: rgba(37,99,235,.08);  border: 1px solid rgba(37,99,235,.25); }}
        .mkt-banner-left  {{ display:flex; align-items:center; gap:14px; }}
        .mkt-banner-icon  {{ font-size:32px; flex-shrink:0; }}
        .mkt-banner-title {{ font-size:17px; font-weight:700; margin-bottom:3px; }}
        .mkt-banner.open   .mkt-banner-title {{ color:#22C55E; }}
        .mkt-banner.closed .mkt-banner-title {{ color:#EAB308; }}
        .mkt-banner.pre    .mkt-banner-title {{ color:#60A5FA; }}
        .mkt-banner-sub   {{ font-size:13px; color:#6B7280; }}
        .mkt-banner-mid   {{ text-align:center; }}
        .mkt-banner-label {{ font-size:12px; color:#6B7280; margin-bottom:2px; }}
        .mkt-banner-time  {{ font-size:26px; font-weight:700; }}
        .mkt-banner.open   .mkt-banner-time {{ color:#22C55E; }}
        .mkt-banner.closed .mkt-banner-time {{ color:#EAB308; }}
        .mkt-banner.pre    .mkt-banner-time {{ color:#60A5FA; }}
        .mkt-banner-date  {{ font-size:12px; color:#6B7280; }}
        .mkt-banner-right {{ display:flex; align-items:center; gap:12px; }}
        .mkt-dw-box {{
            background: rgba(37,99,235,.15);
            border: 1px solid rgba(37,99,235,.3);
            border-radius: 8px;
            padding: 10px 16px;
            text-align: center;
        }}
        .mkt-dw-label {{ font-size:11px; color:#6B7280; margin-bottom:2px; }}
        .mkt-dw-time  {{ font-size:16px; font-weight:700; color:#60A5FA; }}
        .mkt-dw-sub   {{ font-size:11px; color:#6B7280; margin-top:2px; }}

        @media(max-width:768px) {{
            .mkt-banner {{
                margin: 12px;
                border-radius: 10px !important;
                border: 1px solid;
                flex-direction: column;
                align-items: flex-start;
                padding: 14px 40px 16px 16px;
                gap: 12px;
            }}
            .mkt-banner.open   {{ border-color: rgba(34,197,94,.25); }}
            .mkt-banner.closed {{ border-color: rgba(234,179,8,.25); }}
            .mkt-banner.pre    {{ border-color: rgba(37,99,235,.25); }}
            .mkt-banner-left  {{ flex-direction: row; align-items: center; text-align: left; }}
            .mkt-banner-mid   {{ text-align: center; width: 100%; }}
            .mkt-banner-right {{ width: 100%; display: flex; justify-content: center; }}
            .mkt-dw-box       {{ width: 100%; text-align: center; }}
            .mkt-close-btn    {{ position: absolute; top: 10px; right: 10px; }}
        }}

        /* ── RESPONSIVE ── */
        @media (max-width: 768px) {{
            .stats-row {{ grid-template-columns: repeat(2, 1fr); }}
            .tabs {{ display: none; }}
            .hamburger {{ display: flex; }}
            .navbar {{ padding: 10px 12px; }}
            .navbar-meta {{ display: none; }}
            .last-scan {{ display: none; }}
            .desktop-only {{ display: none !important; }}
            .content {{ padding: 12px; }}
            .stat-card {{ padding: 12px; }}
            .stat-value {{ font-size: 22px; }}
        }}
    </style>
</head>
<body>

<!-- NAVBAR -->
<nav class="navbar">
    <div class="navbar-left">
        <img class="logo" src="SwingRadar-logo.webp" alt="SwingRadar" onerror="this.style.display='none'">
    </div>
    <div class="navbar-right">
        <!-- Hamburger — mobile only -->
        <button class="hamburger" onclick="openMenu()" aria-label="Menu">
            <span></span><span></span><span></span>
        </button>
    </div>
</nav>

<!-- MOBILE INFO BAR -->
<div class="mobile-info-bar">Last scan: {last_scan} &nbsp;·&nbsp; {now}</div>

<!-- MARKET STATUS BANNER -->
<div id="mkt-banner-slot"></div>

<!-- TABS — desktop only -->
<div class="tabs">
    <div class="tab active" onclick="showTab('top10', this)">🏆 Top 10</div>
    <div class="tab" onclick="showTab('sectors', this)">📊 Sectors</div>
    <div class="tab" onclick="showTab('analysis', this)">🔬 Analysis</div>
    <div class="tab" onclick="showTab('news', this)">📰 News</div>
</div>

<!-- CONTENT -->
<div class="content">

    <!-- TOP 10 -->
    <div class="tab-panel active" id="tab-top10">
        <!-- MARKET REGIME WIDGET -->
        {regime_html}

        <div class="stats-row">
            <div class="stat-card">
                <div class="stat-label">Monitored</div>
                <div class="stat-value">{total}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Candidates</div>
                <div class="stat-value" style="color:var(--blue)">{candidates}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Confirmed</div>
                <div class="stat-value" style="color:var(--green)">{confirmed}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Generated</div>
                <div class="stat-value" style="font-size:18px;padding-top:6px">{now[11:]}</div>
            </div>
        </div>
        <div class="top10-wrap">
            <div class="table-wrap"><table>
                <thead><tr>
                    <th>#</th><th>Ticker</th><th>Sector</th><th>Status</th>
                    <th style="text-align:right">Stability</th>
                    <th style="text-align:right">Real R/R</th>
                    <th style="text-align:right">Entry $</th>
                    <th style="text-align:right">Stop Loss</th>
                    <th style="text-align:right">Target</th>
                    <th style="text-align:right">Last Updated</th>
                    <th style="text-align:center">Avg AI</th>
                    <th style="text-align:center">Ask AI</th>
                </tr></thead>
                <tbody>{top10_rows if top10_rows else '<tr><td colspan="10" class="empty">No signals yet.</td></tr>'}</tbody>
            </table></div>
        </div>
    </div>

    <!-- SECTORS -->
    <div class="tab-panel" id="tab-sectors">
        {sector_html if sector_html else '<p style="color:var(--muted);padding:24px">No data available.</p>'}
    </div>

    <!-- ANALYSIS -->
    <div class="tab-panel" id="tab-analysis">
        <div class="analysis-search">
            <input type="text" id="analysisSearch" placeholder="🔍 Search ticker..."
                   oninput="filterAnalysis(this.value)"
                   style="width:100%;max-width:300px;background:#1A1D27;border:1px solid #2D3148;
                          border-radius:8px;color:#E2E8F0;font-size:15px;padding:10px 14px;outline:none;
                          margin-bottom:20px;">
        </div>
        <div id="analysisCards">
            {analysis_cards}
        </div>
    </div>

    <!-- NEWS -->
    <div class="tab-panel" id="tab-news">
        <div class="news-wrap">
            <div class="table-wrap"><table>
                <thead><tr>
                    <th>Ticker</th><th>Source</th><th>Time</th><th>Headline</th>
                </tr></thead>
                <tbody>{news_rows}</tbody>
            </table></div>
        </div>
    </div>

</div>

<!-- FOOTER -->
<footer>
    SwingRadar DSS &nbsp;·&nbsp; V2.44 &nbsp;·&nbsp;
    Built by <a href="https://www.nex41.io" target="_blank">Nex41</a>
    &nbsp;·&nbsp;
    <a href="https://www.nex41.io" target="_blank" style="color:var(--muted)">www.nex41.io</a>
    &nbsp;·&nbsp; NYSE / NASDAQ &nbsp;·&nbsp; ISA Account (UK)
    &nbsp;·&nbsp; Auto-refreshes every 15 minutes
</footer>

<!-- MOBILE MENU OVERLAY -->
<div id="mobileMenu" style="display:none;position:fixed;inset:0;background:rgba(15,17,23,0.98);z-index:9999;flex-direction:column;align-items:stretch;padding:20px;gap:10px;overflow-y:auto;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:15px;">
        <span style="color:#6B7280;font-size:14px;font-weight:600;">SwingRadar DSS</span>
        <span onclick="closeMenu()" style="color:#6B7280;font-size:32px;cursor:pointer;line-height:1;">&#x2715;</span>
    </div>
    <div onclick="switchToTab('top10')" class="mobile-tab">&#127942; Top 10</div>
    <div onclick="switchToTab('sectors')" class="mobile-tab">&#128202; Sectors</div>
    <div onclick="switchToTab('analysis')" class="mobile-tab">&#128300; Analysis</div>
    <div onclick="switchToTab('news')" class="mobile-tab">&#128240; News</div>
    <div style="border-top:1px solid #2D3148;margin:20px 0 10px;"></div>
    <a href="journal.php" class="mobile-tab" style="color:#9CA3AF;text-decoration:none;">&#128218; Trade Journal</a>
    <a href="about.php" class="mobile-tab" style="color:#9CA3AF;text-decoration:none;">&#8505;&#65039; How It Works</a>
    <a href="notifications.php" class="mobile-tab" style="color:#9CA3AF;text-decoration:none;">&#128276; Alerts</a>
    <a href="feedback.php" class="mobile-tab" style="color:#9CA3AF;text-decoration:none;">&#128172; Feedback</a>
    <a href="change_password.php" class="mobile-tab" style="color:#9CA3AF;text-decoration:none;">&#128273; Change Password</a>
    <a href="?logout=1" class="mobile-tab" style="color:#FCA5A5;text-decoration:none;">Logout</a>
</div>

<script>
function copyAndOpenGemini(prompt) {{
    if (navigator.clipboard && navigator.clipboard.writeText) {{
        navigator.clipboard.writeText(prompt).then(function() {{
            window.open('https://gemini.google.com/app', '_blank');
            setTimeout(function() {{
                alert('Prompt copied! Paste it (Cmd+V) into Gemini.');
            }}, 800);
        }}).catch(function() {{
            window.open('https://gemini.google.com/app', '_blank');
        }});
    }} else {{ // closed
        window.open('https://gemini.google.com/app', '_blank');
    }}
}}

// Signal data registry — populated at page generation time
var signalsData = {{}};
{reg_script}

function buildAIPrompt(ticker, s) {{
    return "SwingRadar DSS signal for " + ticker + " (" + (s.sector||"\\u2014") + ")\\n\\n"
        + "Status: " + s.status + " | Stability: " + s.stability_score + "%\\n"
        + "Entry: " + (s.entry_limit ? "$"+Number(s.entry_limit).toFixed(2) : "\\u2014") + " | "
        + "SL: "    + (s.stop_loss  ? "$"+Number(s.stop_loss).toFixed(2)  : "\\u2014") + " | "
        + "Target: "+ (s.target     ? "$"+Number(s.target).toFixed(2)     : "\\u2014") + " | "
        + "R/R: "   + (s.real_rr||"\\u2014") + "\\n"
        + "Scores: Tech " + (s.tech_score||0) + " | Fund " + (s.fund_score||0)
        + " | Event " + (s.event_score||0) + " | Final " + (s.final_score||0) + "\\n\\n"
        + "Please analyse this swing trade setup (attach charts 1W/1D/4H/1H):\\n"
        + "1. Technical assessment\\n"
        + "2. Key risks\\n"
        + "3. Quality score X.X/10 + justification\\n"
        + "4. Would you take this trade? Yes/No + why";
}}

function copyPrompt(ticker) {{
    var s = signalsData[ticker];
    if (!s) {{ alert("No data for " + ticker); return; }}
    var prompt = buildAIPrompt(ticker, s);
    if (navigator.clipboard) {{
        navigator.clipboard.writeText(prompt).then(function() {{
            alert("\u2705 Prompt for " + ticker + " copied! Paste into any AI.");
        }}).catch(function() {{ alert("Copy failed — try another browser"); }});
    }} else {{ // closed
        alert("Clipboard not available in this browser");
    }}
}}

function copyAndOpenGemini(el) {{
    var prompt = el.getAttribute('data-prompt') || '';
    if (navigator.clipboard) {{
        navigator.clipboard.writeText(prompt).then(function() {{
            window.open('https://gemini.google.com/app', '_blank');
            setTimeout(function() {{ alert('Prompt copied! Paste (Cmd+V) into Gemini.'); }}, 800);
        }}).catch(function() {{ window.open('https://gemini.google.com/app', '_blank'); }});
    }} else {{ // closed
        window.open('https://gemini.google.com/app', '_blank');
    }}
}}
function switchToTab(name) {{
    document.querySelectorAll('.tab-panel').forEach(function(p) {{ p.classList.remove('active'); }});
    var panel = document.getElementById('tab-' + name);
    if (panel) panel.classList.add('active');
    document.querySelectorAll('.tab').forEach(function(t) {{
        t.classList.remove('active');
        var oc = t.getAttribute('onclick') || '';
        if (oc.indexOf("'" + name + "'") !== -1) t.classList.add('active');
    }});
    closeMenu();
    window.scrollTo({{top: 0, behavior: 'smooth'}});
}}
function showTab(name, el) {{
    switchToTab(name);
    if (el) el.classList.add('active');
}}
function openMenu() {{ document.getElementById('mobileMenu').style.display = 'flex'; }}
function closeMenu() {{ document.getElementById('mobileMenu').style.display = 'none'; }}
function toggleSector(header) {{
    var body = header.nextElementSibling;
    var icon = header.querySelector('.toggle-icon');
    body.classList.toggle('collapsed');
    icon.textContent = body.classList.contains('collapsed') ? '&#9658;' : '&#9660;';
}}
function filterAnalysis(query) {{
    var q = (query || '').toLowerCase().trim();
    document.querySelectorAll('.acard').forEach(function(card) {{
        var ticker = card.dataset.ticker || '';
        card.classList.toggle('hidden', q !== '' && ticker.indexOf(q) === -1);
    }});
}}
document.getElementById('mobileMenu').addEventListener('click', function(e) {{
    if (e.target.id === 'mobileMenu') closeMenu();
}});
var seconds = 900;
setInterval(function() {{ seconds--; if (seconds <= 0) location.reload(); }}, 1000);

// ── Market Status Banner ──────────────────────────────
function setCookie(name, value, hours) {{
    var d = new Date();
    d.setTime(d.getTime() + hours * 3600000);
    document.cookie = name + "=" + value + ";expires=" + d.toUTCString() + ";path=/";
}}
function getCookie(name) {{
    var n = name + "=";
    var ca = document.cookie.split(';');
    for (var i = 0; i < ca.length; i++) {{
        var c = ca[i].trim();
        if (c.indexOf(n) === 0) return c.substring(n.length, c.length);
    }}
    return "";
}}
function closeBanner(type) {{
    var hours = type === 'closed' ? 12 : 24;
    setCookie('sr_banner_' + type, '1', hours);
    var el = document.getElementById('mkt-banner');
    if (el) el.style.display = 'none';
}}
function getMarketStatus() {{
    // NYSE holidays 2026 (UTC dates)
    var holidays = [
        '2026-01-01','2026-01-19','2026-02-16','2026-04-03',
        '2026-05-25','2026-07-03','2026-09-07','2026-11-26','2026-12-25'
    ];
    var now = new Date();
    var utcH = now.getUTCHours();
    var utcM = now.getUTCMinutes();
    var utcMin = utcH * 60 + utcM;
    var dow = now.getUTCDay(); // 0=Sun, 6=Sat
    var dateStr = now.toISOString().slice(0,10);

    // Weekend or holiday
    if (dow === 0 || dow === 6 || holidays.indexOf(dateStr) !== -1) {{
        return 'closed';
    }}

    // NYSE: 13:30–20:00 UTC (BST: 14:30–21:00)
    // Pre-market: 06:00–13:29 UTC
    // Market open: 13:30–20:00 UTC
    // After hours / closed: 20:00–06:00 UTC
    var open_min  = 13 * 60 + 30;  // 13:30 UTC
    var close_min = 20 * 60;       // 20:00 UTC = 21:00 BST
    var pre_min   =  6 * 60;       //  6:00 UTC

    if (utcMin >= open_min && utcMin < close_min) return 'open';
    if (utcMin >= pre_min  && utcMin < open_min)  return 'pre';
    return 'closed';
}}
function renderMarketBanner() {{
    var mktStatus = getMarketStatus();
    if (getCookie('sr_banner_' + mktStatus) === '1') return;

    var now = new Date();
    var bstOffset = 1; // BST = UTC+1 (summer)
    var bstH = (now.getUTCHours() + bstOffset) % 24;
    var bstM = now.getUTCMinutes();
    var bstStr = String(bstH).padStart(2,'0') + ':' + String(bstM).padStart(2,'0');

    var days = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
    var months = ['January','February','March','April','May','June',
                  'July','August','September','October','November','December'];
    var dateLabel = days[now.getUTCDay()] + ', ' + months[now.getUTCMonth()] + ' ' +
                    now.getUTCDate() + ', ' + now.getUTCFullYear();

    var html = '';
    if (mktStatus === 'open') {{
        html = '<div class="mkt-banner open" id="mkt-banner">'
             + '<div class="mkt-banner-left">'
             + '<div class="mkt-banner-icon">📈</div>'
             + '<div><div class="mkt-banner-title">Market open</div>'
             + '<div class="mkt-banner-sub">We are actively scanning and updating candidates.</div></div></div>'
             + '<div class="mkt-banner-mid">'
             + '<div class="mkt-banner-label">Market will close at (BST)</div>'
             + '<div class="mkt-banner-time">21:00 BST ⏰</div>'
             + '<div class="mkt-banner-date">' + dateLabel + '</div></div>'
             + '<div class="mkt-banner-right">'
             + '<div class="mkt-dw-box"><div class="mkt-dw-label">Decision Window</div>'
             + '<div class="mkt-dw-time">16:30 – 18:00 BST</div>'
             + '<div class="mkt-dw-sub">High-probability trading window</div></div></div>'
             + '<button class="mkt-close-btn" onclick="closeBanner(&apos;open&apos;)" title="Dismiss">✕</button>'
             + '</div>';
    }} else if (mktStatus === 'pre') {{
        html = '<div class="mkt-banner pre" id="mkt-banner">'
             + '<div class="mkt-banner-left">'
             + '<div class="mkt-banner-icon">🕐</div>'
             + '<div><div class="mkt-banner-title">Pre-market time</div>'
             + '<div class="mkt-banner-sub">We are currently in pre-market session.</div></div></div>'
             + '<div class="mkt-banner-mid">'
             + '<div class="mkt-banner-label">NYSE opens at (BST)</div>'
             + '<div class="mkt-banner-time">14:30 BST</div>'
             + '<div class="mkt-banner-date">' + dateLabel + '</div></div>'
             + '<div class="mkt-banner-right">'
             + '<div class="mkt-dw-box"><div class="mkt-dw-label">Decision Window today</div>'
             + '<div class="mkt-dw-time">16:30 – 18:00 BST</div>'
             + '<div class="mkt-dw-sub">Updates every 60 min until open</div></div></div>'
             + '<button class="mkt-close-btn" onclick="closeBanner(&apos;pre&apos;)" title="Dismiss">✕</button>'
             + '</div>';
    }} else {{ // closed
        // Next open day calculation
        var next = new Date(now);
        next.setUTCHours(13, 30, 0, 0);
        if (now.getUTCHours() * 60 + now.getUTCMinutes() >= 20 * 60) {{
            next.setUTCDate(next.getUTCDate() + 1);
        }}
        while (next.getUTCDay() === 0 || next.getUTCDay() === 6) {{
            next.setUTCDate(next.getUTCDate() + 1);
        }}
        var nextH = (13 + bstOffset); // 14:30 BST
        var nextDay = days[next.getUTCDay()];

        html = '<div class="mkt-banner closed" id="mkt-banner">'
             + '<div class="mkt-banner-left">'
             + '<div class="mkt-banner-icon">🔒</div>'
             + '<div><div class="mkt-banner-title">Market closed</div>'
             + '<div class="mkt-banner-sub">We will resume scanning when the market opens.</div></div></div>'
             + '<div class="mkt-banner-mid">'
             + '<div class="mkt-banner-label">Market will open at (BST)</div>'
             + '<div class="mkt-banner-time">14:30 BST</div>'
             + '<div class="mkt-banner-date">' + nextDay + ', ' + months[next.getUTCMonth()] + ' ' + next.getUTCDate() + '</div></div>'
             + '<div class="mkt-banner-right">'
             + '<div class="mkt-dw-box"><div class="mkt-dw-label">Decision Window</div>'
             + '<div class="mkt-dw-time">16:30 – 18:00 BST</div>'
             + '<div class="mkt-dw-sub">Next session: ' + nextDay + '</div></div></div>'
             + '<button class="mkt-close-btn" onclick="closeBanner(&apos;closed&apos;)" title="Dismiss">✕</button>'
             + '</div>';
    }}

    var target = document.getElementById('mkt-banner-slot');
    if (target && html) target.innerHTML = html;
}}
renderMarketBanner();
</script>
</body>
</html>"""


# ══════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════

if __name__ == "__main__":
    from datetime import datetime
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Generating SwingRadar dashboard HTML...")

    scans       = get_scans()
    top10       = get_top10(scans)
    news        = get_news()
    last_scan   = get_regime()
    details     = get_stock_details()
    ai_ratings  = get_ai_ratings()
    regime_data = get_regime_data()
    in_decision = is_decision_window_now()

    html = build_html(scans, top10, news, last_scan, details, ai_ratings, True, regime_data)

    import pathlib
    pathlib.Path(OUTPUT_HTML).parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_HTML, 'w', encoding='utf-8') as f:
        f.write(html)

    size_kb = pathlib.Path(OUTPUT_HTML).stat().st_size // 1024
    print(f"  ✅ HTML generated: {OUTPUT_HTML} ({size_kb} KB)")
    print(f"  📊 Stocks: {len(scans)} | Top10: {len(top10)} | News: {len(news)}")

    if FTP_ENABLED:
        assets = [
            "web/index.php",
            "web/register.php",
            "web/admin.php",
            "web/auth.php",
            "web/journal.php",
            "web/about.php",
            "web/notifications.php",
            "web/alert.php",
            "web/feedback.php",
            "web/change_password.php",
            "web/SwingRadar-logo.webp",
            "web/SwingRadar-icon.webp",
            "web/favicon.ico",
            "web/apple-touch-icon.png",
        ]
        upload_ftp(OUTPUT_HTML, FTP_PATH, assets)
    else:
        print("  ℹ️  FTP disabled — set FTP_USER and FTP_PASS to enable upload")
        print(f"  📁 Local file: {OUTPUT_HTML}")