<?php
require_once __DIR__ . '/../inc/db.php';
require_once __DIR__ . '/../inc/funcoes.php';

if (session_status() !== PHP_SESSION_ACTIVE) {
  $secure = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off');
  session_set_cookie_params([
    'httponly' => true,
    'samesite' => 'Lax',
    'secure' => $secure,
  ]);
  session_start();
}

function admin_user_id() {
  return isset($_SESSION['admin_user_id']) ? (int) $_SESSION['admin_user_id'] : 0;
}

function admin_bootstrap_schema() {
  static $done = false;
  if ($done) {
    return;
  }
  $done = true;

  try {
    $pdo = db();

    $adminUserColumns = [];
    foreach ($pdo->query("SHOW COLUMNS FROM admin_users") as $column) {
      $adminUserColumns[(string) $column['Field']] = true;
    }
    if (!isset($adminUserColumns['username'])) {
      $pdo->exec("ALTER TABLE admin_users ADD COLUMN username VARCHAR(80) NULL AFTER email");
      $pdo->exec("ALTER TABLE admin_users ADD UNIQUE KEY ux_admin_users_username (username)");
    }
    if (!isset($adminUserColumns['display_name'])) {
      $pdo->exec("ALTER TABLE admin_users ADD COLUMN display_name VARCHAR(120) NULL AFTER username");
    }

    $adminUsers = $pdo->query("SELECT id, email, username, display_name FROM admin_users ORDER BY id ASC")->fetchAll();
    foreach ($adminUsers as $user) {
      $email = trim((string) ($user['email'] ?? ''));
      $username = trim((string) ($user['username'] ?? ''));
      $displayName = trim((string) ($user['display_name'] ?? ''));
      $fallbackUsername = strtolower((string) preg_replace('/[^a-z0-9._-]+/i', '', strstr($email, '@', true) ?: $email));
      if ($fallbackUsername === '') {
        $fallbackUsername = 'admin' . (int) $user['id'];
      }

      $updates = [];
      $params = [];
      if ($username === '') {
        $updates[] = 'username = ?';
        $params[] = substr($fallbackUsername, 0, 80);
      }
      if ($displayName === '') {
        $updates[] = 'display_name = ?';
        $params[] = substr($username !== '' ? $username : $fallbackUsername, 0, 120);
      }
      if ($updates) {
        $params[] = (int) $user['id'];
        $stmt = $pdo->prepare('UPDATE admin_users SET ' . implode(', ', $updates) . ' WHERE id = ?');
        $stmt->execute($params);
      }
    }

    $offerColumns = [];
    foreach ($pdo->query("SHOW COLUMNS FROM ofertas") as $column) {
      $offerColumns[(string) $column['Field']] = true;
    }
    if (!isset($offerColumns['desconto_percentual'])) {
      $pdo->exec("ALTER TABLE ofertas ADD COLUMN desconto_percentual INT NULL AFTER preco_antigo");
    }
    if (!isset($offerColumns['preco_pix'])) {
      $pdo->exec("ALTER TABLE ofertas ADD COLUMN preco_pix DECIMAL(10,2) NULL AFTER desconto_percentual");
    }
    if (!isset($offerColumns['preco_outros_meios'])) {
      $pdo->exec("ALTER TABLE ofertas ADD COLUMN preco_outros_meios DECIMAL(10,2) NULL AFTER preco_pix");
    }
    if (!isset($offerColumns['parcelas_texto'])) {
      $pdo->exec("ALTER TABLE ofertas ADD COLUMN parcelas_texto VARCHAR(120) NULL AFTER preco_outros_meios");
    }
    if (!isset($offerColumns['frete_texto'])) {
      $pdo->exec("ALTER TABLE ofertas ADD COLUMN frete_texto VARCHAR(160) NULL AFTER parcelas_texto");
    }
    if (!isset($offerColumns['avaliacao_nota'])) {
      $pdo->exec("ALTER TABLE ofertas ADD COLUMN avaliacao_nota DECIMAL(4,2) NULL AFTER frete_texto");
    }
    if (!isset($offerColumns['avaliacao_total'])) {
      $pdo->exec("ALTER TABLE ofertas ADD COLUMN avaliacao_total INT NULL AFTER avaliacao_nota");
    }
    if (!isset($offerColumns['promocao_texto'])) {
      $pdo->exec("ALTER TABLE ofertas ADD COLUMN promocao_texto VARCHAR(255) NULL AFTER avaliacao_total");
    }
    if (!isset($offerColumns['criado_por_admin_id'])) {
      $pdo->exec("ALTER TABLE ofertas ADD COLUMN criado_por_admin_id INT NULL AFTER ativo");
      $pdo->exec("ALTER TABLE ofertas ADD INDEX ix_ofertas_criado_por_admin_id (criado_por_admin_id)");
    }
    if (!isset($offerColumns['criado_por_login'])) {
      $pdo->exec("ALTER TABLE ofertas ADD COLUMN criado_por_login VARCHAR(180) NULL AFTER criado_por_admin_id");
    }

    $owner = $pdo->query("SELECT id, COALESCE(NULLIF(username, ''), email) AS login_name FROM admin_users ORDER BY id ASC LIMIT 1")->fetch();
    if ($owner) {
      $stmt = $pdo->prepare("
        UPDATE ofertas
        SET criado_por_admin_id = ?,
            criado_por_login = ?
        WHERE criado_por_admin_id IS NULL
           OR criado_por_login IS NULL
           OR criado_por_login = ''
      ");
      $stmt->execute([(int) $owner['id'], (string) $owner['login_name']]);
    }
  } catch (Throwable $e) {
    // Mantem o admin funcional mesmo se a migracao falhar temporariamente.
  }
}

function admin_current_user() {
  static $cached = false;
  if ($cached !== false) {
    return $cached;
  }

  admin_bootstrap_schema();

  $id = admin_user_id();
  if ($id <= 0) {
    $cached = null;
    return null;
  }

  try {
    $stmt = db()->prepare("
      SELECT id, email, username, display_name,
             COALESCE(NULLIF(username, ''), email) AS login_name
      FROM admin_users
      WHERE id = ?
      LIMIT 1
    ");
    $stmt->execute([$id]);
    $row = $stmt->fetch();
    $cached = $row ?: null;
    return $cached;
  } catch (Throwable $e) {
    $cached = null;
    return null;
  }
}

function admin_current_login_name() {
  $user = admin_current_user();
  if (!$user) {
    return '';
  }
  return (string) ($user['login_name'] ?? $user['email'] ?? '');
}

function admin_is_logged_in() {
  return admin_user_id() > 0;
}

function admin_require_login() {
  if (!admin_is_logged_in()) {
    header('Location: /admin/index.php');
    exit;
  }
}

function admin_csrf_token() {
  if (empty($_SESSION['admin_csrf'])) {
    $_SESSION['admin_csrf'] = bin2hex(random_bytes(16));
  }
  return $_SESSION['admin_csrf'];
}

function admin_csrf_check_or_die() {
  $token = $_POST['csrf'] ?? '';
  if (!hash_equals($_SESSION['admin_csrf'] ?? '', $token)) {
    unset($_SESSION['admin_csrf']);
    admin_flash_set('error', 'Sua sessao expirou. Tente enviar o formulario novamente.');
    $redirect = $_SERVER['REQUEST_URI'] ?? '/admin/ofertas.php';
    header('Location: ' . $redirect);
    exit;
  }
}

function admin_flash_set($type, $message) {
  $_SESSION['admin_flash'] = [
    'type' => (string) $type,
    'message' => (string) $message,
  ];
}

function admin_flash_get() {
  if (empty($_SESSION['admin_flash']) || !is_array($_SESSION['admin_flash'])) {
    return null;
  }

  $flash = $_SESSION['admin_flash'];
  unset($_SESSION['admin_flash']);
  return $flash;
}

function admin_parse_decimal($value) {
  $raw = trim((string) $value);
  if ($raw === '') {
    return 0.0;
  }
  if (strpos($raw, ',') !== false && strpos($raw, '.') !== false) {
    $normalized = str_replace('.', '', $raw);
    $normalized = str_replace(',', '.', $normalized);
  } elseif (strpos($raw, ',') !== false) {
    $normalized = str_replace(',', '.', $raw);
  } else {
    $normalized = $raw;
  }
  return (float) $normalized;
}

function admin_normalize_slug($slug, $fallbackTitle) {
  $base = trim((string) $slug);
  if ($base === '') {
    $base = (string) $fallbackTitle;
  }
  return slugify($base);
}

function admin_unique_slug(PDO $pdo, $slug, $ignoreId = 0) {
  $base = substr(slugify((string) $slug), 0, 170);
  if ($base === '') {
    $base = 'item';
  }
  $final = $base;
  $i = 2;

  while (true) {
    $sql = 'SELECT id FROM ofertas WHERE slug = ?';
    $args = [$final];
    if ($ignoreId > 0) {
      $sql .= ' AND id <> ?';
      $args[] = $ignoreId;
    }
    $sql .= ' LIMIT 1';

    $stmt = $pdo->prepare($sql);
    $stmt->execute($args);
    $exists = $stmt->fetch();
    if (!$exists) {
      return $final;
    }
    $suffix = '-' . $i;
    $final = substr($base, 0, max(1, 170 - strlen($suffix))) . $suffix;
    $i++;
  }
}

function admin_is_meli_affiliate_url($url) {
  $value = (string) $url;
  return ((str_contains($value, 'wid=') && str_contains($value, 'sid=affiliates'))
      || (str_contains($value, 'wid=') && str_contains($value, 'polycard_client=affiliates')))
    || (str_contains($value, 'wid=') && str_contains($value, 'sid=recos') && str_contains($value, 'affiliate-profile'))
    || (str_contains($value, 'wid=') && str_contains($value, 'source=affiliate-profile'))
    || (str_contains($value, 'wid=') && str_contains($value, 'reco_client=home_affiliate-profile'))
    || (str_contains($value, 'wid=') && str_contains($value, 'polycard_client=') && str_contains($value, 'affiliate-profile'))
    || str_contains($value, '/social/')
    || str_contains($value, 'matt_tool=');
}

function admin_affiliate_audit($store, $url) {
  $storeValue = strtolower(trim((string) $store));
  $value = trim((string) $url);

  if ($value === '') {
    return [
      'severity' => 'broken',
      'status' => 'sem_link',
      'label' => 'Sem link',
      'reason' => 'A oferta nao tem URL afiliada salva.',
    ];
  }

  if ($storeValue === 'mercado livre') {
    $hasWid = str_contains($value, 'wid=');
    $hasSid = str_contains($value, 'sid=affiliates');
    $hasSidRecos = str_contains($value, 'sid=recos');
    $hasPolycard = str_contains($value, 'polycard_client=affiliates');
    $hasAffiliateProfile = str_contains($value, 'affiliate-profile');
    $hasMatt = str_contains($value, 'matt_tool=');
    $hasSocial = str_contains($value, '/social/');

    if ($hasSocial) {
      return ['severity' => 'ok', 'status' => 'social', 'label' => 'OK', 'reason' => 'Link social/oficial do Mercado Livre.'];
    }
    if ($hasMatt) {
      return ['severity' => 'ok', 'status' => 'matt_tool', 'label' => 'OK', 'reason' => 'Link com rastreio matt_tool do afiliado.'];
    }
    if ($hasWid && $hasSidRecos && $hasAffiliateProfile) {
      return ['severity' => 'ok', 'status' => 'wid_recos_affiliate_profile', 'label' => 'OK', 'reason' => 'Link vindo do affiliate-profile do Mercado Livre.'];
    }
    if ($hasWid && $hasPolycard) {
      return ['severity' => 'suspect', 'status' => 'wid_polycard', 'label' => 'Suspeito', 'reason' => 'Tem wid e polycard, mas ainda pode ter sido montado fora da ferramenta oficial.'];
    }
    if ($hasWid && $hasSid) {
      return ['severity' => 'suspect', 'status' => 'wid_sid', 'label' => 'Suspeito', 'reason' => 'Tem wid e sid=affiliates, mas ainda pode ter sido montado fora da ferramenta oficial.'];
    }
    if ($hasWid && $hasAffiliateProfile) {
      return ['severity' => 'suspect', 'status' => 'wid_affiliate_profile', 'label' => 'Suspeito', 'reason' => 'Tem wid e sinais de affiliate-profile, mas sem todos os marcadores fortes.'];
    }
    if ($hasWid) {
      return ['severity' => 'broken', 'status' => 'wid_suspeito', 'label' => 'Errado', 'reason' => 'Tem wid, mas faltam marcadores oficiais de afiliado.'];
    }
    return ['severity' => 'broken', 'status' => 'sem_wid', 'label' => 'Errado', 'reason' => 'Link comum do produto sem marcador de afiliado do Mercado Livre.'];
  }

  if ($storeValue === 'shopee') {
    $hasAn = str_contains($value, 'an_');
    $hasMmp = str_contains($value, 'mmp_pid=');
    $hasUtmAff = str_contains($value, 'utm_medium=affiliates');
    $isShort = str_contains($value, 's.shopee.com.br/');

    if ($hasAn || $hasMmp || $hasUtmAff) {
      return ['severity' => 'ok', 'status' => 'marker_ok', 'label' => 'OK', 'reason' => 'Link com marcador visivel de afiliado da Shopee.'];
    }
    if ($isShort) {
      return ['severity' => 'ok', 'status' => 'short_oficial', 'label' => 'OK', 'reason' => 'Shortlink oficial da Shopee; o rastreio do afiliado costuma aparecer so apos o redirecionamento.'];
    }
    return ['severity' => 'broken', 'status' => 'sem_marcador', 'label' => 'Errado', 'reason' => 'Link Shopee sem marcador visivel de afiliado.'];
  }

  if ($storeValue === 'amazon') {
    $hasTag = str_contains($value, 'tag=');
    $hasAff = str_contains($value, 'aff=');
    $isShort = str_contains($value, 'amzn.to/');

    if ($hasTag) {
      return ['severity' => 'ok', 'status' => 'tag_ok', 'label' => 'OK', 'reason' => 'Link com parametro tag do Amazon Associates.'];
    }
    if ($hasAff) {
      return ['severity' => 'broken', 'status' => 'aff_errado', 'label' => 'Errado', 'reason' => 'Amazon usa tag=..., nao aff=....'];
    }
    if ($isShort) {
      return ['severity' => 'broken', 'status' => 'short_sem_tag', 'label' => 'Errado', 'reason' => 'Shortlink Amazon sem parametro tag visivel.'];
    }
    return ['severity' => 'broken', 'status' => 'sem_tag', 'label' => 'Errado', 'reason' => 'Link Amazon sem parametro tag do Associates.'];
  }

  return [
    'severity' => 'suspect',
    'status' => 'nao_classificado',
    'label' => 'Suspeito',
    'reason' => 'Loja sem regra automatica de auditoria.',
  ];
}

function admin_featured_limit_for_store($store) {
  $normalized = strtolower(trim((string) $store));
  if ($normalized === 'mercado livre') {
    return 2;
  }
  return 0;
}

function admin_enforce_featured_limit(PDO $pdo, $store, $keepOfferId = 0) {
  $limit = admin_featured_limit_for_store($store);
  if ($limit <= 0) {
    return;
  }

  $normalized = strtolower(trim((string) $store));
  $stmt = $pdo->prepare("
    SELECT id
    FROM ofertas
    WHERE LOWER(loja) = ?
      AND destaque = 1
    ORDER BY atualizado_em DESC, id DESC
  ");
  $stmt->execute([$normalized]);
  $featuredIds = array_map('intval', array_column($stmt->fetchAll(), 'id'));

  if ($keepOfferId > 0) {
    $featuredIds = array_values(array_unique(array_merge([$keepOfferId], array_diff($featuredIds, [$keepOfferId]))));
  }

  if (count($featuredIds) <= $limit) {
    return;
  }

  $idsToDisable = array_slice($featuredIds, $limit);
  if (!$idsToDisable) {
    return;
  }

  $placeholders = implode(',', array_fill(0, count($idsToDisable), '?'));
  $disableStmt = $pdo->prepare("UPDATE ofertas SET destaque = 0 WHERE id IN ({$placeholders})");
  $disableStmt->execute($idsToDisable);
}

function admin_shell_exec_enabled() {
  if (!function_exists('shell_exec')) {
    return false;
  }

  $disabled = array_filter(array_map('trim', explode(',', (string) ini_get('disable_functions'))));
  return !in_array('shell_exec', $disabled, true);
}

function admin_python_job_enabled() {
  return defined('AUTOMACAO_PYTHON_BIN')
    && defined('AUTOMACAO_PYTHON_SCRIPT')
    && AUTOMACAO_PYTHON_BIN !== ''
    && AUTOMACAO_PYTHON_SCRIPT !== '';
}

function admin_decode_python_runner_output($output) {
  $trimmed = trim((string) $output);
  if ($trimmed === '') {
    return null;
  }

  $decoded = json_decode($trimmed, true);
  if (is_array($decoded)) {
    return $decoded;
  }

  $start = strpos($trimmed, '{');
  $end = strrpos($trimmed, '}');
  if ($start !== false && $end !== false && $end > $start) {
    $jsonSlice = substr($trimmed, $start, $end - $start + 1);
    $decoded = json_decode($jsonSlice, true);
    if (is_array($decoded)) {
      return $decoded;
    }
  }

  return null;
}

function admin_strip_actor_args(array $args) {
  $clean = [];
  for ($i = 0; $i < count($args); $i++) {
    $arg = (string) $args[$i];
    if ($arg === '--actor-user-id' || $arg === '--actor-login') {
      $i++;
      continue;
    }
    $clean[] = $arg;
  }
  return $clean;
}

function admin_run_python_job(array $args) {
  if (!admin_python_job_enabled()) {
    return [
      'ok' => false,
      'error' => 'AUTOMACAO_PYTHON_BIN ou AUTOMACAO_PYTHON_SCRIPT nao configurados.',
    ];
  }

  if (!admin_shell_exec_enabled()) {
    return [
      'ok' => false,
      'error' => 'shell_exec desabilitado no PHP. Use cron/SSH no servidor.',
    ];
  }

  $scriptPath = (string) AUTOMACAO_PYTHON_SCRIPT;
  if (!is_file($scriptPath)) {
    return [
      'ok' => false,
      'error' => 'Script Python do runner nao encontrado no servidor.',
    ];
  }

  $runCommand = static function (array $commandArgs) use ($scriptPath) {
    $parts = [escapeshellarg((string) AUTOMACAO_PYTHON_BIN), escapeshellarg($scriptPath)];
    foreach ($commandArgs as $arg) {
      $parts[] = escapeshellarg((string) $arg);
    }
    $command = implode(' ', $parts) . ' 2>&1';
    return shell_exec($command);
  };

  $output = $runCommand($args);

  if ($output === null) {
    return [
      'ok' => false,
      'error' => 'Falha ao executar o comando Python no servidor.',
    ];
  }

  $decoded = admin_decode_python_runner_output($output);
  if (is_array($decoded)) {
    return $decoded;
  }

  $rawOutput = trim((string) $output);
  if ((str_contains($rawOutput, '--actor-user-id') || str_contains($rawOutput, '--actor-login'))
    && (str_contains(strtolower($rawOutput), 'unrecognized arguments') || str_contains(strtolower($rawOutput), 'error:'))) {
    $fallbackArgs = admin_strip_actor_args($args);
    if ($fallbackArgs !== $args) {
      $fallbackOutput = $runCommand($fallbackArgs);
      if ($fallbackOutput !== null) {
        $fallbackDecoded = admin_decode_python_runner_output($fallbackOutput);
        if (is_array($fallbackDecoded)) {
          return $fallbackDecoded;
        }
        $rawOutput = trim((string) $fallbackOutput);
      }
    }
  }

  return [
    'ok' => false,
    'error' => $rawOutput !== '' ? $rawOutput : 'O runner Python retornou uma resposta invalida.',
    'raw_output' => $rawOutput,
  ];
}

function admin_fetch_recent_runs(PDO $pdo, $type = 'social', $limit = 12) {
  $limit = max(1, min((int) $limit, 50));
  try {
    $stmt = $pdo->prepare("
      SELECT id, tipo, provider, canal, modo, status, requested_count, processed_count, error_message, criado_em, finalizado_em
      FROM automacao_execucoes
      WHERE tipo = ?
      ORDER BY criado_em DESC, id DESC
      LIMIT {$limit}
    ");
    $stmt->execute([(string) $type]);
    return $stmt->fetchAll();
  } catch (Throwable $e) {
    return [];
  }
}

admin_bootstrap_schema();

function admin_fetch_social_candidates(PDO $pdo, $search = '', $store = '', $limit = 24, $page = 1) {
  $limit = max(1, min((int) $limit, 60));
  $page = max(1, (int) $page);
  $where = [
    'ativo = 1',
    '(expira_em IS NULL OR expira_em > NOW())',
    "imagem_url IS NOT NULL",
    "imagem_url <> ''",
  ];
  $params = [];

  if ($store !== '') {
    $where[] = 'loja = ?';
    $params[] = $store;
  }

  if ($search !== '') {
    $like = '%' . $search . '%';
    $where[] = '(titulo LIKE ? OR categoria LIKE ? OR tags LIKE ? OR loja LIKE ?)';
    array_push($params, $like, $like, $like, $like);
  }

  $sql = "
    SELECT
      o.*,
      COUNT(c.id) AS clicks
    FROM ofertas o
    LEFT JOIN cliques c
      ON c.oferta_id = o.id
      AND c.criado_em >= NOW() - INTERVAL 30 DAY
    WHERE " . implode(' AND ', $where) . "
    GROUP BY o.id
    ORDER BY o.atualizado_em DESC, o.criado_em DESC, o.id DESC
  ";

  $stmt = $pdo->prepare($sql);
  $stmt->execute($params);
  $rows = $stmt->fetchAll() ?: [];

  $eligibleRows = array_values(array_filter($rows, static function ($row) {
    return admin_affiliate_audit($row['loja'] ?? '', $row['url_afiliado'] ?? '')['severity'] === 'ok';
  }));

  $total = count($eligibleRows);
  $pages = max(1, (int) ceil($total / max(1, $limit)));
  $page = min($page, $pages);
  $offset = ($page - 1) * $limit;

  return [
    'items' => array_slice($eligibleRows, $offset, $limit),
    'total' => $total,
    'page' => $page,
    'limit' => $limit,
    'pages' => $pages,
  ];
}

