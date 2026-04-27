<?php
require_once __DIR__ . '/auth.php';

// Logout
if (isset($_GET['logout'])) {
    logout_user();
    header('Location: index.php');
    exit;
}

// Already logged in — serve dashboard
if (is_logged_in()) {
    $dashboard = @file_get_contents(__DIR__ . '/dashboard.html');
    if (!$dashboard) {
        echo '<div style="background:#0F1117;color:#E2E8F0;min-height:100vh;display:flex;align-items:center;justify-content:center;font-family:sans-serif">
              <div style="text-align:center">
                <img src="SwingRadar-logo.webp" style="height:60px;margin-bottom:20px"><br>
                <p style="color:#6B7280">Dashboard is being generated. Please check back in a few minutes.</p>
              </div></div>';
        exit;
    }
    // Inject user info + logout into navbar
    $is_admin = ($_SESSION['user_role'] ?? '') === 'admin';
    $admin_item = $is_admin
        ? '<a href="admin.php" style="display:block;padding:10px 16px;color:#A78BFA;text-decoration:none;font-size:13px;border-bottom:1px solid #2D3148;">&#9881;&#65039; Admin Panel</a>'
        : '';
    $uname = htmlspecialchars($_SESSION['user_name']);
    $user_bar = '
        <div class="desktop-only" style="position:relative;">
            <button id="userBtn" style="background:#1A1D27;border:1px solid #2D3148;border-radius:8px;
                color:#E2E8F0;padding:6px 14px;cursor:pointer;font-size:13px;display:flex;align-items:center;gap:8px;">
                &#128100; ' . $uname . ' <span style="color:#6B7280;font-size:10px;">&#9660;</span>
            </button>
            <div id="userDropdown" style="display:none;position:absolute;right:0;top:calc(100% + 8px);
                background:#1A1D27;border:1px solid #2D3148;border-radius:10px;min-width:190px;
                box-shadow:0 8px 24px rgba(0,0,0,.5);z-index:1000;overflow:hidden;">
                <a href="journal.php" style="display:block;padding:10px 16px;color:#9CA3AF;text-decoration:none;font-size:13px;border-bottom:1px solid #2D3148;">&#128218; Trade Journal</a><a href="about.php" style="display:block;padding:10px 16px;color:#9CA3AF;text-decoration:none;font-size:13px;border-bottom:1px solid #2D3148;">&#8505;&#65039; How It Works</a><a href="notifications.php" style="display:block;padding:10px 16px;color:#9CA3AF;text-decoration:none;font-size:13px;border-bottom:1px solid #2D3148;">&#128276; Alerts</a><a href="feedback.php" style="display:block;padding:10px 16px;color:#9CA3AF;text-decoration:none;font-size:13px;border-bottom:1px solid #2D3148;">&#128172; Feedback</a>
                <a href="change_password.php" style="display:block;padding:10px 16px;color:#9CA3AF;text-decoration:none;font-size:13px;border-bottom:1px solid #2D3148;">&#128273; Change Password</a>
                ' . $admin_item . '
                <a href="?logout=1" style="display:block;padding:10px 16px;color:#FCA5A5;text-decoration:none;font-size:13px;">Logout</a>
            </div>
        </div>
        <script>
        document.getElementById("userBtn").addEventListener("click", function(e) {
            e.stopPropagation();
            var d = document.getElementById("userDropdown");
            d.style.display = d.style.display === "none" ? "block" : "none";
        });
        document.addEventListener("click", function() {
            var d = document.getElementById("userDropdown");
            if (d) d.style.display = "none";
        });
        </script>';
    $dashboard = str_replace('</nav>', $user_bar . '</nav>', $dashboard);
    echo $dashboard;
    exit;
}

// Process login form
$error = '';
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['action']) && $_POST['action'] === 'login') {
    $result = login_user($_POST['email'] ?? '', $_POST['password'] ?? '');
    if ($result['ok']) {
        header('Location: index.php');
        exit;
    }
    $error = $result['error'];
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SwingRadar DSS — Sign In</title>
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
        button{width:100%;background:#2563EB;color:white;border:none;border-radius:8px;padding:12px;font-size:15px;font-weight:600;cursor:pointer;margin-top:20px;transition:background .15s}
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
        <h2>Sign In</h2>
        <p>Enter your credentials to access the dashboard.</p>
        <form method="POST">
            <input type="hidden" name="action" value="login">
            <label>Email</label>
            <input type="email" name="email" placeholder="you@example.com" autofocus required value="<?= htmlspecialchars($_POST['email'] ?? '') ?>">
            <label>Password</label>
            <input type="password" name="password" placeholder="Your password" required>
            <?php if ($error): ?><div class="error">⚠️ <?= htmlspecialchars($error) ?></div><?php endif; ?>
            <button type="submit">Sign In →</button>
        </form>
        <div class="links">
            Don't have an account? <a href="register.php">Register here</a>
        </div>
    </div>
    <footer><a href="https://www.nex41.io" target="_blank">www.nex41.io</a> &nbsp;·&nbsp; NYSE / NASDAQ &nbsp;·&nbsp; ISA Account (UK)</footer>
</div>
</body>
</html>
