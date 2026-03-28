<?php
require_once __DIR__ . '/_init.php';
admin_require_login();

$pdo = db();
$flash = admin_flash_get();
$socialPreviewPayload = $_SESSION['admin_social_preview'] ?? null;
unset($_SESSION['admin_social_preview']);
$pendingSocialJob = $_SESSION['admin_social_pending_job'] ?? null;
$search = trim((string) ($_GET['q'] ?? ''));
$store = trim((string) ($_GET['loja'] ?? ''));
$limitDefault = 10;
$limit = (int) ($_GET['limit'] ?? $limitDefault);
$limit = max(1, min($limit, 30));
$page = max(1, (int) ($_GET['page'] ?? 1));

function social_admin_query(array $overrides = []) {
  global $search, $store, $limit, $page;
  $params = [
    'q' => $search,
    'loja' => $store,
    'limit' => $limit,
    'page' => $page,
  ];
  foreach ($overrides as $key => $value) {
    $params[$key] = $value;
  }
  return http_build_query(array_filter($params, static function ($value) {
    return $value !== '' && $value !== null;
  }));
}

function social_offer_video_url(array $offer): string {
  $manualVideo = trim((string) tag_url_decode($offer['tags'] ?? '', 'offer_video_url:'));
  if ($manualVideo !== '') {
    return $manualVideo;
  }
  return trim((string) tag_url_decode($offer['tags'] ?? '', 'shopee_video_url:'));
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
  admin_csrf_check_or_die();
  $action = (string) ($_POST['acao'] ?? '');
  $redirectQuery = social_admin_query(['page' => 1]);

  if ($action === 'publish_selected') {
    $platform = trim((string) ($_POST['platform'] ?? 'facebook'));
    $mode = trim((string) ($_POST['mode'] ?? 'feed_story_reel'));
    $offerIds = array_values(array_unique(array_filter(array_map('intval', (array) ($_POST['offer_ids'] ?? [])))));

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
    $_SESSION['admin_social_preview'] = null;
    $jobStart = admin_start_python_job_async($args, [
      'kind' => 'social_publish_selected',
      'target_tab' => 'social',
    ]);
    if (!empty($jobStart['ok'])) {
      $_SESSION['admin_social_pending_job'] = [
        'job_id' => (string) ($jobStart['job_id'] ?? ''),
        'kind' => 'social_publish_selected',
        'platform' => $platform,
        'mode' => $mode,
        'redirect_url' => '/admin/social.php?' . $redirectQuery,
      ];
      admin_flash_set('success', 'Publicacao iniciada. Acompanhe o progresso nesta tela.');
    } else {
      admin_flash_set('error', (string) ($jobStart['error'] ?? 'Falha ao iniciar o job social.'));
    }
  } elseif ($action === 'publish_auto') {
    $platform = trim((string) ($_POST['platform'] ?? 'both'));
    $mode = trim((string) ($_POST['mode'] ?? 'feed_story_reel'));
    $autoLimit = max(1, min((int) ($_POST['auto_limit'] ?? 1), 10));
    $_SESSION['admin_social_preview'] = null;
    $jobStart = admin_start_python_job_async(['social', '--platform', $platform, '--mode', $mode, '--limit', (string) $autoLimit], [
      'kind' => 'social_publish_auto',
      'target_tab' => 'social',
    ]);
    if (!empty($jobStart['ok'])) {
      $_SESSION['admin_social_pending_job'] = [
        'job_id' => (string) ($jobStart['job_id'] ?? ''),
        'kind' => 'social_publish_auto',
        'platform' => $platform,
        'mode' => $mode,
        'redirect_url' => '/admin/social.php?' . $redirectQuery,
      ];
      admin_flash_set('success', 'Job social iniciado. Acompanhe o progresso nesta tela.');
    } else {
      admin_flash_set('error', (string) ($jobStart['error'] ?? 'Falha ao iniciar o job social.'));
    }
  }

  header('Location: /admin/social.php?' . $redirectQuery);
  exit;
}

