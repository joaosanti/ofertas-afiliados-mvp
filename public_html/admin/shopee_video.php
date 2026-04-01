<?php
require_once __DIR__ . '/_init.php';
admin_require_login();

$pdo = db();
$flash = admin_flash_get();
$apiSnapshot = admin_shopee_video_api_snapshot();
$search = trim((string) ($_GET['q'] ?? ''));
$limit = max(1, min((int) ($_GET['limit'] ?? 12), 30));
$page = max(1, (int) ($_GET['page'] ?? 1));
$onlyWithVideo = (string) ($_GET['com_video'] ?? '1') !== '0';
$draftStatus = trim((string) ($_GET['draft_status'] ?? ''));
$view = trim((string) ($_GET['view'] ?? 'queue'));
if (!in_array($view, ['queue', 'drafts', 'packages'], true)) {
  $view = 'queue';
}

function shopee_video_admin_query(array $overrides = []) {
  global $search, $limit, $page, $onlyWithVideo, $draftStatus, $view;
  $params = [
    'q' => $search,
    'limit' => $limit,
    'page' => $page,
    'com_video' => $onlyWithVideo ? '1' : '0',
    'draft_status' => $draftStatus,
    'view' => $view,
  ];
  foreach ($overrides as $key => $value) {
    $params[$key] = $value;
  }
  return http_build_query(array_filter($params, static function ($value) {
    return $value !== '' && $value !== null;
  }));
}

function shopee_video_extra_gallery_urls($item) {
  $gallery = array_values(array_filter((array) ($item['image_gallery_urls'] ?? []), static function ($url) {
    return trim((string) $url) !== '';
  }));
  if (count($gallery) <= 1) {
    return [];
  }
  return array_slice($gallery, 1, 5);
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
  admin_csrf_check_or_die();
  $action = trim((string) ($_POST['acao'] ?? ''));

  try {
    if ($action === 'create_selected') {
      $mode = trim((string) ($_POST['mode'] ?? 'manual'));
      $offerIds = array_values(array_unique(array_filter(array_map('intval', (array) ($_POST['offer_ids'] ?? [])))));
      if (!$offerIds) {
        throw new RuntimeException('Selecione pelo menos uma oferta Shopee para gerar rascunho.');
      }

      foreach ($offerIds as $offerId) {
        admin_upsert_shopee_video_draft($pdo, $offerId, $mode, admin_user_id(), admin_current_login_name());
      }

      admin_flash_set('success', count($offerIds) . ' rascunho(s) de Shopee Video atualizados com sucesso.');
    } elseif ($action === 'update_draft_status') {
      $draftId = (int) ($_POST['draft_id'] ?? 0);
      $status = trim((string) ($_POST['status'] ?? ''));
      if ($draftId <= 0) {
        throw new RuntimeException('Rascunho invalido.');
      }
      admin_update_shopee_video_draft_status($pdo, $draftId, $status);
      admin_flash_set('success', 'Status do rascunho atualizado.');
    } elseif ($action === 'export_selected') {
      $draftIds = array_values(array_unique(array_filter(array_map('intval', (array) ($_POST['draft_ids'] ?? [])))));
      $csv = admin_export_shopee_video_drafts_csv($pdo, $draftIds);
      header('Content-Type: text/csv; charset=utf-8');
      header('Content-Disposition: attachment; filename="shopee-video-drafts-' . gmdate('Ymd-His') . '.csv"');
      echo $csv;
      exit;
    } elseif ($action === 'generate_package') {
      $draftId = (int) ($_POST['draft_id'] ?? 0);
      if ($draftId <= 0) {
        throw new RuntimeException('Rascunho invalido para gerar pacote.');
      }
      $resultPayload = admin_run_python_job([
        'shopee-video-package',
        '--draft-id',
        (string) $draftId,
      ]);
      if (empty($resultPayload['ok']) || !is_array($resultPayload['result'] ?? null)) {
        $errorMessage = (string) ($resultPayload['error'] ?? 'Falha ao gerar o pacote profissional.');
        admin_mark_shopee_video_package_error($pdo, $draftId, $errorMessage);
        throw new RuntimeException($errorMessage);
      }
      $storedPackage = admin_store_shopee_video_package_result($pdo, $draftId, (array) $resultPayload['result']);
      if (($storedPackage['status'] ?? '') === 'ready') {
        admin_flash_set('success', 'Pacote profissional gerado com sucesso para o draft #' . $draftId . '.');
      } elseif (($storedPackage['status'] ?? '') === 'partial') {
        admin_flash_set('warn', 'Pacote do draft #' . $draftId . ' foi gerado parcialmente. ' . (string) ($storedPackage['error'] ?? 'Verifique os avisos do pacote.'));
      } else {
        admin_flash_set('error', 'Pacote do draft #' . $draftId . ' nao gerou o video base. ' . (string) ($storedPackage['error'] ?? ''));
      }
    } elseif ($action === 'delete_package') {
      $draftId = (int) ($_POST['draft_id'] ?? 0);
      if ($draftId <= 0) {
        throw new RuntimeException('Pacote invalido.');
      }
      if (!admin_delete_shopee_video_package($pdo, $draftId)) {
        throw new RuntimeException('Nao consegui excluir esse pacote agora.');
      }
      admin_flash_set('success', 'Pacote do draft #' . $draftId . ' removido com sucesso.');
    } elseif ($action === 'delete_all_packages') {
      $deletedCount = admin_delete_all_active_shopee_video_packages($pdo, $search);
      if ($deletedCount <= 0) {
        throw new RuntimeException('Nenhum pacote ativo foi removido.');
      }
      admin_flash_set('success', $deletedCount . ' pacote(s) pro ativo(s) removido(s) com sucesso.');
    } elseif ($action === 'delete_all_drafts') {
      $deletedCount = admin_delete_all_shopee_video_drafts($pdo, $draftStatus);
      if ($deletedCount <= 0) {
        throw new RuntimeException('Nenhum rascunho recente foi removido.');
      }
      admin_flash_set('success', $deletedCount . ' rascunho(s) recente(s) removido(s) com sucesso.');
    } elseif ($action === 'delete_draft') {
      $draftId = (int) ($_POST['draft_id'] ?? 0);
      if ($draftId <= 0) {
        throw new RuntimeException('Rascunho invalido para exclusao.');
      }
      if (!admin_delete_shopee_video_draft($pdo, $draftId)) {
        throw new RuntimeException('Nao consegui excluir esse rascunho agora.');
      }
      admin_flash_set('success', 'Rascunho #' . $draftId . ' removido com sucesso.');
    }
  } catch (Throwable $e) {
    admin_flash_set('error', $e->getMessage());
  }

  header('Location: /admin/shopee_video.php?' . shopee_video_admin_query(['page' => 1]));
  exit;
}

