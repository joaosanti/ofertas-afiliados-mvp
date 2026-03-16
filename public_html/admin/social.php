<?php
require_once __DIR__ . '/_init.php';
admin_require_login();

$pdo = db();
$flash = admin_flash_get();
$search = trim((string) ($_GET['q'] ?? ''));
$store = trim((string) ($_GET['loja'] ?? ''));
$limit = (int) ($_GET['limit'] ?? 24);
$limit = max(6, min($limit, 48));
$resultPayload = null;

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
  admin_csrf_check_or_die();
  $action = (string) ($_POST['acao'] ?? '');

  if ($action === 'publish_selected') {
    $platform = trim((string) ($_POST['platform'] ?? 'facebook'));
    $mode = trim((string) ($_POST['mode'] ?? 'feed'));
    $offerIds = array_values(array_filter(array_map('intval', (array) ($_POST['offer_ids'] ?? []))));

    if (!$offerIds) {
      admin_flash_set('error', 'Selecione pelo menos uma oferta para publicar.');
      header('Location: /admin/social.php');
      exit;
    }

    $args = ['social', '--platform', $platform, '--mode', $mode, '--limit', (string) count($offerIds)];
    foreach ($offerIds as $offerId) {
      $args[] = '--offer-id';
      $args[] = (string) $offerId;
    }
    $resultPayload = admin_run_python_job($args);
  } elseif ($action === 'publish_auto') {
    $platform = trim((string) ($_POST['platform'] ?? 'both'));
    $mode = trim((string) ($_POST['mode'] ?? 'feed_story'));
    $autoLimit = max(1, min((int) ($_POST['auto_limit'] ?? 1), 10));
    $resultPayload = admin_run_python_job(['social', '--platform', $platform, '--mode', $mode, '--limit', (string) $autoLimit]);
  }

  if ($resultPayload !== null) {
    if (!empty($resultPayload['ok'])) {
      admin_flash_set('success', 'Job enviado para o Python. Confira o resultado no historico abaixo.');
    } else {
      admin_flash_set('error', (string) ($resultPayload['error'] ?? 'Falha ao executar o job Python.'));
    }

    $query = [];
    if ($search !== '') {
      $query['q'] = $search;
    }
    if ($store !== '') {
      $query['loja'] = $store;
    }
    $query['limit'] = $limit;

    header('Location: /admin/social.php?' . http_build_query($query));
    exit;
  }
}

