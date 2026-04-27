<?php
require_once __DIR__ . '/auth.php';
require_login();

$success = false;
$error   = '';

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $current  = $_POST['current_password']  ?? '';
    $new_pass = $_POST['new_password']      ?? '';
    $confirm  = $_POST['confirm_password']  ?? '';

    // Verify current password
    $stmt = db()->prepare("SELECT password FROM sr_users WHERE id = ?");
    $stmt->execute([$_SESSION['user_id']]);
    $user = $stmt->fetch(PDO::FETCH_ASSOC);

    if (!$user || !password_verify($current, $user['password'])) {
        $error = 'Current password is incorrect.';
    } elseif (strlen($new_pass) < 8) {
        $error = 'New password must be at least 8 characters.';
    } elseif ($new_pass !== $confirm) {
        $error = 'New passwords do not match.';
    } elseif ($new_pass === $current) {
        $error = 'New password must be different from current password.';
    } else {
        $hash = password_hash($new_pass, PASSWORD_BCRYPT);
        db()->prepare("UPDATE sr_users SET password = ? WHERE id = ?")
            ->execute([$hash, $_SESSION['user_id']]);

        // Invalidate all other sessions
        db()->prepare("DELETE FROM sr_sessions WHERE user_id = ? AND id != ?")
            ->execute([$_SESSION['user_id'], $_SESSION['session_token']]);

        $success = true;
    }
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SwingRadar DSS — Change Password</title>
    <link rel="icon" href="favicon.ico">
    <style>
        *{box-sizing:border-box;margin:0;padding:0}
        body{background:#0F1117;color:#E2E8F0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center}
        .wrap{width:100%;max-width:420px;padding:24px}
        .logo{text-align:center;margin-bottom:32px}
        .logo img{height:60px;margin-bottom:12px}
        .logo .sub{font-size:13px;color:#6B7280}
        .logo .sub a{color:#2563EB;text-decoration:none;font-weight:600}
        .card{background:#1A1D27;border:1px solid #2D3148;border-radius:12px;padding:32px}
        .card h2{font-size:18px;font-weight:600;margin-bottom:8px}
        .card p{font-size:13px;color:#6B7280;margin-bottom:24px}
        label{display:block;font-size:12px;font-weight:600;color:#9CA3AF;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;margin-top:16px}
        input{width:100%;background:#0F1117;border:1px solid #2D3148;border-radius:8px;color:#E2E8F0;font-size:15px;padding:10px 14px;outline:none;transition:border-color .15s}
        input:focus{border-color:#2563EB}
        .error{background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.3);color:#FCA5A5;border-radius:8px;padding:10px 14px;font-size:13px;margin-top:12px}
        .success{background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.3);color:#86EFAC;border-radius:8px;padding:16px;font-size:14px;margin-top:12px;line-height:1.6}
        button{width:100%;background:#2563EB;color:white;border:none;border-radius:8px;padding:12px;font-size:15px;font-weight:600;cursor:pointer;margin-top:20px;transition:background .15s}
        button:hover{background:#1D4ED8}
        .links{text-align:center;margin-top:20px;font-size:13px;color:#6B7280}
        .links a{color:#2563EB;text-decoration:none}
        footer{text-align:center;margin-top:24px;font-size:12px;color:#4B5563}
        footer a{color:#2563EB;text-decoration:none}
        .req{font-size:11px;color:#6B7280;margin-top:4px}
    </style>
</head>
<body>
<div class="wrap">
    <div class="logo">
        <img src="SwingRadar-logo.webp" alt="SwingRadar" onerror="this.style.display='none'">
        <div class="sub">Decision Support System &nbsp;·&nbsp; Built by <a href="https://www.nex41.io" target="_blank">Nex41</a></div>
    </div>
    <div class="card">
        <h2>Change Password</h2>
        <p>Logged in as <strong><?= htmlspecialchars($_SESSION['user_email'] ?? '') ?></strong></p>

        <?php if ($success): ?>
            <div class="success">
                ✅ <strong>Password changed successfully!</strong><br><br>
                All other active sessions have been signed out.
            </div>
            <div class="links" style="margin-top:24px">
                <a href="index.php">← Back to Dashboard</a>
            </div>
        <?php else: ?>
            <form method="POST">
                <label>Current Password</label>
                <input type="password" name="current_password" placeholder="Your current password" autofocus required>

                <label>New Password</label>
                <input type="password" name="new_password" placeholder="Min. 8 characters" required>
                <p class="req">At least 8 characters.</p>

                <label>Confirm New Password</label>
                <input type="password" name="confirm_password" placeholder="Repeat new password" required>

                <?php if ($error): ?>
                    <div class="error">⚠️ <?= htmlspecialchars($error) ?></div>
                <?php endif; ?>

                <button type="submit">Update Password →</button>
            </form>
            <div class="links">
                <a href="index.php">← Back to Dashboard</a>
            </div>
        <?php endif; ?>
    </div>
    <footer><a href="https://www.nex41.io" target="_blank">www.nex41.io</a></footer>
</div>
</body>
</html>