$offersPayload = admin_fetch_social_candidates($pdo, $search, $store, $limit, $page);
$offers = (array) ($offersPayload['items'] ?? []);
foreach ($offers as &$offer) {
  $offer['video_url'] = social_offer_video_url((array) $offer);
  $offer['has_video'] = $offer['video_url'] !== '';
}
unset($offer);
$offersTotal = (int) ($offersPayload['total'] ?? 0);
$page = (int) ($offersPayload['page'] ?? $page);
$totalPages = (int) ($offersPayload['pages'] ?? 1);
$stores = $pdo->query("
  SELECT loja, COUNT(*) AS total
  FROM ofertas
  WHERE ativo = 1 AND (expira_em IS NULL OR expira_em > NOW())
  GROUP BY loja
  ORDER BY total DESC, loja ASC
")->fetchAll();
$recentRuns = admin_fetch_recent_runs($pdo, 'social', 3);
$pythonEnabled = admin_python_job_enabled();
$shellEnabled = admin_shell_exec_enabled();
$adminCssVersion = (string) @filemtime(__DIR__ . '/../assets/css/admin.css');
?>
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Admin - Social</title>
  <link rel="icon" type="image/png" href="/assets/img/logo-zp.png">
  <link rel="stylesheet" href="/assets/css/style.css">
  <link rel="stylesheet" href="/assets/css/admin.css?v=<?= urlencode($adminCssVersion) ?>">
</head>
<body class="admin-page">
<?php admin_render_header('social'); ?>
<template data-legacy-admin-header>
  <div class="container admin-header">
    <div class="admin-brand">
      <a class="admin-brand-link" href="/admin/ofertas.php">
        <div class="admin-brand-mark">
          <img src="/assets/img/logo-zp.png" alt="Zero Preco">
        </div>
      </a>
      <div class="admin-brand-copy">
        <strong>Zero Preço Admin</strong>
        <span>Controle ofertas, links e publicações em um só lugar.</span>
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
      <a class="badge" href="/admin/oferta_editar.php">Nova oferta</a>
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
        <span class="admin-kicker">Seleção social</span>
        <h1>Publicação social</h1>
      </div>
      <div class="admin-hero-actions">
        <span class="admin-status <?= $pythonEnabled ? 'ok' : 'warn' ?>"><?= $pythonEnabled ? 'Runner Python configurado' : 'Configure o runner Python' ?></span>
        <span class="admin-status <?= $shellEnabled ? 'ok' : 'warn' ?>"><?= $shellEnabled ? 'shell_exec habilitado' : 'shell_exec desabilitado' ?></span>
      </div>
    </div>
  </section>

  <?php if (is_array($pendingSocialJob) && !empty($pendingSocialJob['job_id'])): ?>
    <?php
      $pendingPlatform = (string) ($pendingSocialJob['platform'] ?? 'both');
      $pendingMode = (string) ($pendingSocialJob['mode'] ?? 'feed_story_reel');
      $progressTitle = 'Publicando nas redes sociais';
      if ($pendingPlatform === 'instagram') {
        $progressTitle = 'Publicando no Instagram';
      } elseif ($pendingPlatform === 'facebook') {
        $progressTitle = 'Publicando no Facebook';
      } elseif ($pendingPlatform === 'whatsapp') {
        $progressTitle = 'Preparando WhatsApp';
      }
    ?>
    <section class="admin-panel admin-progress-card" id="social-progress-card" data-job-id="<?= h((string) $pendingSocialJob['job_id']) ?>" data-status-url="/admin/social_job_status.php?job_id=<?= urlencode((string) $pendingSocialJob['job_id']) ?>">
      <div class="admin-panel-head">
        <div>
          <h2 class="admin-section-title"><?= h($progressTitle) ?></h2>
          <p id="social-progress-label">Preparando o processamento no servidor.</p>
        </div>
        <div class="admin-meta-row">
          <span class="admin-meta-chip admin-meta-chip-soft" id="social-progress-time">0s</span>
          <span class="admin-meta-chip admin-meta-chip-soft"><?= h($pendingPlatform) ?>/<?= h($pendingMode) ?></span>
        </div>
      </div>
      <div class="admin-progress-bar" aria-hidden="true">
        <div class="admin-progress-bar-fill" id="social-progress-fill" style="width: 10%;"></div>
      </div>
      <p class="admin-card-subtitle">No celular, a tela pode ficar aberta enquanto o painel atualiza automaticamente o andamento da publicacao.</p>
    </section>
  <?php endif; ?>

  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Rodar automático agora</h2>
        <p>Usa a mesma lógica do cron. Se você atualizar os arquivos Python no servidor, os próximos disparos manual e automático já usam a versão nova.</p>
      </div>
    </div>
    <form method="post" class="admin-filter-form">
      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
      <input type="hidden" name="acao" value="publish_auto">
      <div class="admin-field-grid admin-field-grid-compact">
        <div class="admin-field">
          <label for="platform_auto">Plataforma</label>
          <select id="platform_auto" name="platform">
            <option value="facebook">Facebook</option>
            <option value="instagram">Instagram</option>
            <option value="both" selected>Facebook + Instagram</option>
            <option value="whatsapp">WhatsApp</option>
          </select>
        </div>
        <div class="admin-field">
          <label for="mode_auto">Formato</label>
          <select id="mode_auto" name="mode">
            <option value="feed">Feed</option>
            <option value="reel">Reel</option>
            <option value="feed_story">Feed + Story</option>
            <option value="feed_story_reel" selected>Feed + Story + Reel</option>
            <option value="story">Story</option>
            <option value="web">WhatsApp Web Local</option>
          </select>
        </div>
        <div class="admin-field">
          <label for="auto_limit">Quantidade</label>
          <input id="auto_limit" type="number" name="auto_limit" value="1" min="1" max="10">
        </div>
        <div class="admin-field admin-field-submit">
          <label>&nbsp;</label>
          <button class="btn" type="submit">Rodar job automático</button>
        </div>
      </div>
    </form>
  </section>

  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Selecionar produtos manualmente</h2>
        <p>Esta tela substitui a seleção do painel Python. O processamento continua no Python, mas a curadoria fica no PHP.</p>
      </div>
    </div>

    <form method="get" class="admin-filter-form">
      <div class="admin-field-grid admin-field-grid-compact">
        <div class="admin-field">
          <label for="q">Buscar</label>
          <input id="q" name="q" value="<?= h($search) ?>" placeholder="Título, categoria, tag ou loja">
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
          <input id="limit" type="number" name="limit" value="<?= (int) $limit ?>" min="1" max="30">
        </div>
        <div class="admin-field admin-field-submit">
          <label>&nbsp;</label>
          <button class="btn-link primary" type="submit">Filtrar</button>
        </div>
      </div>
      <input type="hidden" name="page" value="1">
    </form>

    <form method="post" id="social-manual-form">
      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
      <input type="hidden" name="acao" value="publish_selected">
      <div class="admin-field-grid admin-field-grid-compact" style="margin-top:18px;">
        <div class="admin-field">
          <label for="platform_manual">Plataforma</label>
          <select id="platform_manual" name="platform">
            <option value="facebook">Facebook</option>
            <option value="instagram">Instagram</option>
            <option value="both" selected>Facebook + Instagram</option>
            <option value="whatsapp">WhatsApp</option>
          </select>
        </div>
        <div class="admin-field">
          <label for="mode_manual">Formato</label>
          <select id="mode_manual" name="mode">
            <option value="feed">Feed</option>
            <option value="reel">Reel</option>
            <option value="feed_story">Feed + Story</option>
            <option value="feed_story_reel" selected>Feed + Story + Reel</option>
            <option value="story">Story</option>
            <option value="web">WhatsApp Web Local</option>
          </select>
        </div>
        <div class="admin-field admin-field-submit">
          <label>&nbsp;</label>
          <button class="btn" type="submit" id="social-manual-submit">Publicar selecionadas</button>
        </div>
      </div>

      <?php if (is_array($socialPreviewPayload) && ($socialPreviewPayload['platform'] ?? '') === 'whatsapp' && !empty($socialPreviewPayload['items'])): ?>
        <div class="admin-side-card" style="margin-top:18px;">
          <strong>Preview WhatsApp Web Local</strong>
          <div class="admin-help" style="margin-top:8px;">Imagem e legenda prontas para abrir no WhatsApp Web e enviar manualmente.</div>
          <?php if (!empty($socialPreviewPayload['stories_deploy_error'])): ?>
            <div class="admin-alert error" style="margin-top:12px;"><?= h((string) $socialPreviewPayload['stories_deploy_error']) ?></div>
          <?php endif; ?>
          <div class="admin-offers-grid" style="margin-top:14px;">
            <?php foreach ((array) $socialPreviewPayload['items'] as $index => $item): ?>
              <?php $previewImage = (string) ($item['image_url'] ?? $item['product_image_url'] ?? ''); ?>
              <?php $fallbackImage = (string) ($item['product_image_url'] ?? ''); ?>
              <?php $previewMessage = (string) ($item['message'] ?? ''); ?>
              <article class="admin-offer-card" style="padding:16px;">
                <div class="admin-offer-layout" style="grid-template-columns: 112px minmax(0, 1fr);">
                  <div>
                    <?php if ($previewImage !== ''): ?>
                      <img
                        class="admin-offer-thumb"
                        src="<?= h($previewImage) ?>"
                        alt="<?= h((string) ($item['title'] ?? 'Preview WhatsApp')) ?>"
                        <?= $fallbackImage !== '' ? 'onerror="if(this.dataset.fallback){this.onerror=null;this.src=this.dataset.fallback;}" data-fallback="' . h($fallbackImage) . '"' : '' ?>
                      >
                    <?php else: ?>
                      <div class="admin-thumb-fallback">WA</div>
                    <?php endif; ?>
                  </div>
                  <div>
                    <h3 class="admin-card-title"><?= h((string) ($item['title'] ?? ('Item ' . ($index + 1)))) ?></h3>
                    <div class="admin-help" style="margin-top:10px; white-space:pre-wrap;"><?= h($previewMessage) ?></div>
                    <div class="admin-card-actions" style="margin-top:12px;">
                      <?php if (!empty($item['web_share_url'])): ?>
                        <a class="btn-link primary" href="<?= h((string) $item['web_share_url']) ?>" target="_blank" rel="noopener">Abrir no WhatsApp Web</a>
                      <?php endif; ?>
                      <?php if ($previewImage !== ''): ?>
                        <button class="btn-link" type="button" data-copy-image="<?= h($previewImage) ?>">Copiar imagem</button>
                      <?php endif; ?>
                      <?php if ($previewMessage !== ''): ?>
                        <button class="btn-link" type="button" data-copy-text="<?= h($previewMessage) ?>">Copiar legenda</button>
                      <?php endif; ?>
                      <?php if (!empty($item['cta_url'])): ?>
                        <a class="btn-link" href="<?= h((string) $item['cta_url']) ?>" target="_blank" rel="noopener sponsored nofollow">Link afiliado</a>
                      <?php endif; ?>
                    </div>
                  </div>
                </div>
              </article>
            <?php endforeach; ?>
          </div>
        </div>
      <?php endif; ?>

      <?php if (!$offers): ?>
        <div class="admin-empty" style="margin-top:18px;">Nenhuma oferta elegível para publicação com estes filtros.</div>
      <?php else: ?>
        <div class="admin-meta-row" style="margin-top:18px;">
          <span class="admin-meta-chip"><?= (int) $offersTotal ?> ofertas eleg&iacute;veis</span>
          <span class="admin-meta-chip">P&aacute;gina <?= (int) $page ?> de <?= (int) $totalPages ?></span>
          <span class="admin-meta-chip" id="social-selected-count">0 selecionadas</span>
          <button class="btn-link" type="button" id="social-clear-selection">Desmarcar selecionadas</button>
        </div>
        <div class="admin-offers-grid" style="margin-top:18px;">
          <?php foreach ($offers as $offer): ?>
            <article class="admin-offer-card" data-social-offer-card="<?= !empty($offer['has_video']) ? '1' : '0' ?>">
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
                    <?php if (!empty($offer['has_video'])): ?>
                      <span class="admin-status warn">Vídeo cadastrado</span>
                      <span class="admin-status ok" data-social-video-badge>Vai usar vídeo</span>
                    <?php endif; ?>
                    <span class="admin-status ok">Afiliado OK</span>
                  </div>
                </div>
                <div class="admin-mini-grid">
                  <div class="admin-side-card">
                    <label class="admin-check-chip">
                      <input type="checkbox" name="offer_ids[]" value="<?= (int) $offer['id'] ?>" data-social-offer-checkbox>
                      Selecionar oferta <?= (int) $offer['id'] ?>
                    </label>
                  </div>
                  <div class="admin-side-card">
                    <strong>Link afiliado</strong>
                    <div class="admin-card-actions" style="margin-top:10px;">
                      <a class="btn-link" href="<?= h($offer['url_afiliado']) ?>" target="_blank" rel="noopener sponsored nofollow">Link afiliado</a>
                    </div>
                  </div>
                </div>
              </div>
            </article>
          <?php endforeach; ?>
        </div>
        <?php if ($totalPages > 1): ?>
          <div class="admin-meta-row" style="margin-top:18px; gap:10px; flex-wrap:wrap;">
            <?php if ($page > 1): ?>
              <a class="btn-link" href="/admin/social.php?<?= h(social_admin_query(['page' => $page - 1])) ?>">P&aacute;gina anterior</a>
            <?php endif; ?>
            <?php for ($pageNumber = max(1, $page - 2); $pageNumber <= min($totalPages, $page + 2); $pageNumber++): ?>
              <a class="btn-link <?= $pageNumber === $page ? 'primary' : '' ?>" href="/admin/social.php?<?= h(social_admin_query(['page' => $pageNumber])) ?>">
                <?= (int) $pageNumber ?>
              </a>
            <?php endfor; ?>
            <?php if ($page < $totalPages): ?>
              <a class="btn-link" href="/admin/social.php?<?= h(social_admin_query(['page' => $page + 1])) ?>">Pr&oacute;xima p&aacute;gina</a>
            <?php endif; ?>
          </div>
        <?php endif; ?>
      <?php endif; ?>
    </form>
  </section>

  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Histórico de execuções</h2>
        <p>O cron e o botao manual gravam no mesmo historico.</p>
      </div>
    </div>
    <?php if (!$recentRuns): ?>
      <div class="admin-empty">Nenhuma execução social registrada ainda.</div>
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

  (function () {
    var progressCard = document.getElementById('social-progress-card');
    if (!progressCard) {
      return;
    }

    var statusUrl = progressCard.getAttribute('data-status-url');
    var fill = document.getElementById('social-progress-fill');
    var label = document.getElementById('social-progress-label');
    var elapsed = document.getElementById('social-progress-time');
    var finished = false;

    function formatElapsed(seconds) {
      var total = Math.max(0, Number(seconds) || 0);
      if (total < 60) {
        return total + 's';
      }
      var minutes = Math.floor(total / 60);
      var rest = total % 60;
      return minutes + 'm ' + rest + 's';
    }

    async function pollStatus() {
      if (finished || !statusUrl) {
        return;
      }
      try {
        var response = await fetch(statusUrl, { credentials: 'same-origin', cache: 'no-store' });
        var payload = await response.json();
        if (!payload || !payload.ok) {
          window.setTimeout(pollStatus, 2500);
          return;
        }
        if (fill) {
          fill.style.width = Math.max(8, Math.min(100, Number(payload.progress_percent) || 10)) + '%';
        }
        if (label && payload.progress_label) {
          label.textContent = payload.progress_label;
        }
        if (elapsed) {
          elapsed.textContent = formatElapsed(payload.elapsed_seconds);
        }
        if (payload.status === 'success' || payload.status === 'error') {
          finished = true;
          window.location.href = payload.redirect_url || '/admin/social.php';
          return;
        }
      } catch (error) {
      }
      window.setTimeout(pollStatus, 2500);
    }

    window.setTimeout(pollStatus, 1200);
  })();

  (function () {
    var storageKey = 'admin-social-selected-offers';
    var form = document.getElementById('social-manual-form');
    var checkboxes = document.querySelectorAll('[data-social-offer-checkbox]');
    var selectedCount = document.getElementById('social-selected-count');
    var clearButton = document.getElementById('social-clear-selection');
    if (!form || !checkboxes.length) {
      return;
    }

    function loadSelected() {
      try {
        return JSON.parse(window.localStorage.getItem(storageKey) || '[]');
      } catch (error) {
        return [];
      }
    }

    function saveSelected(values) {
      window.localStorage.setItem(storageKey, JSON.stringify(values));
    }

    function updateSelectedCount(values) {
      if (selectedCount) {
        selectedCount.textContent = values.length + ' selecionadas';
      }
    }

    var selected = loadSelected().map(function (value) { return String(value); });
    checkboxes.forEach(function (checkbox) {
      var value = String(checkbox.value);
      checkbox.checked = selected.indexOf(value) !== -1;
      checkbox.addEventListener('change', function () {
        var current = loadSelected().map(function (item) { return String(item); });
        if (checkbox.checked) {
          if (current.indexOf(value) === -1) {
            current.push(value);
          }
        } else {
          current = current.filter(function (item) { return item !== value; });
        }
        saveSelected(current);
        updateSelectedCount(current);
      });
    });
    updateSelectedCount(selected);

    if (clearButton) {
      clearButton.addEventListener('click', function () {
        saveSelected([]);
        checkboxes.forEach(function (checkbox) {
          checkbox.checked = false;
        });
        updateSelectedCount([]);
      });
    }

    form.addEventListener('submit', function () {
      form.querySelectorAll('input[data-social-selected-hidden]').forEach(function (input) {
        input.remove();
      });
      loadSelected().forEach(function (value) {
        var hidden = document.createElement('input');
        hidden.type = 'hidden';
        hidden.name = 'offer_ids[]';
        hidden.value = value;
        hidden.setAttribute('data-social-selected-hidden', '1');
        form.appendChild(hidden);
      });
    });
  })();

  (function () {
    var imageButtons = document.querySelectorAll('[data-copy-image]');
    imageButtons.forEach(function (button) {
      button.addEventListener('click', async function () {
        var imageUrl = button.getAttribute('data-copy-image') || '';
        if (!imageUrl) {
          return;
        }

        var original = button.textContent;
        try {
          if (!navigator.clipboard || !window.ClipboardItem) {
            throw new Error('clipboard-image-unavailable');
          }

          var response = await fetch(imageUrl, { credentials: 'same-origin' });
          if (!response.ok) {
            throw new Error('image-fetch-failed');
          }

          var blob = await response.blob();
          var clipboardBlob = blob;
          if (blob.type !== 'image/png') {
            clipboardBlob = await new Promise(function (resolve, reject) {
              var image = new Image();
              image.crossOrigin = 'anonymous';
              image.onload = function () {
                var canvas = document.createElement('canvas');
                canvas.width = image.naturalWidth || image.width;
                canvas.height = image.naturalHeight || image.height;
                var context = canvas.getContext('2d');
                if (!context) {
                  reject(new Error('canvas-context-unavailable'));
                  return;
                }
                context.drawImage(image, 0, 0);
                canvas.toBlob(function (pngBlob) {
                  if (!pngBlob) {
                    reject(new Error('png-conversion-failed'));
                    return;
                  }
                  resolve(pngBlob);
                }, 'image/png');
              };
              image.onerror = function () {
                reject(new Error('image-load-failed'));
              };
              image.src = imageUrl;
            });
          }

          await navigator.clipboard.write([
            new ClipboardItem({
              'image/png': clipboardBlob
            })
          ]);

          button.textContent = 'Imagem copiada';
        } catch (error) {
          button.textContent = 'Nao copiou';
        }

        window.setTimeout(function () {
          button.textContent = original;
        }, 1600);
      });
    });
  })();

  (function () {
    var copyButtons = document.querySelectorAll('[data-copy-text]');
    if (!copyButtons.length || !navigator.clipboard || !navigator.clipboard.writeText) {
      return;
    }

    copyButtons.forEach(function (button) {
      button.addEventListener('click', function () {
        var text = button.getAttribute('data-copy-text') || '';
        if (!text) {
          return;
        }

        navigator.clipboard.writeText(text).then(function () {
          var original = button.textContent;
          button.textContent = 'Copiado';
          window.setTimeout(function () {
            button.textContent = original;
          }, 1400);
        });
      });
    });
  })();

  (function () {
    var platform = document.getElementById('platform_manual');
    var mode = document.getElementById('mode_manual');
    var submit = document.getElementById('social-manual-submit');
    if (!platform || !mode || !submit) {
      return;
    }

    function syncManualSubmitLabel() {
      var isWhatsappWeb = platform.value === 'whatsapp' && mode.value === 'web';
      submit.textContent = isWhatsappWeb ? 'Preparar' : 'Publicar selecionadas';
    }

    function manualModeUsesVideo() {
      if (platform.value === 'whatsapp' || mode.value === 'web') {
        return false;
      }
      return ['story', 'reel', 'feed_story', 'feed_story_reel'].indexOf(mode.value) !== -1;
    }

    function syncVideoBadges() {
      var useVideo = manualModeUsesVideo();
      document.querySelectorAll('[data-social-offer-card="1"] [data-social-video-badge]').forEach(function (badge) {
        badge.hidden = !useVideo;
      });
    }

    function syncManualMode() {
      if (platform.value === 'whatsapp') {
        mode.value = 'web';
      } else if (mode.value === 'web') {
        mode.value = 'feed_story_reel';
      }
    }

    platform.addEventListener('change', function () {
      syncManualMode();
      syncManualSubmitLabel();
      syncVideoBadges();
    });
    platform.addEventListener('change', syncManualSubmitLabel);
    mode.addEventListener('change', syncManualSubmitLabel);
    mode.addEventListener('change', syncVideoBadges);
    syncManualMode();
    syncManualSubmitLabel();
    syncVideoBadges();
  })();

  (function () {
    var forms = document.querySelectorAll('#social-manual-form, .admin-filter-form');
    forms.forEach(function (form) {
      form.addEventListener('submit', function () {
        var submitter = form.querySelector('button[type="submit"]');
        if (!submitter) {
          return;
        }
        submitter.disabled = true;
        if (submitter.id === 'social-manual-submit') {
          submitter.textContent = 'Iniciando...';
        } else {
          submitter.textContent = 'Processando...';
        }
      });
    });
  })();
</script>
</body>
</html>
