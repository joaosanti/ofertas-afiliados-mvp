<?php
require_once __DIR__ . '/_init.php';
admin_require_login();

$pdo = db();
$flash = admin_flash_get();
$recentRuns = admin_fetch_recent_runs($pdo, 'import', 3);
$resultPayload = null;
$adminCssVersion = (string) @filemtime(__DIR__ . '/../assets/css/admin.css');
$currentAdminLogin = admin_current_login_name();

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
  admin_csrf_check_or_die();
  $action = (string) ($_POST['acao'] ?? '');

  if ($action === 'import_file') {
    if (empty($_FILES['arquivo']['tmp_name']) || !is_uploaded_file($_FILES['arquivo']['tmp_name'])) {
      admin_flash_set('error', 'Envie um arquivo para importar.');
      header('Location: /admin/importar.php');
      exit;
    }

    $kind = trim((string) ($_POST['kind'] ?? ''));
    $tmpDir = sys_get_temp_dir();
    $target = $tmpDir . DIRECTORY_SEPARATOR . 'zp-import-' . bin2hex(random_bytes(8)) . '-' . basename((string) $_FILES['arquivo']['name']);
    if (!move_uploaded_file($_FILES['arquivo']['tmp_name'], $target)) {
      admin_flash_set('error', 'Nao foi possivel mover o arquivo enviado.');
      header('Location: /admin/importar.php');
      exit;
    }

    try {
      $args = ['import-file', '--kind', $kind, '--input-file', $target];
      if ($currentAdminLogin !== '') {
        $args[] = '--actor-user-id';
        $args[] = (string) admin_user_id();
        $args[] = '--actor-login';
        $args[] = $currentAdminLogin;
      }
      $resultPayload = admin_run_python_job($args);
    } finally {
      @unlink($target);
    }
  } elseif ($action === 'import_links') {
    $content = trim((string) ($_POST['links'] ?? ''));
    if ($content === '') {
      admin_flash_set('error', 'Cole pelo menos um link.');
      header('Location: /admin/importar.php');
      exit;
    }

    $tmpDir = sys_get_temp_dir();
    $target = $tmpDir . DIRECTORY_SEPARATOR . 'zp-links-' . bin2hex(random_bytes(8)) . '.txt';
    file_put_contents($target, $content);
    try {
      $args = ['import-links', '--input-file', $target];
      if ($currentAdminLogin !== '') {
        $args[] = '--actor-user-id';
        $args[] = (string) admin_user_id();
        $args[] = '--actor-login';
        $args[] = $currentAdminLogin;
      }
      $resultPayload = admin_run_python_job($args);
    } finally {
      @unlink($target);
    }
  }

  if ($resultPayload !== null) {
    if (!empty($resultPayload['ok'])) {
      $summary = is_array($resultPayload['result'] ?? null) ? $resultPayload['result'] : [];
      $processed = (int) ($summary['processed'] ?? 0);
      $created = (int) ($summary['created'] ?? 0);
      $updated = (int) ($summary['updated'] ?? 0);
      $skipped = (int) ($summary['skipped'] ?? 0);

      if (($created + $updated) > 0) {
        admin_flash_set('success', "Importacao concluida: {$created} criada(s), {$updated} atualizada(s), {$skipped} pulada(s).");
      } else {
        admin_flash_set('error', "Importacao concluida sem gravar ofertas: {$processed} processada(s), {$skipped} pulada(s).");
      }
    } else {
      admin_flash_set('error', (string) ($resultPayload['error'] ?? 'Falha ao executar importacao.'));
    }
    header('Location: /admin/importar.php');
    exit;
  }
}
?>
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Admin - Importar</title>
  <link rel="icon" type="image/png" href="/assets/img/logo-zp.png">
  <link rel="stylesheet" href="/assets/css/style.css">
  <link rel="stylesheet" href="/assets/css/admin.css?v=<?= urlencode($adminCssVersion) ?>">
</head>
<body class="admin-page">
<?php admin_render_header('importar'); ?>
<template data-legacy-admin-header>
  <div class="container admin-header">
    <div class="admin-brand">
      <a class="admin-brand-link" href="/admin/ofertas.php">
        <div class="admin-brand-mark">
          <img src="/assets/img/logo-zp.png" alt="Zero Preco">
        </div>
      </a>
      <div class="admin-brand-copy">
        <strong>Zero Preco Admin</strong>
        <span>Controle ofertas, links e publicacoes em um so lugar.</span>
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
      <a class="badge" href="/admin/ofertas.php">Ofertas</a>
      <a class="badge" href="/admin/social.php">Social</a>
      <a class="badge" href="/admin/logout.php">Sair</a>
    </div>
  </div>
