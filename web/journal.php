<?php
require_once __DIR__ . '/auth.php';
require_login();

$user_id = $_SESSION['user_id'];

// ── Init tables ───────────────────────────
db()->exec("CREATE TABLE IF NOT EXISTS sr_trades (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    user_id       INT NOT NULL,
    ticker        VARCHAR(20) NOT NULL,
    sector        VARCHAR(100),
    trade_type    ENUM('PAPER','REAL') DEFAULT 'PAPER',
    status        ENUM('OPEN','CLOSED') DEFAULT 'OPEN',
    entry_price   DECIMAL(10,4) NOT NULL,
    stop_loss     DECIMAL(10,4),
    target        DECIMAL(10,4),
    exit_price    DECIMAL(10,4),
    shares        INT DEFAULT 1,
    real_rr       DECIMAL(6,2),
    stability     DECIMAL(5,2),
    market_regime VARCHAR(20),
    signal_date   DATE,
    entry_date    DATETIME DEFAULT CURRENT_TIMESTAMP,
    exit_date     DATETIME,
    exit_reason   VARCHAR(50),
    pnl_pct       DECIMAL(8,4),
    mae_pct       DECIMAL(8,4),
    mfe_pct       DECIMAL(8,4),
    notes         TEXT,
    is_public     TINYINT(1) DEFAULT 0,
    INDEX(user_id), INDEX(status), INDEX(ticker)
)");

// ── Handle actions ────────────────────────
$msg = '';
$msg_type = 'success';

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $action = $_POST['action'] ?? '';

    // Open new trade
    if ($action === 'open') {
        $ticker     = strtoupper(trim($_POST['ticker'] ?? ''));
        $entry      = (float)($_POST['entry_price'] ?? 0);
        $sl         = (float)($_POST['stop_loss'] ?? 0);
        $target_p   = (float)($_POST['target'] ?? 0);
        $type       = $_POST['trade_type'] === 'REAL' ? 'REAL' : 'PAPER';
        $shares     = max(1, (int)($_POST['shares'] ?? 1));
        $stability  = (float)($_POST['stability'] ?? 0);
        $rr         = (float)($_POST['real_rr'] ?? 0);
        $regime     = $_POST['market_regime'] ?? 'NEUTRAL';
        $notes      = trim($_POST['notes'] ?? '');
        $sector     = trim($_POST['sector'] ?? '');
        $public     = isset($_POST['is_public']) ? 1 : 0;

        if ($ticker && $entry > 0) {
            db()->prepare("INSERT INTO sr_trades
                (user_id,ticker,sector,trade_type,entry_price,stop_loss,target,shares,
                 stability,real_rr,market_regime,notes,is_public,signal_date)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,CURDATE())")
                ->execute([$user_id,$ticker,$sector,$type,$entry,$sl,$target_p,$shares,
                           $stability,$rr,$regime,$notes,$public]);
            $msg = "✅ Trade opened: {$ticker} @ \${$entry}";
        }
    }

    // Close trade
    if ($action === 'close') {
        $trade_id   = (int)($_POST['trade_id'] ?? 0);
        $exit_price = (float)($_POST['exit_price'] ?? 0);
        $reason     = $_POST['exit_reason'] ?? 'Manual';
        $mae        = (float)($_POST['mae_pct'] ?? 0);
        $mfe        = (float)($_POST['mfe_pct'] ?? 0);

        // Get entry price
        $t = db()->prepare("SELECT entry_price,trade_type,ticker FROM sr_trades WHERE id=? AND user_id=?");
        $t->execute([$trade_id, $user_id]);
        $t = $t->fetch(PDO::FETCH_ASSOC);

        if ($t && $exit_price > 0) {
            $pnl = (($exit_price - $t['entry_price']) / $t['entry_price']) * 100;
            db()->prepare("UPDATE sr_trades SET
                status='CLOSED', exit_price=?, exit_date=NOW(),
                exit_reason=?, pnl_pct=?, mae_pct=?, mfe_pct=?
                WHERE id=? AND user_id=?")
                ->execute([$exit_price, $reason, round($pnl,4), $mae, $mfe, $trade_id, $user_id]);
            $msg = sprintf("%s %s closed | P&L: %+.2f%%", $t['trade_type'], $t['ticker'], $pnl);
            $msg_type = $pnl >= 0 ? 'success' : 'error';
        }
    }

    // Toggle public
    if ($action === 'toggle_public') {
        $trade_id = (int)($_POST['trade_id'] ?? 0);
        db()->prepare("UPDATE sr_trades SET is_public = 1-is_public WHERE id=? AND user_id=?")
            ->execute([$trade_id, $user_id]);
    }

    // Delete trade
    if ($action === 'delete') {
        $trade_id = (int)($_POST['trade_id'] ?? 0);
        db()->prepare("DELETE FROM sr_trades WHERE id=? AND user_id=? AND status='OPEN'")
            ->execute([$trade_id, $user_id]);
        $msg = 'Trade deleted.';
    }
}

