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
  return '20260331_3';
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
    if (!isset($offerColumns['imagem_urls_json'])) {
      $pdo->exec("ALTER TABLE ofertas ADD COLUMN imagem_urls_json MEDIUMTEXT NULL AFTER imagem_url");
    }
    if (!isset($offerColumns['video_urls_json'])) {
      $pdo->exec("ALTER TABLE ofertas ADD COLUMN video_urls_json MEDIUMTEXT NULL AFTER imagem_urls_json");
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

    $pdo->exec("
      CREATE TABLE IF NOT EXISTS shopee_video_drafts (
        id INT AUTO_INCREMENT PRIMARY KEY,
        oferta_id INT NOT NULL,
        status VARCHAR(40) NOT NULL DEFAULT 'manual_ready',
        publish_mode VARCHAR(20) NOT NULL DEFAULT 'manual',
        title_snapshot VARCHAR(255) NOT NULL,
        price_snapshot DECIMAL(10,2) NOT NULL DEFAULT 0,
        caption TEXT NULL,
        affiliate_url TEXT NOT NULL,
        offer_url TEXT NULL,
        video_source_url TEXT NULL,
        image_url TEXT NULL,
        notes TEXT NULL,
        creative_payload_json MEDIUMTEXT NULL,
        package_payload_json MEDIUMTEXT NULL,
        package_status VARCHAR(40) NOT NULL DEFAULT 'not_started',
        package_job_id VARCHAR(140) NULL,
        package_error TEXT NULL,
        package_generated_at DATETIME NULL,
        api_status VARCHAR(40) NOT NULL DEFAULT 'not_supported',
        api_response_json MEDIUMTEXT NULL,
        last_error TEXT NULL,
        created_by_admin_id INT NULL,
        created_by_login VARCHAR(180) NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        published_at DATETIME NULL,
        UNIQUE KEY ux_shopee_video_drafts_oferta_id (oferta_id),
        KEY ix_shopee_video_drafts_status (status),
        KEY ix_shopee_video_drafts_publish_mode (publish_mode),
        CONSTRAINT fk_shopee_video_drafts_oferta FOREIGN KEY (oferta_id) REFERENCES ofertas(id) ON DELETE CASCADE
      ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ");

    $draftColumns = [];
    foreach ($pdo->query("SHOW COLUMNS FROM shopee_video_drafts") as $column) {
      $draftColumns[(string) $column['Field']] = true;
    }
    if (!isset($draftColumns['creative_payload_json'])) {
      $pdo->exec("ALTER TABLE shopee_video_drafts ADD COLUMN creative_payload_json MEDIUMTEXT NULL AFTER notes");
    }
    if (!isset($draftColumns['package_payload_json'])) {
      $pdo->exec("ALTER TABLE shopee_video_drafts ADD COLUMN package_payload_json MEDIUMTEXT NULL AFTER creative_payload_json");
    }
    if (!isset($draftColumns['package_status'])) {
      $pdo->exec("ALTER TABLE shopee_video_drafts ADD COLUMN package_status VARCHAR(40) NOT NULL DEFAULT 'not_started' AFTER package_payload_json");
      $pdo->exec("ALTER TABLE shopee_video_drafts ADD INDEX ix_shopee_video_drafts_package_status (package_status)");
    }
    if (!isset($draftColumns['package_job_id'])) {
      $pdo->exec("ALTER TABLE shopee_video_drafts ADD COLUMN package_job_id VARCHAR(140) NULL AFTER package_status");
    }
    if (!isset($draftColumns['package_error'])) {
      $pdo->exec("ALTER TABLE shopee_video_drafts ADD COLUMN package_error TEXT NULL AFTER package_job_id");
    }
    if (!isset($draftColumns['package_generated_at'])) {
      $pdo->exec("ALTER TABLE shopee_video_drafts ADD COLUMN package_generated_at DATETIME NULL AFTER package_error");
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
    ['id' => 'auditoria', 'label' => 'Auditoria', 'href' => '/admin/auditoria_links.php'],
    ['id' => 'importar', 'label' => 'Importar', 'href' => '/admin/importar.php'],
    ['id' => 'social', 'label' => 'Social', 'href' => '/admin/social.php'],
    ['id' => 'shopee_video', 'label' => 'Shopee Video', 'href' => '/admin/shopee_video.php'],
    ['id' => 'youtube_cortes', 'label' => 'YouTube cortes', 'href' => '/admin/youtube_cortes.php'],
    ['id' => 'site', 'label' => 'Ver site', 'href' => '/'],
    ['id' => 'logout', 'label' => 'Sair', 'href' => '/admin/logout.php'],
  ];
}

function admin_offer_subnav_items() {
  return [
    ['id' => 'catalogo', 'label' => 'Catalogo', 'href' => '/admin/ofertas.php'],
    ['id' => 'clicks', 'label' => 'Cliques detalhados', 'href' => '/admin/ofertas_cliques.php'],
    ['id' => 'auditoria', 'label' => 'Auditoria links', 'href' => '/admin/auditoria_links.php'],
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
  $host = strtolower((string) parse_url($value, PHP_URL_HOST));
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

  if ($host === 'meli.la') {
    return ['severity' => 'ok', 'status' => 'meli_short', 'label' => 'OK strict', 'reason' => 'Shortlink oficial gerado na Central de Afiliados do Mercado Livre.'];
  }
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

  $lines = preg_split('/\R+/', $trimmed) ?: [];
  for ($index = count($lines) - 1; $index >= 0; $index--) {
    $line = trim((string) ($lines[$index] ?? ''));
    if ($line === '' || strpos($line, '{') === false || strrpos($line, '}') === false) {
      continue;
    }
    $lineStart = strpos($line, '{');
    $lineEnd = strrpos($line, '}');
    if ($lineStart === false || $lineEnd === false || $lineEnd <= $lineStart) {
      continue;
    }
    $jsonLineSlice = substr($line, $lineStart, $lineEnd - $lineStart + 1);
    $decoded = json_decode($jsonLineSlice, true);
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
  $parts = [
    'PYTHONIOENCODING=UTF-8',
    'PYTHONUTF8=1',
    'LC_ALL=C.UTF-8',
    'LANG=C.UTF-8',
    escapeshellarg((string) AUTOMACAO_PYTHON_BIN),
    escapeshellarg($scriptPath),
  ];
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
  $storedMeta = array_merge($meta, [
    'job_id' => $jobId,
    'status' => 'running',
    'created_at' => gmdate('c'),
    'kind' => (string) ($meta['kind'] ?? 'generic'),
    'target_tab' => (string) ($meta['target_tab'] ?? 'gerar'),
    'args' => array_values($args),
  ]);
  admin_write_python_job_meta($jobId, $storedMeta);

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

  $storedMeta = admin_read_python_job_meta($jobId) ?: $storedMeta;
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
    $parts = [
      'PYTHONIOENCODING=UTF-8',
      'PYTHONUTF8=1',
      'LC_ALL=C.UTF-8',
      'LANG=C.UTF-8',
      escapeshellarg((string) AUTOMACAO_PYTHON_BIN),
      escapeshellarg($scriptPath),
    ];
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

function admin_shopee_social_story_public_url($filename) {
  $name = trim((string) $filename);
  if ($name === '' || preg_match('/[\/\\\\]/', $name)) {
    return '';
  }
  return '/stories/' . rawurlencode($name);
}

function admin_shopee_social_story_local_path($filename) {
  $name = trim((string) $filename);
  if ($name === '' || preg_match('/[\/\\\\]/', $name)) {
    return null;
  }
  $path = dirname(__DIR__) . DIRECTORY_SEPARATOR . 'stories' . DIRECTORY_SEPARATOR . $name;
  return is_file($path) ? $path : null;
}

function admin_fetch_recent_social_reel_assets(PDO $pdo, $store = 'Shopee', $search = '', $limit = 60, $offerId = 0) {
  $limit = max(1, min((int) $limit, 100));
  $normalizedStore = trim((string) $store);
  $normalizedSearch = trim((string) $search);
  $requestedOfferId = max(0, (int) $offerId);

  try {
    $stmt = $pdo->query("
      SELECT id, canal, modo, status, criado_em, result_json
      FROM automacao_execucoes
      WHERE tipo = 'social'
        AND status <> 'running'
        AND result_json IS NOT NULL
      ORDER BY criado_em DESC, id DESC
      LIMIT 120
    ");
    $runs = $stmt->fetchAll() ?: [];
  } catch (Throwable $e) {
    return [];
  }

  $assetsByOfferId = [];
  foreach ($runs as $run) {
    $result = admin_decode_json_assoc($run['result_json'] ?? '');
    $items = is_array($result['items'] ?? null) ? $result['items'] : [];
    foreach ($items as $item) {
      $currentOfferId = (int) ($item['offer_id'] ?? 0);
      if ($currentOfferId <= 0) {
        continue;
      }
      if ($requestedOfferId > 0 && $currentOfferId !== $requestedOfferId) {
        continue;
      }
      if (isset($assetsByOfferId[$currentOfferId])) {
        continue;
      }
      $reelFile = trim((string) ($item['reel_file'] ?? ''));
      if ($reelFile === '') {
        continue;
      }
      $localPath = admin_shopee_social_story_local_path($reelFile);
      if ($localPath === null) {
        continue;
      }
      $assetsByOfferId[$currentOfferId] = [
        'offer_id' => $currentOfferId,
        'social_reel_file' => $reelFile,
        'social_reel_local_path' => $localPath,
        'social_reel_public_url' => admin_shopee_social_story_public_url($reelFile),
        'social_run_id' => (int) ($run['id'] ?? 0),
        'social_channel' => (string) ($run['canal'] ?? ''),
        'social_mode' => (string) ($run['modo'] ?? ''),
        'social_status' => (string) ($run['status'] ?? ''),
        'social_created_at' => (string) ($run['criado_em'] ?? ''),
        'social_reel_source' => (string) ($item['reel_source'] ?? ''),
      ];
      if ($requestedOfferId > 0) {
        break 2;
      }
    }
  }

  if (!$assetsByOfferId) {
    return [];
  }

  $offerIds = array_keys($assetsByOfferId);
  $placeholders = implode(',', array_fill(0, count($offerIds), '?'));
  $sql = "
    SELECT o.*
    FROM ofertas o
    WHERE o.id IN ($placeholders)
      AND o.loja = ?
      AND o.ativo = 1
      AND (o.expira_em IS NULL OR o.expira_em > NOW())
  ";
  $params = $offerIds;
  $params[] = $normalizedStore !== '' ? $normalizedStore : 'Shopee';

  try {
    $stmt = $pdo->prepare($sql);
    $stmt->execute($params);
    $offers = $stmt->fetchAll() ?: [];
  } catch (Throwable $e) {
    return [];
  }

  $matches = [];
  foreach ($offerIds as $currentOfferId) {
    foreach ($offers as $offer) {
      if ((int) ($offer['id'] ?? 0) !== (int) $currentOfferId) {
        continue;
      }
      if (!admin_affiliate_is_acceptable(admin_affiliate_audit($offer['loja'] ?? '', $offer['url_afiliado'] ?? ''))) {
        continue;
      }
      if ($normalizedSearch !== '') {
        $haystack = mb_strtolower(trim(implode(' ', [
          (string) ($offer['titulo'] ?? ''),
          (string) ($offer['categoria'] ?? ''),
          (string) ($offer['tags'] ?? ''),
        ])), 'UTF-8');
        $needle = mb_strtolower($normalizedSearch, 'UTF-8');
        if ($needle !== '' && !str_contains($haystack, $needle)) {
          continue;
        }
      }
      $matches[] = $offer + $assetsByOfferId[$currentOfferId];
      break;
    }
    if (count($matches) >= $limit) {
      break;
    }
  }

  return $matches;
}

function admin_fetch_recent_social_reel_asset(PDO $pdo, $offerId) {
  $items = admin_fetch_recent_social_reel_assets($pdo, 'Shopee', '', 1, (int) $offerId);
  return $items ? $items[0] : null;
}

function admin_decode_json_assoc($value) {
  if (is_array($value)) {
    return $value;
  }

  $raw = trim((string) $value);
  if ($raw === '') {
    return null;
  }

  $decoded = json_decode($raw, true);
  return is_array($decoded) ? $decoded : null;
}

function admin_shopee_cleanup_summary_from_result($result) {
  $payload = is_array($result['result'] ?? null) ? $result['result'] : (is_array($result) ? $result : []);
  $processedTotal = max(0, (int) ($payload['processed_total'] ?? 0));
  $trimmedDeleted = max(0, (int) ($payload['trimmed_deleted'] ?? $payload['shopee_pool_trimmed_deleted'] ?? 0));
  $invalidDeleted = max(0, (int) ($payload['invalid_deleted'] ?? $payload['shopee_pool_invalid_deleted'] ?? 0));
  $checkedLinks = max(0, (int) ($payload['checked_links'] ?? $payload['shopee_pool_checked_links'] ?? 0));
  $keepLatest = max(0, (int) ($payload['kept_latest'] ?? $payload['shopee_pool_keep_latest'] ?? 0));
  $keptCount = 0;

  if ($processedTotal > 0) {
    $keptCount = max(0, $processedTotal - $trimmedDeleted - $invalidDeleted);
  } elseif ($keepLatest > 0) {
    $keptCount = max(0, $keepLatest - $invalidDeleted);
  }

  return [
    'processed_total' => $processedTotal,
    'kept_count' => $keptCount,
    'keep_latest' => $keepLatest,
    'checked_links' => $checkedLinks,
    'trimmed_deleted' => $trimmedDeleted,
    'invalid_deleted' => $invalidDeleted,
    'has_data' => ($processedTotal + $checkedLinks + $trimmedDeleted + $invalidDeleted + $keepLatest) > 0,
  ];
}

function admin_fetch_latest_shopee_cleanup_run(PDO $pdo) {
  try {
    $stmt = $pdo->query("
      SELECT id, tipo, provider, modo, status, requested_count, processed_count, error_message, criado_em, finalizado_em, result_json
      FROM automacao_execucoes
      WHERE tipo = 'maintenance'
        AND provider = 'shopee'
        AND modo = 'cleanup'
      ORDER BY criado_em DESC, id DESC
      LIMIT 1
    ");
    $row = $stmt->fetch();
    if (!$row) {
      return null;
    }

    $result = admin_decode_json_assoc($row['result_json'] ?? '');
    $row['result'] = $result ?: [];
    $row['summary'] = admin_shopee_cleanup_summary_from_result($result ?: []);
    return $row;
  } catch (Throwable $e) {
    return null;
  }
}

function admin_fetch_shopee_catalog_snapshot(PDO $pdo) {
  try {
    $currentCount = (int) $pdo->query("SELECT COUNT(*) FROM ofertas WHERE LOWER(loja) = 'shopee'")->fetchColumn();
  } catch (Throwable $e) {
    $currentCount = 0;
  }

  return [
    'current_count' => $currentCount,
    'latest_cleanup' => admin_fetch_latest_shopee_cleanup_run($pdo),
  ];
}

admin_bootstrap_schema();

function admin_fetch_social_candidates(PDO $pdo, $search = '', $store = '', $limit = 24, $page = 1, $onlyWithVideo = false) {
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

  if ($onlyWithVideo) {
    $where[] = "(tags LIKE '%offer_video_url:%' OR tags LIKE '%shopee_video_url:%' OR (video_urls_json IS NOT NULL AND video_urls_json <> '' AND video_urls_json <> '[]'))";
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

function admin_shopee_video_offer_video_url($offer) {
  $manualVideo = trim((string) tag_url_decode($offer['tags'] ?? '', 'offer_video_url:'));
  if ($manualVideo !== '') {
    return $manualVideo;
  }
  $shopeeTaggedVideo = trim((string) tag_url_decode($offer['tags'] ?? '', 'shopee_video_url:'));
  if ($shopeeTaggedVideo !== '' && preg_match('~\.(mp4|m4v|webm|mov)(?:[?#].*)?$~i', $shopeeTaggedVideo)) {
    return $shopeeTaggedVideo;
  }
  $videoGallery = admin_shopee_video_decode_url_list($offer['video_urls_json'] ?? ($offer['video_urls'] ?? []));
  if ($videoGallery) {
    return trim((string) $videoGallery[0]);
  }
  return '';
}

function admin_env_value($key, $default = '') {
  $name = trim((string) $key);
  if ($name === '') {
    return $default;
  }

  $runtimeValue = getenv($name);
  if ($runtimeValue !== false && trim((string) $runtimeValue) !== '') {
    return trim((string) $runtimeValue);
  }

  static $parsedFiles = null;
  if ($parsedFiles === null) {
    $parsedFiles = [];
    $paths = [
      dirname(__DIR__, 2) . DIRECTORY_SEPARATOR . 'automacao_ofertas' . DIRECTORY_SEPARATOR . '.env',
      dirname(__DIR__, 2) . DIRECTORY_SEPARATOR . '.env',
    ];
    foreach ($paths as $path) {
      if (!is_file($path)) {
        continue;
      }
      $rows = @file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
      if (!is_array($rows)) {
        continue;
      }
      foreach ($rows as $row) {
        $line = trim((string) $row);
        if ($line === '' || str_starts_with($line, '#') || !str_contains($line, '=')) {
          continue;
        }
        [$envKey, $envValue] = explode('=', $line, 2);
        $envKey = trim((string) $envKey);
        if ($envKey === '' || isset($parsedFiles[$envKey])) {
          continue;
        }
        $envValue = trim((string) $envValue);
        if ((str_starts_with($envValue, '"') && str_ends_with($envValue, '"')) || (str_starts_with($envValue, "'") && str_ends_with($envValue, "'"))) {
          $envValue = substr($envValue, 1, -1);
        }
        $parsedFiles[$envKey] = $envValue;
      }
    }
  }

  return array_key_exists($name, $parsedFiles) ? (string) $parsedFiles[$name] : $default;
}

function admin_shopee_video_api_snapshot() {
  $credential = trim((string) (admin_env_value('SHOPEE_API_KEY') ?: admin_env_value('SHOPEE_APP_ID') ?: admin_env_value('SHOPEE_PARTNER_ID') ?: ''));
  $secret = trim((string) (admin_env_value('SHOPEE_API_SECRET') ?: admin_env_value('SHOPEE_SECRET_KEY') ?: ''));
  return [
    'catalog_api_configured' => $credential !== '' && $secret !== '',
    'publish_api_supported' => false,
    'publish_api_status' => 'not_confirmed_public',
    'publish_api_message' => 'Nao ha endpoint publico confirmado para publicar no feed do Shopee Video.',
  ];
}

function admin_shopee_video_json_decode($value) {
  $raw = trim((string) $value);
  if ($raw === '') {
    return null;
  }
  $decoded = json_decode($raw, true);
  return is_array($decoded) ? $decoded : null;
}

function admin_shopee_video_decode_url_list($value) {
  if (is_array($value)) {
    $rawItems = $value;
  } else {
    $decoded = admin_shopee_video_json_decode($value);
    if (is_array($decoded)) {
      $rawItems = $decoded;
    } else {
      $raw = trim((string) $value);
      $rawItems = $raw !== '' ? [$raw] : [];
    }
  }

  $urls = [];
  foreach ($rawItems as $item) {
    $url = trim((string) $item);
    if ($url === '' || !preg_match('~^https?://~i', $url)) {
      continue;
    }
    if (in_array($url, $urls, true)) {
      continue;
    }
    $urls[] = $url;
  }
  return $urls;
}

function admin_shopee_video_offer_gallery_urls($offer) {
  $gallery = admin_shopee_video_decode_url_list($offer['imagem_urls_json'] ?? ($offer['image_urls'] ?? []));
  $primary = trim((string) ($offer['imagem_url'] ?? ($offer['image_url'] ?? '')));
  if ($primary !== '' && !in_array($primary, $gallery, true)) {
    array_unshift($gallery, $primary);
  }
  return $gallery;
}

function admin_shopee_video_offer_video_gallery_urls($offer) {
  $gallery = admin_shopee_video_decode_url_list($offer['video_urls_json'] ?? ($offer['video_urls'] ?? []));
  $primary = trim((string) ($offer['video_url'] ?? ($offer['video_source_url'] ?? '')));
  if ($primary !== '' && !in_array($primary, $gallery, true)) {
    array_unshift($gallery, $primary);
  }
  return $gallery;
}

function admin_shopee_video_money($value) {
  return 'R$ ' . number_format((float) $value, 2, ',', '.');
}

function admin_shopee_video_discount_percent($offer) {
  if (isset($offer['desconto_percentual']) && $offer['desconto_percentual'] !== null && $offer['desconto_percentual'] !== '') {
    return max(0, (int) round((float) $offer['desconto_percentual']));
  }
  $price = (float) ($offer['preco'] ?? 0);
  $oldPrice = (float) ($offer['preco_antigo'] ?? 0);
  if ($price <= 0 || $oldPrice <= $price) {
    return 0;
  }
  return max(0, (int) round((($oldPrice - $price) / $oldPrice) * 100));
}

function admin_shopee_video_category_hashtags($category) {
  $normalized = strtolower(trim((string) $category));
  $map = [
    'celular' => ['#celular', '#smartphone'],
    'fone' => ['#fonebluetooth', '#fone'],
    'beleza' => ['#beleza', '#autocuidado'],
    'casa' => ['#achadinhosdecasa', '#utilidadesdomesticas'],
    'cozinha' => ['#cozinha', '#utilidadesdomesticas'],
    'moda' => ['#moda', '#look'],
    'eletron' => ['#eletronicos', '#gadget'],
    'gamer' => ['#setupgamer', '#gamer'],
  ];
  foreach ($map as $keyword => $hashtags) {
    if ($normalized !== '' && str_contains($normalized, $keyword)) {
      return $hashtags;
    }
  }
  return ['#achadinhos', '#promocao'];
}

function admin_shopee_video_normalize_hashtag_token($value) {
  $raw = trim((string) $value);
  if ($raw === '') {
    return '';
  }
  if (preg_match('~^https?://~i', $raw)) {
    return '';
  }
  if (str_contains($raw, ':')) {
    return '';
  }
  $slug = str_replace('-', '', slugify($raw));
  if ($slug === '') {
    return '';
  }
  return '#' . strtolower($slug);
}

function admin_shopee_video_offer_hashtags($offer, $limit = 6) {
  $limit = max(1, (int) $limit);
  $hashtags = [];

  $rawTags = preg_split('/[\r\n,]+/', (string) ($offer['tags'] ?? '')) ?: [];
  foreach ($rawTags as $tag) {
    $normalized = admin_shopee_video_normalize_hashtag_token($tag);
    if ($normalized === '' || in_array($normalized, $hashtags, true)) {
      continue;
    }
    $hashtags[] = $normalized;
    if (count($hashtags) >= $limit) {
      return $hashtags;
    }
  }

  foreach (admin_shopee_video_category_hashtags($offer['categoria'] ?? '') as $tag) {
    $normalized = admin_shopee_video_normalize_hashtag_token($tag);
    if ($normalized === '' || in_array($normalized, $hashtags, true)) {
      continue;
    }
    $hashtags[] = $normalized;
    if (count($hashtags) >= $limit) {
      return $hashtags;
    }
  }

  foreach (['#shopee', '#shopeevideo', '#ofertas', '#achadinhos'] as $tag) {
    if (!in_array($tag, $hashtags, true)) {
      $hashtags[] = $tag;
    }
    if (count($hashtags) >= $limit) {
      break;
    }
  }

  return $hashtags;
}

function admin_shopee_video_truncate_text($value, $maxChars) {
  $text = trim((string) $value);
  $maxChars = max(1, (int) $maxChars);
  if ($text === '') {
    return '';
  }
  if (function_exists('mb_strlen') && function_exists('mb_substr')) {
    if (mb_strlen($text, 'UTF-8') <= $maxChars) {
      return $text;
    }
    return rtrim((string) mb_substr($text, 0, max(1, $maxChars - 1), 'UTF-8')) . '…';
  }
  if (strlen($text) <= $maxChars) {
    return $text;
  }
  return rtrim(substr($text, 0, max(1, $maxChars - 3))) . '...';
}

function admin_shopee_video_compact_caption($offer, $maxChars = 150) {
  $title = trim((string) ($offer['titulo'] ?? $offer['title_snapshot'] ?? 'Oferta Shopee'));
  $price = admin_shopee_video_money($offer['preco'] ?? 0);
  $discount = admin_shopee_video_discount_percent($offer);
  $coupon = trim((string) ($offer['cupom'] ?? ''));
  $hashtags = admin_shopee_video_offer_hashtags($offer, 5);
  $hashtagsText = implode(' ', $hashtags);

  $baseCandidates = [];
  if ($coupon !== '') {
    $baseCandidates[] = 'Cupom ' . $coupon . ' no ' . $title . ' por ' . $price . '.';
    $baseCandidates[] = $title . ' com cupom por ' . $price . '.';
  }
  if ($discount > 0) {
    $baseCandidates[] = $title . ' com ' . $discount . '% off por ' . $price . '.';
  }
  $baseCandidates[] = $title . ' por ' . $price . ' na Shopee.';
  $baseCandidates[] = $title . ' por ' . $price . '.';
  $baseCandidates[] = 'Achado Shopee por ' . $price . '.';

  foreach ($baseCandidates as $candidate) {
    $final = trim($hashtagsText . ' ' . $candidate);
    if ((function_exists('mb_strlen') ? mb_strlen($final, 'UTF-8') : strlen($final)) <= $maxChars) {
      return $final;
    }
  }

  $reserve = ($hashtagsText !== '' ? ((function_exists('mb_strlen') ? mb_strlen($hashtagsText, 'UTF-8') : strlen($hashtagsText)) + 1) : 0);
  $available = max(20, (int) $maxChars - $reserve);
  $shortTitle = admin_shopee_video_truncate_text($title, max(12, $available - 12));
  $fallback = trim($hashtagsText . ' ' . $shortTitle . ' ' . $price);
  if ((function_exists('mb_strlen') ? mb_strlen($fallback, 'UTF-8') : strlen($fallback)) <= $maxChars) {
    return $fallback;
  }

  return admin_shopee_video_truncate_text(trim($hashtagsText . ' ' . $price), $maxChars);
}

function admin_shopee_video_variant_seed($offer, $salt = '') {
  $base = implode('|', [
    (string) ($offer['id'] ?? $offer['oferta_id'] ?? ''),
    trim((string) ($offer['titulo'] ?? $offer['title_snapshot'] ?? '')),
    (string) $salt,
  ]);
  return abs((int) crc32($base));
}

function admin_shopee_video_pick_variant($offer, $salt, array $options) {
  if (!$options) {
    return '';
  }
  $index = admin_shopee_video_variant_seed($offer, $salt) % count($options);
  return (string) ($options[$index] ?? $options[0]);
}

function admin_shopee_video_build_creative_payload($offer) {
  $title = trim((string) ($offer['titulo'] ?? $offer['title_snapshot'] ?? 'Oferta Shopee'));
  $price = admin_shopee_video_money($offer['preco'] ?? 0);
  $oldPriceValue = isset($offer['preco_antigo']) ? (float) $offer['preco_antigo'] : 0.0;
  $oldPrice = $oldPriceValue > 0 ? admin_shopee_video_money($oldPriceValue) : '';
  $pixPriceValue = isset($offer['preco_pix']) ? (float) $offer['preco_pix'] : 0.0;
  $pixPrice = $pixPriceValue > 0 ? admin_shopee_video_money($pixPriceValue) : '';
  $coupon = trim((string) ($offer['cupom'] ?? ''));
  $shipping = trim((string) ($offer['frete_texto'] ?? ''));
  $installments = trim((string) ($offer['parcelas_texto'] ?? ''));
  $category = trim((string) ($offer['categoria'] ?? 'Achadinhos'));
  $discount = admin_shopee_video_discount_percent($offer);

  $angle = 'achadinho util do dia';
  if ($coupon !== '') {
    $angle = 'cupom e acao imediata';
  } elseif ($discount >= 35) {
    $angle = 'desconto agressivo';
  } elseif ($pixPrice !== '') {
    $angle = 'preco no pix';
  } elseif ($shipping !== '') {
    $angle = 'beneficio de frete';
  }

  if ($coupon !== '') {
    $hook = admin_shopee_video_pick_variant($offer, 'hook_coupon', [
      'Cupom na Shopee e produto chamando clique: ' . $title,
      'Achado com cupom na Shopee: ' . $title,
      'Se liga nesse achado com cupom: ' . $title,
    ]);
    $coverText = admin_shopee_video_pick_variant($offer, 'cover_coupon', [
      'CUPOM + ' . $price,
      'CUPOM ' . $coupon,
      'OFERTA + ' . $price,
    ]);
  } elseif ($discount >= 35) {
    $hook = admin_shopee_video_pick_variant($offer, 'hook_discount', [
      'Olha esse achado na Shopee com ' . $discount . '% off',
      'Desconto forte na Shopee: ' . $discount . '% off nesse produto',
      'Esse achado apareceu com ' . $discount . '% de desconto',
    ]);
    $coverText = admin_shopee_video_pick_variant($offer, 'cover_discount', [
      $discount . '% OFF',
      'CAIU PRA ' . $price,
      'ACHADO ' . $discount . '%',
    ]);
  } elseif ($pixPrice !== '') {
    $hook = admin_shopee_video_pick_variant($offer, 'hook_pix', [
      'Esse produto ficou forte no Pix: ' . $title,
      'Preco no Pix que chamou atencao agora',
      'Olha como esse item ficou no Pix: ' . $pixPrice,
    ]);
    $coverText = admin_shopee_video_pick_variant($offer, 'cover_pix', [
      'NO PIX ' . $pixPrice,
      'PIX ' . $pixPrice,
      'PIX + OFERTA',
    ]);
  } else {
    $hook = admin_shopee_video_pick_variant($offer, 'hook_general', [
      'Passando esse achado da Shopee que chamou atencao',
      'Se liga nesse achadinho da Shopee que apareceu agora',
      'Olha esse produto da Shopee com cara de venda rapida',
      'Achei esse item na Shopee e o preco ficou interessante',
    ]);
    $coverText = admin_shopee_video_pick_variant($offer, 'cover_general', [
      'ACHADO ' . $price,
      'OFERTA ' . $price,
      'VALE O CLIQUE',
    ]);
  }

  $cta = $coupon !== ''
    ? admin_shopee_video_pick_variant($offer, 'cta_coupon', [
        'Clica no link e testa o cupom ' . $coupon . '.',
        'Abre o link agora e valida o cupom ' . $coupon . '.',
        'Toca no link e aproveita o cupom ' . $coupon . ' enquanto aparece.',
      ])
    : admin_shopee_video_pick_variant($offer, 'cta_primary', [
        'Abre o link e ve os detalhes completos com Zero Preço.',
      ]);

  $valuePoints = [];
  $valuePoints[] = $title;
  if ($oldPrice !== '' && $oldPriceValue > (float) ($offer['preco'] ?? 0)) {
    $valuePoints[] = 'Antes ' . $oldPrice . ', agora ' . $price . '.';
  } else {
    $valuePoints[] = 'Preco atual em destaque: ' . $price . '.';
  }
  if ($pixPrice !== '') {
    $valuePoints[] = 'No Pix pode ficar por ' . $pixPrice . '.';
  }
  if ($installments !== '') {
    $valuePoints[] = $installments;
  }
  if ($shipping !== '') {
    $valuePoints[] = $shipping;
  }
  if ($coupon !== '') {
    $valuePoints[] = 'Cupom visivel: ' . $coupon . '.';
  }

  $hashtags = admin_shopee_video_offer_hashtags($offer, 6);

  $captionLines = [
    $hook,
    'Produto: ' . $title,
    'Preco destaque: ' . $price,
  ];
  if ($oldPrice !== '' && $oldPriceValue > (float) ($offer['preco'] ?? 0)) {
    $captionLines[] = 'Preco anterior: ' . $oldPrice;
  }
  if ($pixPrice !== '') {
    $captionLines[] = 'Preco no Pix: ' . $pixPrice;
  }
  if ($installments !== '') {
    $captionLines[] = 'Parcelamento: ' . $installments;
  }
  if ($shipping !== '') {
    $captionLines[] = 'Frete: ' . $shipping;
  }
  if ($coupon !== '') {
    $captionLines[] = 'Cupom: ' . $coupon;
  }
  $captionLines[] = $cta;
  $captionLines[] = implode(' ', $hashtags);

  return [
    'angle' => $angle,
    'hook' => $hook,
    'cover_text' => $coverText,
    'cta_text' => $cta,
    'duration_seconds' => 8,
    'value_points' => $valuePoints,
    'hashtags' => $hashtags,
    'caption' => implode("\n", array_values(array_filter($captionLines, static function ($line) {
      return trim((string) $line) !== '';
    }))),
    'short_caption' => admin_shopee_video_compact_caption($offer, 150),
    'shot_plan' => [
      [
        'segment' => '0-2s',
        'goal' => 'gancho inicial',
        'overlay' => $hook,
      'direction' => 'Abrir com close forte, texto grande e ritmo de oferta.',
      ],
      [
        'segment' => '2-5s',
        'goal' => 'prova de oferta',
        'overlay' => $price . ($discount > 0 ? ' | ' . $discount . '% OFF' : ''),
      'direction' => 'Mostrar preco, produto e vantagem principal sem enrolar.',
      ],
      [
        'segment' => '5-8s',
        'goal' => 'fechamento com CTA',
        'overlay' => admin_shopee_video_pick_variant($offer, 'cta_final', [
          'Abre o link e ve os detalhes completos com Zero Preço.',
        ]),
        'direction' => 'Encerrar com energia, CTA clara e marca no frame final.',
      ],
    ],
    'edit_notes' => array_values(array_filter([
      'Usar video vertical 9:16.',
      'Gancho forte no primeiro segundo com texto em caixa alta.',
      'Cortes curtos, mais energia e ritmo de venda.',
      'Mostrar preco e beneficio principal antes dos 4 segundos.',
      'Deixar a CTA visivel no fechamento.',
      $coupon !== '' ? 'Reforcar o cupom ' . $coupon . ' no frame final.' : '',
      $discount >= 35 ? 'Destacar o desconto com selo grande.' : '',
    ])),
    'publish_checklist' => [
      'Confirmar se o produto exibido e o produto marcado sao o mesmo item.',
      'Revisar preco e cupom antes de publicar.',
      'Checar se o link de afiliado esta correto.',
      'Manter titulo curto e direto no app da Shopee.',
      'Publicar na vertical com capa legivel.',
    ],
  ];
}

function admin_shopee_video_status_label($status) {
  $map = [
    'manual_ready' => 'Pronto manual',
    'needs_video' => 'Sem video',
    'api_blocked' => 'API bloqueada',
    'published' => 'Publicado',
    'error' => 'Erro',
    'archived' => 'Arquivado',
  ];
  $normalized = trim((string) $status);
  return $map[$normalized] ?? ($normalized !== '' ? $normalized : 'Pendente');
}

function admin_shopee_video_status_class($status) {
  $normalized = trim((string) $status);
  if (in_array($normalized, ['manual_ready', 'published'], true)) {
    return 'ok';
  }
  if (in_array($normalized, ['needs_video', 'api_blocked'], true)) {
    return 'warn';
  }
  if (in_array($normalized, ['error', 'archived'], true)) {
    return 'off';
  }
  return 'warn';
}

function admin_shopee_video_package_status_label($status) {
  $map = [
    'not_started' => 'Pacote pendente',
    'ready' => 'Pacote pronto',
    'partial' => 'Pacote parcial',
    'stale' => 'Pacote desatualizado',
    'error' => 'Pacote com erro',
  ];
  $normalized = trim((string) $status);
  return $map[$normalized] ?? ($normalized !== '' ? $normalized : 'Pacote pendente');
}

function admin_shopee_video_package_status_class($status) {
  $normalized = trim((string) $status);
  if ($normalized === 'ready') {
    return 'ok';
  }
  if (in_array($normalized, ['not_started', 'stale', 'partial'], true)) {
    return 'warn';
  }
  if ($normalized === 'error') {
    return 'off';
  }
  return 'warn';
}

function admin_shopee_video_default_caption($offer) {
  $creative = admin_shopee_video_build_creative_payload($offer);
  return (string) ($creative['caption'] ?? 'Confira os detalhes no link do video.');
}

function admin_shopee_video_short_caption($offer) {
  $creative = admin_shopee_video_build_creative_payload($offer);
  return (string) ($creative['short_caption'] ?? admin_shopee_video_compact_caption($offer, 150));
}

function admin_fetch_shopee_video_candidates(PDO $pdo, $search = '', $limit = 24, $page = 1, $onlyWithVideo = true) {
  $limit = max(1, min((int) $limit, 60));
  $page = max(1, (int) $page);
  $where = [
    "o.loja = 'Shopee'",
    'o.ativo = 1',
    '(o.expira_em IS NULL OR o.expira_em > NOW())',
    "o.imagem_url IS NOT NULL",
    "o.imagem_url <> ''",
  ];
  $params = [];

  if ($search !== '') {
    $like = '%' . $search . '%';
    $where[] = '(o.titulo LIKE ? OR o.categoria LIKE ? OR o.tags LIKE ? OR o.loja LIKE ?)';
    array_push($params, $like, $like, $like, $like);
  }

  if ($onlyWithVideo) {
    $where[] = "(o.tags LIKE '%shopee_video_url:%' OR o.tags LIKE '%offer_video_url:%')";
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

  $eligibleRows = [];
  foreach ($rows as $row) {
    if (!admin_affiliate_is_acceptable(admin_affiliate_audit($row['loja'] ?? '', $row['url_afiliado'] ?? ''))) {
      continue;
    }
    $videoUrl = admin_shopee_video_offer_video_url($row);
    if ($onlyWithVideo && $videoUrl === '') {
      continue;
    }
    $row['video_url'] = $videoUrl;
    $row['has_video'] = $videoUrl !== '';
    $row['image_gallery_urls'] = admin_shopee_video_offer_gallery_urls($row);
    $row['video_gallery_urls'] = admin_shopee_video_offer_video_gallery_urls($row);
    $eligibleRows[] = $row;
  }

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
    'total_visible' => $total,
  ];
}

function admin_fetch_shopee_video_drafts(PDO $pdo, $status = '', $limit = 30) {
  $limit = max(1, min((int) $limit, 100));
  try {
    $sql = "
      SELECT
        d.*,
        o.slug,
        o.loja,
        o.categoria,
        o.preco,
        o.preco_antigo,
        o.cupom,
        o.imagem_url,
        o.imagem_urls_json,
        o.url_afiliado,
        o.video_urls_json,
        o.tags,
        o.atualizado_em AS oferta_atualizado_em
      FROM shopee_video_drafts d
      INNER JOIN ofertas o
        ON o.id = d.oferta_id
    ";
    $params = [];
    if ($status !== '') {
      $sql .= " WHERE d.status = ? ";
      $params[] = $status;
    }
    $sql .= " ORDER BY o.atualizado_em DESC, d.updated_at DESC, d.id DESC LIMIT {$limit}";
    $stmt = $pdo->prepare($sql);
    $stmt->execute($params);
    $rows = $stmt->fetchAll() ?: [];
    foreach ($rows as &$row) {
      $row['status_label'] = admin_shopee_video_status_label($row['status'] ?? '');
      $row['status_class'] = admin_shopee_video_status_class($row['status'] ?? '');
      $row['creative_payload'] = admin_shopee_video_json_decode($row['creative_payload_json'] ?? '');
      $row['package_payload'] = admin_shopee_video_json_decode($row['package_payload_json'] ?? '');
      $row['image_gallery_urls'] = admin_shopee_video_offer_gallery_urls($row);
      $row['video_gallery_urls'] = admin_shopee_video_offer_video_gallery_urls($row);
      $row['package_status_label'] = admin_shopee_video_package_status_label($row['package_status'] ?? '');
      $row['package_status_class'] = admin_shopee_video_package_status_class($row['package_status'] ?? '');
    }
    unset($row);
    return $rows;
  } catch (Throwable $e) {
    return [];
  }
}

function admin_upsert_shopee_video_draft(PDO $pdo, $offerId, $mode = 'manual', $actorUserId = null, $actorLogin = null) {
  $stmt = $pdo->prepare("
    SELECT id, slug, titulo, preco, preco_antigo, desconto_percentual, preco_pix, parcelas_texto, frete_texto, categoria, cupom, imagem_url, url_afiliado, tags
    FROM ofertas
    WHERE id = ?
      AND ativo = 1
      AND loja = 'Shopee'
    LIMIT 1
  ");
  $stmt->execute([(int) $offerId]);
  $offer = $stmt->fetch();
  if (!$offer) {
    throw new RuntimeException('Oferta Shopee nao encontrada para criar o rascunho.');
  }

  $videoUrl = admin_shopee_video_offer_video_url($offer);
  $normalizedMode = $mode === 'api' ? 'api' : 'manual';
  $hasImage = trim((string) ($offer['imagem_url'] ?? '')) !== '';
  if ($normalizedMode === 'api') {
    $status = 'api_blocked';
    $apiStatus = 'not_supported';
    $notes = 'Sem endpoint publico confirmado para publicar no Shopee Video. Use este rascunho no fluxo manual.';
  } else {
    $status = ($videoUrl !== '' || $hasImage) ? 'manual_ready' : 'needs_video';
    $apiStatus = 'manual_only';
    $notes = ($videoUrl !== '' || $hasImage)
      ? 'Rascunho pronto para gerar pacote pro e postar manualmente no app da Shopee.'
      : 'Oferta sem video e sem imagem suficiente para gerar pacote agora.';
  }
  $creativePayload = admin_shopee_video_build_creative_payload($offer);
  $caption = admin_shopee_video_default_caption($offer);
  $offerUrl = '/oferta/' . rawurlencode((string) ($offer['slug'] ?? ''));

  $upsert = $pdo->prepare("
    INSERT INTO shopee_video_drafts
      (oferta_id, status, publish_mode, title_snapshot, price_snapshot, caption, affiliate_url, offer_url, video_source_url, image_url, notes, creative_payload_json, package_status, api_status, created_by_admin_id, created_by_login, published_at, last_error, package_error)
    VALUES
      (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)
    ON DUPLICATE KEY UPDATE
      status = VALUES(status),
      publish_mode = VALUES(publish_mode),
      title_snapshot = VALUES(title_snapshot),
      price_snapshot = VALUES(price_snapshot),
      caption = VALUES(caption),
      affiliate_url = VALUES(affiliate_url),
      offer_url = VALUES(offer_url),
      video_source_url = VALUES(video_source_url),
      image_url = VALUES(image_url),
      notes = VALUES(notes),
      creative_payload_json = VALUES(creative_payload_json),
      package_status = CASE
        WHEN package_payload_json IS NULL OR package_payload_json = '' THEN 'not_started'
        ELSE 'stale'
      END,
      api_status = VALUES(api_status),
      created_by_admin_id = VALUES(created_by_admin_id),
      created_by_login = VALUES(created_by_login),
      last_error = NULL,
      package_error = NULL,
      published_at = CASE WHEN VALUES(status) = 'published' THEN COALESCE(published_at, NOW()) ELSE published_at END
  ");
  $upsert->execute([
    (int) $offer['id'],
    $status,
    $normalizedMode,
    (string) $offer['titulo'],
    (float) $offer['preco'],
    $caption,
    (string) $offer['url_afiliado'],
    $offerUrl,
    $videoUrl !== '' ? $videoUrl : null,
    (string) ($offer['imagem_url'] ?? ''),
    $notes,
    json_encode($creativePayload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES),
    'not_started',
    $apiStatus,
    $actorUserId !== null ? (int) $actorUserId : null,
    $actorLogin !== null ? (string) $actorLogin : null,
  ]);
}

function admin_update_shopee_video_draft_status(PDO $pdo, $draftId, $status) {
  $allowed = ['manual_ready', 'needs_video', 'api_blocked', 'published', 'error', 'archived'];
  $normalized = trim((string) $status);
  if (!in_array($normalized, $allowed, true)) {
    throw new RuntimeException('Status invalido para o rascunho do Shopee Video.');
  }

  $stmt = $pdo->prepare("
    UPDATE shopee_video_drafts
    SET status = ?,
        published_at = CASE WHEN ? = 'published' THEN COALESCE(published_at, NOW()) ELSE published_at END,
        updated_at = NOW()
    WHERE id = ?
    LIMIT 1
  ");
  $stmt->execute([$normalized, $normalized, (int) $draftId]);
}

function admin_store_shopee_video_package_result(PDO $pdo, $draftId, array $result) {
  $existingStmt = $pdo->prepare("SELECT package_payload_json FROM shopee_video_drafts WHERE id = ? LIMIT 1");
  $existingStmt->execute([(int) $draftId]);
  $existingPayload = $existingStmt->fetchColumn();
  if ($existingPayload) {
    admin_delete_shopee_video_package_files(admin_shopee_video_json_decode($existingPayload));
  }

  $creativePayload = isset($result['creative']) && is_array($result['creative']) ? $result['creative'] : null;
  $files = isset($result['files']) && is_array($result['files']) ? $result['files'] : [];
  $warnings = isset($result['warnings']) && is_array($result['warnings']) ? array_values(array_filter(array_map('trim', $result['warnings']))) : [];
  $compactWarnings = [];
  foreach ($warnings as $warning) {
    $normalized = (string) $warning;
    if ($normalized === '') {
      continue;
    }
    if (stripos($normalized, 'marcacao de link no video') !== false || stripos($normalized, 'Video original nao baixado') !== false) {
      $compactWarnings['source_video'] = 'Aviso tecnico no video original da Shopee. O pacote final foi gerado com fallback.';
      continue;
    }
    $compactWarnings[] = $normalized;
  }
  $warnings = array_values(array_unique(array_filter(array_map('strval', $compactWarnings))));
  $bestVideoPath = '';
  foreach (['reel_video_final', 'reel_video_tts_subtitled', 'reel_video_tts', 'reel_video', 'source_video'] as $videoKey) {
    if (!empty(($files[$videoKey]['path'] ?? ''))) {
      $bestVideoPath = (string) $files[$videoKey]['path'];
      break;
    }
  }
  $hasReelVideo = $bestVideoPath !== '';
  $hasAnyFile = false;
  foreach ($files as $entry) {
    if (!is_array($entry)) {
      continue;
    }
    if (!empty($entry['path'])) {
      $hasAnyFile = true;
      break;
    }
  }
  if ($hasReelVideo) {
    $packageStatus = 'ready';
    $packageError = $warnings ? implode(' | ', $warnings) : null;
  } elseif ($hasAnyFile) {
    $packageStatus = 'partial';
    $packageError = $warnings ? implode(' | ', $warnings) : 'Pacote gerado sem o video base. Verifique o metadata/warnings.';
  } else {
    $packageStatus = 'error';
    $packageError = $warnings ? implode(' | ', $warnings) : 'Pacote nao gerou arquivos utilizaveis.';
  }
  $stmt = $pdo->prepare("
    UPDATE shopee_video_drafts
    SET creative_payload_json = COALESCE(?, creative_payload_json),
        package_payload_json = ?,
        package_status = ?,
        package_job_id = ?,
        package_error = ?,
        package_generated_at = NOW(),
        updated_at = NOW()
    WHERE id = ?
    LIMIT 1
  ");
  $stmt->execute([
    $creativePayload ? json_encode($creativePayload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) : null,
    json_encode($result, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES),
    $packageStatus,
    trim((string) ($result['job_id'] ?? '')),
    $packageError,
    (int) $draftId,
  ]);
  return [
    'status' => $packageStatus,
    'error' => $packageError,
    'has_reel_video' => $hasReelVideo,
  ];
}

function admin_mark_shopee_video_package_running(PDO $pdo, $draftId, $jobId) {
  $stmt = $pdo->prepare("
    UPDATE shopee_video_drafts
    SET package_status = 'running',
        package_job_id = ?,
        package_error = NULL,
        updated_at = NOW()
    WHERE id = ?
    LIMIT 1
  ");
  $stmt->execute([trim((string) $jobId), (int) $draftId]);
}

function admin_mark_shopee_video_package_error(PDO $pdo, $draftId, $message) {
  $stmt = $pdo->prepare("
    UPDATE shopee_video_drafts
    SET package_status = 'error',
        package_error = ?,
        updated_at = NOW()
    WHERE id = ?
    LIMIT 1
  ");
  $stmt->execute([trim((string) $message), (int) $draftId]);
}

function admin_shopee_video_package_ttl_hours() {
  return 24;
}

function admin_shopee_video_safe_local_path($path) {
  $candidate = trim((string) $path);
  if ($candidate === '') {
    return null;
  }
  $realPath = realpath($candidate);
  if ($realPath === false || !is_file($realPath)) {
    return null;
  }
  $projectRoot = realpath(dirname(__DIR__, 2));
  if ($projectRoot === false) {
    return null;
  }
  if (!str_starts_with(str_replace('\\', '/', $realPath), str_replace('\\', '/', $projectRoot))) {
    return null;
  }
  return $realPath;
}

function admin_delete_shopee_video_package_files($packagePayload) {
  if (!is_array($packagePayload)) {
    return 0;
  }
  $files = is_array($packagePayload['files'] ?? null) ? $packagePayload['files'] : [];
  if (!$files) {
    return 0;
  }

  $deleted = 0;
  $directories = [];
  foreach ($files as $entry) {
    if (!is_array($entry)) {
      continue;
    }
    if (!empty($entry['persistent'])) {
      continue;
    }
    $safePath = admin_shopee_video_safe_local_path($entry['path'] ?? '');
    if ($safePath === null) {
      continue;
    }
    $normalizedPath = str_replace('\\', '/', $safePath);
    if (strpos($normalizedPath, '/public_html/uploads/ofertas_videos/') !== false) {
      continue;
    }
    $directory = dirname($safePath);
    if (@unlink($safePath)) {
      $deleted++;
      $directories[$directory] = true;
    }
  }

  $runtimeRoot = realpath(dirname(__DIR__, 2) . DIRECTORY_SEPARATOR . 'automacao_ofertas' . DIRECTORY_SEPARATOR . 'runtime' . DIRECTORY_SEPARATOR . 'shopee_video');
  if ($runtimeRoot !== false) {
    foreach (array_keys($directories) as $directory) {
      $current = realpath($directory);
      while ($current !== false && str_starts_with(str_replace('\\', '/', $current), str_replace('\\', '/', $runtimeRoot))) {
        $items = @scandir($current);
        if (!is_array($items) || count(array_diff($items, ['.', '..'])) > 0) {
          break;
        }
        @rmdir($current);
        if ($current === $runtimeRoot) {
          break;
        }
        $current = realpath(dirname($current));
      }
    }
  }

  return $deleted;
}

function admin_reset_shopee_video_package(PDO $pdo, $draftId, $message = 'Pacote removido manualmente.') {
  $draftId = (int) $draftId;
  if ($draftId <= 0) {
    return false;
  }

  try {
    $stmt = $pdo->prepare("
      SELECT package_payload_json
      FROM shopee_video_drafts
      WHERE id = ?
      LIMIT 1
    ");
    $stmt->execute([$draftId]);
    $row = $stmt->fetch();
    if (!$row) {
      return false;
    }

    admin_delete_shopee_video_package_files(admin_shopee_video_json_decode($row['package_payload_json'] ?? ''));

    $updateStmt = $pdo->prepare("
      UPDATE shopee_video_drafts
      SET package_payload_json = NULL,
          package_status = 'not_started',
          package_job_id = NULL,
          package_error = ?,
          package_generated_at = NULL,
          updated_at = NOW()
      WHERE id = ?
      LIMIT 1
    ");
    $updateStmt->execute([trim((string) $message), $draftId]);
    return true;
  } catch (Throwable $e) {
    return false;
  }
}

function admin_delete_shopee_video_package(PDO $pdo, $draftId) {
  return admin_reset_shopee_video_package($pdo, $draftId, 'Pacote removido manualmente pelo admin.');
}

function admin_delete_shopee_video_draft(PDO $pdo, $draftId) {
  $draftId = (int) $draftId;
  if ($draftId <= 0) {
    return false;
  }

  try {
    $stmt = $pdo->prepare("
      SELECT package_payload_json
      FROM shopee_video_drafts
      WHERE id = ?
      LIMIT 1
    ");
    $stmt->execute([$draftId]);
    $row = $stmt->fetch();
    if (!$row) {
      return false;
    }

    admin_delete_shopee_video_package_files(admin_shopee_video_json_decode($row['package_payload_json'] ?? ''));

    $deleteStmt = $pdo->prepare("
      DELETE FROM shopee_video_drafts
      WHERE id = ?
      LIMIT 1
    ");
    $deleteStmt->execute([$draftId]);
    return $deleteStmt->rowCount() > 0;
  } catch (Throwable $e) {
    return false;
  }
}

function admin_delete_all_shopee_video_drafts(PDO $pdo, $status = '') {
  try {
    $sql = "
      SELECT id, package_payload_json
      FROM shopee_video_drafts
    ";
    $params = [];
    if ($status !== '') {
      $sql .= " WHERE status = ? ";
      $params[] = $status;
    }
    $sql .= " ORDER BY updated_at DESC, id DESC";
    $stmt = $pdo->prepare($sql);
    $stmt->execute($params);
    $rows = $stmt->fetchAll() ?: [];
    if (!$rows) {
      return 0;
    }

    $deleteStmt = $pdo->prepare("
      DELETE FROM shopee_video_drafts
      WHERE id = ?
      LIMIT 1
    ");

    $deleted = 0;
    foreach ($rows as $row) {
      admin_delete_shopee_video_package_files(admin_shopee_video_json_decode($row['package_payload_json'] ?? ''));
      $deleteStmt->execute([(int) ($row['id'] ?? 0)]);
      if ($deleteStmt->rowCount() > 0) {
        $deleted++;
      }
    }
    return $deleted;
  } catch (Throwable $e) {
    return 0;
  }
}

function admin_delete_all_active_shopee_video_packages(PDO $pdo, $search = '') {
  $ttlHours = admin_shopee_video_package_ttl_hours();
  try {
    $sql = "
      SELECT d.id
      FROM shopee_video_drafts d
      INNER JOIN ofertas o
        ON o.id = d.oferta_id
      WHERE d.package_status IN ('ready', 'partial')
        AND d.package_generated_at IS NOT NULL
        AND d.package_generated_at >= (NOW() - INTERVAL {$ttlHours} HOUR)
    ";
    $params = [];
    if ($search !== '') {
      $sql .= " AND (d.title_snapshot LIKE ? OR o.categoria LIKE ? OR o.tags LIKE ?) ";
      $like = '%' . $search . '%';
      array_push($params, $like, $like, $like);
    }
    $sql .= " ORDER BY d.package_generated_at DESC, d.updated_at DESC";
    $stmt = $pdo->prepare($sql);
    $stmt->execute($params);
    $rows = $stmt->fetchAll() ?: [];
    if (!$rows) {
      return 0;
    }

    $deleted = 0;
    foreach ($rows as $row) {
      if (admin_reset_shopee_video_package($pdo, (int) ($row['id'] ?? 0), 'Pacote removido manualmente em lote pelo admin.')) {
        $deleted++;
      }
    }
    return $deleted;
  } catch (Throwable $e) {
    return 0;
  }
}

function admin_cleanup_expired_shopee_video_packages(PDO $pdo, $ttlHours = 24) {
  $ttlHours = max(1, (int) $ttlHours);
  try {
    $stmt = $pdo->query("
      SELECT id, package_payload_json
      FROM shopee_video_drafts
      WHERE package_payload_json IS NOT NULL
        AND package_payload_json <> ''
        AND package_generated_at IS NOT NULL
        AND package_generated_at < (NOW() - INTERVAL {$ttlHours} HOUR)
    ");
    $rows = $stmt->fetchAll() ?: [];
    if (!$rows) {
      return 0;
    }

    $cleanupStmt = $pdo->prepare("
      UPDATE shopee_video_drafts
      SET package_payload_json = NULL,
          package_status = 'not_started',
          package_job_id = NULL,
          package_error = ?,
          package_generated_at = NULL,
          updated_at = NOW()
      WHERE id = ?
      LIMIT 1
    ");

    $cleaned = 0;
    foreach ($rows as $row) {
      admin_delete_shopee_video_package_files(admin_shopee_video_json_decode($row['package_payload_json'] ?? ''));
      $cleanupStmt->execute([
        'Pacote removido automaticamente apos ' . $ttlHours . ' horas.',
        (int) $row['id'],
      ]);
      $cleaned++;
    }
    return $cleaned;
  } catch (Throwable $e) {
    return 0;
  }
}

function admin_fetch_shopee_video_packages(PDO $pdo, $search = '', $limit = 30) {
  $limit = max(1, min((int) $limit, 100));
  $ttlHours = admin_shopee_video_package_ttl_hours();
  try {
    $sql = "
      SELECT
        d.*,
        o.slug,
        o.loja,
        o.categoria,
        o.preco,
        o.preco_antigo,
        o.cupom,
        o.imagem_url,
        o.imagem_urls_json,
        o.url_afiliado,
        o.video_urls_json,
        o.tags,
        o.atualizado_em AS oferta_atualizado_em
      FROM shopee_video_drafts d
      INNER JOIN ofertas o
        ON o.id = d.oferta_id
      WHERE d.package_status IN ('ready', 'partial')
        AND d.package_generated_at IS NOT NULL
        AND d.package_generated_at >= (NOW() - INTERVAL {$ttlHours} HOUR)
    ";
    $params = [];
    if ($search !== '') {
      $sql .= " AND (d.title_snapshot LIKE ? OR o.categoria LIKE ? OR o.tags LIKE ?) ";
      $like = '%' . $search . '%';
      array_push($params, $like, $like, $like);
    }
    $sql .= " ORDER BY o.atualizado_em DESC, d.updated_at DESC, d.package_generated_at DESC LIMIT {$limit}";
    $stmt = $pdo->prepare($sql);
    $stmt->execute($params);
    $rows = $stmt->fetchAll() ?: [];
    foreach ($rows as &$row) {
      $row['creative_payload'] = admin_shopee_video_json_decode($row['creative_payload_json'] ?? '');
      $row['package_payload'] = admin_shopee_video_json_decode($row['package_payload_json'] ?? '');
      $row['image_gallery_urls'] = admin_shopee_video_offer_gallery_urls($row);
      $row['video_gallery_urls'] = admin_shopee_video_offer_video_gallery_urls($row);
      $generatedAt = strtotime((string) ($row['package_generated_at'] ?? ''));
      $expiresAt = $generatedAt ? ($generatedAt + ($ttlHours * 3600)) : 0;
      $row['expires_at'] = $expiresAt ? date('Y-m-d H:i:s', $expiresAt) : '';
      $row['expires_in_seconds'] = $expiresAt ? max(0, $expiresAt - time()) : 0;
      $row['package_status_label'] = admin_shopee_video_package_status_label($row['package_status'] ?? '');
      $row['package_status_class'] = admin_shopee_video_package_status_class($row['package_status'] ?? '');
    }
    unset($row);
    return $rows;
  } catch (Throwable $e) {
    return [];
  }
}

function admin_export_shopee_video_drafts_csv(PDO $pdo, array $draftIds) {
  $ids = array_values(array_unique(array_filter(array_map('intval', $draftIds))));
  if (!$ids) {
    throw new RuntimeException('Selecione pelo menos um rascunho para exportar.');
  }

  $placeholders = implode(',', array_fill(0, count($ids), '?'));
  $stmt = $pdo->prepare("
    SELECT id, oferta_id, status, publish_mode, title_snapshot, price_snapshot, caption, affiliate_url, offer_url, video_source_url, image_url, notes, api_status, package_status, package_job_id, updated_at
    FROM shopee_video_drafts
    WHERE id IN ($placeholders)
    ORDER BY updated_at DESC, id DESC
  ");
  $stmt->execute($ids);
  $rows = $stmt->fetchAll() ?: [];
  if (!$rows) {
    throw new RuntimeException('Nenhum rascunho selecionado foi encontrado.');
  }

  $stream = fopen('php://temp', 'r+');
  fputcsv($stream, ['draft_id', 'offer_id', 'status', 'publish_mode', 'title', 'price', 'caption', 'affiliate_url', 'offer_url', 'video_source_url', 'image_url', 'notes', 'api_status', 'package_status', 'package_job_id', 'updated_at'], ';');
  foreach ($rows as $row) {
    fputcsv($stream, [
      (int) $row['id'],
      (int) $row['oferta_id'],
      (string) $row['status'],
      (string) $row['publish_mode'],
      (string) $row['title_snapshot'],
      number_format((float) $row['price_snapshot'], 2, '.', ''),
      (string) ($row['caption'] ?? ''),
      (string) ($row['affiliate_url'] ?? ''),
      (string) ($row['offer_url'] ?? ''),
      (string) ($row['video_source_url'] ?? ''),
      (string) ($row['image_url'] ?? ''),
      (string) ($row['notes'] ?? ''),
      (string) ($row['api_status'] ?? ''),
      (string) ($row['package_status'] ?? ''),
      (string) ($row['package_job_id'] ?? ''),
      (string) ($row['updated_at'] ?? ''),
    ], ';');
  }
  rewind($stream);
  $csv = stream_get_contents($stream);
  fclose($stream);
  return (string) $csv;
}

