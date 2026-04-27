<?php
/**
 * SwingRadar DSS — Auth Core
 * Built by Nex41 · www.nex41.io
 */

// ── Database Config ───────────────────────
// Zmień na swoje dane z panelu lh.pl
define('DB_HOST', 'sql56.lh.pl');
define('DB_NAME', 'serwer82250_lion');
define('DB_USER', 'serwer82250_lion');
define('DB_PASS', 'j>LaL&k^f0MFh%9>');  // Hasło z panelu lh.pl → Bazy MySQL

define('SESSION_NAME',  'swingRadar_auth');
define('SESSION_HOURS', 8);
define('SITE_NAME',     'SwingRadar DSS');
define('SITE_URL',      'https://www.nex41.io/swingradar/');

// ── Session ───────────────────────────────
session_name(SESSION_NAME);
session_start();

// ── DB Connection ─────────────────────────
function db(): PDO {
    static $pdo = null;
    if ($pdo === null) {
        $pdo = new PDO(
            'mysql:host=' . DB_HOST . ';dbname=' . DB_NAME . ';charset=utf8mb4',
            DB_USER, DB_PASS,
            [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]
        );
    }
    return $pdo;
}

// ── Init tables ───────────────────────────
function init_tables(): void {
    db()->exec("
        CREATE TABLE IF NOT EXISTS sr_users (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            email           VARCHAR(255) UNIQUE NOT NULL,
            name            VARCHAR(100) NOT NULL,
            password        VARCHAR(255) NOT NULL,
            status          ENUM('pending','active','blocked') DEFAULT 'pending',
            role            ENUM('user','admin') DEFAULT 'user',
            alerts_enabled  TINYINT(1) DEFAULT 0,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_login      DATETIME
        )
    ");
    // Migration: add alerts_enabled if missing
    try {
        db()->exec("ALTER TABLE sr_users ADD COLUMN alerts_enabled TINYINT(1) DEFAULT 0");
    } catch (Exception $e) {} // Column already exists
    db()->exec("
        CREATE TABLE IF NOT EXISTS sr_sessions (
            id         VARCHAR(64) PRIMARY KEY,
            user_id    INT NOT NULL,
            expires_at DATETIME NOT NULL,
            ip         VARCHAR(45),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ");
}

// ── Auth helpers ──────────────────────────
function is_logged_in(): bool {
    if (empty($_SESSION['user_id'])) return false;
    // Verify session in DB
    $stmt = db()->prepare("
        SELECT s.user_id, u.status, u.name, u.email, u.role
        FROM sr_sessions s
        JOIN sr_users u ON u.id = s.user_id
        WHERE s.id = ? AND s.expires_at > NOW()
    ");
    $stmt->execute([$_SESSION['session_token'] ?? '']);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if (!$row || $row['status'] !== 'active') return false;
    $_SESSION['user_name']  = $row['name'];
    $_SESSION['user_email'] = $row['email'];
    $_SESSION['user_role']  = $row['role'];
    return true;
}

function login_user(string $email, string $password): array {
    $stmt = db()->prepare("SELECT * FROM sr_users WHERE email = ?");
    $stmt->execute([strtolower(trim($email))]);
    $user = $stmt->fetch(PDO::FETCH_ASSOC);

    if (!$user || !password_verify($password, $user['password'])) {
        sleep(1);
        return ['ok' => false, 'error' => 'Invalid email or password.'];
    }
    if ($user['status'] === 'pending') {
        return ['ok' => false, 'error' => 'Your account is awaiting approval. You will receive an email when approved.'];
    }
    if ($user['status'] === 'blocked') {
        return ['ok' => false, 'error' => 'Your account has been suspended.'];
    }

    // Create session
    $token = bin2hex(random_bytes(32));
    $expires = date('Y-m-d H:i:s', time() + SESSION_HOURS * 3600);
    db()->prepare("
        INSERT INTO sr_sessions (id, user_id, expires_at, ip)
        VALUES (?, ?, ?, ?)
    ")->execute([$token, $user['id'], $expires, $_SERVER['REMOTE_ADDR'] ?? '']);

    // Update last login
    db()->prepare("UPDATE sr_users SET last_login = NOW() WHERE id = ?")
        ->execute([$user['id']]);

    $_SESSION['user_id']      = $user['id'];
    $_SESSION['session_token'] = $token;
    $_SESSION['user_name']    = $user['name'];
    $_SESSION['user_email']   = $user['email'];
    $_SESSION['user_role']    = $user['role'];

    return ['ok' => true];
}

function register_user(string $email, string $name, string $password): array {
    $email = strtolower(trim($email));
    $name  = trim($name);

    if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
        return ['ok' => false, 'error' => 'Invalid email address.'];
    }
    if (strlen($name) < 2) {
        return ['ok' => false, 'error' => 'Name must be at least 2 characters.'];
    }
    if (strlen($password) < 8) {
        return ['ok' => false, 'error' => 'Password must be at least 8 characters.'];
    }

    // Check duplicate
    $stmt = db()->prepare("SELECT id FROM sr_users WHERE email = ?");
    $stmt->execute([$email]);
    if ($stmt->fetch()) {
        return ['ok' => false, 'error' => 'An account with this email already exists.'];
    }

    $hash = password_hash($password, PASSWORD_BCRYPT);
    db()->prepare("
        INSERT INTO sr_users (email, name, password, status) VALUES (?, ?, ?, 'pending')
    ")->execute([$email, $name, $hash]);

    return ['ok' => true];
}

function logout_user(): void {
    if (!empty($_SESSION['session_token'])) {
        db()->prepare("DELETE FROM sr_sessions WHERE id = ?")
            ->execute([$_SESSION['session_token']]);
    }
    session_destroy();
}

function require_login(): void {
    if (!is_logged_in()) {
        header('Location: index.php');
        exit;
    }
}

function is_admin(): bool {
    return ($_SESSION['user_role'] ?? '') === 'admin';
}

// Init on load
try {
    init_tables();
} catch (Exception $e) {
    die('<p style="color:white;padding:40px;font-family:sans-serif">Database error: ' . htmlspecialchars($e->getMessage()) . '</p>');
}
