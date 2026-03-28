<?php
require_once __DIR__ . '/_init.php';
admin_require_login();

$flash = admin_flash_get();

$pdo = db();
$targetStores = ['Mercado Livre', 'Shopee', 'Amazon'];
$feedback = '';
$selectedPublication = trim((string) ($_GET['publicacao'] ?? ''));
if (!in_array($selectedPublication, ['', 'ativo', 'inativo'], true)) {
  $selectedPublication = '';
}
$selectedSeverity = trim((string) ($_GET['diagnostico'] ?? ''));
if (!in_array($selectedSeverity, ['', 'ok', 'suspect', 'broken'], true)) {
  $selectedSeverity = '';
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
  admin_csrf_check_or_die();
  $action = (string) ($_POST['action'] ?? '');

  if ($action === 'safe_mode') {
    $stmt = $pdo->query("SELECT id, loja, url_afiliado FROM ofertas WHERE LOWER(loja) IN ('mercado livre', 'shopee', 'amazon')");
    $rows = $stmt->fetchAll();
    $idsToDisable = [];
    foreach ($rows as $row) {
      $audit = admin_affiliate_audit($row['loja'], $row['url_afiliado']);
      if (!admin_affiliate_is_acceptable($audit)) {
        $idsToDisable[] = (int) $row['id'];
      }
    }
    if ($idsToDisable) {
      $placeholders = implode(',', array_fill(0, count($idsToDisable), '?'));
      $update = $pdo->prepare("UPDATE ofertas SET ativo = 0 WHERE id IN ($placeholders)");
      $update->execute($idsToDisable);
    }
    $feedback = 'Modo seguro reaplicado: apenas links classificados como OK permanecem ativos.';
  } elseif ($action === 'reactivate_one') {
    $id = (int) ($_POST['id'] ?? 0);
    if ($id > 0) {
      $itemStmt = $pdo->prepare("SELECT id, loja, url_afiliado FROM ofertas WHERE id = ? LIMIT 1");
      $itemStmt->execute([$id]);
      $item = $itemStmt->fetch();
      if ($item) {
        $audit = admin_affiliate_audit($item['loja'], $item['url_afiliado']);
        if (admin_affiliate_is_acceptable($audit)) {
          $pdo->prepare("UPDATE ofertas SET ativo = 1 WHERE id = ?")->execute([$id]);
          $feedback = 'Oferta reativada com sucesso.';
        } else {
          $feedback = 'A oferta nao foi reativada porque o link atual ainda nao esta classificado como OK.';
        }
      }
    }
  } elseif ($action === 'reactivate_ok_filtered') {
    $targetStore = trim((string) ($_POST['target_store'] ?? ''));
    $whereSql = '';
    $params = [];
    if ($targetStore !== '' && in_array($targetStore, $targetStores, true)) {
      $whereSql = 'WHERE loja = ?';
      $params[] = $targetStore;
    }
    $itemStmt = $pdo->prepare("
      SELECT id, loja, url_afiliado
      FROM ofertas
      $whereSql
    ");
    $itemStmt->execute($params);
    $items = $itemStmt->fetchAll();
    $idsToEnable = [];
    foreach ($items as $item) {
      $audit = admin_affiliate_audit($item['loja'], $item['url_afiliado']);
      if (admin_affiliate_is_acceptable($audit)) {
        $idsToEnable[] = (int) $item['id'];
      }
    }
    if ($idsToEnable) {
      $placeholders = implode(',', array_fill(0, count($idsToEnable), '?'));
      $pdo->prepare("UPDATE ofertas SET ativo = 1 WHERE id IN ($placeholders)")->execute($idsToEnable);
    }
    $feedback = 'Reativacao concluida: apenas links OK da selecao atual foram ligados.';
  }
}

$selectedStore = trim((string) ($_GET['loja'] ?? ''));
if ($selectedStore !== '' && !in_array($selectedStore, $targetStores, true)) {
  $selectedStore = '';
}

$whereParts = [];
$params = [];
if ($selectedStore !== '') {
  $whereParts[] = 'loja = ?';
  $params[] = $selectedStore;
}
if ($selectedPublication === 'ativo') {
  $whereParts[] = 'ativo = 1';
}
if ($selectedPublication === 'inativo') {
  $whereParts[] = 'ativo = 0';
}
$whereSql = $whereParts ? ('WHERE ' . implode(' AND ', $whereParts)) : '';

$stmt = $pdo->prepare("
  SELECT id, titulo, slug, preco, loja, url_afiliado, atualizado_em, ativo
  FROM ofertas
  $whereSql
  ORDER BY loja ASC, atualizado_em DESC, id DESC
  LIMIT 1600
");
$stmt->execute($params);
$rows = $stmt->fetchAll();

$summary = [];
$samples = [
  'broken' => [],
  'suspect' => [],
  'ok' => [],
];
$actionLinks = [
  'Mercado Livre' => [
    'broken' => '/admin/ml_corrigir_lote.php',
    'suspect' => '/admin/ml_corrigir_lote.php?status=wid_polycard_affiliates',
  ],
  'Shopee' => [
    'broken' => '/admin/ofertas.php?loja=' . urlencode('Shopee'),
    'suspect' => '/admin/ofertas.php?loja=' . urlencode('Shopee'),
  ],
  'Amazon' => [
    'broken' => '/admin/ofertas.php?loja=' . urlencode('Amazon'),
    'suspect' => '/admin/ofertas.php?loja=' . urlencode('Amazon'),
  ],
];

foreach ($rows as $row) {
  $store = (string) $row['loja'];
  $audit = admin_affiliate_audit($store, $row['url_afiliado']);

  if ($selectedSeverity !== '' && $audit['severity'] !== $selectedSeverity) {
    continue;
  }

  if (!isset($summary[$store])) {
    $summary[$store] = [
      'total' => 0,
      'ok' => 0,
      'suspect' => 0,
      'broken' => 0,
    ];
  }

  $summary[$store]['total']++;
  $summary[$store][$audit['severity']]++;

  if (count($samples[$audit['severity']]) < 12) {
    $samples[$audit['severity']][] = $row + ['audit' => $audit];
  }
}
?>
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Admin - Auditoria de Links</title>
  <link rel="stylesheet" href="/assets/css/style.css">
  <link rel="stylesheet" href="/assets/css/admin.css">
  <style>
    .admin-wrap { display:grid; gap:18px; }
    .panel { background:#fff; border:1px solid #d9e2f2; border-radius:18px; padding:18px; }
    .filters, .stats { display:flex; gap:10px; flex-wrap:wrap; }
    .stat { min-width:150px; padding:12px 14px; border:1px solid #d9e2f2; border-radius:14px; background:#f8fbff; }
    .stat strong { display:block; font-size:22px; color:#10213a; }
    .muted { color:#617089; font-size:13px; }
    .status { display:inline-flex; align-items:center; gap:6px; font-size:12px; padding:5px 10px; border-radius:999px; border:1px solid #d8e2f2; color:#324564; margin:0 6px 6px 0; }
    .status.ok { background:#eef8f0; color:#1d6b39; border-color:#c9ead3; }
    .status.suspect { background:#fff7e7; color:#8a5a00; border-color:#f0deaf; }
    .status.broken { background:#feeff1; color:#9d1c35; border-color:#f4c7cf; }
    .table-wrap { overflow-x:auto; }
    table { width:100%; border-collapse:collapse; min-width:1080px; }
    th, td { border-bottom:1px solid #e7edf7; text-align:left; padding:12px 10px; vertical-align:top; font-size:14px; }
    th { color:#42577c; font-size:12px; text-transform:uppercase; letter-spacing:.06em; }
    .url-box { max-width:360px; word-break:break-all; color:#435776; font-size:12px; line-height:1.45; }
  </style>
</head>
<body class="admin-page">
<header>
  <div class="container" style="display:flex; align-items:center; justify-content:space-between; gap:10px;">
    <div style="font-weight:700;">Auditoria de links afiliados</div>
    <div style="display:flex; gap:8px; flex-wrap:wrap;">
      <a class="badge" href="/admin/ofertas.php">Ofertas</a>
      <a class="badge" href="/admin/ml_corrigir_lote.php">Corrigir ML em lote</a>
      <a class="badge" href="/admin/logout.php">Sair</a>
    </div>
  </div>
</header>

<main class="container admin-wrap">
  <?php if ($flash): ?>
    <div class="admin-alert <?= h((string) ($flash['type'] ?? '')) ?>"><?= h((string) ($flash['message'] ?? '')) ?></div>
  <?php endif; ?>
  <section class="panel">
    <div class="muted">Classificacao automatica por loja</div>
    <div style="font-weight:700; color:#10213a; margin-top:4px;">Links foram separados em `aparentemente ok`, `suspeito` e `definitivamente errado`.</div>
    <?php if ($feedback !== ''): ?>
      <div class="status ok" style="margin-top:12px;"><?= h($feedback) ?></div>
    <?php endif; ?>
    <div class="filters" style="margin-top:14px;">
      <a class="badge" href="/admin/auditoria_links.php">Todas</a>
      <?php foreach ($targetStores as $store): ?>
        <a class="badge" href="/admin/auditoria_links.php?loja=<?= urlencode($store) ?>&publicacao=<?= urlencode($selectedPublication) ?>&diagnostico=<?= urlencode($selectedSeverity) ?>"><?= h($store) ?></a>
      <?php endforeach; ?>
      <a class="badge" href="/admin/auditoria_links.php?loja=<?= urlencode($selectedStore) ?>&publicacao=ativo&diagnostico=<?= urlencode($selectedSeverity) ?>">So ativos</a>
      <a class="badge" href="/admin/auditoria_links.php?loja=<?= urlencode($selectedStore) ?>&publicacao=inativo&diagnostico=<?= urlencode($selectedSeverity) ?>">So inativos</a>
      <a class="badge" href="/admin/auditoria_links.php?loja=<?= urlencode($selectedStore) ?>&publicacao=<?= urlencode($selectedPublication) ?>&diagnostico=broken">So errados</a>
      <a class="badge" href="/admin/auditoria_links.php?loja=<?= urlencode($selectedStore) ?>&publicacao=<?= urlencode($selectedPublication) ?>&diagnostico=suspect">So suspeitos</a>
      <a class="badge" href="/admin/auditoria_links.php?loja=<?= urlencode($selectedStore) ?>&publicacao=<?= urlencode($selectedPublication) ?>&diagnostico=ok">So OK</a>
    </div>
    <form method="post" style="margin-top:14px;">
      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
      <input type="hidden" name="action" value="safe_mode">
      <button class="btn" type="submit">Reaplicar modo seguro</button>
    </form>
    <form method="post" style="margin-top:10px;">
      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
      <input type="hidden" name="action" value="reactivate_ok_filtered">
      <input type="hidden" name="target_store" value="<?= h($selectedStore) ?>">
      <button class="btn" type="submit">Reativar OK da selecao atual</button>
    </form>
  </section>

  <?php foreach ($summary as $store => $numbers): ?>
    <section class="panel">
      <div style="display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; align-items:flex-start;">
        <div>
          <h2 style="margin:0; color:#10213a;"><?= h($store) ?></h2>
          <div class="muted">Resumo da auditoria automatica para a loja.</div>
          <div class="filters" style="margin-top:10px;">
            <?php if (!empty($actionLinks[$store]['broken'])): ?>
              <a class="badge" href="<?= h($actionLinks[$store]['broken']) ?>">Abrir errados</a>
            <?php endif; ?>
            <?php if (!empty($actionLinks[$store]['suspect'])): ?>
              <a class="badge" href="<?= h($actionLinks[$store]['suspect']) ?>">Abrir suspeitos</a>
            <?php endif; ?>
            <a class="badge" href="/admin/ofertas.php?loja=<?= urlencode($store) ?>">Ver ofertas da loja</a>
          </div>
        </div>
        <div class="stats">
          <div class="stat"><span class="muted">Total</span><strong><?= (int) $numbers['total'] ?></strong></div>
          <div class="stat"><span class="muted">Aparentemente OK</span><strong><?= (int) $numbers['ok'] ?></strong></div>
          <div class="stat"><span class="muted">Suspeitos</span><strong><?= (int) $numbers['suspect'] ?></strong></div>
          <div class="stat"><span class="muted">Errados</span><strong><?= (int) $numbers['broken'] ?></strong></div>
        </div>
      </div>
    </section>
  <?php endforeach; ?>

  <?php foreach (['broken' => 'Definitivamente errado', 'suspect' => 'Suspeito', 'ok' => 'Aparentemente ok'] as $severity => $title): ?>
    <section class="panel table-wrap">
      <h3 style="margin-top:0; color:#10213a;"><?= h($title) ?></h3>
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Loja</th>
            <th>Publicacao</th>
            <th>Oferta</th>
            <th>Diagnostico</th>
            <th>URL</th>
            <th>Acao</th>
          </tr>
        </thead>
        <tbody>
          <?php if (empty($samples[$severity])): ?>
            <tr><td colspan="6" class="muted">Nenhum exemplo nesta faixa.</td></tr>
          <?php else: ?>
            <?php foreach ($samples[$severity] as $item): ?>
              <tr>
                <td><?= (int) $item['id'] ?></td>
                <td><?= h($item['loja']) ?></td>
                <td>
                  <span class="status <?= ((int) $item['ativo'] === 1) ? 'ok' : 'broken' ?>">
                    <?= ((int) $item['ativo'] === 1) ? 'Ativo' : 'Inativo' ?>
                  </span>
                </td>
                <td>
                  <strong><?= h($item['titulo']) ?></strong>
                  <div class="muted">slug: <?= h($item['slug']) ?></div>
                  <div class="muted">atualizado em: <?= h((string) $item['atualizado_em']) ?></div>
                </td>
                <td>
                  <span class="status <?= h($severity) ?>"><?= h($item['audit']['label']) ?></span>
                  <div class="muted"><?= h($item['audit']['reason']) ?></div>
                </td>
                <td><div class="url-box"><?= h($item['url_afiliado']) ?></div></td>
                <td>
                  <a class="badge" href="/admin/oferta_editar.php?id=<?= (int) $item['id'] ?>">Editar</a>
                  <?php if ($item['loja'] === 'Mercado Livre' && $severity !== 'ok'): ?>
                    <a class="badge" href="/admin/ml_corrigir_lote.php">Corrigir ML</a>
                  <?php endif; ?>
                  <?php if ($item['loja'] !== 'Mercado Livre' && $severity !== 'ok'): ?>
                    <a class="badge" href="/admin/ofertas.php?loja=<?= urlencode($item['loja']) ?>">Filtrar loja</a>
                  <?php endif; ?>
                  <?php if ($severity === 'ok'): ?>
                    <form method="post" style="display:inline-block; margin-top:6px;">
                      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
                      <input type="hidden" name="action" value="reactivate_one">
                      <input type="hidden" name="id" value="<?= (int) $item['id'] ?>">
                      <button class="badge" type="submit">Reativar</button>
                    </form>
                  <?php endif; ?>
                </td>
              </tr>
            <?php endforeach; ?>
          <?php endif; ?>
        </tbody>
      </table>
    </section>
  <?php endforeach; ?>
</main>
</body>
</html>

