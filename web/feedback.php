<?php
require_once __DIR__ . '/auth.php';
require_login();

// Create feedback table if not exists
db()->exec("
    CREATE TABLE IF NOT EXISTS sr_feedback (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        user_id     INT NOT NULL,
        user_email  VARCHAR(255),
        rating      TINYINT NOT NULL,
        category    VARCHAR(50),
        message     TEXT NOT NULL,
        created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
    )
");

$success = false;
$error   = '';

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $rating   = (int)($_POST['rating']   ?? 0);
    $category = trim($_POST['category']  ?? '');
    $message  = trim($_POST['message']   ?? '');

    if ($rating < 1 || $rating > 5) {
        $error = 'Please select a rating.';
    } elseif (strlen($message) < 10) {
        $error = 'Message must be at least 10 characters.';
    } else {
        db()->prepare("
            INSERT INTO sr_feedback (user_id, user_email, rating, category, message)
            VALUES (?, ?, ?, ?, ?)
        ")->execute([
            $_SESSION['user_id'],
            $_SESSION['user_email'] ?? '',
            $rating,
            $category,
            $message
        ]);
        $success = true;
    }
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SwingRadar — Feedback</title>
    <link rel="icon" href="favicon.ico">
    <style>
        *{box-sizing:border-box;margin:0;padding:0}
        body{background:#0F1117;color:#E2E8F0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}
        .wrap{width:100%;max-width:520px}
        .logo{text-align:center;margin-bottom:28px}
        .logo img{height:52px;margin-bottom:10px}
        .logo .sub{font-size:13px;color:#6B7280}
        .logo .sub a{color:#2563EB;text-decoration:none;font-weight:600}
        .card{background:#1A1D27;border:1px solid #2D3148;border-radius:12px;padding:32px}
        .card h2{font-size:20px;font-weight:600;margin-bottom:6px}
        .card p{font-size:13px;color:#6B7280;margin-bottom:24px}
        label{display:block;font-size:12px;font-weight:600;color:#9CA3AF;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;margin-top:20px}
        input,select,textarea{width:100%;background:#0F1117;border:1px solid #2D3148;border-radius:8px;color:#E2E8F0;font-size:15px;padding:10px 14px;outline:none;transition:border-color .15s;font-family:inherit}
        input:focus,select:focus,textarea:focus{border-color:#2563EB}
        textarea{resize:vertical;min-height:120px}
        select option{background:#1A1D27}

        /* Star rating */
        .stars{display:flex;gap:8px;margin-top:6px}
        .stars input{display:none}
        .stars label{font-size:32px;cursor:pointer;color:#374151;transition:color .1s;text-transform:none;letter-spacing:0;padding:0;margin:0;width:auto}
        .stars input:checked ~ label,
        .stars label:hover,
        .stars label:hover ~ label{color:#374151}
        .stars input:checked + label,
        .stars label:hover{color:#F59E0B}
        .stars{flex-direction:row-reverse}
        .stars label:hover,
        .stars label:hover ~ label,
        .stars input:checked ~ label{color:#F59E0B}

        .error{background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.3);color:#FCA5A5;border-radius:8px;padding:10px 14px;font-size:13px;margin-top:12px}
        .success{background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.3);color:#86EFAC;border-radius:8px;padding:20px;font-size:14px;line-height:1.6}
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
        <h2>Share Your Feedback</h2>
        <p>Help us improve SwingRadar. Your feedback is read personally.</p>

        <?php if ($success): ?>
            <div class="success">
                ✅ <strong>Thank you for your feedback!</strong><br><br>
                We appreciate you taking the time to share your thoughts. It helps us make SwingRadar better.
            </div>
            <div class="links" style="margin-top:24px">
                <a href="index.php">← Back to Dashboard</a>
            </div>
        <?php else: ?>
            <form method="POST">
                <label>Overall Rating</label>
                <div class="stars">
                    <input type="radio" name="rating" id="s5" value="5" <?= ($_POST['rating']??'')==5?'checked':'' ?>>
                    <label for="s5" title="Excellent">★</label>
                    <input type="radio" name="rating" id="s4" value="4" <?= ($_POST['rating']??'')==4?'checked':'' ?>>
                    <label for="s4" title="Good">★</label>
                    <input type="radio" name="rating" id="s3" value="3" <?= ($_POST['rating']??'')==3?'checked':'' ?>>
                    <label for="s3" title="Average">★</label>
                    <input type="radio" name="rating" id="s2" value="2" <?= ($_POST['rating']??'')==2?'checked':'' ?>>
                    <label for="s2" title="Poor">★</label>
                    <input type="radio" name="rating" id="s1" value="1" <?= ($_POST['rating']??'')==1?'checked':'' ?>>
                    <label for="s1" title="Very Poor">★</label>
                </div>

                <label>Category</label>
                <select name="category">
                    <option value="">— Select category —</option>
                    <option value="Signal Quality" <?= ($_POST['category']??'')=='Signal Quality'?'selected':'' ?>>📊 Signal Quality</option>
                    <option value="Dashboard UX" <?= ($_POST['category']??'')=='Dashboard UX'?'selected':'' ?>>🖥️ Dashboard UX</option>
                    <option value="Mobile Experience" <?= ($_POST['category']??'')=='Mobile Experience'?'selected':'' ?>>📱 Mobile Experience</option>
                    <option value="Performance" <?= ($_POST['category']??'')=='Performance'?'selected':'' ?>>⚡ Performance</option>
                    <option value="Missing Feature" <?= ($_POST['category']??'')=='Missing Feature'?'selected':'' ?>>💡 Missing Feature</option>
                    <option value="Bug Report" <?= ($_POST['category']??'')=='Bug Report'?'selected':'' ?>>🐛 Bug Report</option>
                    <option value="General" <?= ($_POST['category']??'')=='General'?'selected':'' ?>>💬 General</option>
                </select>

                <label>Your Message</label>
                <textarea name="message" placeholder="What's working well? What could be improved? Any features you'd like to see?"><?= htmlspecialchars($_POST['message']??'') ?></textarea>

                <?php if ($error): ?>
                    <div class="error">⚠️ <?= htmlspecialchars($error) ?></div>
                <?php endif; ?>

                <button type="submit">Send Feedback →</button>
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
