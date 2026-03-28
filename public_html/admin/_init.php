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

function admin_schema_bootstrap_marker_path() {
  return __DIR__ . '/.admin_schema_bootstrap.json';
}

function admin_schema_bootstrap_version() {
  return '20260324_1';
}

function admin_schema_bootstrap_should_skip() {
  $path = admin_schema_bootstrap_marker_path();
  if (!is_file($path)) {
    return false;
  }

  $raw = @file_get_contents($path);
  if (!is_string($raw) || trim($raw) === '') {
    return false;
  }

  $decoded = json_decode($raw, true);
  if (!is_array($decoded)) {
    return false;
  }

  if ((string) ($decoded['version'] ?? '') !== admin_schema_bootstrap_version()) {
    return false;
  }

  $checkedAt = strtotime((string) ($decoded['checked_at'] ?? ''));
  if (!$checkedAt) {
    return false;
  }

  $ttl = ((string) ($decoded['status'] ?? '') === 'success') ? 86400 * 30 : 900;
  return (time() - $checkedAt) < $ttl;
}

function admin_schema_bootstrap_mark($status, $error = '') {
  $payload = [
    'version' => admin_schema_bootstrap_version(),
    'status' => (string) $status,
    'checked_at' => gmdate('c'),
    'error' => trim((string) $error),
  ];
  @file_put_contents(admin_schema_bootstrap_marker_path(), json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES));
}