$offers = admin_fetch_social_candidates($pdo, $search, $store, $limit);
$stores = $pdo->query("
  SELECT loja, COUNT(*) AS total
  FROM ofertas
  WHERE ativo = 1 AND (expira_em IS NULL OR expira_em > NOW())
  GROUP BY loja
  ORDER BY total DESC, loja ASC
")->fetchAll();
$recentRuns = admin_fetch_recent_runs($pdo, 'social', 12);
$pythonEnabled = admin_python_job_enabled();
$shellEnabled = admin_shell_exec_enabled();
?>
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Admin - Social</title>
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
        <strong>Social e automacao</strong>
        <span>Selecao manual no PHP e execucao do job pelo Python/cron.</span>
      </div>
    </div>
    <div class="admin-header-actions">
      <a class="badge" href="/admin/ofertas.php">Ofertas</a>
      <a class="badge" href="/admin/oferta_editar.php">Nova oferta</a>
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
        <span class="admin-kicker">Selecao social</span>
        <h1>Escolha as ofertas no /admin e deixe o Python cuidar da publicacao.</h1>
        <p>O cron nao atualiza codigo sozinho: ele apenas executa o que estiver salvo no servidor. Quando voce subir uma nova versao do Python, o proximo cron ja usa essa versao automaticamente.</p>
      </div>
      <div class="admin-hero-actions">
        <span class="admin-status <?= $pythonEnabled ? 'ok' : 'warn' ?>"><?= $pythonEnabled ? 'Runner Python configurado' : 'Configure o runner Python' ?></span>
        <span class="admin-status <?= $shellEnabled ? 'ok' : 'warn' ?>"><?= $shellEnabled ? 'shell_exec habilitado' : 'shell_exec desabilitado' ?></span>
      </div>
    </div>
  </section>

  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Rodar automatico agora</h2>
        <p>Usa a mesma logica do cron. Se voce atualizar os arquivos Python no servidor, os proximos disparos manual e automatico ja usam a versao nova.</p>
      </div>
    </div>
    <form method="post" class="admin-filter-form">
      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
      <input type="hidden" name="acao" value="publish_auto">
      <div class="admin-field-grid">
        <div class="admin-field">
          <label for="platform_auto">Plataforma</label>
          <select id="platform_auto" name="platform">
            <option value="facebook">Facebook</option>
            <option value="instagram">Instagram</option>
            <option value="both" selected>Facebook + Instagram</option>
          </select>
        </div>
        <div class="admin-field">
          <label for="mode_auto">Formato</label>
          <select id="mode_auto" name="mode">
            <option value="feed">Feed</option>
            <option value="reel">Reel</option>
            <option value="feed_story" selected>Feed + Story</option>
            <option value="story">Story</option>
          </select>
        </div>
        <div class="admin-field">
          <label for="auto_limit">Quantidade</label>
          <input id="auto_limit" type="number" name="auto_limit" value="1" min="1" max="10">
        </div>
      </div>
      <div class="admin-form-actions">
        <button class="btn" type="submit">Rodar job automatico</button>
      </div>
    </form>
  </section>

  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Selecionar produtos manualmente</h2>
        <p>Esta tela substitui a selecao do painel Python. O processamento continua no Python, mas a curadoria fica no PHP.</p>
      </div>
    </div>

    <form method="get" class="admin-filter-form">
      <div class="admin-field-grid">
        <div class="admin-field">
          <label for="q">Buscar</label>
          <input id="q" name="q" value="<?= h($search) ?>" placeholder="Titulo, categoria, tag ou loja">
        </div>
        <div class="admin-field">
          <label for="loja">Loja</label>
          <select id="loja" name="loja">
            <option value="">Todas</option>
            <?php foreach ($stores as $storeRow): ?>
              <option value="<?= h($storeRow['loja']) ?>" <?= $store === $storeRow['loja'] ? 'selected' : '' ?>>
                <?= h($storeRow['loja']) ?> (<?= (int) $storeRow['total'] ?>)
              </option>
            <?php endforeach; ?>
          </select>
        </div>
        <div class="admin-field">
          <label for="limit">Limite</label>
          <input id="limit" type="number" name="limit" value="<?= (int) $limit ?>" min="6" max="48">
        </div>
      </div>
      <div class="admin-form-actions">
        <button class="btn-link primary" type="submit">Filtrar</button>
      </div>
    </form>

    <form method="post">
      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
      <input type="hidden" name="acao" value="publish_selected">
      <div class="admin-field-grid" style="margin-top:18px;">
        <div class="admin-field">
          <label for="platform_manual">Plataforma</label>
          <select id="platform_manual" name="platform">
            <option value="facebook">Facebook</option>
            <option value="instagram">Instagram</option>
            <option value="both" selected>Facebook + Instagram</option>
          </select>
        </div>
        <div class="admin-field">
          <label for="mode_manual">Formato</label>
          <select id="mode_manual" name="mode">
            <option value="feed">Feed</option>
            <option value="reel">Reel</option>
            <option value="feed_story" selected>Feed + Story</option>
            <option value="story">Story</option>
          </select>
        </div>
      </div>

      <?php if (!$offers): ?>
        <div class="admin-empty" style="margin-top:18px;">Nenhuma oferta elegivel para publicacao com estes filtros.</div>
      <?php else: ?>
        <div class="admin-offers-grid" style="margin-top:18px;">
          <?php foreach ($offers as $offer): ?>
            <article class="admin-offer-card">
              <div class="admin-offer-layout">
                <div>
                  <img class="admin-offer-thumb" src="<?= h($offer['imagem_url']) ?>" alt="<?= h($offer['titulo']) ?>">
                </div>
                <div>
                  <div class="admin-card-topline">
                    <div>
                      <h3 class="admin-card-title"><?= h($offer['titulo']) ?></h3>
                      <div class="admin-card-subtitle">ID <?= (int) $offer['id'] ?> · <?= h($offer['loja']) ?> · <?= h($offer['categoria']) ?></div>
                    </div>
                  </div>
                  <div class="admin-preview-price">
                    <span class="admin-price">R$ <?= number_format((float) $offer['preco'], 2, ',', '.') ?></span>
                    <?php if ($offer['preco_antigo'] !== null && (float) $offer['preco_antigo'] > (float) $offer['preco']): ?>
                      <span class="admin-price-old">R$ <?= number_format((float) $offer['preco_antigo'], 2, ',', '.') ?></span>
                    <?php endif; ?>
                  </div>
                  <div class="admin-meta-row" style="margin-top:12px;">
                    <span class="admin-meta-chip"><?= (int) ($offer['clicks'] ?? 0) ?> cliques</span>
                    <?php if (!empty($offer['cupom'])): ?>
                      <span class="admin-meta-chip">cupom <?= h($offer['cupom']) ?></span>
                    <?php endif; ?>
                    <span class="admin-status ok">Afiliado OK</span>
                  </div>
                </div>
                <div class="admin-mini-grid">
                  <div class="admin-side-card">
                    <label class="admin-check-chip">
                      <input type="checkbox" name="offer_ids[]" value="<?= (int) $offer['id'] ?>">
                      Selecionar oferta <?= (int) $offer['id'] ?>
                    </label>
                  </div>
                  <div class="admin-side-card">
                    <strong>Link afiliado</strong>
                    <div class="admin-url-box"><?= h($offer['url_afiliado']) ?></div>
                  </div>
                </div>
              </div>
            </article>
          <?php endforeach; ?>
        </div>
        <div class="admin-form-actions" style="margin-top:18px;">
          <button class="btn" type="submit">Publicar selecionadas</button>
        </div>
      <?php endif; ?>
    </form>
  </section>

  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Historico de execucoes</h2>
        <p>O cron e o botao manual gravam no mesmo historico.</p>
      </div>
    </div>
    <?php if (!$recentRuns): ?>
      <div class="admin-empty">Nenhuma execucao social registrada ainda.</div>
    <?php else: ?>
      <div class="admin-offers-grid">
        <?php foreach ($recentRuns as $run): ?>
          <article class="admin-offer-card">
            <div class="admin-meta-row">
              <span class="admin-meta-chip">Run #<?= (int) $run['id'] ?></span>
              <span class="admin-status <?= $run['status'] === 'success' ? 'ok' : ($run['status'] === 'running' ? 'warn' : 'off') ?>"><?= h($run['status']) ?></span>
              <span class="admin-meta-chip"><?= h((string) ($run['canal'] ?? '-')) ?>/<?= h((string) ($run['modo'] ?? '-')) ?></span>
              <span class="admin-meta-chip">solicitado <?= (int) ($run['requested_count'] ?? 0) ?></span>
              <span class="admin-meta-chip">processado <?= (int) ($run['processed_count'] ?? 0) ?></span>
            </div>
            <div class="admin-help" style="margin-top:12px;">
              Criado em <?= h((string) $run['criado_em']) ?>
              <?php if (!empty($run['finalizado_em'])): ?>
                · Finalizado em <?= h((string) $run['finalizado_em']) ?>
              <?php endif; ?>
            </div>
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
