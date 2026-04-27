<?php
require_once __DIR__ . '/auth.php';

if (is_logged_in()) {
    header('Location: index.php');
    exit;
}

$success = false;
$error   = '';

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    if ($_POST['password'] !== $_POST['password2']) {
        $error = 'Passwords do not match.';
    } else {
        $result = register_user($_POST['email'] ?? '', $_POST['name'] ?? '', $_POST['password'] ?? '');
        if ($result['ok']) {
            $success = true;
        } else {
            $error = $result['error'];
        }
    }
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SwingRadar DSS — Register</title>
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
        .notice{background:rgba(37,99,235,.1);border:1px solid rgba(37,99,235,.3);color:#93C5FD;border-radius:8px;padding:12px 14px;font-size:13px;margin-bottom:20px;line-height:1.5}
    </style>
</head>
<body>
<div class="wrap">
    <div class="logo">
        <img src="SwingRadar-logo.webp" alt="SwingRadar" onerror="this.style.display='none'">
        <div class="sub">Decision Support System &nbsp;·&nbsp; Built by <a href="https://www.nex41.io" target="_blank">Nex41</a></div>
    </div>
    <div class="card">
        <h2>Create Account</h2>
        <p>Register to request access to the SwingRadar dashboard.</p>

        <?php if ($success): ?>
            <div class="success">
                ✅ <strong>Registration successful!</strong><br><br>
                Your account is pending approval. You will be notified once access is granted.
            </div>
            <div class="links" style="margin-top:24px">
                <a href="index.php">← Back to Sign In</a>
            </div>
        <?php else: ?>
            <div class="notice">
                ℹ️ Access requires manual approval. You will be notified by email once your account is activated.
            </div>
            <form method="POST">
                <label>Full Name</label>
                <input type="text" name="name" placeholder="Your name" required
                       value="<?= htmlspecialchars($_POST['name'] ?? '') ?>">
                <label>Email</label>
                <input type="email" name="email" placeholder="you@example.com" required
                       value="<?= htmlspecialchars($_POST['email'] ?? '') ?>">
                <label>Password</label>
                <input type="password" name="password" placeholder="Min. 8 characters" required>
                <label>Confirm Password</label>
                <input type="password" name="password2" placeholder="Repeat password" required>
                <?php if ($error): ?><div class="error">⚠️ <?= htmlspecialchars($error) ?></div><?php endif; ?>
                <button type="submit">Request Access →</button>
            </form>
            <div class="links">
                Already have an account? <a href="index.php">Sign In</a>
            </div>
        <?php endif; ?>
    </div>
    <footer><a href="https://www.nex41.io" target="_blank">www.nex41.io</a> &nbsp;·&nbsp; NYSE / NASDAQ &nbsp;·&nbsp; ISA Account (UK)</footer>
</div>
</body>
</html>