// ── Load data ─────────────────────────────
$open_trades = db()->prepare("SELECT * FROM sr_trades WHERE user_id=? AND status='OPEN' ORDER BY entry_date DESC");
$open_trades->execute([$user_id]);
$open_trades = $open_trades->fetchAll(PDO::FETCH_ASSOC);

$closed_trades = db()->prepare("SELECT * FROM sr_trades WHERE user_id=? AND status='CLOSED' ORDER BY exit_date DESC LIMIT 50");
$closed_trades->execute([$user_id]);
$closed_trades = $closed_trades->fetchAll(PDO::FETCH_ASSOC);

// ── Statistics ────────────────────────────
$stats = [];
if (count($closed_trades) >= 2) {
    $pnls    = array_column($closed_trades, 'pnl_pct');
    $winners = array_filter($pnls, fn($p) => $p > 0);
    $losers  = array_filter($pnls, fn($p) => $p <= 0);
    $n       = count($pnls);

    $win_rate  = count($winners) / $n * 100;
    $avg_win   = count($winners) ? array_sum($winners)/count($winners) : 0;
    $avg_loss  = count($losers)  ? abs(array_sum($losers)/count($losers)) : 0.001;
    $total_pnl = array_sum($pnls);

    $gross_win  = array_sum($winners);
    $gross_loss = abs(array_sum($losers)) ?: 0.001;
    $pf         = $gross_win / $gross_loss;

    $expectancy = ($win_rate/100 * $avg_win) - ((1-$win_rate/100) * $avg_loss);

    // Max drawdown
    $cum = 0; $peak = 0; $dd = 0;
    foreach ($pnls as $p) {
        $cum += $p;
        $peak = max($peak, $cum);
        $dd   = min($dd, $cum - $peak);
    }

    // Sharpe (simplified)
    $mean  = array_sum($pnls) / $n;
    $var   = array_sum(array_map(fn($p) => pow($p-$mean,2), $pnls)) / $n;
    $std   = sqrt($var) ?: 0.001;
    $sharpe = $mean / $std * sqrt($n);

    $stats = compact('win_rate','avg_win','avg_loss','total_pnl',
                     'pf','expectancy','dd','sharpe','n');
}

// ── Top 10 signals for auto-fill ─────────
$signals = [];
try {
    // Fetch from dashboard.html signal data if available — fallback to empty
    // In production, this would query the same SQLite via API
    // For now we just show empty select and let user type
} catch(Exception $e) {}

