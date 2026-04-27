<?php
require_once __DIR__ . '/auth.php';
require_login();
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SwingRadar — How It Works</title>
    <link rel="icon" href="favicon.ico">
    <style>
        *{box-sizing:border-box;margin:0;padding:0}
        body{background:#0F1117;color:#E2E8F0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.7}
        .navbar{background:#1A1D27;border-bottom:1px solid #2D3148;padding:12px 24px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100}
        .navbar img{height:32px}
        .navbar a{color:#6B7280;text-decoration:none;font-size:13px;padding:6px 14px;background:#252836;border:1px solid #2D3148;border-radius:6px}
        .navbar a:hover{color:#E2E8F0}
        .hero{text-align:center;padding:64px 24px 48px;max-width:760px;margin:0 auto}
        .hero img{height:70px;margin-bottom:20px}
        .hero h1{font-size:36px;font-weight:700;margin-bottom:12px;background:linear-gradient(135deg,#2563EB,#8B5CF6);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
        .hero p{font-size:17px;color:#9CA3AF;max-width:600px;margin:0 auto}
        .content{max-width:820px;margin:0 auto;padding:0 24px 80px}
        h2{font-size:22px;font-weight:700;color:#E2E8F0;margin:48px 0 12px;padding-bottom:8px;border-bottom:1px solid #2D3148}
        h3{font-size:16px;font-weight:600;color:#60A5FA;margin:24px 0 8px}
        p{color:#9CA3AF;margin-bottom:12px;font-size:15px}
        .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin:20px 0}
        .card{background:#1A1D27;border:1px solid #2D3148;border-radius:10px;padding:20px}
        .card .icon{font-size:28px;margin-bottom:10px}
        .card .title{font-size:14px;font-weight:700;color:#E2E8F0;margin-bottom:6px}
        .card .desc{font-size:13px;color:#6B7280;line-height:1.5}
        .timeline{margin:20px 0}
        .step{display:flex;gap:16px;margin-bottom:20px}
        .step-num{width:32px;height:32px;border-radius:50%;background:#2563EB;color:white;font-weight:700;font-size:14px;display:flex;align-items:center;justify-content:center;flex-shrink:0;margin-top:2px}
        .step-body .title{font-size:15px;font-weight:600;color:#E2E8F0;margin-bottom:4px}
        .step-body .desc{font-size:14px;color:#6B7280}
        table{width:100%;border-collapse:collapse;margin:16px 0}
        th{background:#1E2130;color:#6B7280;font-size:11px;text-transform:uppercase;letter-spacing:.05em;padding:10px 12px;text-align:left;border-bottom:1px solid #2D3148}
        td{padding:10px 12px;border-bottom:1px solid #1E2130;font-size:14px;color:#9CA3AF}
        td strong{color:#E2E8F0}
        tr:hover td{background:#1A1D27}
        .badge{display:inline-block;padding:2px 10px;border-radius:20px;font-size:12px;font-weight:600}
        .badge-blue{background:rgba(37,99,235,.15);color:#60A5FA}
        .badge-green{background:rgba(34,197,94,.15);color:#4ADE80}
        .badge-gray{background:rgba(107,114,128,.15);color:#9CA3AF}
        .highlight{background:#1A1D27;border:1px solid #2D3148;border-left:3px solid #2563EB;border-radius:8px;padding:16px 20px;margin:16px 0}
        .highlight p{margin:0;font-size:14px}
        .window-box{background:#1A1D27;border:1px solid #F59E0B;border-radius:10px;padding:20px 24px;margin:16px 0}
        .window-box .wtime{font-size:22px;font-weight:700;color:#F59E0B;margin-bottom:6px}
        .window-box p{margin:0;font-size:14px}
        footer{text-align:center;padding:24px;color:#4B5563;font-size:12px;border-top:1px solid #1E2130}
        footer a{color:#2563EB;text-decoration:none}
        @media(max-width:600px){.hero h1{font-size:26px}.cards{grid-template-columns:1fr}}
    </style>
</head>
<body>

<nav class="navbar">
    <img src="SwingRadar-logo.webp" alt="SwingRadar" onerror="this.style.display='none'">
    <a href="index.php">← Back to Dashboard</a>
</nav>

<div class="hero">
    <img src="SwingRadar-logo.webp" alt="SwingRadar" onerror="this.style.display='none'">
    <h1>How SwingRadar Works</h1>
    <p>SwingRadar is your daily edge in the US market.<br>Every 15 minutes, it analyses over 150 stocks on NYSE and NASDAQ and surfaces only the swing trade setups with the strongest case — so you spend your time deciding, not searching.</p>
</div>

<div class="content">

    <!-- WHAT IS IT -->
    <h2>What Is SwingRadar?</h2>
    <p>SwingRadar is <strong>not a trading bot</strong>. It does not place orders, manage positions, or make decisions on your behalf. It is a <strong>Decision Support System (DSS)</strong> — an automated research engine that monitors 150+ stocks continuously during market hours, scores them across multiple dimensions, and presents a ranked shortlist of the best setups.</p>
    <p>You make the final call — SwingRadar just delivers the best candidates. Every order is placed manually by you.</p>

    <div class="cards">
        <div class="card"><div class="icon">🔍</div><div class="title">Scans Broadly</div><div class="desc">150+ stocks across NYSE and NASDAQ, refreshed every 15 minutes during market hours.</div></div>
        <div class="card"><div class="icon">🛡️</div><div class="title">Filters Aggressively</div><div class="desc">Hard rules eliminate low-quality candidates before any scoring occurs.</div></div>
        <div class="card"><div class="icon">📊</div><div class="title">Scores Rigorously</div><div class="desc">Three independent dimensions — Technical, Fundamental, Event — combined into a Final Score.</div></div>
        <div class="card"><div class="icon">✅</div><div class="title">Confirms Patiently</div><div class="desc">A signal must stay strong across multiple scans before it becomes actionable.</div></div>
    </div>

    <!-- WHO IS IT FOR -->
    <h2>Who Is It For?</h2>
    <div class="cards">
        <div class="card"><div class="icon">📈</div><div class="title">Swing traders</div><div class="desc">You trade US stocks and look for setups lasting days to weeks. You want a structured, repeatable process — not gut feeling.</div></div>
        <div class="card"><div class="icon">⏱️</div><div class="title">Busy investors</div><div class="desc">You don't have 8 hours to watch charts. SwingRadar does the scanning — you review the shortlist in the 90-minute decision window.</div></div>
        <div class="card"><div class="icon">🤖</div><div class="title">AI-assisted traders</div><div class="desc">You want a second opinion before committing. SwingRadar feeds structured signal data directly into Claude, ChatGPT, Gemini or Grok with one click.</div></div>
    </div>

    <!-- HOW IT SCANS -->
    <h2>How It Scans</h2>
    <p>Every 15 minutes during the NYSE session, SwingRadar runs through a four-stage pipeline:</p>


    <div style="margin:24px 0;overflow-x:auto">
    <svg width="100%" viewBox="0 0 680 520" role="img" style="max-width:680px">
    <title>SwingRadar 4-stage scan pipeline</title>
    <defs><marker id="a1" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></marker></defs>
    <rect x="200" y="30" width="280" height="72" rx="8" fill="#E6F1FB" stroke="#185FA5" stroke-width="0.5"/>
    <text font-family="sans-serif" font-size="14" font-weight="500" x="340" y="62" text-anchor="middle" fill="#0C447C">1 · Universe construction</text>
    <text font-family="sans-serif" font-size="12" x="340" y="82" text-anchor="middle" fill="#185FA5">127 watchlist + 20 dynamic stocks ≈ 150 total</text>
    <line x1="340" y1="102" x2="340" y2="138" stroke="#888" stroke-width="1" marker-end="url(#a1)"/>
    <rect x="200" y="140" width="280" height="72" rx="8" fill="#FCEBEB" stroke="#A32D2D" stroke-width="0.5"/>
    <text font-family="sans-serif" font-size="14" font-weight="500" x="340" y="172" text-anchor="middle" fill="#791F1F">2 · Hard filters</text>
    <text font-family="sans-serif" font-size="12" x="340" y="192" text-anchor="middle" fill="#A32D2D">Volume, price, earnings veto, gap rules</text>
    <line x1="480" y1="176" x2="555" y2="176" stroke="#E24B4A" stroke-width="0.5" stroke-dasharray="4 3" marker-end="url(#a1)"/>
    <text font-family="sans-serif" font-size="12" x="564" y="172" fill="#A32D2D">Rejected</text>
    <text font-family="sans-serif" font-size="12" x="564" y="186" fill="#A32D2D">immediately</text>
    <line x1="340" y1="212" x2="340" y2="248" stroke="#888" stroke-width="1" marker-end="url(#a1)"/>
    <rect x="200" y="250" width="280" height="72" rx="8" fill="#E1F5EE" stroke="#0F6E56" stroke-width="0.5"/>
    <text font-family="sans-serif" font-size="14" font-weight="500" x="340" y="282" text-anchor="middle" fill="#085041">3 · Multi-dimensional scoring</text>
    <text font-family="sans-serif" font-size="12" x="340" y="302" text-anchor="middle" fill="#0F6E56">Technical 50% · Fundamental 30% · Event 20%</text>
    <line x1="340" y1="322" x2="340" y2="358" stroke="#888" stroke-width="1" marker-end="url(#a1)"/>
    <rect x="200" y="360" width="280" height="72" rx="8" fill="#EEEDFE" stroke="#534AB7" stroke-width="0.5"/>
    <text font-family="sans-serif" font-size="14" font-weight="500" x="340" y="392" text-anchor="middle" fill="#3C3489">4 · Signal lifecycle tracking</text>
    <text font-family="sans-serif" font-size="12" x="340" y="412" text-anchor="middle" fill="#534AB7">Must stay strong across ≥3 scans (45 min)</text>
    <line x1="340" y1="432" x2="340" y2="458" stroke="#888" stroke-width="1" marker-end="url(#a1)"/>
    <rect x="240" y="460" width="200" height="44" rx="22" fill="#639922" stroke="#3B6D11" stroke-width="0.5"/>
    <text font-family="sans-serif" font-size="14" font-weight="500" x="340" y="487" text-anchor="middle" fill="#EAF3DE">Top 10 signals</text>
    <path d="M200 396 L100 396 L100 66 L200 66" fill="none" stroke="#ccc" stroke-width="0.5" stroke-dasharray="4 3" marker-end="url(#a1)"/>
    <text font-family="sans-serif" font-size="12" x="56" y="230" text-anchor="middle" fill="#999">Every</text>
    <text font-family="sans-serif" font-size="12" x="56" y="245" text-anchor="middle" fill="#999">15 min</text>
    </svg></div>
    <div class="timeline" style="display:none">
        <div class="step">
            <div class="step-num">1</div>
            <div class="step-body">
                <div class="title">Universe Construction</div>
                <div class="desc">Combines a curated watchlist of 127 blue-chip stocks with up to 20 dynamic stocks sourced from today's biggest gainers, most-actives, and a real-time screener (min. $2B market cap, $10–$500 price). Total: ~150 stocks per cycle.</div>
            </div>
        </div>
        <div class="step">
            <div class="step-num">2</div>
            <div class="step-body">
                <div class="title">Hard Filters</div>
                <div class="desc">Dollar volume below $20M, price below $5, earnings within 3 days, micro-float stocks, and gap-down days are all immediately rejected. No exceptions.</div>
            </div>
        </div>
        <div class="step">
            <div class="step-num">3</div>
            <div class="step-body">
                <div class="title">Multi-Dimensional Scoring</div>
                <div class="desc">Every stock that passes filtering is evaluated across Technical (50%), Fundamental (30%), and Event (20%) dimensions. The result is a Final Score from 0 to 100.</div>
            </div>
        </div>
        <div class="step">
            <div class="step-num">4</div>
            <div class="step-body">
                <div class="title">Signal Lifecycle Tracking</div>
                <div class="desc">Scores are tracked over time. A stock must sustain a high score across at least 3 consecutive scans (45 minutes) before it can advance — eliminating one-scan spikes.</div>
            </div>
        </div>
    </div>

    <!-- SCORING -->
    <h2>How Scores Are Calculated</h2>
    <p>The Final Score is a weighted combination of three independent components:</p>

    <table>
        <thead><tr><th>Component</th><th>Weight</th><th>Key Signals</th></tr></thead>
        <tbody>
            <tr><td><strong>Technical Score</strong></td><td>50%</td><td>RSI window (40–70), Relative Volume (RVOL), EMA alignment, 1M / 3M / 5D price momentum, float category</td></tr>
            <tr><td><strong>Fundamental Score</strong></td><td>30%</td><td>ROE, Debt/Equity, EPS growth, Piotroski F-Score, Altman Z-Score, insider buying/selling ratio</td></tr>
            <tr><td><strong>Event / Catalyst Score</strong></td><td>20%</td><td>Analyst price target upside, recent upgrades/downgrades, consensus rating, recent SEC 8-K filings</td></tr>
        </tbody>
    </table>


    <div style="margin:24px 0;overflow-x:auto">
    <svg width="100%" viewBox="0 0 680 340" role="img" style="max-width:680px">
    <title>Scoring model breakdown</title>
    <defs><marker id="a2" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></marker></defs>
    <rect x="30" y="20" width="180" height="220" rx="8" fill="#E6F1FB" stroke="#185FA5" stroke-width="0.5"/>
    <text font-family="sans-serif" font-size="14" font-weight="500" x="120" y="48" text-anchor="middle" fill="#0C447C">Technical</text>
    <text font-family="sans-serif" font-size="22" font-weight="500" x="120" y="72" text-anchor="middle" fill="#185FA5">50%</text>
    <line x1="50" y1="84" x2="190" y2="84" stroke="#B5D4F4" stroke-width="0.5"/>
    <text font-family="sans-serif" font-size="12" x="50" y="104" fill="#185FA5">RSI 40–70 range</text>
    <text font-family="sans-serif" font-size="12" x="50" y="122" fill="#185FA5">Relative volume (RVOL)</text>
    <text font-family="sans-serif" font-size="12" x="50" y="140" fill="#185FA5">EMA 20 alignment</text>
    <text font-family="sans-serif" font-size="12" x="50" y="158" fill="#185FA5">1M / 3M momentum</text>
    <text font-family="sans-serif" font-size="12" x="50" y="176" fill="#185FA5">5D price change</text>
    <text font-family="sans-serif" font-size="12" x="50" y="194" fill="#185FA5">Float category</text>
    <text font-family="sans-serif" font-size="12" x="50" y="212" fill="#185FA5">Gap penalty</text>
    <rect x="250" y="20" width="180" height="220" rx="8" fill="#E1F5EE" stroke="#0F6E56" stroke-width="0.5"/>
    <text font-family="sans-serif" font-size="14" font-weight="500" x="340" y="48" text-anchor="middle" fill="#085041">Fundamental</text>
    <text font-family="sans-serif" font-size="22" font-weight="500" x="340" y="72" text-anchor="middle" fill="#0F6E56">30%</text>
    <line x1="270" y1="84" x2="410" y2="84" stroke="#9FE1CB" stroke-width="0.5"/>
    <text font-family="sans-serif" font-size="12" x="270" y="104" fill="#0F6E56">ROE &gt; 15%</text>
    <text font-family="sans-serif" font-size="12" x="270" y="122" fill="#0F6E56">Debt / Equity ratio</text>
    <text font-family="sans-serif" font-size="12" x="270" y="140" fill="#0F6E56">EPS growth trend</text>
    <text font-family="sans-serif" font-size="12" x="270" y="158" fill="#0F6E56">Piotroski F-Score</text>
    <text font-family="sans-serif" font-size="12" x="270" y="176" fill="#0F6E56">Altman Z-Score</text>
    <text font-family="sans-serif" font-size="12" x="270" y="194" fill="#0F6E56">Insider buying ratio</text>
    <text font-family="sans-serif" font-size="12" x="270" y="212" fill="#E24B4A">Veto rules apply ⚠</text>
    <rect x="470" y="20" width="180" height="220" rx="8" fill="#FAEEDA" stroke="#BA7517" stroke-width="0.5"/>
    <text font-family="sans-serif" font-size="14" font-weight="500" x="560" y="48" text-anchor="middle" fill="#633806">Event / Catalyst</text>
    <text font-family="sans-serif" font-size="22" font-weight="500" x="560" y="72" text-anchor="middle" fill="#BA7517">20%</text>
    <line x1="490" y1="84" x2="630" y2="84" stroke="#FAC775" stroke-width="0.5"/>
    <text font-family="sans-serif" font-size="12" x="490" y="104" fill="#BA7517">Analyst upside %</text>
    <text font-family="sans-serif" font-size="12" x="490" y="122" fill="#BA7517">Recent upgrades</text>
    <text font-family="sans-serif" font-size="12" x="490" y="140" fill="#BA7517">Consensus rating</text>
    <text font-family="sans-serif" font-size="12" x="490" y="158" fill="#BA7517">SEC 8-K filings</text>
    <text font-family="sans-serif" font-size="12" x="490" y="176" fill="#BA7517">Today's % change</text>
    <text font-family="sans-serif" font-size="12" x="490" y="194" fill="#E24B4A">Downgrade penalty</text>
    <line x1="120" y1="240" x2="120" y2="272" stroke="#185FA5" stroke-width="0.5" marker-end="url(#a2)"/>
    <line x1="340" y1="240" x2="340" y2="272" stroke="#0F6E56" stroke-width="0.5" marker-end="url(#a2)"/>
    <line x1="560" y1="240" x2="560" y2="272" stroke="#BA7517" stroke-width="0.5" marker-end="url(#a2)"/>
    <path d="M120 272 Q340 292 560 272" fill="none" stroke="#ccc" stroke-width="0.5"/>
    <rect x="240" y="294" width="200" height="36" rx="18" fill="#534AB7" stroke="#3C3489" stroke-width="0.5"/>
    <text font-family="sans-serif" font-size="14" font-weight="500" x="340" y="317" text-anchor="middle" fill="#EEEDFE">Final Score (0–100)</text>
    </svg></div>
    <div class="highlight">
        <p>Veto rules within the Fundamental dimension can collapse a score to zero regardless of the technical picture — for example, a negative ROE, Piotroski score below 3, or Altman Z-Score in the distress zone.</p>
    </div>

    <!-- SIGNAL STATES -->
    <h2>Signal States</h2>
    <table>
        <thead><tr><th>Status</th><th>Condition</th><th>Meaning</th></tr></thead>
        <tbody>
            <tr>
                <td><span class="badge badge-gray">⚫ NEW</span></td>
                <td>First scan or insufficient history</td>
                <td>Watching — too early to act</td>
            </tr>
            <tr>
                <td><span class="badge badge-blue">🔵 CANDIDATE</span></td>
                <td>Strong score sustained across ≥3 scans, upward trend confirmed</td>
                <td>Building strength — monitor closely. Entry/SL/Target levels are shown.</td>
            </tr>
            <tr>
                <td><span class="badge badge-green">🟢 CONFIRMED</span></td>
                <td>CANDIDATE + inside the Decision Window + RVOL > 1.2 + Real R/R > 2.0</td>
                <td>Actionable signal — all criteria met</td>
            </tr>
        </tbody>
    </table>


    <div style="margin:24px 0;overflow-x:auto">
    <svg width="100%" viewBox="0 0 680 200" role="img" style="max-width:680px">
    <title>Signal lifecycle</title>
    <defs><marker id="a3" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></marker></defs>
    <rect x="30" y="60" width="155" height="80" rx="8" fill="#F1EFE8" stroke="#5F5E5A" stroke-width="0.5"/>
    <text font-family="sans-serif" font-size="18" x="107" y="97" text-anchor="middle" fill="#5F5E5A">⚫</text>
    <text font-family="sans-serif" font-size="14" font-weight="500" x="107" y="118" text-anchor="middle" fill="#444441">NEW</text>
    <text font-family="sans-serif" font-size="12" x="107" y="134" text-anchor="middle" fill="#888780">Watching</text>
    <line x1="185" y1="100" x2="242" y2="100" stroke="#888" stroke-width="1" marker-end="url(#a3)"/>
    <text font-family="sans-serif" font-size="11" x="214" y="90" text-anchor="middle" fill="#999">Score strong</text>
    <text font-family="sans-serif" font-size="11" x="214" y="103" text-anchor="middle" fill="#999">≥3 scans</text>
    <rect x="244" y="60" width="192" height="80" rx="8" fill="#E6F1FB" stroke="#185FA5" stroke-width="0.5"/>
    <text font-family="sans-serif" font-size="18" x="340" y="97" text-anchor="middle" fill="#185FA5">🔵</text>
    <text font-family="sans-serif" font-size="14" font-weight="500" x="340" y="118" text-anchor="middle" fill="#0C447C">CANDIDATE</text>
    <text font-family="sans-serif" font-size="12" x="340" y="134" text-anchor="middle" fill="#185FA5">Monitor closely</text>
    <line x1="436" y1="100" x2="490" y2="100" stroke="#888" stroke-width="1" marker-end="url(#a3)"/>
    <text font-family="sans-serif" font-size="11" x="463" y="84" text-anchor="middle" fill="#999">Decision</text>
    <text font-family="sans-serif" font-size="11" x="463" y="97" text-anchor="middle" fill="#999">window +</text>
    <text font-family="sans-serif" font-size="11" x="463" y="110" text-anchor="middle" fill="#999">RVOL&gt;1.2</text>
    <rect x="492" y="60" width="158" height="80" rx="8" fill="#EAF3DE" stroke="#3B6D11" stroke-width="0.5"/>
    <text font-family="sans-serif" font-size="18" x="571" y="97" text-anchor="middle" fill="#3B6D11">🟢</text>
    <text font-family="sans-serif" font-size="14" font-weight="500" x="571" y="118" text-anchor="middle" fill="#27500A">CONFIRMED</text>
    <text font-family="sans-serif" font-size="12" x="571" y="134" text-anchor="middle" fill="#3B6D11">Actionable</text>
    <path d="M571 140 L571 168 L107 168 L107 140" fill="none" stroke="#E24B4A" stroke-width="0.5" stroke-dasharray="4 3" marker-end="url(#a3)"/>
    <text font-family="sans-serif" font-size="12" x="340" y="164" text-anchor="middle" fill="#A32D2D">Score drops → degrades back automatically</text>
    </svg></div>
    <!-- STABILITY SCORE -->
    <h2>Stability Score</h2>
    <p>Stability Score measures how consistently a stock has been scoring well — not just today, but across its entire scan history. It rewards stocks that build strength gradually and penalises those that spike and fade.</p>
    <p>A Stability Score above 80% means the signal has been strong and consistent across many scans. Above 90% is exceptional. This is the primary ranking column in the Top 10 table.</p>

    <!-- DECISION WINDOW -->
    <h2>The Decision Window</h2>
    <div class="window-box">
        <div class="wtime">⏰ 16:30 – 18:00 BST (UK Summer Time)</div>
        <p>This is the 90-minute window each trading day when CONFIRMED signals are generated and actionable price levels are finalised.</p>
    </div>

<div style="margin:24px 0;overflow-x:auto">
    <svg width="100%" viewBox="0 0 680 160" role="img" style="max-width:680px">
    <title>SwingRadar daily timeline BST</title>
    <rect x="40" y="62" width="600" height="36" rx="6" fill="#1A1D27" stroke="#2D3148" stroke-width="0.5"/>
    <!-- Pre-market -->
    <rect x="40" y="62" width="180" height="36" rx="6" fill="#252836"/>
    <rect x="218" y="62" width="2" height="36" fill="#2D3148"/>
    <!-- NYSE session — full width including under decision window -->
    <rect x="220" y="62" width="420" height="36" fill="#1E3A5F"/>
    <!-- Decision window overlay on top -->
    <rect x="362" y="54" width="120" height="52" rx="6" fill="#BA7517" opacity="0.2" stroke="#BA7517" stroke-width="1.5"/>
    <rect x="362" y="62" width="120" height="36" fill="#F59E0B" opacity="0.2"/>
    <text font-family="sans-serif" font-size="12" font-weight="500" x="130" y="85" text-anchor="middle" fill="#6B7280">Pre-market</text>
    <text font-family="sans-serif" font-size="12" font-weight="500" x="290" y="85" text-anchor="middle" fill="#60A5FA">NYSE session</text>
    <text font-family="sans-serif" font-size="11" font-weight="500" x="422" y="81" text-anchor="middle" fill="#F59E0B">Decision</text>
    <text font-family="sans-serif" font-size="11" font-weight="500" x="422" y="95" text-anchor="middle" fill="#F59E0B">window</text>
    <text font-family="sans-serif" font-size="11" x="40"  y="118" text-anchor="middle" fill="#4B5563">06:00</text>
    <text font-family="sans-serif" font-size="11" x="220" y="118" text-anchor="middle" fill="#4B5563">13:30</text>
    <text font-family="sans-serif" font-size="12" x="362" y="118" text-anchor="middle" fill="#F59E0B">16:30</text>
    <text font-family="sans-serif" font-size="12" x="482" y="118" text-anchor="middle" fill="#F59E0B">18:00</text>
    <text font-family="sans-serif" font-size="11" x="640" y="118" text-anchor="middle" fill="#4B5563">21:00</text>
    <line x1="40"  y1="98"  x2="40"  y2="106" stroke="#374151" stroke-width="1"/>
    <line x1="220" y1="98"  x2="220" y2="106" stroke="#374151" stroke-width="1"/>
    <line x1="362" y1="106" x2="362" y2="114" stroke="#F59E0B" stroke-width="1.5"/>
    <line x1="482" y1="106" x2="482" y2="114" stroke="#F59E0B" stroke-width="1.5"/>
    <line x1="640" y1="98"  x2="640" y2="106" stroke="#374151" stroke-width="1"/>
    <text font-family="sans-serif" font-size="11" x="130" y="50" text-anchor="middle" fill="#4B5563">News · data refresh</text>
    <text font-family="sans-serif" font-size="11" x="284" y="50" text-anchor="middle" fill="#4B5563">Scans every 15 min</text>
    <text font-family="sans-serif" font-size="11" x="422" y="40" text-anchor="middle" fill="#F59E0B">CONFIRMED signals</text>
    <line x1="130" y1="52" x2="130" y2="62" stroke="#374151" stroke-width="0.5" stroke-dasharray="2 2"/>
    <line x1="284" y1="52" x2="284" y2="62" stroke="#374151" stroke-width="0.5" stroke-dasharray="2 2"/>
    <line x1="422" y1="42" x2="422" y2="54" stroke="#F59E0B" stroke-width="0.5" stroke-dasharray="2 2"/>
    <text font-family="sans-serif" font-size="11" x="340" y="148" text-anchor="middle" fill="#374151">All times in BST · British Summer Time (UTC+1)</text>
    </svg></div>
    <p>The window opens approximately 2.5 hours after the NYSE open. By this point, intraday volume patterns have stabilised, Relative Volume is meaningful, and there is still enough session time remaining for a trade to develop. Most CONFIRMED signals appear precisely in this window — when volume and momentum are at their most reliable.</p>
    <p>Outside this window, CANDIDATE signals are visible with indicative Entry/SL/Target levels — but they should be treated as informational only. CONFIRMED status is only assigned during the window.</p>

    <!-- PRICE LEVELS -->
    <h2>Entry, Stop Loss & Target</h2>
    <table>
        <thead><tr><th>Level</th><th>How It's Calculated</th></tr></thead>
        <tbody>
            <tr><td><strong>Entry Limit</strong></td><td>Current price + 0.3% slippage buffer</td></tr>
            <tr><td><strong>Stop Loss</strong></td><td>Entry − 1.5 × ATR(14) — below recent volatility range</td></tr>
            <tr><td><strong>Target</strong></td><td>Analyst median price target, capped at +10% from entry for realistic swing timeframe</td></tr>
            <tr><td><strong>Real R/R</strong></td><td>Reward ÷ Risk, already accounting for UK Stamp Duty (0.5%) and slippage</td></tr>
        </tbody>
    </table>
    <p>A minimum Real R/R of 2.0 is required for CONFIRMED status. Signals below this threshold remain as CANDIDATE regardless of their score.</p>

    <!-- MARKET REGIME -->
    <h2>Market Regime Awareness</h2>
    <p>At the start of every scan, SwingRadar checks how many of the 11 S&P 500 sectors are advancing or declining today. This determines the current market regime:</p>
    <div class="cards">
        <div class="card"><div class="icon">🟢</div><div class="title">BULL</div><div class="desc">7+ sectors advancing. Thresholds are relaxed — more candidates surface.</div></div>
        <div class="card"><div class="icon">🟡</div><div class="title">NEUTRAL</div><div class="desc">Mixed market. Standard thresholds apply.</div></div>
        <div class="card"><div class="icon">🔴</div><div class="title">BEAR</div><div class="desc">7+ sectors declining. Thresholds are raised — only the strongest signals pass.</div></div>
    </div>

    <!-- ASK AI -->
    <h2>Ask AI — How to Use It</h2>
    <p>Every stock in the Top 10 has four AI consultation buttons: <strong>Claude, ChatGPT, Gemini, Grok</strong>. Clicking any of them opens the selected AI with a pre-filled prompt containing the full signal data — scores, entry levels, sector, stability, and a structured request for analysis.</p>

    <div class="highlight">
        <p>The prompt asks the AI to assess the signal quality, identify key risks, and provide a score from <strong>1.0 to 10.0</strong>. After receiving the AI's response, attach your price charts (1W, 1D, 4H, 1H timeframes) for a complete picture. In practice, <strong>Claude + Grok</strong> tend to give the most actionable signal assessments.</p>
    </div>

    <h3>Recommended workflow</h3>
    <div class="timeline">
        <div class="step">
            <div class="step-num">1</div>
            <div class="step-body"><div class="title">Open the Decision Window (16:30 BST)</div><div class="desc">Review the Top 10 table. Focus on CONFIRMED signals first, then strong CANDIDATES.</div></div>
        </div>
        <div class="step">
            <div class="step-num">2</div>
            <div class="step-body"><div class="title">Click Ask AI for your shortlist</div><div class="desc">Send the pre-filled prompt to 2–3 AI assistants. Each receives the full signal context automatically.</div></div>
        </div>
        <div class="step">
            <div class="step-num">3</div>
            <div class="step-body"><div class="title">Attach price charts</div><div class="desc">Share 1W and 1D charts in the AI chat. Add 4H and 1H for entry timing. The AI will incorporate the visual context into its assessment.</div></div>
        </div>
        <div class="step">
            <div class="step-num">4</div>
            <div class="step-body"><div class="title">Record the AI scores</div><div class="desc">Enter the scores from each AI into the rating fields in the Top 10 table. The Avg AI column calculates automatically.</div></div>
        </div>
        <div class="step">
            <div class="step-num">5</div>
            <div class="step-body"><div class="title">Make your decision</div><div class="desc">You have the SwingRadar signal, the AI assessment, and the charts. The final call is yours.</div></div>
        </div>
    </div>

    <!-- AVG AI -->
    <h2>Avg AI Score</h2>
    <p>The <strong>Avg AI</strong> column in the Top 10 table shows the average quality score assigned to each signal by AI assistants — Claude, ChatGPT, Gemini, and Grok — during the current decision window.</p>
    <p>All Top 10 signals are evaluated by AI for analysis quality each session. The score reflects how well the signal holds up under AI scrutiny: strength of the technical setup, fundamental backing, risk/reward quality, and overall conviction. It is not a price prediction — it is an assessment of the signal's analytical quality.</p>

    <table>
        <thead><tr><th>Avg AI Score</th><th>Interpretation</th></tr></thead>
        <tbody>
            <tr><td><strong style="color:#4ADE80">8.0 – 10.0</strong></td><td>High conviction — strong setup across multiple dimensions</td></tr>
            <tr><td><strong style="color:#EAB308">5.0 – 7.9</strong></td><td>Moderate — worth reviewing but proceed with caution</td></tr>
            <tr><td><strong style="color:#F87171">1.0 – 4.9</strong></td><td>Weak — AI sees significant concerns with this setup</td></tr>
        </tbody>
    </table>

    <p>Over time, these scores are used to <strong>calibrate the SwingRadar model</strong> — identifying which scoring components best predict signals that AI consistently rates highly, and adjusting weights accordingly.</p>

    <!-- PRE-MARKET -->
    <h2>Pre-Market Intelligence</h2>
    <p>Before the NYSE opens each morning, SwingRadar runs two preparation tasks:</p>
    <div class="cards">
        <div class="card"><div class="icon">🔄</div><div class="title">Cache Warm-Up</div><div class="desc">Fundamental data, analyst targets, and historical prices for all 127 watchlist stocks are refreshed so the first scan of the day is instant.</div></div>
        <div class="card"><div class="icon">📰</div><div class="title">News Scan</div><div class="desc">The latest headlines for every watchlist stock are collected and stored. Available in the News tab before the open.</div></div>
    </div>

    <!-- DATA FRESHNESS -->
    <h2>Data Freshness Indicator</h2>
    <p>The Last Updated column in the Top 10 table uses a colour indicator to show how recent the data is:</p>
    <div class="cards">
        <div class="card"><div class="icon">🟢</div><div class="title">Fresh (< 1 hour)</div><div class="desc">Data is current. Levels are reliable.</div></div>
        <div class="card"><div class="icon">🟡</div><div class="title">Moderate (1–4 hours)</div><div class="desc">Check if market conditions have changed.</div></div>
        <div class="card"><div class="icon">🔴</div><div class="title">Stale (> 4 hours)</div><div class="desc">Market is likely closed or scanner was offline. Treat levels as indicative only.</div></div>
    </div>

</div>

    <!-- CTA -->
    <div style="text-align:center;padding:48px 0 32px;border-top:1px solid #2D3148;margin-top:48px">
        <p style="font-size:18px;font-weight:600;color:#E2E8F0;margin-bottom:8px">Ready to see it in action?</p>
        <p style="color:#6B7280;margin-bottom:24px">Log in and check today's Top 10 signals.</p>
        <a href="index.php" style="display:inline-block;background:#2563EB;color:white;text-decoration:none;
            padding:12px 32px;border-radius:8px;font-weight:600;font-size:15px;transition:background .15s">
            Go to Dashboard →
        </a>
    </div>
</div>

<footer>
    SwingRadar DSS &nbsp;·&nbsp; Built by <a href="https://www.nex41.io" target="_blank" rel="noopener">Nex41</a>
    &nbsp;·&nbsp; NYSE / NASDAQ &nbsp;·&nbsp; ISA Account (UK)
</footer>

</body>
</html>
