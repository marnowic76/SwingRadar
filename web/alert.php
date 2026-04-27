<?php
/**
 * SwingRadar Alert Endpoint
 * Called by scanner_daemon.py when a new CONFIRMED signal appears.
 * Sends email to all users with alerts_enabled = 1.
 */
require_once __DIR__ . '/auth.php';

// ── Security — secret key must match daemon config ──
define('ALERT_SECRET', 'SR_ALERT_2026_nex41');

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    die('Method not allowed');
}

$secret = $_POST['secret'] ?? '';
if (!hash_equals(ALERT_SECRET, $secret)) {
    http_response_code(403);
    die('Forbidden');
}

// ── Parse signal data ──
$ticker   = strtoupper(trim($_POST['ticker']   ?? ''));
$sector   = trim($_POST['sector']              ?? '—');
$stability = (float)($_POST['stability']       ?? 0);
$entry    = (float)($_POST['entry']            ?? 0);
$sl       = (float)($_POST['sl']               ?? 0);
$target   = (float)($_POST['target']           ?? 0);
$rr       = (float)($_POST['rr']               ?? 0);

if (!$ticker) {
    http_response_code(400);
    die('Missing ticker');
}

// ── Duplicate check — don't send same ticker twice in 4h ──
try {
    db()->exec("CREATE TABLE IF NOT EXISTS sr_alert_log (
        id         INT AUTO_INCREMENT PRIMARY KEY,
        ticker     VARCHAR(20) NOT NULL,
        sent_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
        recipients INT DEFAULT 0
    )");

    $recent = db()->prepare("
        SELECT id FROM sr_alert_log
        WHERE ticker = ? AND sent_at > DATE_SUB(NOW(), INTERVAL 4 HOUR)
    ");
    $recent->execute([$ticker]);
    if ($recent->fetch()) {
        http_response_code(200);
        die(json_encode(['status' => 'skipped', 'reason' => 'already sent within 4h']));
    }
} catch (Exception $e) {
    // Table creation failed — continue anyway
}

// ── Get opted-in users ──
$users = db()->query("
    SELECT email, name FROM sr_users
    WHERE status = 'active' AND alerts_enabled = 1
")->fetchAll(PDO::FETCH_ASSOC);

if (empty($users)) {
    http_response_code(200);
    die(json_encode(['status' => 'no_recipients']));
}

// ── Build email ──
$fmt_entry  = $entry  > 0 ? '$' . number_format($entry,  2) : '—';
$fmt_sl     = $sl     > 0 ? '$' . number_format($sl,     2) : '—';
$fmt_target = $target > 0 ? '$' . number_format($target, 2) : '—';
$fmt_rr     = $rr     > 0 ? number_format($rr, 2) : '—';
$fmt_stab   = number_format($stability, 1) . '%';

$dashboard_url = 'https://www.nex41.io/swingradar/';

$subject = "🟢 SwingRadar CONFIRMED: {$ticker} | R/R {$fmt_rr} | Stability {$fmt_stab}";

$html_body = <<<HTML
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0F1117;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0F1117;padding:32px 0;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

  <!-- Header -->
  <tr><td style="background:#1A1D27;border:1px solid #2D3148;border-radius:12px 12px 0 0;padding:24px 28px;">
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td>
          <div style="font-size:11px;color:#6B7280;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px;">SwingRadar DSS · Decision Support System</div>
          <div style="font-size:22px;font-weight:700;color:#22C55E;">🟢 New CONFIRMED Signal</div>
        </td>
        <td align="right">
          <div style="font-size:28px;font-weight:800;color:#E2E8F0;">{$ticker}</div>
          <div style="font-size:13px;color:#6B7280;">{$sector}</div>
        </td>
      </tr>
    </table>
  </td></tr>

  <!-- Metrics -->
  <tr><td style="background:#131620;border-left:1px solid #2D3148;border-right:1px solid #2D3148;padding:20px 28px;">
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td align="center" style="padding:8px;">
          <div style="font-size:11px;color:#6B7280;text-transform:uppercase;letter-spacing:.05em;">Stability</div>
          <div style="font-size:24px;font-weight:700;color:#E2E8F0;">{$fmt_stab}</div>
        </td>
        <td align="center" style="padding:8px;border-left:1px solid #2D3148;">
          <div style="font-size:11px;color:#6B7280;text-transform:uppercase;letter-spacing:.05em;">Real R/R</div>
          <div style="font-size:24px;font-weight:700;color:#A78BFA;">{$fmt_rr}</div>
        </td>
      </tr>
    </table>
  </td></tr>

  <!-- Levels -->
  <tr><td style="background:#1A1D27;border-left:1px solid #2D3148;border-right:1px solid #2D3148;padding:20px 28px;">
    <table width="100%" cellpadding="8" cellspacing="0">
      <tr>
        <td align="center" style="background:#0F1117;border-radius:8px;">
          <div style="font-size:11px;color:#6B7280;margin-bottom:4px;">ENTRY</div>
          <div style="font-size:20px;font-weight:700;color:#60A5FA;">{$fmt_entry}</div>
        </td>
        <td width="12"></td>
        <td align="center" style="background:#0F1117;border-radius:8px;">
          <div style="font-size:11px;color:#6B7280;margin-bottom:4px;">STOP LOSS</div>
          <div style="font-size:20px;font-weight:700;color:#F87171;">{$fmt_sl}</div>
        </td>
        <td width="12"></td>
        <td align="center" style="background:#0F1117;border-radius:8px;">
          <div style="font-size:11px;color:#6B7280;margin-bottom:4px;">TARGET</div>
          <div style="font-size:20px;font-weight:700;color:#4ADE80;">{$fmt_target}</div>
        </td>
      </tr>
    </table>
  </td></tr>

  <!-- CTA -->
  <tr><td style="background:#1A1D27;border:1px solid #2D3148;border-radius:0 0 12px 12px;padding:20px 28px;text-align:center;">
    <a href="{$dashboard_url}" style="display:inline-block;background:#2563EB;color:white;text-decoration:none;
       padding:12px 32px;border-radius:8px;font-weight:600;font-size:15px;">
      View on Dashboard →
    </a>
    <div style="margin-top:12px;font-size:12px;color:#4B5563;">
      Decision window: 16:30 – 18:00 BST &nbsp;·&nbsp;
      <a href="{$dashboard_url}?unsubscribe=1" style="color:#4B5563;">Unsubscribe</a>
    </div>
  </td></tr>

  <!-- Footer -->
  <tr><td style="padding:16px 0;text-align:center;">
    <div style="font-size:11px;color:#374151;">
      SwingRadar DSS · Built by <a href="https://www.nex41.io" style="color:#2563EB;text-decoration:none;">Nex41</a>
      · NYSE / NASDAQ · This is not financial advice.
    </div>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>
HTML;

$plain_body = "SwingRadar CONFIRMED: {$ticker}\n\n"
    . "Sector: {$sector} | Stability: {$fmt_stab} | R/R: {$fmt_rr}\n"
    . "Entry: {$fmt_entry} | Stop Loss: {$fmt_sl} | Target: {$fmt_target}\n\n"
    . "Decision window: 16:30 – 18:00 BST\n"
    . "Dashboard: {$dashboard_url}\n\n"
    . "This is not financial advice. To unsubscribe, log in and disable alerts in your profile.\n"
    . "Built by Nex41 · www.nex41.io";

// ── Send emails ──
$sent = 0;
$from = 'SwingRadar DSS <noreply@nex41.io>';

foreach ($users as $user) {
    $to = $user['email'];

    $headers  = "MIME-Version: 1.0\r\n";
    $headers .= "Content-Type: text/html; charset=UTF-8\r\n";
    $headers .= "From: {$from}\r\n";
    $headers .= "Reply-To: noreply@nex41.io\r\n";
    $headers .= "X-Mailer: SwingRadar/1.0\r\n";

    if (mail($to, $subject, $html_body, $headers)) {
        $sent++;
    }
}

// ── Log ──
try {
    db()->prepare("INSERT INTO sr_alert_log (ticker, recipients) VALUES (?, ?)")
        ->execute([$ticker, $sent]);
} catch (Exception $e) {}

http_response_code(200);
echo json_encode([
    'status'     => 'sent',
    'ticker'     => $ticker,
    'recipients' => $sent,
]);