?>
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SwingRadar — Trade Journal</title>
<link rel="icon" href="favicon.ico">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0F1117;color:#E2E8F0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-height:100vh}
.navbar{background:#1A1D27;border-bottom:1px solid #2D3148;padding:12px 24px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100}
.navbar img{height:32px}
.navbar-right{display:flex;gap:8px;align-items:center}
.navbar a{color:#6B7280;text-decoration:none;font-size:13px;padding:6px 14px;background:#252836;border:1px solid #2D3148;border-radius:6px}
.navbar a:hover{color:#E2E8F0}
.content{max-width:1100px;margin:0 auto;padding:24px}
h1{font-size:24px;font-weight:700;margin-bottom:4px}
.subtitle{color:#6B7280;font-size:14px;margin-bottom:24px}
.tabs{display:flex;gap:4px;border-bottom:1px solid #2D3148;margin-bottom:24px}
.tab{padding:8px 18px;cursor:pointer;color:#6B7280;font-weight:500;border-bottom:2px solid transparent;transition:all .15s;background:none;border-top:none;border-left:none;border-right:none;font-size:14px}
.tab.active,.tab:hover{color:#E2E8F0}
.tab.active{border-bottom-color:#2563EB}
.panel{display:none}
.panel.active{display:block}
/* Cards */
.stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px}
.stat-card{background:#1A1D27;border:1px solid #2D3148;border-radius:10px;padding:16px}
.stat-label{font-size:11px;color:#6B7280;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px}
.stat-value{font-size:26px;font-weight:700}
.stat-sub{font-size:12px;color:#6B7280;margin-top:3px}
/* Form */
.form-card{background:#1A1D27;border:1px solid #2D3148;border-radius:10px;padding:24px;margin-bottom:24px}
.form-card h3{font-size:16px;font-weight:600;margin-bottom:20px}
.form-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.form-group{display:flex;flex-direction:column;gap:6px}
.form-group label{font-size:12px;font-weight:600;color:#9CA3AF;text-transform:uppercase;letter-spacing:.05em}
.form-group input,.form-group select,.form-group textarea{background:#0F1117;border:1px solid #2D3148;border-radius:8px;color:#E2E8F0;font-size:14px;padding:9px 12px;outline:none;transition:border-color .15s;font-family:inherit}
.form-group input:focus,.form-group select:focus{border-color:#2563EB}
.form-group select option{background:#1A1D27}
.form-full{grid-column:1/-1}
.btn{padding:10px 20px;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;border:none;transition:all .15s}
.btn-primary{background:#2563EB;color:white}
.btn-primary:hover{background:#1D4ED8}
.btn-success{background:rgba(34,197,94,.15);color:#22C55E;border:1px solid rgba(34,197,94,.3)}
.btn-danger{background:rgba(239,68,68,.15);color:#F87171;border:1px solid rgba(239,68,68,.3)}
.btn-sm{padding:4px 10px;font-size:12px;border-radius:6px}
/* Table */
.table-wrap{background:#1A1D27;border:1px solid #2D3148;border-radius:10px;overflow:hidden;margin-bottom:24px;overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13px}
th{background:#1E2130;color:#6B7280;font-size:11px;text-transform:uppercase;letter-spacing:.05em;padding:10px 12px;text-align:left;border-bottom:1px solid #2D3148;white-space:nowrap}
td{padding:10px 12px;border-bottom:1px solid #1E2130;vertical-align:middle}
tr:last-child td{border-bottom:none}
tr:hover td{background:#1E2130}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600}
.badge-paper{background:rgba(139,92,246,.15);color:#A78BFA}
.badge-real{background:rgba(251,191,36,.15);color:#FCD34D}
.badge-open{background:rgba(37,99,235,.15);color:#60A5FA}
.pnl-pos{color:#22C55E;font-weight:700}
.pnl-neg{color:#F87171;font-weight:700}
/* Msg */
.msg{padding:10px 16px;border-radius:8px;font-size:13px;margin-bottom:16px}
.msg.success{background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.3);color:#86EFAC}
.msg.error{background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.3);color:#FCA5A5}
.empty{text-align:center;color:#6B7280;padding:32px}
/* Close form */
.close-form{background:#0F1117;border-top:1px solid #2D3148;padding:12px 16px;display:none}
.close-form.open{display:block}
.close-grid{display:grid;grid-template-columns:repeat(4,1fr) auto;gap:8px;align-items:end}
/* Toggle */
.type-toggle{display:flex;gap:4px}
.type-btn{padding:8px 16px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;border:1px solid #2D3148;background:#0F1117;color:#6B7280;transition:all .15s}
.type-btn.active-paper{background:rgba(139,92,246,.15);color:#A78BFA;border-color:rgba(139,92,246,.4)}
.type-btn.active-real{background:rgba(251,191,36,.15);color:#FCD34D;border-color:rgba(251,191,36,.4)}
@media(max-width:768px){
    .stats-grid{grid-template-columns:repeat(2,1fr)}
    .form-grid{grid-template-columns:1fr}
    .content{padding:16px}
    .close-grid{grid-template-columns:1fr 1fr}
}
</style>
</head>
<body>

<nav class="navbar">
    <img src="SwingRadar-logo.webp" alt="SwingRadar" onerror="this.style.display='none'">
    <div class="navbar-right">
        <a href="index.php">← Dashboard</a>
    </div>
</nav>

<div class="content">
    <h1>📈 Trade Journal</h1>
    <div class="subtitle">Track your paper and real trades. Private by default.</div>

    <?php if ($msg): ?>
        <div class="msg <?= $msg_type ?>"><?= htmlspecialchars($msg) ?></div>
    <?php endif; ?>

    <!-- TABS -->
    <div class="tabs">
        <button class="tab active" onclick="switchTab('open')">📂 Open (<?= count($open_trades) ?>)</button>
        <button class="tab" onclick="switchTab('new')">➕ New Trade</button>
        <button class="tab" onclick="switchTab('closed')">✅ Closed (<?= count($closed_trades) ?>)</button>
        <button class="tab" onclick="switchTab('stats')">📊 Statistics</button>
    </div>

    <!-- OPEN TRADES -->
    <div class="panel active" id="panel-open">
        <?php if (empty($open_trades)): ?>
            <div class="table-wrap"><p class="empty">No open trades. Open your first trade using the ➕ New Trade tab.</p></div>
        <?php else: ?>
        <div class="table-wrap">
            <table>
                <thead><tr>
                    <th>Ticker</th><th>Type</th><th>Entry</th><th>Stop Loss</th>
                    <th>Target</th><th>R/R</th><th>Stab%</th><th>Regime</th>
                    <th>Opened</th><th>Notes</th><th>Actions</th>
                </tr></thead>
                <tbody>
                <?php foreach ($open_trades as $t): ?>
                <tr>
                    <td><strong><?= htmlspecialchars($t['ticker']) ?></strong>
                        <?php if ($t['sector']): ?>
                        <br><span style="font-size:11px;color:#6B7280"><?= htmlspecialchars($t['sector']) ?></span>
                        <?php endif; ?>
                    </td>
                    <td><span class="badge badge-<?= strtolower($t['trade_type']) ?>"><?= $t['trade_type'] ?></span></td>
                    <td style="color:#60A5FA;font-weight:600">$<?= number_format($t['entry_price'],2) ?></td>
                    <td style="color:#F87171">$<?= $t['stop_loss'] ? number_format($t['stop_loss'],2) : '—' ?></td>
                    <td style="color:#4ADE80">$<?= $t['target'] ? number_format($t['target'],2) : '—' ?></td>
                    <td><?= $t['real_rr'] ? number_format($t['real_rr'],2) : '—' ?></td>
                    <td><?= $t['stability'] ? number_format($t['stability'],1).'%' : '—' ?></td>
                    <td style="font-size:12px;color:#6B7280"><?= htmlspecialchars($t['market_regime'] ?? '—') ?></td>
                    <td style="font-size:12px;color:#6B7280;white-space:nowrap"><?= substr($t['entry_date'],0,10) ?></td>
                    <td style="font-size:12px;color:#6B7280;max-width:150px"><?= htmlspecialchars(substr($t['notes']??'',0,40)) ?></td>
                    <td>
                        <button class="btn btn-success btn-sm" onclick="toggleClose(<?= $t['id'] ?>)">Close</button>
                        <form method="POST" style="display:inline" onsubmit="return confirm('Delete?')">
                            <input type="hidden" name="action" value="delete">
                            <input type="hidden" name="trade_id" value="<?= $t['id'] ?>">
                            <button type="submit" class="btn btn-danger btn-sm">✕</button>
                        </form>
                    </td>
                </tr>
                <!-- Close form row -->
                <tr id="close-row-<?= $t['id'] ?>" style="display:none;background:#0F1117">
                    <td colspan="11" style="padding:0">
                    <form method="POST" style="padding:16px;display:grid;grid-template-columns:repeat(5,1fr) auto;gap:10px;align-items:end">
                        <input type="hidden" name="action" value="close">
                        <input type="hidden" name="trade_id" value="<?= $t['id'] ?>">
                        <div>
                            <label style="font-size:11px;color:#6B7280;display:block;margin-bottom:4px">Exit Price</label>
                            <input type="number" name="exit_price" step="0.01" placeholder="$0.00" required
                                   style="width:100%;background:#1A1D27;border:1px solid #2D3148;border-radius:6px;color:#E2E8F0;padding:7px 10px;font-size:13px">
                        </div>
                        <div>
                            <label style="font-size:11px;color:#6B7280;display:block;margin-bottom:4px">Reason</label>
                            <select name="exit_reason" style="width:100%;background:#1A1D27;border:1px solid #2D3148;border-radius:6px;color:#E2E8F0;padding:7px 10px;font-size:13px">
                                <option>Target Hit</option>
                                <option>Stop Hit</option>
                                <option>Manual</option>
                                <option>Time Exit</option>
                            </select>
                        </div>
                        <div>
                            <label style="font-size:11px;color:#6B7280;display:block;margin-bottom:4px">MAE %</label>
                            <input type="number" name="mae_pct" step="0.01" placeholder="-2.5"
                                   style="width:100%;background:#1A1D27;border:1px solid #2D3148;border-radius:6px;color:#E2E8F0;padding:7px 10px;font-size:13px">
                        </div>
                        <div>
                            <label style="font-size:11px;color:#6B7280;display:block;margin-bottom:4px">MFE %</label>
                            <input type="number" name="mfe_pct" step="0.01" placeholder="5.2"
                                   style="width:100%;background:#1A1D27;border:1px solid #2D3148;border-radius:6px;color:#E2E8F0;padding:7px 10px;font-size:13px">
                        </div>
                        <div style="display:flex;gap:8px;align-items:flex-end">
                            <button type="submit" class="btn btn-primary" style="white-space:nowrap">💾 Close Trade</button>
                            <button type="button" class="btn btn-danger" onclick="toggleClose(<?= $t['id'] ?>)">Cancel</button>
                        </div>
                    </form>
                    </td>
                </tr>
                <?php endforeach; ?>
                </tbody>
            </table>
        </div>
        <?php endif; ?>
    </div>

    <!-- NEW TRADE -->
    <div class="panel" id="panel-new">
        <div class="form-card">
            <h3>Open New Trade</h3>
            <form method="POST">
                <input type="hidden" name="action" value="open">
                <div class="form-grid">
                    <div class="form-group">
                        <label>Ticker *</label>
                        <input type="text" name="ticker" placeholder="e.g. AAPL" required
                               style="text-transform:uppercase" oninput="this.value=this.value.toUpperCase()">
                    </div>
                    <div class="form-group">
                        <label>Sector</label>
                        <input type="text" name="sector" placeholder="e.g. Mega-cap Tech">
                    </div>
                    <div class="form-group">
                        <label>Trade Type</label>
                        <select name="trade_type">
                            <option value="PAPER">📝 Paper Trade</option>
                            <option value="REAL">💰 Real Trade</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Entry Price ($) *</label>
                        <input type="number" name="entry_price" step="0.01" placeholder="0.00" required>
                    </div>
                    <div class="form-group">
                        <label>Stop Loss ($)</label>
                        <input type="number" name="stop_loss" step="0.01" placeholder="0.00">
                    </div>
                    <div class="form-group">
                        <label>Target ($)</label>
                        <input type="number" name="target" step="0.01" placeholder="0.00">
                    </div>
                    <div class="form-group">
                        <label>Real R/R</label>
                        <input type="number" name="real_rr" step="0.01" placeholder="2.10">
                    </div>
                    <div class="form-group">
                        <label>Stability Score (%)</label>
                        <input type="number" name="stability" step="0.1" placeholder="85.0">
                    </div>
                    <div class="form-group">
                        <label>Market Regime</label>
                        <select name="market_regime">
                            <option>NEUTRAL</option>
                            <option>BULL</option>
                            <option>BEAR</option>
                        </select>
                    </div>
                    <div class="form-group form-full">
                        <label>Notes (optional)</label>
                        <textarea name="notes" rows="2" placeholder="Why are you taking this trade?"></textarea>
                    </div>
                    <div class="form-group" style="flex-direction:row;align-items:center;gap:10px">
                        <input type="checkbox" name="is_public" id="is_public" style="width:auto">
                        <label for="is_public" style="text-transform:none;letter-spacing:0;font-size:13px;color:#9CA3AF">
                            Make this trade public (visible to other users)
                        </label>
                    </div>
                </div>
                <div style="margin-top:20px">
                    <button type="submit" class="btn btn-primary">📂 Open Trade</button>
                </div>
            </form>
        </div>
    </div>

    <!-- CLOSED TRADES -->
    <div class="panel" id="panel-closed">
        <?php if (empty($closed_trades)): ?>
            <div class="table-wrap"><p class="empty">No closed trades yet.</p></div>
        <?php else: ?>
        <div class="table-wrap">
            <table>
                <thead><tr>
                    <th>Ticker</th><th>Type</th><th>Entry</th><th>Exit</th>
                    <th>P&L %</th><th>R/R</th><th>Stab%</th>
                    <th>Reason</th><th>MAE%</th><th>MFE%</th>
                    <th>Opened</th><th>Closed</th><th>Public</th>
                </tr></thead>
                <tbody>
                <?php foreach ($closed_trades as $t):
                    $pnl = (float)$t['pnl_pct'];
                    $pnl_class = $pnl >= 0 ? 'pnl-pos' : 'pnl-neg';
                    $pnl_str = sprintf('%+.2f%%', $pnl);
                ?>
                <tr>
                    <td><strong><?= htmlspecialchars($t['ticker']) ?></strong></td>
                    <td><span class="badge badge-<?= strtolower($t['trade_type']) ?>"><?= $t['trade_type'] ?></span></td>
                    <td style="color:#60A5FA">$<?= number_format($t['entry_price'],2) ?></td>
                    <td>$<?= number_format($t['exit_price'],2) ?></td>
                    <td class="<?= $pnl_class ?>"><?= $pnl_str ?></td>
                    <td><?= $t['real_rr'] ? number_format($t['real_rr'],2) : '—' ?></td>
                    <td><?= $t['stability'] ? number_format($t['stability'],1).'%' : '—' ?></td>
                    <td style="font-size:12px;color:#6B7280"><?= htmlspecialchars($t['exit_reason']??'—') ?></td>
                    <td style="color:#F87171;font-size:12px"><?= $t['mae_pct'] ? number_format($t['mae_pct'],2).'%' : '—' ?></td>
                    <td style="color:#4ADE80;font-size:12px"><?= $t['mfe_pct'] ? number_format($t['mfe_pct'],2).'%' : '—' ?></td>
                    <td style="font-size:12px;color:#6B7280"><?= substr($t['entry_date'],0,10) ?></td>
                    <td style="font-size:12px;color:#6B7280"><?= substr($t['exit_date']??'',0,10) ?></td>
                    <td style="white-space:nowrap">
                        <form method="POST" style="display:inline">
                            <input type="hidden" name="action" value="toggle_public">
                            <input type="hidden" name="trade_id" value="<?= $t['id'] ?>">
                            <button type="submit" class="btn btn-sm" style="background:none;border:1px solid #2D3148;color:#6B7280;cursor:pointer"
                                    title="Toggle public">
                                <?= $t['is_public'] ? '🌐' : '🔒' ?>
                            </button>
                        </form>
                        <?php if ($t['is_public'] && $t['exit_price']): ?>
                        <button onclick="shareOnX(
                            '<?= $t['ticker'] ?>',
                            '<?= $t['entry_price'] ?>',
                            '<?= $t['exit_price'] ?>',
                            '<?= $t['pnl_pct'] ?>',
                            '<?= $t['real_rr'] ?? 0 ?>',
                            '<?= $t['stability'] ?? 0 ?>'
                        )" class="btn btn-sm" style="background:rgba(0,0,0,.3);border:1px solid #333;color:#E2E8F0;cursor:pointer;margin-left:4px"
                           title="Share on X">𝕏</button>
                        <?php endif; ?>
                    </td>
                </tr>
                <?php endforeach; ?>
                </tbody>
            </table>
        </div>
        <?php endif; ?>
    </div>

    <!-- STATISTICS -->
    <div class="panel" id="panel-stats">
        <?php if (count($closed_trades) < 2): ?>
            <div class="table-wrap">
                <p class="empty">At least 2 closed trades required for statistics.</p>
            </div>
        <?php else: ?>

        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">Total Trades</div>
                <div class="stat-value"><?= $stats['n'] ?></div>
                <div class="stat-sub">closed trades</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Win Rate</div>
                <div class="stat-value" style="color:<?= $stats['win_rate'] >= 50 ? '#22C55E' : '#F87171' ?>">
                    <?= number_format($stats['win_rate'],1) ?>%
                </div>
                <div class="stat-sub">Avg win <?= number_format($stats['avg_win'],2) ?>% · Avg loss <?= number_format($stats['avg_loss'],2) ?>%</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Profit Factor</div>
                <div class="stat-value" style="color:<?= $stats['pf'] >= 1.5 ? '#22C55E' : '#EAB308' ?>">
                    <?= number_format($stats['pf'],2) ?>
                </div>
                <div class="stat-sub"><?= $stats['pf'] >= 1.5 ? '✅ Good' : '⚠️ Developing' ?></div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Expectancy</div>
                <div class="stat-value" style="color:<?= $stats['expectancy'] >= 0 ? '#22C55E' : '#F87171' ?>">
                    <?= sprintf('%+.2f', $stats['expectancy']) ?>%
                </div>
                <div class="stat-sub">per trade</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Total P&L</div>
                <div class="stat-value" style="color:<?= $stats['total_pnl'] >= 0 ? '#22C55E' : '#F87171' ?>">
                    <?= sprintf('%+.2f', $stats['total_pnl']) ?>%
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Max Drawdown</div>
                <div class="stat-value" style="color:<?= $stats['dd'] > -20 ? '#EAB308' : '#F87171' ?>">
                    <?= number_format($stats['dd'],2) ?>%
                </div>
                <div class="stat-sub"><?= $stats['dd'] > -20 ? '✅ OK' : '⚠️ High' ?></div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Sharpe Ratio</div>
                <div class="stat-value" style="color:<?= $stats['sharpe'] >= 1 ? '#22C55E' : '#EAB308' ?>">
                    <?= number_format($stats['sharpe'],2) ?>
                </div>
                <div class="stat-sub"><?= $stats['sharpe'] >= 1 ? '✅ Good' : '⚠️ Developing' ?></div>
            </div>
        </div>

        <!-- P&L by regime -->
        <?php
        $by_regime = [];
        foreach ($closed_trades as $t) {
            $r = $t['market_regime'] ?? 'NEUTRAL';
            if (!isset($by_regime[$r])) $by_regime[$r] = ['pnls'=>[],'wins'=>0];
            $by_regime[$r]['pnls'][] = (float)$t['pnl_pct'];
            if ((float)$t['pnl_pct'] > 0) $by_regime[$r]['wins']++;
        }
        if (count($by_regime) > 1):
        ?>
        <div style="background:#1A1D27;border:1px solid #2D3148;border-radius:10px;overflow:hidden;margin-bottom:24px">
            <div style="padding:14px 16px;font-weight:600;border-bottom:1px solid #2D3148">Results by Market Regime</div>
            <table>
                <thead><tr><th>Regime</th><th>Trades</th><th>Win Rate</th><th>Avg P&L</th><th>Total P&L</th></tr></thead>
                <tbody>
                <?php foreach ($by_regime as $regime => $data):
                    $cnt = count($data['pnls']);
                    $wr  = $cnt ? round($data['wins']/$cnt*100,1) : 0;
                    $avg = $cnt ? array_sum($data['pnls'])/$cnt : 0;
                    $tot = array_sum($data['pnls']);
                    $col = $regime==='BULL'?'#22C55E':($regime==='BEAR'?'#F87171':'#EAB308');
                ?>
                <tr>
                    <td><span style="color:<?= $col ?>;font-weight:600"><?= $regime ?></span></td>
                    <td><?= $cnt ?></td>
                    <td><?= $wr ?>%</td>
                    <td class="<?= $avg>=0?'pnl-pos':'pnl-neg' ?>"><?= sprintf('%+.2f',$avg) ?>%</td>
                    <td class="<?= $tot>=0?'pnl-pos':'pnl-neg' ?>"><?= sprintf('%+.2f',$tot) ?>%</td>
                </tr>
                <?php endforeach; ?>
                </tbody>
            </table>
        </div>
        <?php endif; ?>

        <?php endif; ?>

        <?php
        // Best trade — share CTA
        if (!empty($closed_trades)):
            $best = null;
            foreach ($closed_trades as $t) {
                if ($t['is_public'] && (!$best || (float)$t['pnl_pct'] > (float)$best['pnl_pct'])) {
                    $best = $t;
                }
            }
            if ($best && (float)$best['pnl_pct'] > 0):
        ?>
        <div style="background:rgba(37,99,235,.08);border:1px solid rgba(37,99,235,.2);
            border-radius:10px;padding:16px 20px;display:flex;align-items:center;
            justify-content:space-between;flex-wrap:wrap;gap:12px">
            <div>
                <div style="font-size:13px;font-weight:600;color:#E2E8F0;margin-bottom:2px">
                    🏆 Your best public trade: <strong><?= $best['ticker'] ?></strong>
                    <span style="color:#22C55E"><?= sprintf('%+.2f', $best['pnl_pct']) ?>%</span>
                </div>
                <div style="font-size:12px;color:#6B7280">Share it and help others discover SwingRadar</div>
            </div>
            <button onclick="shareOnX(
                '<?= $best['ticker'] ?>',
                '<?= $best['entry_price'] ?>',
                '<?= $best['exit_price'] ?>',
                '<?= $best['pnl_pct'] ?>',
                '<?= $best['real_rr'] ?? 0 ?>',
                '<?= $best['stability'] ?? 0 ?>'
            )" style="background:#000;color:white;border:none;border-radius:8px;
                      padding:10px 20px;font-size:14px;font-weight:600;cursor:pointer">
                𝕏 Share on X
            </button>
        </div>
        <?php endif; endif; ?>
    </div>

</div><!-- /content -->

<script>
function switchTab(name) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    document.getElementById('panel-' + name).classList.add('active');
    event.target.classList.add('active');
}
function toggleClose(id) {
    var row = document.getElementById('close-row-' + id);
    row.style.display = row.style.display === 'none' ? 'table-row' : 'none';
}

function shareOnX(ticker, entry, exit, pnl, rr, stability) {
    var pnlStr  = (pnl >= 0 ? '+' : '') + parseFloat(pnl).toFixed(2);
    var emoji   = pnl >= 10 ? '🚀' : pnl >= 5 ? '🔥' : pnl >= 0 ? '✅' : '📉';
    var text    = emoji + ' Just closed ' + ticker + ' swing trade\n'
                + 'Entry: $' + parseFloat(entry).toFixed(2)
                + ' → Exit: $' + parseFloat(exit).toFixed(2)
                + ' (' + pnlStr + '%)\n'
                + 'R/R ' + parseFloat(rr).toFixed(2)
                + ' | Stability ' + parseFloat(stability).toFixed(1) + '%\n'
                + 'Signal by @SwingRadarDSS 📡\n'
                + '#SwingTrading #SwingRadar #StockMarket';
    var url     = 'https://x.com/intent/tweet?text=' + encodeURIComponent(text)
                + '&url=' + encodeURIComponent('https://nex41.io/swingradar/');
    window.open(url, '_blank', 'width=600,height=400');
}
</script>
</body>
</html>
