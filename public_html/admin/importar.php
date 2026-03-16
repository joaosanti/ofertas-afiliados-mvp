<?php
require_once __DIR__ . '/_init.php';
admin_require_login();

$pdo = db();
$flash = admin_flash_get();
$recentRuns = admin_fetch_recent_runs($pdo, 'import', 12);
$resultPayload = null;

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
      $resultPayload = admin_run_python_job(['import-file', '--kind', $kind, '--input-file', $target]);
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
      $resultPayload = admin_run_python_job(['import-links', '--input-file', $target]);
    } finally {
      @unlink($target);
    }
  }

  if ($resultPayload !== null) {
    if (!empty($resultPayload['ok'])) {
      admin_flash_set('success', 'Importacao executada pelo Python com sucesso.');
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
  <link rel="stylesheet" href="/assets/css/style.css">
  <link rel="stylesheet" href="/assets/css/admin.css">
</head>
<body class="admin-page">
<header>
  <div class="container admin-header">
    <div class="admin-brand">
      <div class="admin-brand-mark">
        <img src="/assets/img/logo-zp.png" alt="Zero Preco">
      </div>
      <div class="admin-brand-copy">
        <strong>Importacao manual</strong>
        <span>Arquivo e texto no PHP, processamento no Python.</span>
      </div>
    </div>
    <div class="admin-header-actions">
      <a class="badge" href="/admin/ofertas.php">Ofertas</a>
      <a class="badge" href="/admin/social.php">Social</a>
      <a class="badge" href="/admin/logout.php">Sair</a>
    </div>
  </div>
</header>

<main class="container admin-shell">
  <?php if ($flash): ?>
    <div class="admin-alert <?= h((string) ($flash['type'] ?? '')) ?>"><?= h((string) ($flash['message'] ?? '')) ?></div>
  <?php endif; ?>

  <section class="admin-hero">
    <div class="admin-hero-head">
      <div class="admin-hero-copy">
        <span class="admin-kicker">Importar ofertas</span>
        <h1>Suba arquivo ou cole links no /admin sem depender do painel Python online.</h1>
        <p>Esse fluxo usa o mesmo motor de normalizacao e gravacao no banco. O PHP so organiza a interface e chama o runner Python no servidor.</p>
      </div>
    </div>
  </section>

  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Importar por arquivo</h2>
        <p>Use CSV da Shopee ou TXT com links da Amazon/Mercado Livre.</p>
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
        <p>Cole um link por linha. O Python identifica a loja, tenta ler os dados e grava as ofertas validas.</p>
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
</body>
</html>
