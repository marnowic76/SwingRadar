<?php
require_once __DIR__ . '/auth.php';
require_login();

$success = false;
$error   = '';

// Handle unsubscribe via GET
if (isset($_GET['unsubscribe'])) {
    db()->prepare("UPDATE sr_users SET alerts_enabled = 0 WHERE id = ?")
        ->execute([$_SESSION['user_id']]);
    $success = true;
    $_SESSION['alerts_enabled'] = 0;
}

// Handle form POST
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $enabled = isset($_POST['alerts_enabled']) ? 1 : 0;
    db()->prepare("UPDATE sr_users SET alerts_enabled = ? WHERE id = ?")
        ->execute([$enabled, $_SESSION['user_id']]);
    $_SESSION['alerts_enabled'] = $enabled;
    $success = true;
}

// Get current setting
$user = db()->prepare("SELECT alerts_enabled, email, name FROM sr_users WHERE id = ?");
$user->execute([$_SESSION['user_id']]);
$user = $user->fetch(PDO::FETCH_ASSOC);
$alerts_on = (bool)($user['alerts_enabled'] ?? 0);
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SwingRadar — Notifications</title>
    <link rel="icon" href="favicon.ico">
    <style>
        *{box-sizing:border-box;margin:0;padding:0}
        body{background:#0F1117;color:#E2E8F0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}
        .wrap{width:100%;max-width:480px}
        .logo{text-align:center;margin-bottom:28px}
        .logo img{height:52px;margin-bottom:10px}
        .logo .sub{font-size:13px;color:#6B7280}
        .logo .sub a{color:#2563EB;text-decoration:none;font-weight:600}
        .card{background:#1A1D27;border:1px solid #2D3148;border-radius:12px;padding:32px}
        .card h2{font-size:20px;font-weight:600;margin-bottom:8px}
        .card p{font-size:14px;color:#6B7280;margin-bottom:24px;line-height:1.6}
        .toggle-row{display:flex;align-items:center;justify-content:space-between;
            background:#0F1117;border:1px solid #2D3148;border-radius:10px;padding:16px 20px;margin-bottom:20px}
        .toggle-label{font-size:15px;font-weight:600}
        .toggle-sub{font-size:12px;color:#6B7280;margin-top:3px}
        .toggle{position:relative;display:inline-block;width:48px;height:26px}
        .toggle input{opacity:0;width:0;height:0}
        .slider{position:absolute;cursor:pointer;inset:0;background:#374151;border-radius:26px;transition:.2s}
        .slider:before{content:"";position:absolute;width:20px;height:20px;left:3px;bottom:3px;background:white;border-radius:50%;transition:.2s}
        input:checked + .slider{background:#2563EB}
        input:checked + .slider:before{transform:translateX(22px)}
        .preview{background:#0F1117;border:1px solid #2D3148;border-radius:8px;padding:16px;margin-bottom:20px}
        .preview-title{font-size:12px;color:#6B7280;text-transform:uppercase;letter-spacing:.05em;margin-bottom:10px}
        .preview-row{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
        .preview-badge{background:rgba(34,197,94,.15);color:#22C55E;font-size:11px;font-weight:600;padding:2px 8px;border-radius:4px}
        .preview-entry{color:#60A5FA;font-weight:600}
        .preview-sl{color:#F87171;font-weight:600}
        .preview-tgt{color:#4ADE80;font-weight:600}
        .success{background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.3);color:#86EFAC;border-radius:8px;padding:10px 14px;font-size:13px;margin-bottom:16px}
        button{width:100%;background:#2563EB;color:white;border:none;border-radius:8px;padding:12px;font-size:15px;font-weight:600;cursor:pointer;transition:background .15s}
        button:hover{background:#1D4ED8}
        .links{text-align:center;margin-top:20px;font-size:13px;color:#6B7280}
        .links a{color:#2563EB;text-decoration:none}
        footer{text-align:center;margin-top:24px;font-size:12px;color:#4B5563}
        footer a{color:#2563EB;text-decoration:none}
    </style>
</head>
<body>
<div class="wrap">
    <div class="logo">
        <img src="SwingRadar-logo.webp" alt="SwingRadar" onerror="this.style.display='none'">
        <div class="sub">Decision Support System &nbsp;·&nbsp; Built by <a href="https://www.nex41.io" target="_blank">Nex41</a></div>
    </div>

    <div class="card">
        <h2>🔔 Signal Alerts</h2>
        <p>Get an email when a new <strong>CONFIRMED</strong> signal appears during the decision window (16:30–18:00 BST). Alerts are sent to <strong><?= htmlspecialchars($user['email']) ?></strong>.</p>

        <?php if ($success): ?>
            <div class="success">✅ Settings saved.</div>
        <?php endif; ?>

        <form method="POST">
            <div class="toggle-row">
                <div>
                    <div class="toggle-label">Email alerts</div>
                    <div class="toggle-sub">Notify me when a CONFIRMED signal appears</div>
                </div>
                <label class="toggle">
                    <input type="checkbox" name="alerts_enabled" <?= $alerts_on ? 'checked' : '' ?> onchange="this.form.submit()">
                    <span class="slider"></span>
                </label>
            </div>
        </form>

        <!-- Preview -->
        <div class="preview">
            <div class="preview-title">Example alert email</div>
            <div class="preview-row">
                <span style="font-size:16px;font-weight:700">ORCL</span>
                <span class="preview-badge">🟢 CONFIRMED</span>
            </div>
            <div style="font-size:12px;color:#6B7280;margin-bottom:8px">Mega-cap Tech · Stability 90.4% · R/R 2.10</div>
            <div style="display:flex;gap:16px;font-size:13px">
                <div>Entry <span class="preview-entry">$173.42</span></div>
                <div>SL <span class="preview-sl">$165.18</span></div>
                <div>Target <span class="preview-tgt">$190.76</span></div>
            </div>
        </div>

        <div class="links">
            <a href="index.php">← Back to Dashboard</a>
        </div>
    </div>
    <footer><a href="https://www.nex41.io" target="_blank">www.nex41.io</a></footer>
</div>
</body>
</html>