$expiredPackageCount = admin_cleanup_expired_shopee_video_packages($pdo, admin_shopee_video_package_ttl_hours());
$candidatesPayload = admin_fetch_shopee_video_candidates($pdo, $search, $limit, $page, $onlyWithVideo);
$candidates = (array) ($candidatesPayload['items'] ?? []);
$candidateTotal = (int) ($candidatesPayload['total'] ?? 0);
$page = (int) ($candidatesPayload['page'] ?? $page);
$totalPages = (int) ($candidatesPayload['pages'] ?? 1);
$drafts = admin_fetch_shopee_video_drafts($pdo, $draftStatus, 30);
$packages = admin_fetch_shopee_video_packages($pdo, $search, 60);
$packageTtlHours = admin_shopee_video_package_ttl_hours();
$adminCssVersion = (string) @filemtime(__DIR__ . '/../assets/css/admin.css');
?>
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Admin - Shopee Video</title>
  <link rel="icon" type="image/png" href="/assets/img/logo-zp.png">
  <link rel="stylesheet" href="/assets/css/style.css">
  <link rel="stylesheet" href="/assets/css/admin.css?v=<?= urlencode($adminCssVersion) ?>">
</head>
<body class="admin-page">
<?php admin_render_header('shopee_video'); ?>

<main class="container admin-shell">
  <?php if ($flash): ?>
    <div class="admin-alert <?= h((string) ($flash['type'] ?? '')) ?>"><?= h((string) ($flash['message'] ?? '')) ?></div>
  <?php endif; ?>
  <?php if ($expiredPackageCount > 0): ?>
    <div class="admin-alert warn"><?= (int) $expiredPackageCount ?> pacote(s) pro expiraram e foram removidos automaticamente do servidor.</div>
  <?php endif; ?>

  <section class="admin-hero">
    <div class="admin-hero-head">
      <div class="admin-hero-copy">
        <span class="admin-kicker">Shopee Video</span>
        <h1>Fila de postagem</h1>
        <p class="admin-card-subtitle">Use o banco atual para montar rascunhos, reaproveitar o video do produto quando existir e separar o que ainda depende de postagem manual no app.</p>
      </div>
      <div class="admin-hero-actions">
        <span class="admin-status <?= !empty($apiSnapshot['catalog_api_configured']) ? 'ok' : 'warn' ?>">
          <?= !empty($apiSnapshot['catalog_api_configured']) ? 'Catalogo API configurado' : 'Catalogo API pendente' ?>
        </span>
        <span class="admin-status warn">Publicacao API nao confirmada</span>
      </div>
    </div>
  </section>

  <nav class="admin-subnav" aria-label="Submenu Shopee Video">
    <a class="admin-subnav-link <?= $view === 'queue' ? 'is-active' : '' ?>" href="/admin/shopee_video.php?<?= h(shopee_video_admin_query(['view' => 'queue', 'page' => 1])) ?>">
      Fila e gerar rascunhos
    </a>
    <a class="admin-subnav-link <?= $view === 'drafts' ? 'is-active' : '' ?>" href="/admin/shopee_video.php?<?= h(shopee_video_admin_query(['view' => 'drafts', 'page' => 1])) ?>">
      Rascunhos recentes
    </a>
    <a class="admin-subnav-link <?= $view === 'packages' ? 'is-active' : '' ?>" href="/admin/shopee_video.php?<?= h(shopee_video_admin_query(['view' => 'packages', 'page' => 1])) ?>">
      Pacotes pro ativos
    </a>
  </nav>

  <?php if ($view === 'queue'): ?>
  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Como usar</h2>
        <p>Fluxo recomendado: gerar rascunho, copiar legenda, abrir video do produto, postar no app da Shopee e voltar aqui para marcar como publicado.</p>
      </div>
    </div>
    <div class="admin-meta-row">
      <span class="admin-meta-chip">1. Selecionar ofertas Shopee com video</span>
      <span class="admin-meta-chip">2. Criar rascunho manual</span>
      <span class="admin-meta-chip">3. Gerar pacote pro</span>
      <span class="admin-meta-chip">4. Postar no app da Shopee</span>
      <span class="admin-meta-chip">5. Marcar publicado</span>
    </div>
    <div class="admin-alert warn" style="margin-top:16px;">
      <?= h((string) ($apiSnapshot['publish_api_message'] ?? 'A publicacao automatica por API ainda nao esta disponivel neste MVP.')) ?>
    </div>
  </section>

  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Gerar rascunhos</h2>
        <p>O modo <strong>manual</strong> deixa tudo pronto para postagem no app. O modo <strong>API</strong> apenas sinaliza tentativa futura e salva o item como bloqueado.</p>
      </div>
    </div>

    <form method="get" class="admin-filter-form">
      <div class="admin-field-grid admin-field-grid-compact">
        <div class="admin-field">
          <label for="q">Buscar</label>
          <input id="q" name="q" value="<?= h($search) ?>" placeholder="Titulo, categoria ou tag">
        </div>
        <div class="admin-field">
          <label for="limit">Limite</label>
          <input id="limit" type="number" name="limit" value="<?= (int) $limit ?>" min="1" max="30">
        </div>
        <div class="admin-field">
          <label for="com_video">Filtro</label>
          <select id="com_video" name="com_video">
            <option value="1" <?= $onlyWithVideo ? 'selected' : '' ?>>So com video</option>
            <option value="0" <?= !$onlyWithVideo ? 'selected' : '' ?>>Todos</option>
          </select>
        </div>
        <div class="admin-field admin-field-submit">
          <label>&nbsp;</label>
          <button class="btn-link primary" type="submit">Filtrar</button>
        </div>
      </div>
      <input type="hidden" name="page" value="1">
    </form>

    <form method="post" id="shopee-video-create-form">
      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
      <input type="hidden" name="acao" value="create_selected">
      <div class="admin-field-grid admin-field-grid-compact" style="margin-top:18px;">
        <div class="admin-field">
          <label for="mode">Modo</label>
          <select id="mode" name="mode">
            <option value="manual" selected>Manual pronto</option>
            <option value="api">Marcar tentativa API</option>
          </select>
        </div>
        <div class="admin-field admin-field-submit">
          <label>&nbsp;</label>
          <button class="btn" type="submit" id="shopee-video-create-submit">Gerar rascunhos selecionados</button>
        </div>
      </div>

      <?php if (!$candidates): ?>
        <div class="admin-empty" style="margin-top:18px;">Nenhuma oferta Shopee elegivel com estes filtros.</div>
      <?php else: ?>
        <div class="admin-meta-row" style="margin-top:18px;">
          <span class="admin-meta-chip"><?= (int) $candidateTotal ?> ofertas elegiveis</span>
          <span class="admin-meta-chip">Pagina <?= (int) $page ?> de <?= (int) $totalPages ?></span>
          <span class="admin-meta-chip" id="shopee-video-selected-count">0 selecionadas</span>
          <button class="btn-link" type="button" id="shopee-video-clear-selection">Desmarcar selecionadas</button>
        </div>

        <div class="admin-offers-grid" style="margin-top:18px;">
          <?php foreach ($candidates as $offer): ?>
            <article class="admin-offer-card">
              <div class="admin-offer-layout">
                <div>
                  <img class="admin-offer-thumb" src="<?= h((string) $offer['imagem_url']) ?>" alt="<?= h((string) $offer['titulo']) ?>">
                </div>
                <div>
                  <div class="admin-card-topline">
                    <div>
                      <h3 class="admin-card-title"><?= h((string) $offer['titulo']) ?></h3>
                      <div class="admin-card-subtitle">ID <?= (int) $offer['id'] ?> · Shopee · <?= h((string) $offer['categoria']) ?></div>
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
                    <span class="admin-status <?= !empty($offer['has_video']) ? 'ok' : 'warn' ?>">
                      <?= !empty($offer['has_video']) ? 'Video detectado' : 'Sem video detectado' ?>
                    </span>
                    <?php if (!empty($offer['image_gallery_urls'])): ?>
                      <span class="admin-meta-chip"><?= count((array) $offer['image_gallery_urls']) ?> imagem(ns)</span>
                    <?php endif; ?>
                    <?php if (!empty($offer['video_gallery_urls'])): ?>
                      <span class="admin-meta-chip"><?= count((array) $offer['video_gallery_urls']) ?> video(s)</span>
                    <?php endif; ?>
                    <?php if (!empty($offer['cupom'])): ?>
                      <span class="admin-meta-chip">cupom <?= h((string) $offer['cupom']) ?></span>
                    <?php endif; ?>
                  </div>
                  <?php $extraImages = shopee_video_extra_gallery_urls($offer); ?>
                  <?php if ($extraImages): ?>
                    <div style="display:flex; gap:8px; flex-wrap:wrap; margin-top:12px;">
                      <?php foreach ($extraImages as $imageUrl): ?>
                        <a href="<?= h((string) $imageUrl) ?>" target="_blank" rel="noopener">
                          <img src="<?= h((string) $imageUrl) ?>" alt="Imagem extra importada" style="width:64px; height:64px; object-fit:cover; border-radius:12px; border:1px solid rgba(15,23,42,.12);">
                        </a>
                      <?php endforeach; ?>
                    </div>
                  <?php endif; ?>
                  <div class="admin-card-actions" style="margin-top:12px;">
                    <a class="btn-link" href="<?= h((string) $offer['url_afiliado']) ?>" target="_blank" rel="noopener sponsored nofollow">Link afiliado</a>
                    <?php if (!empty($offer['video_url'])): ?>
                      <a class="btn-link" href="<?= h((string) $offer['video_url']) ?>" target="_blank" rel="noopener">Abrir video</a>
                      <a class="btn-link primary" href="/admin/shopee_video_download.php?offer_id=<?= (int) $offer['id'] ?>&type=video">Baixar video</a>
                      <a class="btn-link" href="/admin/shopee_video_download.php?offer_id=<?= (int) $offer['id'] ?>&type=caption">Baixar legenda .txt</a>
                    <?php endif; ?>
                  </div>
                </div>
                <div class="admin-mini-grid">
                  <div class="admin-side-card">
                    <label class="admin-check-chip">
                      <input type="checkbox" name="offer_ids[]" value="<?= (int) $offer['id'] ?>" data-shopee-video-offer-checkbox>
                      Selecionar oferta <?= (int) $offer['id'] ?>
                    </label>
                  </div>
                  <div class="admin-side-card">
                    <strong>Legenda sugerida</strong>
                    <div class="admin-help" style="margin-top:10px; white-space:pre-wrap;"><?= h(admin_shopee_video_default_caption($offer)) ?></div>
                  </div>
                </div>
              </div>
            </article>
          <?php endforeach; ?>
        </div>

        <?php if ($totalPages > 1): ?>
          <div class="admin-meta-row" style="margin-top:18px; gap:10px; flex-wrap:wrap;">
            <?php if ($page > 1): ?>
              <a class="btn-link" href="/admin/shopee_video.php?<?= h(shopee_video_admin_query(['page' => $page - 1])) ?>">Pagina anterior</a>
            <?php endif; ?>
            <?php for ($pageNumber = max(1, $page - 2); $pageNumber <= min($totalPages, $page + 2); $pageNumber++): ?>
              <a class="btn-link <?= $pageNumber === $page ? 'primary' : '' ?>" href="/admin/shopee_video.php?<?= h(shopee_video_admin_query(['page' => $pageNumber])) ?>">
                <?= (int) $pageNumber ?>
              </a>
            <?php endfor; ?>
            <?php if ($page < $totalPages): ?>
              <a class="btn-link" href="/admin/shopee_video.php?<?= h(shopee_video_admin_query(['page' => $page + 1])) ?>">Proxima pagina</a>
            <?php endif; ?>
          </div>
        <?php endif; ?>
      <?php endif; ?>
    </form>
  </section>

  <?php elseif ($view === 'drafts'): ?>
  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Rascunhos recentes</h2>
        <p>Controle o status da postagem, gere o pacote profissional por draft e exporte lotes em CSV para usar em outras automacoes internas.</p>
      </div>
    </div>

    <form method="get" class="admin-filter-form">
      <div class="admin-field-grid admin-field-grid-compact">
        <div class="admin-field">
          <label for="draft_status">Status</label>
          <select id="draft_status" name="draft_status">
            <option value="">Todos</option>
            <option value="manual_ready" <?= $draftStatus === 'manual_ready' ? 'selected' : '' ?>>Pronto manual</option>
            <option value="needs_video" <?= $draftStatus === 'needs_video' ? 'selected' : '' ?>>Sem video</option>
            <option value="api_blocked" <?= $draftStatus === 'api_blocked' ? 'selected' : '' ?>>API bloqueada</option>
            <option value="published" <?= $draftStatus === 'published' ? 'selected' : '' ?>>Publicado</option>
            <option value="error" <?= $draftStatus === 'error' ? 'selected' : '' ?>>Erro</option>
            <option value="archived" <?= $draftStatus === 'archived' ? 'selected' : '' ?>>Arquivado</option>
          </select>
        </div>
        <div class="admin-field admin-field-submit">
          <label>&nbsp;</label>
          <button class="btn-link primary" type="submit">Filtrar rascunhos</button>
        </div>
      </div>
      <input type="hidden" name="q" value="<?= h($search) ?>">
      <input type="hidden" name="limit" value="<?= (int) $limit ?>">
      <input type="hidden" name="page" value="<?= (int) $page ?>">
      <input type="hidden" name="com_video" value="<?= $onlyWithVideo ? '1' : '0' ?>">
      <input type="hidden" name="view" value="drafts">
    </form>

    <?php if (!$drafts): ?>
      <div class="admin-empty" style="margin-top:18px;">Nenhum rascunho Shopee Video salvo ainda.</div>
    <?php else: ?>
      <form method="post" id="shopee-video-export-form" style="margin-top:18px;">
        <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
        <input type="hidden" name="acao" value="export_selected">
      </form>
      <div class="admin-meta-row" style="margin-top:18px;">
        <span class="admin-meta-chip"><?= count($drafts) ?> rascunho(s) carregados</span>
        <span class="admin-meta-chip" id="shopee-video-draft-selected-count">0 selecionados</span>
        <button class="btn-link primary" type="submit" form="shopee-video-export-form">Exportar CSV selecionados</button>
        <button class="btn-link" type="button" id="shopee-video-clear-draft-selection">Desmarcar CSV</button>
      </div>
      <form method="post" style="margin-top:14px;">
        <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
        <input type="hidden" name="acao" value="delete_all_drafts">
        <button class="btn-link danger" type="submit" onclick="return confirm('Excluir todos os rascunhos recentes listados agora?');">Excluir todos os rascunhos recentes</button>
      </form>

      <div class="admin-offers-grid" style="margin-top:18px;">
        <?php foreach ($drafts as $draft): ?>
          <article class="admin-offer-card">
            <div class="admin-offer-layout">
              <div>
                <img class="admin-offer-thumb" src="<?= h((string) ($draft['image_url'] ?: $draft['imagem_url'])) ?>" alt="<?= h((string) $draft['title_snapshot']) ?>">
              </div>
              <div>
                <div class="admin-card-topline">
                  <div>
                    <h3 class="admin-card-title"><?= h((string) $draft['title_snapshot']) ?></h3>
                    <div class="admin-card-subtitle">Draft #<?= (int) $draft['id'] ?> · Oferta #<?= (int) $draft['oferta_id'] ?> · <?= h((string) $draft['publish_mode']) ?></div>
                  </div>
                </div>
                <div class="admin-meta-row" style="margin-top:12px;">
                  <span class="admin-status <?= h((string) $draft['status_class']) ?>"><?= h((string) $draft['status_label']) ?></span>
                  <span class="admin-status <?= h((string) ($draft['package_status_class'] ?? 'warn')) ?>"><?= h((string) ($draft['package_status_label'] ?? 'Pacote pendente')) ?></span>
                  <span class="admin-meta-chip">Atualizado <?= h((string) $draft['updated_at']) ?></span>
                  <?php if (!empty($draft['image_gallery_urls'])): ?>
                    <span class="admin-meta-chip"><?= count((array) $draft['image_gallery_urls']) ?> imagem(ns)</span>
                  <?php endif; ?>
                  <?php if (!empty($draft['video_gallery_urls'])): ?>
                    <span class="admin-meta-chip"><?= count((array) $draft['video_gallery_urls']) ?> video(s)</span>
                  <?php endif; ?>
                  <?php if (!empty($draft['published_at'])): ?>
                    <span class="admin-meta-chip">Publicado <?= h((string) $draft['published_at']) ?></span>
                  <?php endif; ?>
                </div>
                <?php $draftExtraImages = shopee_video_extra_gallery_urls($draft); ?>
                <?php if ($draftExtraImages): ?>
                  <div style="display:flex; gap:8px; flex-wrap:wrap; margin-top:12px;">
                    <?php foreach ($draftExtraImages as $imageUrl): ?>
                      <a href="<?= h((string) $imageUrl) ?>" target="_blank" rel="noopener">
                        <img src="<?= h((string) $imageUrl) ?>" alt="Imagem extra importada" style="width:64px; height:64px; object-fit:cover; border-radius:12px; border:1px solid rgba(15,23,42,.12);">
                      </a>
                    <?php endforeach; ?>
                  </div>
                <?php endif; ?>
                <?php $creative = is_array($draft['creative_payload'] ?? null) ? (array) $draft['creative_payload'] : []; ?>
                <?php if ($creative): ?>
                  <div class="admin-meta-row" style="margin-top:12px;">
                    <?php if (!empty($creative['angle'])): ?>
                      <span class="admin-meta-chip">Angulo: <?= h((string) $creative['angle']) ?></span>
                    <?php endif; ?>
                    <?php if (!empty($creative['cover_text'])): ?>
                      <span class="admin-meta-chip">Capa: <?= h((string) $creative['cover_text']) ?></span>
                    <?php endif; ?>
                  </div>
                  <?php if (!empty($creative['hook'])): ?>
                    <div class="admin-help" style="margin-top:12px;"><strong>Hook:</strong> <?= h((string) $creative['hook']) ?></div>
                  <?php endif; ?>
                  <?php if (!empty($creative['cta_text'])): ?>
                    <div class="admin-help" style="margin-top:8px;"><strong>CTA:</strong> <?= h((string) $creative['cta_text']) ?></div>
                  <?php endif; ?>
                <?php endif; ?>
                <div class="admin-help" style="margin-top:12px; white-space:pre-wrap;"><?= h((string) ($draft['caption'] ?? '')) ?></div>
                <?php if (!empty($draft['notes'])): ?>
                  <div class="admin-help" style="margin-top:12px;"><?= h((string) $draft['notes']) ?></div>
                <?php endif; ?>
                <?php if (!empty($draft['package_error'])): ?>
                  <div class="admin-alert error" style="margin-top:12px;"><?= h((string) $draft['package_error']) ?></div>
                <?php endif; ?>
                <?php if (!empty(($draft['package_payload']['warnings'] ?? [])) && is_array($draft['package_payload']['warnings'])): ?>
                  <div class="admin-alert warn" style="margin-top:12px;"><?= h(implode(' | ', array_filter(array_map('strval', (array) $draft['package_payload']['warnings'])))) ?></div>
                <?php endif; ?>
                <?php if (!empty($draft['last_error'])): ?>
                  <div class="admin-alert error" style="margin-top:12px;"><?= h((string) $draft['last_error']) ?></div>
                <?php endif; ?>
                <div class="admin-card-actions" style="margin-top:12px;">
                  <?php if (!empty($draft['video_source_url'])): ?>
                    <a class="btn-link primary" href="<?= h((string) $draft['video_source_url']) ?>" target="_blank" rel="noopener">Abrir video</a>
                    <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $draft['id'] ?>&type=video">Baixar video</a>
                    <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $draft['id'] ?>&type=package">Baixar pacote</a>
                  <?php endif; ?>
                  <a class="btn-link" href="<?= h((string) $draft['affiliate_url']) ?>" target="_blank" rel="noopener sponsored nofollow">Link afiliado</a>
                  <?php if (!empty($draft['offer_url'])): ?>
                    <a class="btn-link" href="<?= h((string) $draft['offer_url']) ?>" target="_blank" rel="noopener">Pagina da oferta</a>
                  <?php endif; ?>
                  <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $draft['id'] ?>&type=caption">Baixar legenda .txt</a>
                  <?php if (($draft['package_status'] ?? '') === 'ready'): ?>
                    <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $draft['id'] ?>&type=brief">Brief</a>
                    <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $draft['id'] ?>&type=checklist">Checklist</a>
                    <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $draft['id'] ?>&type=voiceover">Narracao</a>
                    <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $draft['id'] ?>&type=metadata">Metadata</a>
                    <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $draft['id'] ?>&type=poster">Poster</a>
                    <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $draft['id'] ?>&type=square_card">Card</a>
                    <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $draft['id'] ?>&type=reel_video">Video base</a>
                    <?php if (!empty(($draft['package_payload']['files']['tts_audio']['path'] ?? ''))): ?>
                      <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $draft['id'] ?>&type=tts_audio">Audio IA</a>
                    <?php endif; ?>
                    <?php if (!empty(($draft['package_payload']['files']['reel_video_tts']['path'] ?? ''))): ?>
                      <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $draft['id'] ?>&type=reel_video_tts">Video narrado</a>
                    <?php endif; ?>
                    <?php if (!empty(($draft['package_payload']['files']['subtitle_srt']['path'] ?? ''))): ?>
                      <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $draft['id'] ?>&type=subtitle_srt">Legenda SRT</a>
                    <?php endif; ?>
                    <?php if (!empty(($draft['package_payload']['files']['reel_video_tts_subtitled']['path'] ?? ''))): ?>
                      <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $draft['id'] ?>&type=reel_video_tts_subtitled">Video legendado</a>
                    <?php endif; ?>
                    <?php if (!empty(($draft['package_payload']['files']['music_bed']['path'] ?? ''))): ?>
                      <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $draft['id'] ?>&type=music_bed">Trilha</a>
                    <?php endif; ?>
                    <?php if (!empty(($draft['package_payload']['files']['reel_video_final']['path'] ?? ''))): ?>
                      <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $draft['id'] ?>&type=reel_video_final">Video final</a>
                    <?php endif; ?>
                    <?php if (!empty(($draft['package_payload']['files']['source_video']['path'] ?? ''))): ?>
                      <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $draft['id'] ?>&type=source_video">Video original</a>
                    <?php endif; ?>
                  <?php endif; ?>
                  <button class="btn-link" type="button" data-copy-text="<?= h((string) ($draft['caption'] ?? '')) ?>">Copiar legenda</button>
                  <?php if (!empty($draft['video_source_url'])): ?>
                    <button class="btn-link" type="button" data-copy-text="<?= h((string) $draft['video_source_url']) ?>">Copiar URL do video</button>
                  <?php endif; ?>
                </div>
              </div>
              <div class="admin-mini-grid">
                <div class="admin-side-card">
                  <label class="admin-check-chip">
                    <input type="checkbox" name="draft_ids[]" value="<?= (int) $draft['id'] ?>" form="shopee-video-export-form" data-shopee-video-draft-checkbox>
                    Selecionar draft <?= (int) $draft['id'] ?>
                  </label>
                </div>
                <div class="admin-side-card">
                  <strong>Pacote profissional</strong>
                  <div class="admin-card-actions" style="margin-top:10px; flex-direction:column; align-items:flex-start;">
                    <form method="post">
                      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
                      <input type="hidden" name="acao" value="generate_package">
                      <input type="hidden" name="draft_id" value="<?= (int) $draft['id'] ?>">
                      <button class="btn-link primary" type="submit"><?= ($draft['package_status'] ?? '') === 'ready' ? 'Regenerar pacote pro' : 'Gerar pacote pro' ?></button>
                    </form>
                    <?php if (($draft['package_status'] ?? '') === 'ready'): ?>
                      <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $draft['id'] ?>&type=package">Baixar pacote pro</a>
                    <?php endif; ?>
                  </div>
                </div>
                <div class="admin-side-card">
                  <strong>Status rapido</strong>
                  <div class="admin-card-actions" style="margin-top:10px; flex-direction:column; align-items:flex-start;">
                    <form method="post">
                      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
                      <input type="hidden" name="acao" value="update_draft_status">
                      <input type="hidden" name="draft_id" value="<?= (int) $draft['id'] ?>">
                      <input type="hidden" name="status" value="published">
                      <button class="btn-link primary" type="submit">Marcar publicado</button>
                    </form>
                    <form method="post">
                      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
                      <input type="hidden" name="acao" value="update_draft_status">
                      <input type="hidden" name="draft_id" value="<?= (int) $draft['id'] ?>">
                      <input type="hidden" name="status" value="error">
                      <button class="btn-link" type="submit">Marcar erro</button>
                    </form>
                    <form method="post">
                      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
                      <input type="hidden" name="acao" value="update_draft_status">
                      <input type="hidden" name="draft_id" value="<?= (int) $draft['id'] ?>">
                      <input type="hidden" name="status" value="archived">
                      <button class="btn-link" type="submit">Arquivar</button>
                    </form>
                    <form method="post">
                      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
                      <input type="hidden" name="acao" value="delete_draft">
                      <input type="hidden" name="draft_id" value="<?= (int) $draft['id'] ?>">
                      <button class="btn-link danger" type="submit" onclick="return confirm('Excluir o rascunho #<?= (int) $draft['id'] ?> agora?');">Excluir rascunho</button>
                    </form>
                  </div>
                </div>
              </div>
            </div>
          </article>
        <?php endforeach; ?>
      </div>
    <?php endif; ?>
  </section>
  <?php else: ?>
  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Pacotes pro ativos</h2>
        <p>Itens gerados recentemente para copiar, baixar e postar. Tudo expira automaticamente em <?= (int) $packageTtlHours ?> horas.</p>
      </div>
    </div>

    <form method="get" class="admin-filter-form">
      <div class="admin-field-grid admin-field-grid-compact">
        <div class="admin-field">
          <label for="q_packages">Buscar</label>
          <input id="q_packages" name="q" value="<?= h($search) ?>" placeholder="Titulo, categoria ou tag">
        </div>
        <div class="admin-field admin-field-submit">
          <label>&nbsp;</label>
          <button class="btn-link primary" type="submit">Filtrar pacotes</button>
        </div>
      </div>
      <input type="hidden" name="view" value="packages">
    </form>

    <?php if (!$packages): ?>
      <div class="admin-empty" style="margin-top:18px;">Nenhum pacote pro ativo neste momento.</div>
    <?php else: ?>
      <div class="admin-meta-row" style="margin-top:18px;">
        <span class="admin-meta-chip"><?= count($packages) ?> pacote(s) ativo(s)</span>
        <span class="admin-meta-chip">Expiracao automatica em <?= (int) $packageTtlHours ?>h</span>
      </div>
      <form method="post" style="margin-top:14px;">
        <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
        <input type="hidden" name="acao" value="delete_all_packages">
        <button class="btn-link danger" type="submit" onclick="return confirm('Excluir todos os pacotes pro ativos listados agora?');">Excluir todos os pacotes ativos</button>
      </form>

      <div class="admin-offers-grid" style="margin-top:18px;">
        <?php foreach ($packages as $package): ?>
          <?php $creative = is_array($package['creative_payload'] ?? null) ? (array) $package['creative_payload'] : []; ?>
          <article class="admin-offer-card">
            <div class="admin-offer-layout">
              <div>
                <img class="admin-offer-thumb" src="<?= h((string) ($package['image_url'] ?: $package['imagem_url'])) ?>" alt="<?= h((string) $package['title_snapshot']) ?>">
              </div>
              <div>
                <div class="admin-card-topline">
                  <div>
                    <h3 class="admin-card-title"><?= h((string) $package['title_snapshot']) ?></h3>
                    <div class="admin-card-subtitle">Draft #<?= (int) $package['id'] ?> · Oferta #<?= (int) $package['oferta_id'] ?> · expira em <?= h((string) ($package['expires_at'] ?? '')) ?></div>
                  </div>
                </div>
                <div class="admin-meta-row" style="margin-top:12px;">
                  <span class="admin-status <?= h((string) ($package['package_status_class'] ?? 'ok')) ?>"><?= h((string) ($package['package_status_label'] ?? 'Pacote pronto')) ?></span>
                  <span class="admin-meta-chip">Gerado <?= h((string) ($package['package_generated_at'] ?? '')) ?></span>
                  <span class="admin-meta-chip"><?= h((string) ($package['categoria'] ?? 'Shopee')) ?></span>
                  <?php if (!empty($package['image_gallery_urls'])): ?>
                    <span class="admin-meta-chip"><?= count((array) $package['image_gallery_urls']) ?> imagem(ns)</span>
                  <?php endif; ?>
                  <?php if (!empty($package['video_gallery_urls'])): ?>
                    <span class="admin-meta-chip"><?= count((array) $package['video_gallery_urls']) ?> video(s)</span>
                  <?php endif; ?>
                </div>
                <?php $packageExtraImages = shopee_video_extra_gallery_urls($package); ?>
                <?php if ($packageExtraImages): ?>
                  <div style="display:flex; gap:8px; flex-wrap:wrap; margin-top:12px;">
                    <?php foreach ($packageExtraImages as $imageUrl): ?>
                      <a href="<?= h((string) $imageUrl) ?>" target="_blank" rel="noopener">
                        <img src="<?= h((string) $imageUrl) ?>" alt="Imagem extra importada" style="width:64px; height:64px; object-fit:cover; border-radius:12px; border:1px solid rgba(15,23,42,.12);">
                      </a>
                    <?php endforeach; ?>
                  </div>
                <?php endif; ?>
                <?php if (!empty($creative['hook'])): ?>
                  <div class="admin-help" style="margin-top:12px;"><strong>Hook:</strong> <?= h((string) $creative['hook']) ?></div>
                <?php endif; ?>
                <?php if (!empty($creative['cover_text'])): ?>
                  <div class="admin-help" style="margin-top:8px;"><strong>Capa:</strong> <?= h((string) $creative['cover_text']) ?></div>
                <?php endif; ?>
                <?php if (!empty(($package['package_payload']['warnings'] ?? [])) && is_array($package['package_payload']['warnings'])): ?>
                  <div class="admin-alert warn" style="margin-top:12px;"><?= h(implode(' | ', array_filter(array_map('strval', (array) $package['package_payload']['warnings'])))) ?></div>
                <?php endif; ?>
                <div class="admin-help" style="margin-top:12px; white-space:pre-wrap;"><?= h((string) ($package['caption'] ?? '')) ?></div>
                <div class="admin-card-actions" style="margin-top:12px;">
                  <a class="btn-link primary" href="/admin/shopee_video_download.php?draft_id=<?= (int) $package['id'] ?>&type=package">Baixar pacote pro</a>
                  <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $package['id'] ?>&type=brief">Brief</a>
                  <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $package['id'] ?>&type=checklist">Checklist</a>
                  <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $package['id'] ?>&type=voiceover">Narracao</a>
                  <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $package['id'] ?>&type=metadata">Metadata</a>
                  <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $package['id'] ?>&type=poster">Poster</a>
                  <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $package['id'] ?>&type=square_card">Card</a>
                  <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $package['id'] ?>&type=reel_video">Video base</a>
                  <?php if (!empty(($package['package_payload']['files']['tts_audio']['path'] ?? ''))): ?>
                    <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $package['id'] ?>&type=tts_audio">Audio IA</a>
                  <?php endif; ?>
                  <?php if (!empty(($package['package_payload']['files']['reel_video_tts']['path'] ?? ''))): ?>
                    <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $package['id'] ?>&type=reel_video_tts">Video narrado</a>
                  <?php endif; ?>
                  <?php if (!empty(($package['package_payload']['files']['subtitle_srt']['path'] ?? ''))): ?>
                    <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $package['id'] ?>&type=subtitle_srt">Legenda SRT</a>
                  <?php endif; ?>
                  <?php if (!empty(($package['package_payload']['files']['reel_video_tts_subtitled']['path'] ?? ''))): ?>
                    <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $package['id'] ?>&type=reel_video_tts_subtitled">Video legendado</a>
                  <?php endif; ?>
                  <?php if (!empty(($package['package_payload']['files']['music_bed']['path'] ?? ''))): ?>
                    <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $package['id'] ?>&type=music_bed">Trilha</a>
                  <?php endif; ?>
                  <?php if (!empty(($package['package_payload']['files']['reel_video_final']['path'] ?? ''))): ?>
                    <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $package['id'] ?>&type=reel_video_final">Video final</a>
                  <?php endif; ?>
                  <?php if (!empty(($package['package_payload']['files']['source_video']['path'] ?? ''))): ?>
                    <a class="btn-link" href="/admin/shopee_video_download.php?draft_id=<?= (int) $package['id'] ?>&type=source_video">Video original</a>
                  <?php endif; ?>
                  <button class="btn-link" type="button" data-copy-text="<?= h((string) ($package['caption'] ?? '')) ?>">Copiar legenda</button>
                  <?php if (!empty($creative['hook'])): ?>
                    <button class="btn-link" type="button" data-copy-text="<?= h((string) $creative['hook']) ?>">Copiar hook</button>
                  <?php endif; ?>
                  <form method="post" style="display:inline-flex;">
                    <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
                    <input type="hidden" name="acao" value="delete_package">
                    <input type="hidden" name="draft_id" value="<?= (int) $package['id'] ?>">
                    <button class="btn-link danger" type="submit" onclick="return confirm('Excluir este pacote pro agora?');">Excluir pacote</button>
                  </form>
                </div>
              </div>
              <div class="admin-mini-grid">
                <div class="admin-side-card">
                  <strong>Copias rapidas</strong>
                  <div class="admin-card-actions" style="margin-top:10px; flex-direction:column; align-items:flex-start;">
                    <?php if (!empty($creative['cta_text'])): ?>
                      <button class="btn-link" type="button" data-copy-text="<?= h((string) $creative['cta_text']) ?>">Copiar CTA</button>
                    <?php endif; ?>
                    <?php if (!empty($creative['cover_text'])): ?>
                      <button class="btn-link" type="button" data-copy-text="<?= h((string) $creative['cover_text']) ?>">Copiar capa</button>
                    <?php endif; ?>
                    <a class="btn-link" href="<?= h((string) $package['affiliate_url']) ?>" target="_blank" rel="noopener sponsored nofollow">Link afiliado</a>
                  </div>
                </div>
                <div class="admin-side-card">
                  <strong>Retencao</strong>
                  <div class="admin-help" style="margin-top:10px;">Este pacote fica disponivel por até <?= (int) $packageTtlHours ?> horas. Depois os arquivos sao apagados automaticamente para manter o servidor limpo.</div>
                </div>
              </div>
            </div>
          </article>
        <?php endforeach; ?>
      </div>
    <?php endif; ?>
  </section>
  <?php endif; ?>
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
    var storageKey = 'admin-shopee-video-selected-offers';
    var form = document.getElementById('shopee-video-create-form');
    var checkboxes = document.querySelectorAll('[data-shopee-video-offer-checkbox]');
    var selectedCount = document.getElementById('shopee-video-selected-count');
    var clearButton = document.getElementById('shopee-video-clear-selection');
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

    function updateCount(values) {
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
        updateCount(current);
      });
    });
    updateCount(selected);

    if (clearButton) {
      clearButton.addEventListener('click', function () {
        saveSelected([]);
        checkboxes.forEach(function (checkbox) {
          checkbox.checked = false;
        });
        updateCount([]);
      });
    }

    form.addEventListener('submit', function () {
      form.querySelectorAll('input[data-shopee-video-selected-hidden]').forEach(function (input) {
        input.remove();
      });
      loadSelected().forEach(function (value) {
        var hidden = document.createElement('input');
        hidden.type = 'hidden';
        hidden.name = 'offer_ids[]';
        hidden.value = value;
        hidden.setAttribute('data-shopee-video-selected-hidden', '1');
        form.appendChild(hidden);
      });
    });
  })();

  (function () {
    var storageKey = 'admin-shopee-video-selected-drafts';
    var form = document.getElementById('shopee-video-export-form');
    var checkboxes = document.querySelectorAll('[data-shopee-video-draft-checkbox]');
    var selectedCount = document.getElementById('shopee-video-draft-selected-count');
    var clearButton = document.getElementById('shopee-video-clear-draft-selection');
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

    function updateCount(values) {
      if (selectedCount) {
        selectedCount.textContent = values.length + ' selecionados';
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
        updateCount(current);
      });
    });
    updateCount(selected);

    if (clearButton) {
      clearButton.addEventListener('click', function () {
        saveSelected([]);
        checkboxes.forEach(function (checkbox) {
          checkbox.checked = false;
        });
        updateCount([]);
      });
    }

    form.addEventListener('submit', function () {
      form.querySelectorAll('input[data-shopee-video-draft-hidden]').forEach(function (input) {
        input.remove();
      });
      loadSelected().forEach(function (value) {
        var hidden = document.createElement('input');
        hidden.type = 'hidden';
        hidden.name = 'draft_ids[]';
        hidden.value = value;
        hidden.setAttribute('data-shopee-video-draft-hidden', '1');
        form.appendChild(hidden);
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
    var forms = document.querySelectorAll('form');
    forms.forEach(function (form) {
      form.addEventListener('submit', function () {
        var submitter = form.querySelector('button[type="submit"]');
        if (!submitter) {
          return;
        }
        submitter.disabled = true;
        if (submitter.id === 'shopee-video-create-submit') {
          submitter.textContent = 'Gerando...';
        } else if (submitter.textContent) {
          submitter.textContent = 'Processando...';
        }
      });
    });
  })();
</script>
</body>
</html>
