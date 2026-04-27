<?php
require_once __DIR__ . '/auth.php';
require_login();
if (!is_admin()) {
    header('Location: index.php');
    exit;
}

$msg = '';

// Approve / Block / Delete user
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $id     = (int)($_POST['user_id'] ?? 0);
    $action = $_POST['action'] ?? '';

    if ($id && in_array($action, ['approve', 'block', 'delete'])) {
        if ($action === 'delete') {
            db()->prepare("DELETE FROM sr_users WHERE id = ? AND role != 'admin'")->execute([$id]);
            $msg = 'User deleted.';
        } else {
            $status = $action === 'approve' ? 'active' : 'blocked';
            db()->prepare("UPDATE sr_users SET status = ? WHERE id = ?")->execute([$status, $id]);
            $msg = $action === 'approve' ? '✅ User approved.' : '🚫 User blocked.';
        }
    }
}

// Get all users
$users = db()->query("SELECT * FROM sr_users ORDER BY created_at DESC")->fetchAll(PDO::FETCH_ASSOC);
$pending = array_filter($users, fn($u) => $u['status'] === 'pending');
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SwingRadar — Admin</title>
    <link rel="icon" href="favicon.ico">
    <style>
        *{box-sizing:border-box;margin:0;padding:0}
        body{background:#0F1117;color:#E2E8F0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:24px}
        .navbar{background:#1A1D27;border:1px solid #2D3148;border-radius:10px;padding:12px 20px;display:flex;align-items:center;justify-content:space-between;margin-bottom:24px}
        .navbar img{height:30px}
        .navbar a{color:#6B7280;text-decoration:none;font-size:13px}
        .navbar a:hover{color:#E2E8F0}
        h1{font-size:22px;margin-bottom:20px}
        .msg{background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.3);color:#86EFAC;border-radius:8px;padding:10px 16px;margin-bottom:20px;font-size:14px}
        .section{background:#1A1D27;border:1px solid #2D3148;border-radius:10px;overflow:hidden;margin-bottom:24px}
        .section-header{padding:14px 20px;font-weight:600;font-size:15px;border-bottom:1px solid #2D3148;display:flex;align-items:center;gap:8px}
        .badge{background:rgba(239,68,68,.2);color:#FCA5A5;border-radius:20px;padding:2px 10px;font-size:12px}
        table{width:100%;border-collapse:collapse;font-size:13px}
        th{padding:10px 16px;text-align:left;color:#6B7280;font-size:11px;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid #2D3148}
        td{padding:10px 16px;border-bottom:1px solid #1E2130;vertical-align:middle}
        tr:last-child td{border-bottom:none}
        tr:hover td{background:#252836}
        .status-pending{color:#FCD34D}
        .status-active{color:#4ADE80}
        .status-blocked{color:#F87171}
        .btn{display:inline-block;padding:4px 12px;border-radius:6px;font-size:12px;font-weight:600;border:none;cursor:pointer;text-decoration:none}
        .btn-green{background:rgba(34,197,94,.15);color:#4ADE80}
        .btn-red{background:rgba(239,68,68,.15);color:#F87171}
        .btn-gray{background:rgba(107,114,128,.15);color:#9CA3AF}
        .btn:hover{opacity:.8}
        .empty{text-align:center;color:#6B7280;padding:24px}
    </style>
</head>
<body>
<div class="navbar">
    <img src="SwingRadar-logo.webp" alt="SwingRadar" onerror="this.style.display='none'">
    <div style="display:flex;gap:16px;align-items:center">
        <a href="index.php">← Dashboard</a>
        <a href="index.php?logout=1">Logout</a>
    </div>
</div>

<h1>👥 User Management</h1>

<?php if ($msg): ?><div class="msg"><?= htmlspecialchars($msg) ?></div><?php endif; ?>

<!-- Pending -->
<div class="section">
    <div class="section-header">
        ⏳ Pending Approval
        <?php if (count($pending) > 0): ?>
            <span class="badge"><?= count($pending) ?> waiting</span>
        <?php endif; ?>
    </div>
    <?php $pending_list = array_values($pending); ?>
    <?php if (empty($pending_list)): ?>
        <p class="empty">No pending registrations.</p>
    <?php else: ?>
    <table>
        <thead><tr><th>Name</th><th>Email</th><th>Registered</th><th>Actions</th></tr></thead>
        <tbody>
        <?php foreach ($pending_list as $u): ?>
        <tr>
            <td><?= htmlspecialchars($u['name']) ?></td>
            <td><?= htmlspecialchars($u['email']) ?></td>
            <td style="color:#6B7280"><?= substr($u['created_at'], 0, 16) ?></td>
            <td>
                <form method="POST" style="display:inline">
                    <input type="hidden" name="user_id" value="<?= $u['id'] ?>">
                    <input type="hidden" name="action" value="approve">
                    <button type="submit" class="btn btn-green">✅ Approve</button>
                </form>
                <form method="POST" style="display:inline;margin-left:6px">
                    <input type="hidden" name="user_id" value="<?= $u['id'] ?>">
                    <input type="hidden" name="action" value="delete">
                    <button type="submit" class="btn btn-red" onclick="return confirm('Delete this user?')">🗑 Delete</button>
                </form>
            </td>
        </tr>
        <?php endforeach; ?>
        </tbody>
    </table>
    <?php endif; ?>
</div>

<!-- All Users -->
<div class="section">
    <div class="section-header">👤 All Users (<?= count($users) ?>)</div>
    <?php if (empty($users)): ?>
        <p class="empty">No users yet.</p>
    <?php else: ?>
    <table>
        <thead><tr><th>Name</th><th>Email</th><th>Status</th><th>Role</th><th>Last Login</th><th>Actions</th></tr></thead>
        <tbody>
        <?php foreach ($users as $u): ?>
        <tr>
            <td><?= htmlspecialchars($u['name']) ?></td>
            <td><?= htmlspecialchars($u['email']) ?></td>
            <td><span class="status-<?= $u['status'] ?>"><?= ucfirst($u['status']) ?></span></td>
            <td style="color:<?= $u['role']==='admin'?'#A78BFA':'#6B7280' ?>"><?= ucfirst($u['role']) ?></td>
            <td style="color:#6B7280"><?= $u['last_login'] ? substr($u['last_login'], 0, 16) : '—' ?></td>
            <td>
                <?php if ($u['role'] !== 'admin'): ?>
                <?php if ($u['status'] !== 'active'): ?>
                <form method="POST" style="display:inline">
                    <input type="hidden" name="user_id" value="<?= $u['id'] ?>">
                    <input type="hidden" name="action" value="approve">
                    <button type="submit" class="btn btn-green">Approve</button>
                </form>
                <?php endif; ?>
                <?php if ($u['status'] !== 'blocked'): ?>
                <form method="POST" style="display:inline;margin-left:4px">
                    <input type="hidden" name="user_id" value="<?= $u['id'] ?>">
                    <input type="hidden" name="action" value="block">
                    <button type="submit" class="btn btn-red">Block</button>
                </form>
                <?php endif; ?>
                <form method="POST" style="display:inline;margin-left:4px">
                    <input type="hidden" name="user_id" value="<?= $u['id'] ?>">
                    <input type="hidden" name="action" value="delete">
                    <button type="submit" class="btn btn-gray" onclick="return confirm('Delete?')">Delete</button>
                </form>
                <?php else: ?>
                <span style="color:#6B7280;font-size:12px">Admin — protected</span>
                <?php endif; ?>
            </td>
        </tr>
        <?php endforeach; ?>
        </tbody>
    </table>
    <?php endif; ?>
</div>
<?php
// Feedback section
try {
    db()->exec("CREATE TABLE IF NOT EXISTS sr_feedback (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        user_email VARCHAR(255),
        rating TINYINT NOT NULL,
        category VARCHAR(50),
        message TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )");
    $feedbacks  = db()->query("SELECT * FROM sr_feedback ORDER BY created_at DESC")->fetchAll(PDO::FETCH_ASSOC);
    $avg_rating = count($feedbacks) ? round(array_sum(array_column($feedbacks, 'rating')) / count($feedbacks), 1) : 0;
} catch(Exception $e) { $feedbacks = []; $avg_rating = 0; }
?>
<div class="section" style="margin-top:24px">
    <div class="section-header">
        💬 User Feedback (<?php echo count($feedbacks); ?> total<?php if($avg_rating): ?> &nbsp;·&nbsp; Avg: <?php echo str_repeat('★',(int)round($avg_rating)) . ' ' . $avg_rating; ?>/5<?php endif; ?>)
    </div>
    <?php if(empty($feedbacks)): ?>
        <p class="empty">No feedback submitted yet.</p>
    <?php else: ?>
    <table>
        <thead><tr><th>User</th><th>Rating</th><th>Category</th><th>Message</th><th>Date</th></tr></thead>
        <tbody>
        <?php foreach($feedbacks as $fb): ?>
        <tr>
            <td style="color:#9CA3AF;font-size:12px"><?php echo htmlspecialchars($fb['user_email']); ?></td>
            <td style="color:#F59E0B"><?php echo str_repeat('★',$fb['rating']) . str_repeat('☆',5-$fb['rating']); ?></td>
            <td style="font-size:12px;color:#6B7280"><?php echo htmlspecialchars($fb['category']?:'—'); ?></td>
            <td style="max-width:380px;font-size:13px"><?php echo htmlspecialchars($fb['message']); ?></td>
            <td style="color:#6B7280;font-size:12px;white-space:nowrap"><?php echo substr($fb['created_at'],0,16); ?></td>
        </tr>
        <?php endforeach; ?>
        </tbody>
    </table>
    <?php endif; ?>
</div>
</body>
</html>