function admin_bootstrap_schema() {
  static $done = false;
  if ($done) {
    return;
  }
  $done = true;

  if (admin_schema_bootstrap_should_skip()) {
    return;
  }

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

    admin_purge_zero_price_offers($pdo);
    admin_schema_bootstrap_mark('success');
  } catch (Throwable $e) {
    admin_schema_bootstrap_mark('error', $e->getMessage());
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

function admin_primary_nav_items() {
  return [
    ['id' => 'ofertas', 'label' => 'Ofertas', 'href' => '/admin/ofertas.php'],
    ['id' => 'nova_oferta', 'label' => '+ Nova oferta', 'href' => '/admin/oferta_editar.php'],
    ['id' => 'importar', 'label' => 'Importar', 'href' => '/admin/importar.php'],
    ['id' => 'social', 'label' => 'Social', 'href' => '/admin/social.php'],
    ['id' => 'youtube_cortes', 'label' => 'YouTube cortes', 'href' => '/admin/youtube_cortes.php'],
    ['id' => 'site', 'label' => 'Ver site', 'href' => '/'],
    ['id' => 'logout', 'label' => 'Sair', 'href' => '/admin/logout.php'],
  ];
}

function admin_offer_subnav_items() {
  return [
    ['id' => 'catalogo', 'label' => 'Catalogo', 'href' => '/admin/ofertas.php'],
    ['id' => 'clicks', 'label' => 'Cliques detalhados', 'href' => '/admin/ofertas_cliques.php'],
  ];
}

function admin_render_offer_subnav($current = 'catalogo') {
  $current = trim((string) $current);
  ?>
  <nav class="admin-subnav" aria-label="Submenu Ofertas">
    <?php foreach (admin_offer_subnav_items() as $item): ?>
      <?php $itemId = (string) ($item['id'] ?? ''); ?>
      <a class="admin-subnav-link <?= $itemId === $current ? 'is-active' : '' ?>" href="<?= h((string) ($item['href'] ?? '#')) ?>">
        <?= h((string) ($item['label'] ?? '')) ?>
      </a>
    <?php endforeach; ?>
  </nav>
  <?php
}

function admin_click_log_file() {
  return rtrim(sys_get_temp_dir(), DIRECTORY_SEPARATOR) . DIRECTORY_SEPARATOR . 'zeropreco-site-logs' . DIRECTORY_SEPARATOR . 'outbound-clicks.jsonl';
}

function admin_read_click_log_entries($limit = 200) {
  $path = admin_click_log_file();
  if (!is_file($path)) {
    return [];
  }

  $lines = @file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
  if (!is_array($lines) || !$lines) {
    return [];
  }

  $entries = [];
  for ($index = count($lines) - 1; $index >= 0; $index--) {
    $decoded = json_decode((string) $lines[$index], true);
    if (!is_array($decoded)) {
      continue;
    }
    $entries[] = $decoded;
    if (count($entries) >= max(1, (int) $limit)) {
      break;
    }
  }

  return $entries;
}

function admin_render_header($current = '') {
  $current = trim((string) $current);
  ?>
  <header>
    <div class="container admin-header">
      <div class="admin-brand">
        <a class="admin-brand-link" href="/admin/ofertas.php">
          <div class="admin-brand-mark">
            <img src="/assets/img/logo-zp.png" alt="Zero Preco">
          </div>
        </a>
        <div class="admin-brand-copy">
          <strong>Zero Pre&ccedil;o Admin</strong>
          <span>Cat&aacute;logo, afiliados e curadoria em um painel mais visual.</span>
        </div>
      </div>
      <button
        class="btn admin-menu-toggle"
        type="button"
        aria-expanded="false"
        aria-controls="admin-header-actions"
        data-admin-menu-toggle
      >
        Menu
      </button>
      <div class="admin-header-actions" id="admin-header-actions" data-admin-menu>
        <?php foreach (admin_primary_nav_items() as $item): ?>
          <?php $itemId = (string) ($item['id'] ?? ''); ?>
          <a class="<?= $itemId === $current ? 'badge is-primary' : 'badge' ?>" href="<?= h((string) ($item['href'] ?? '#')) ?>">
            <?= h((string) ($item['label'] ?? '')) ?>
          </a>
        <?php endforeach; ?>
      </div>
    </div>
  </header>
  <?php
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

function admin_offer_price_is_zero_or_less($value) {
  return admin_parse_decimal($value) <= 0;
}

function admin_purge_zero_price_offers(PDO $pdo) {
  $ids = $pdo->query("SELECT id FROM ofertas WHERE COALESCE(preco, 0) <= 0")->fetchAll(PDO::FETCH_COLUMN);
  if (!$ids) {
    return 0;
  }

  $ids = array_map('intval', $ids);
  $placeholders = implode(',', array_fill(0, count($ids), '?'));
  $pdo->prepare("DELETE FROM cliques WHERE oferta_id IN ($placeholders)")->execute($ids);
  $pdo->prepare("DELETE FROM ofertas WHERE id IN ($placeholders)")->execute($ids);
  return count($ids);
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

function admin_meli_affiliate_audit($url) {
  $value = trim((string) $url);
  $hasWid = str_contains($value, 'wid=');
  $hasSid = str_contains($value, 'sid=affiliates');
  $hasSidRecos = str_contains($value, 'sid=recos');
  $hasPolycard = str_contains($value, 'polycard_client=affiliates');
  $hasAffiliateProfile = str_contains($value, 'affiliate-profile');
  $hasSourceAffiliateProfile = str_contains($value, 'source=affiliate-profile');
  $hasRecoAffiliateProfile = str_contains($value, 'reco_client=home_affiliate-profile');
  $hasMatt = str_contains($value, 'matt_tool=');
  $hasSocial = str_contains($value, '/social/');
  $hasTrackingId = str_contains($value, 'tracking_id=');
  $hasMattEvent = str_contains($value, 'matt_event_ts=');
  $hasMattTracing = str_contains($value, 'matt_tracing_id=');
  $hasAffiliateProfileFlow = $hasSourceAffiliateProfile && $hasRecoAffiliateProfile;
  $hasAffiliateProfileTrace = $hasTrackingId || $hasMattEvent || $hasMattTracing;

  if ($hasSocial) {
    return ['severity' => 'ok', 'status' => 'social', 'label' => 'OK strict', 'reason' => 'Link social/oficial do Mercado Livre.'];
  }
  if ($hasMatt) {
    return ['severity' => 'ok', 'status' => 'matt_tool', 'label' => 'OK strict', 'reason' => 'Link com rastreio matt_tool do afiliado.'];
  }
  if ($hasWid && $hasSidRecos && $hasAffiliateProfile) {
    return ['severity' => 'suspect', 'status' => 'wid_recos_affiliate_profile', 'label' => 'Suspeito', 'reason' => 'Link veio do fluxo affiliate-profile com wid e sid=recos, mas o confiavel para o projeto continua sendo social/matt_tool.'];
  }
  if ($hasAffiliateProfileFlow && $hasAffiliateProfileTrace) {
    return ['severity' => 'suspect', 'status' => 'affiliate_profile_reco', 'label' => 'Suspeito', 'reason' => 'URL final do produto com sinais de affiliate-profile, mas sem marcador forte no proprio link.'];
  }
  if ($hasWid && $hasAffiliateProfile) {
    return ['severity' => 'suspect', 'status' => 'wid_affiliate_profile', 'label' => 'Suspeito', 'reason' => 'Tem wid e sinais de affiliate-profile, mas sem marcador forte de social/matt_tool.'];
  }
  if ($hasWid && $hasPolycard) {
    return ['severity' => 'suspect', 'status' => 'wid_polycard', 'label' => 'Suspeito', 'reason' => 'Tem wid e polycard, mas ainda pode ter sido montado fora da ferramenta oficial.'];
  }
  if ($hasWid && $hasSid) {
    return ['severity' => 'suspect', 'status' => 'wid_sid', 'label' => 'Suspeito', 'reason' => 'Tem wid e sid=affiliates, mas ainda pode ter sido montado fora da ferramenta oficial.'];
  }
  if ($hasWid) {
    return ['severity' => 'broken', 'status' => 'wid_suspeito', 'label' => 'Errado', 'reason' => 'Tem wid, mas faltam marcadores oficiais ou sinais suficientes do fluxo de afiliado.'];
  }
  return ['severity' => 'broken', 'status' => 'sem_wid', 'label' => 'Errado', 'reason' => 'Link comum do produto sem marcador visivel de afiliado do Mercado Livre.'];
}

function admin_is_meli_affiliate_url($url) {
  $audit = admin_meli_affiliate_audit($url);
  return ((string) ($audit['severity'] ?? '')) === 'ok';
}

function admin_affiliate_is_acceptable($audit) {
  return ((string) ($audit['severity'] ?? '')) === 'ok';
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
    return admin_meli_affiliate_audit($value);
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

function admin_automation_root_path() {
  if (!defined('AUTOMACAO_PYTHON_SCRIPT') || AUTOMACAO_PYTHON_SCRIPT === '') {
    return null;
  }
  $root = dirname((string) AUTOMACAO_PYTHON_SCRIPT);
  return is_dir($root) ? $root : null;
}

function admin_youtube_cuts_retention_seconds() {
  return 12 * 60 * 60;
}

function admin_youtube_cuts_runtime_dir() {
  $automationRoot = admin_automation_root_path();
  if (!$automationRoot) {
    return null;
  }

  $runtimeDir = $automationRoot . DIRECTORY_SEPARATOR . 'runtime' . DIRECTORY_SEPARATOR . 'youtube_cuts';
  return is_dir($runtimeDir) ? $runtimeDir : null;
}

function admin_delete_tree($path) {
  if (!is_dir($path)) {
    return is_file($path) ? @unlink($path) : true;
  }

  $items = @scandir($path);
  if (!is_array($items)) {
    return @rmdir($path);
  }

  foreach ($items as $item) {
    if ($item === '.' || $item === '..') {
      continue;
    }
    $child = $path . DIRECTORY_SEPARATOR . $item;
    if (is_dir($child) && !is_link($child)) {
      admin_delete_tree($child);
      continue;
    }
    @unlink($child);
  }

  return @rmdir($path);
}

function admin_youtube_cuts_job_created_ts($jobDir) {
  $manifestPath = $jobDir . DIRECTORY_SEPARATOR . 'manifest.json';
  if (is_file($manifestPath)) {
    $mtime = @filemtime($manifestPath);
    if ($mtime) {
      return (int) $mtime;
    }
  }

  $jobName = basename($jobDir);
  if (preg_match('/-(\d{14})$/', $jobName, $matches)) {
    $dt = DateTime::createFromFormat('YmdHis', $matches[1], new DateTimeZone('UTC'));
    if ($dt instanceof DateTime) {
      return $dt->getTimestamp();
    }
  }

  $dirMtime = @filemtime($jobDir);
  return $dirMtime ? (int) $dirMtime : time();
}

function admin_youtube_cuts_cleanup_expired() {
  $runtimeDir = admin_youtube_cuts_runtime_dir();
  if (!$runtimeDir) {
    return 0;
  }

  $removed = 0;
  $now = time();
  $ttl = admin_youtube_cuts_retention_seconds();
  $items = @scandir($runtimeDir);
  if (!is_array($items)) {
    return 0;
  }

  foreach ($items as $item) {
    if ($item === '.' || $item === '..') {
      continue;
    }
    $jobDir = $runtimeDir . DIRECTORY_SEPARATOR . $item;
    if (!is_dir($jobDir)) {
      continue;
    }
    $createdTs = admin_youtube_cuts_job_created_ts($jobDir);
    if (($createdTs + $ttl) > $now) {
      continue;
    }
    if (admin_delete_tree($jobDir)) {
      $removed++;
    }
  }

  return $removed;
}

function admin_youtube_cuts_delete_job($jobId) {
  $runtimeDir = admin_youtube_cuts_runtime_dir();
  $safeJobId = preg_replace('/[^A-Za-z0-9_-]+/', '', (string) $jobId);
  if (!$runtimeDir || $safeJobId === '') {
    return false;
  }

  $jobDir = realpath($runtimeDir . DIRECTORY_SEPARATOR . $safeJobId);
  if ($jobDir === false || strpos($jobDir, realpath($runtimeDir)) !== 0 || !is_dir($jobDir)) {
    return false;
  }

  return admin_delete_tree($jobDir);
}

function admin_youtube_cuts_asset_path($jobId, $filename) {
  $runtimeDir = admin_youtube_cuts_runtime_dir();
  $safeJobId = preg_replace('/[^A-Za-z0-9_-]+/', '', (string) $jobId);
  $safeFile = basename((string) $filename);
  if (!$runtimeDir || $safeJobId === '' || $safeFile === '') {
    return null;
  }

  $runtimeReal = realpath($runtimeDir);
  if ($runtimeReal === false) {
    return null;
  }

  $jobDir = realpath($runtimeReal . DIRECTORY_SEPARATOR . $safeJobId);
  if ($jobDir === false || strpos($jobDir, $runtimeReal) !== 0 || !is_dir($jobDir)) {
    return null;
  }

  $assetPath = $jobDir . DIRECTORY_SEPARATOR . $safeFile;
  if (!is_file($assetPath)) {
    return null;
  }

  $assetReal = realpath($assetPath);
  if ($assetReal === false || strpos($assetReal, $jobDir) !== 0) {
    return null;
  }

  return $assetReal;
}

function admin_youtube_cuts_list_jobs($limit = 20) {
  admin_youtube_cuts_cleanup_expired();

  $runtimeDir = admin_youtube_cuts_runtime_dir();
  $runtimeReal = $runtimeDir ? realpath($runtimeDir) : false;
  if ($runtimeReal === false) {
    return [];
  }

  $jobs = [];
  foreach (glob($runtimeReal . DIRECTORY_SEPARATOR . '*', GLOB_ONLYDIR) ?: [] as $jobDir) {
    $manifestPath = $jobDir . DIRECTORY_SEPARATOR . 'manifest.json';
    if (!is_file($manifestPath)) {
      continue;
    }

    $manifest = json_decode((string) @file_get_contents($manifestPath), true);
    if (!is_array($manifest)) {
      continue;
    }

    $createdTs = admin_youtube_cuts_job_created_ts($jobDir);
    $expiresTs = $createdTs + admin_youtube_cuts_retention_seconds();
    $cuts = array_values(array_filter((array) ($manifest['cuts'] ?? []), static function ($cut) {
      return is_array($cut) && !empty($cut['video_filename']);
    }));
    $totalBytes = 0;
    foreach ($cuts as $cut) {
      $path = $jobDir . DIRECTORY_SEPARATOR . basename((string) ($cut['video_filename'] ?? ''));
      if (is_file($path)) {
        $totalBytes += (int) @filesize($path);
      }
    }

    $jobs[] = [
      'job_id' => (string) ($manifest['job_id'] ?? basename($jobDir)),
      'mode' => (string) ($manifest['mode'] ?? 'short'),
      'selection_strategy' => (string) ($manifest['selection_strategy'] ?? ''),
      'target_channel_profile_id' => (int) ($manifest['target_channel_profile_id'] ?? 0),
      'target_channel_profile_name' => (string) ($manifest['target_channel_profile_name'] ?? ''),
      'video' => is_array($manifest['video'] ?? null) ? $manifest['video'] : [],
      'transcript' => is_array($manifest['transcript'] ?? null) ? $manifest['transcript'] : [],
      'cuts' => $cuts,
      'created_ts' => $createdTs,
      'expires_ts' => $expiresTs,
      'manifest_path' => $manifestPath,
      'total_bytes' => $totalBytes,
    ];
  }

  usort($jobs, static function ($a, $b) {
    return (int) ($b['created_ts'] ?? 0) <=> (int) ($a['created_ts'] ?? 0);
  });

  return array_slice($jobs, 0, max(1, min((int) $limit, 100)));
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

function admin_python_job_runtime_dir() {
  $automationRoot = admin_automation_root_path();
  if (!$automationRoot) {
    return null;
  }

  $runtimeDir = $automationRoot . DIRECTORY_SEPARATOR . 'runtime' . DIRECTORY_SEPARATOR . 'admin_python_jobs';
  if (!is_dir($runtimeDir)) {
    @mkdir($runtimeDir, 0775, true);
  }
  return is_dir($runtimeDir) ? $runtimeDir : null;
}

function admin_python_job_file_path($jobId, $extension) {
  $runtimeDir = admin_python_job_runtime_dir();
  $safeJobId = preg_replace('/[^A-Za-z0-9_-]+/', '', (string) $jobId);
  $safeExtension = preg_replace('/[^A-Za-z0-9]+/', '', (string) $extension);
  if (!$runtimeDir || $safeJobId === '' || $safeExtension === '') {
    return null;
  }
  return $runtimeDir . DIRECTORY_SEPARATOR . $safeJobId . '.' . $safeExtension;
}

function admin_python_job_command(array $args) {
  $scriptPath = (string) AUTOMACAO_PYTHON_SCRIPT;
  $parts = [escapeshellarg((string) AUTOMACAO_PYTHON_BIN), escapeshellarg($scriptPath)];
  foreach ($args as $arg) {
    $parts[] = escapeshellarg((string) $arg);
  }
  return implode(' ', $parts);
}

function admin_write_python_job_meta($jobId, array $meta) {
  $metaPath = admin_python_job_file_path($jobId, 'json');
  if (!$metaPath) {
    return false;
  }
  return @file_put_contents($metaPath, json_encode($meta, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES)) !== false;
}

function admin_read_python_job_meta($jobId) {
  $metaPath = admin_python_job_file_path($jobId, 'json');
  if (!$metaPath || !is_file($metaPath)) {
    return null;
  }
  $decoded = json_decode((string) @file_get_contents($metaPath), true);
  return is_array($decoded) ? $decoded : null;
}

function admin_start_python_job_async(array $args, array $meta = []) {
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

  $jobId = 'pyjob_' . gmdate('YmdHis') . '_' . bin2hex(random_bytes(4));
  $outputPath = admin_python_job_file_path($jobId, 'out');
  $exitPath = admin_python_job_file_path($jobId, 'exit');
  if (!$outputPath || !$exitPath) {
    return [
      'ok' => false,
      'error' => 'Nao foi possivel preparar o diretório de jobs do admin.',
    ];
  }

  @unlink($outputPath);
  @unlink($exitPath);
  admin_write_python_job_meta($jobId, [
    'job_id' => $jobId,
    'status' => 'running',
    'created_at' => gmdate('c'),
    'kind' => (string) ($meta['kind'] ?? 'generic'),
    'target_tab' => (string) ($meta['target_tab'] ?? 'gerar'),
    'args' => array_values($args),
  ]);

  $runnerCommand = admin_python_job_command($args);
  $backgroundCommand = "nohup sh -c "
    . escapeshellarg($runnerCommand . ' > ' . escapeshellarg($outputPath) . ' 2>&1; status=$?; printf "%s" "$status" > ' . escapeshellarg($exitPath))
    . ' >/dev/null 2>&1 & echo $!';
  $pid = trim((string) shell_exec($backgroundCommand));

  if ($pid === '') {
    return [
      'ok' => false,
      'error' => 'Falha ao iniciar o job Python em segundo plano.',
    ];
  }

  $storedMeta = admin_read_python_job_meta($jobId) ?: [];
  $storedMeta['pid'] = $pid;
  admin_write_python_job_meta($jobId, $storedMeta);

  return [
    'ok' => true,
    'job_id' => $jobId,
    'pid' => $pid,
  ];
}

function admin_python_job_status($jobId) {
  $meta = admin_read_python_job_meta($jobId);
  if (!is_array($meta)) {
    return [
      'ok' => false,
      'error' => 'Job do admin nao encontrado.',
    ];
  }

  $outputPath = admin_python_job_file_path($jobId, 'out');
  $exitPath = admin_python_job_file_path($jobId, 'exit');
  $rawOutput = $outputPath && is_file($outputPath) ? trim((string) @file_get_contents($outputPath)) : '';
  $elapsedSeconds = max(0, time() - strtotime((string) ($meta['created_at'] ?? 'now')));

  if (!$exitPath || !is_file($exitPath)) {
    return [
      'ok' => true,
      'status' => 'running',
      'job' => $meta,
      'elapsed_seconds' => $elapsedSeconds,
      'raw_output' => $rawOutput,
    ];
  }

  $exitCode = (int) trim((string) @file_get_contents($exitPath));
  $decoded = admin_decode_python_runner_output($rawOutput);
  $success = is_array($decoded) && !empty($decoded['ok']) && $exitCode === 0;
  $status = $success ? 'success' : 'error';
  $meta['status'] = $status;
  $meta['finished_at'] = gmdate('c');
  admin_write_python_job_meta($jobId, $meta);

  return [
    'ok' => true,
    'status' => $status,
    'job' => $meta,
    'elapsed_seconds' => $elapsedSeconds,
    'payload' => is_array($decoded) ? $decoded : null,
    'raw_output' => $rawOutput,
    'exit_code' => $exitCode,
  ];
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
    return admin_affiliate_is_acceptable(admin_affiliate_audit($row['loja'] ?? '', $row['url_afiliado'] ?? ''));
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