</template>

<main class="container admin-shell">
  <?php if ($flash): ?>
    <div class="admin-alert <?= h((string) ($flash['type'] ?? '')) ?>"><?= h((string) ($flash['message'] ?? '')) ?></div>
  <?php endif; ?>

  <section class="admin-hero">
    <div class="admin-hero-head">
      <div class="admin-hero-copy">
        <span class="admin-kicker">Importar ofertas</span>
        <h1>Importar ofertas</h1>
      </div>
    </div>
  </section>

  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Importar por arquivo</h2>
        <p>Use CSV da Shopee ou TXT com links da Amazon/Mercado Livre. Os itens novos desta importacao ficam marcados com o login <?= h($currentAdminLogin ?: 'atual') ?>.</p>
      </div>
    </div>
    <form method="post" enctype="multipart/form-data">
      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
      <input type="hidden" name="acao" value="import_file">
      <div class="admin-field-grid">
        <div class="admin-field">
          <label for="kind">Tipo de arquivo</label>
          <select id="kind" name="kind">
            <option value="shopee_csv">Shopee CSV</option>
            <option value="amazon_txt">Amazon TXT</option>
            <option value="mercadolivre_txt">Mercado Livre TXT</option>
          </select>
        </div>
        <div class="admin-field">
          <label for="arquivo">Arquivo</label>
          <input id="arquivo" type="file" name="arquivo" required>
        </div>
      </div>
      <div class="admin-form-actions">
        <button class="btn" type="submit">Importar arquivo</button>
      </div>
    </form>
  </section>

  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Importar por texto e links</h2>
        <p>Cole um link por linha. O Python identifica a loja, tenta ler os dados e grava as ofertas validas com autoria do login atual.</p>
      </div>
    </div>
    <form method="post">
      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
      <input type="hidden" name="acao" value="import_links">
      <div class="admin-field-grid">
        <div class="admin-field is-full">
          <label for="links">Links</label>
          <textarea id="links" name="links" rows="8" placeholder="https://...&#10;https://..."></textarea>
        </div>
      </div>
      <div class="admin-form-actions">
        <button class="btn" type="submit">Importar links</button>
      </div>
    </form>
  </section>

  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Historico de importacoes</h2>
        <p>Mostra os jobs de importacao registrados no banco.</p>
      </div>
    </div>
    <?php if (!$recentRuns): ?>
      <div class="admin-empty">Nenhuma importacao registrada ainda.</div>
    <?php else: ?>
      <div class="admin-offers-grid">
        <?php foreach ($recentRuns as $run): ?>
          <article class="admin-offer-card">
            <div class="admin-meta-row">
              <span class="admin-meta-chip">Run #<?= (int) $run['id'] ?></span>
              <span class="admin-status <?= $run['status'] === 'success' ? 'ok' : ($run['status'] === 'running' ? 'warn' : 'off') ?>"><?= h($run['status']) ?></span>
              <span class="admin-meta-chip"><?= h((string) ($run['provider'] ?? '-')) ?></span>
              <span class="admin-meta-chip">processado <?= (int) ($run['processed_count'] ?? 0) ?></span>
            </div>
            <div class="admin-help" style="margin-top:12px;">Criado em <?= h((string) $run['criado_em']) ?></div>
            <?php if (!empty($run['error_message'])): ?>
              <div class="admin-alert error" style="margin-top:12px;"><?= h((string) $run['error_message']) ?></div>
            <?php endif; ?>
          </article>
        <?php endforeach; ?>
      </div>
    <?php endif; ?>
  </section>
</main>
<script>
  (function () {
    var toggle = document.querySelector('[data-admin-menu-toggle]');
    var menu = document.querySelector('[data-admin-menu]');
    if (!toggle || !menu) {
      return;
    }

    function syncMenuState() {
      if (window.innerWidth > 640) {
        document.body.classList.remove('admin-menu-open');
        toggle.setAttribute('aria-expanded', 'false');
      }
    }

    toggle.addEventListener('click', function () {
      var isOpen = document.body.classList.toggle('admin-menu-open');
      toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    });

    window.addEventListener('resize', syncMenuState);
    syncMenuState();
  })();
</script>
</body>
</html>
