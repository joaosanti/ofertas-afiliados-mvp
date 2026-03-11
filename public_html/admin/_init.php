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
      return ['severity' => 'suspect', 'status' => 'short_sem_marcador', 'label' => 'Suspeito', 'reason' => 'Shortlink da Shopee sem marcador visivel; pode funcionar, mas nao esta comprovado na URL salva.'];
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

