<?php
require_once __DIR__ . '/_init.php';
admin_require_login();

$flash = admin_flash_get();
$pdo = db();
$filter = trim((string) ($_GET['loja'] ?? ''));
$mode = trim((string) ($_GET['modo'] ?? ''));
$search = trim((string) ($_GET['q'] ?? ''));
$limitDefault = 10;
$limit = (int) ($_GET['limit'] ?? $limitDefault);
$limit = max(1, min($limit, 30));
$page = max(1, (int) ($_GET['page'] ?? 1));

function admin_offer_tag_parts($rawTags) {
  $text = trim((string) $rawTags);
  if ($text === '') {
    return [];
  }

  $parts = preg_split('/[\r\n,]+/', $text) ?: [];
  $clean = [];
  foreach ($parts as $part) {
    $value = trim((string) $part);
    if ($value === '' || in_array($value, $clean, true)) {
      continue;
    }
    $clean[] = $value;
  }
  return $clean;
}

function admin_offer_is_url($value) {
  $text = trim((string) $value);
  if ($text === '') {
    return false;
  }
  return (bool) preg_match('~^https?://~i', $text);
}

function admin_offer_tag_is_not_url($value) {
  return !admin_offer_is_url($value);
}

function admin_offer_video_url($rawTags) {
  $manualVideo = tag_url_decode($rawTags, 'offer_video_url:');
  if ($manualVideo !== '') {
    return $manualVideo;
  }
  return tag_url_decode($rawTags, 'shopee_video_url:');
}

function admin_offer_query($mode, $filter, $search, $pageOverride = null, $limitOverride = null) {
  global $limit, $page;
  $query = [];
  if ($mode !== '') {
    $query['modo'] = $mode;
  }
  if ($filter !== '') {
    $query['loja'] = $filter;
  }
  if ($search !== '') {
    $query['q'] = $search;
  }
  $query['limit'] = $limitOverride !== null ? (int) $limitOverride : $limit;
  $query['page'] = $pageOverride !== null ? (int) $pageOverride : $page;
  return '/admin/ofertas.php' . ($query ? '?' . http_build_query($query) : '');
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
  admin_csrf_check_or_die();
  $acao = (string) ($_POST['acao'] ?? '');
  $id = (int) ($_POST['id'] ?? 0);

  if ($id > 0 && in_array($acao, ['toggle_ativo', 'toggle_destaque', 'excluir'], true)) {
    if ($acao === 'toggle_ativo') {
      $pdo->prepare('UPDATE ofertas SET ativo = IF(ativo=1, 0, 1) WHERE id=?')->execute([$id]);
    }

    if ($acao === 'toggle_destaque') {
      $storeStmt = $pdo->prepare('SELECT loja, destaque FROM ofertas WHERE id=? LIMIT 1');
      $storeStmt->execute([$id]);
      $offerRow = $storeStmt->fetch();
      if ($offerRow) {
        $nextHighlight = ((int) $offerRow['destaque'] === 1) ? 0 : 1;
        $pdo->prepare('UPDATE ofertas SET destaque = ? WHERE id=?')->execute([$nextHighlight, $id]);
        if ($nextHighlight === 1) {
          admin_enforce_featured_limit($pdo, $offerRow['loja'], $id);
        }
      }
    }

    if ($acao === 'excluir') {
      $pdo->prepare('DELETE FROM ofertas WHERE id=? LIMIT 1')->execute([$id]);
      admin_flash_set('success', 'Oferta excluida com sucesso.');
    }
  }

  header('Location: ' . admin_offer_query($mode, $filter, $search));
  exit;
}

$sql = 'SELECT o.id, o.titulo, o.slug, o.preco, o.preco_antigo, o.loja, o.categoria, o.destaque, o.ativo, o.criado_em, o.atualizado_em, o.url_afiliado,
               o.criado_por_login, o.imagem_url, o.cupom, o.tags, COUNT(c.id) AS clicks
        FROM ofertas o
        LEFT JOIN cliques c ON c.oferta_id = o.id';
$where = [];
$params = [];

if ($filter !== '') {
  $where[] = 'o.loja = ?';
  $params[] = $filter;
}

if ($search !== '') {
  $like = '%' . $search . '%';
  $where[] = '(o.titulo LIKE ? OR o.slug LIKE ? OR o.categoria LIKE ? OR o.tags LIKE ? OR o.loja LIKE ?)';
  array_push($params, $like, $like, $like, $like, $like);
}

if ($mode === 'ml_invalidos') {
  $where[] = "LOWER(o.loja) = 'mercado livre'";
  $where[] = "(
    o.url_afiliado NOT LIKE '%/social/%'
    AND o.url_afiliado NOT LIKE '%matt_tool=%'
    AND o.url_afiliado NOT LIKE '%affiliate-profile%'
    AND o.url_afiliado NOT LIKE '%polycard_client=affiliates%'
    AND (
      o.url_afiliado NOT LIKE '%wid=%'
      OR o.url_afiliado NOT LIKE '%sid=affiliates%'
    )
  )";
} elseif ($mode === 'com_video') {
  $where[] = "(o.tags LIKE '%offer_video_url:%' OR o.tags LIKE '%shopee_video_url:%')";
}

if ($where) {
  $sql .= ' WHERE ' . implode(' AND ', $where);
}

$countSql = 'SELECT COUNT(*) FROM ofertas o';
if ($where) {
  $countSql .= ' WHERE ' . implode(' AND ', $where);
}
$countStmt = $pdo->prepare($countSql);
$countStmt->execute($params);
$offersTotal = (int) $countStmt->fetchColumn();
$totalPages = max(1, (int) ceil($offersTotal / $limit));
$page = min($page, $totalPages);
$offset = ($page - 1) * $limit;

$sql .= ' GROUP BY o.id, o.titulo, o.slug, o.preco, o.preco_antigo, o.loja, o.categoria, o.destaque, o.ativo, o.criado_em, o.atualizado_em, o.url_afiliado, o.criado_por_login, o.imagem_url, o.cupom, o.tags';
$sql .= ' ORDER BY o.atualizado_em DESC, o.criado_em DESC, o.id DESC LIMIT ' . $limit . ' OFFSET ' . $offset;

$stmt = $pdo->prepare($sql);
$stmt->execute($params);
$ofertas = $stmt->fetchAll();
$lojas = $pdo->query('SELECT loja, COUNT(*) AS total FROM ofertas GROUP BY loja ORDER BY total DESC, loja ASC')->fetchAll();
$videoOfferCount = (int) $pdo->query("SELECT COUNT(*) FROM ofertas WHERE tags LIKE '%offer_video_url:%' OR tags LIKE '%shopee_video_url:%'")->fetchColumn();
$adminCssVersion = (string) @filemtime(__DIR__ . '/../assets/css/admin.css');
?>
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Admin - Ofertas</title>
  <link rel="icon" type="image/png" href="/assets/img/logo-zp.png">
  <link rel="stylesheet" href="/assets/css/style.css">
  <link rel="stylesheet" href="/assets/css/admin.css?v=<?= urlencode($adminCssVersion) ?>">
</head>
<body class="admin-page">
<?php admin_render_header('ofertas'); ?>
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
    <button class="btn admin-menu-toggle" type="button" aria-expanded="false" aria-controls="admin-header-actions" data-admin-menu-toggle>
      Menu
    </button>
    <div class="admin-header-actions" id="admin-header-actions" data-admin-menu>
      <a class="badge" href="/admin/oferta_editar.php">+ Nova oferta</a>
      <a class="badge" href="/admin/importar.php">Importar</a>
      <a class="badge" href="/admin/social.php">Social</a>
      <a class="badge" href="/">Ver site</a>
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
        <a class="admin-kicker" href="/admin/ofertas.php">Gerenciador de produtos</a>
        <h1>Catalogo de ofertas</h1>
      </div>
      <div class="admin-hero-actions">
        <a class="btn-link primary" href="/admin/oferta_editar.php">Criar oferta</a>
      </div>
    </div>
  </section>

  <?php admin_render_offer_subnav('catalogo'); ?>

  <section class="admin-panel">
    <form method="get" class="admin-filter-form">
      <div class="admin-search-toolbar">
        <div class="admin-field admin-field-search">
          <label for="q">Pesquisar produto</label>
          <input id="q" name="q" value="<?= h($search) ?>" placeholder="Titulo, slug, categoria, tags ou loja">
        </div>
        <div class="admin-field admin-field-compact">
          <label for="loja">Lojas</label>
          <select id="loja" name="loja">
            <option value="">Todas</option>
            <?php foreach ($lojas as $loja): ?>
              <option value="<?= h((string) $loja['loja']) ?>" <?= $filter === (string) $loja['loja'] ? 'selected' : '' ?>>
                <?= h((string) $loja['loja']) ?>
              </option>
            <?php endforeach; ?>
          </select>
        </div>
        <div class="admin-field admin-field-compact">
          <label for="limit">Limite</label>
          <input id="limit" type="number" name="limit" value="<?= (int) $limit ?>" min="1" max="30">
        </div>
        <div class="admin-form-actions admin-form-actions-inline">
          <button class="btn-link primary" type="submit">Pesquisar</button>
          <a class="badge" href="/admin/ofertas.php">Limpar</a>
        </div>
      </div>
      <input type="hidden" name="page" value="1">
      <?php if ($mode !== ''): ?>
        <input type="hidden" name="modo" value="<?= h($mode) ?>">
      <?php endif; ?>
    </form>

    <div class="admin-filter-row">
      <span class="admin-meta-chip admin-meta-chip-soft"><?= $offersTotal ?> ofertas elegiveis</span>
      <span class="admin-meta-chip admin-meta-chip-soft">Pagina <?= (int) $page ?> de <?= (int) $totalPages ?></span>
      <a class="badge <?= $mode === '' ? 'is-primary' : '' ?>" href="<?= h(admin_offer_query('', $filter, $search, 1)) ?>">Todos</a>
      <a class="badge <?= $mode === 'com_video' ? 'is-primary' : '' ?>" href="<?= h(admin_offer_query('com_video', $filter, $search, 1)) ?>">Com video (<?= $videoOfferCount ?>)</a>
      <a class="badge <?= $mode === 'ml_invalidos' ? 'is-primary' : '' ?>" href="<?= h(admin_offer_query('ml_invalidos', $filter, $search, 1)) ?>">Revisar link ML</a>
      <?php foreach ($lojas as $loja): ?>
        <a class="badge" href="<?= h(admin_offer_query($mode, (string) $loja['loja'], $search, 1)) ?>"><?= h((string) $loja['loja']) ?> (<?= (int) $loja['total'] ?>)</a>
      <?php endforeach; ?>
      <?php if ($page > 1): ?>
        <a class="badge" href="<?= h(admin_offer_query($mode, $filter, $search, $page - 1)) ?>">Pagina anterior</a>
      <?php endif; ?>
      <?php if ($page < $totalPages): ?>
        <a class="badge" href="<?= h(admin_offer_query($mode, $filter, $search, $page + 1)) ?>">Proxima pagina</a>
      <?php endif; ?>
    </div>
  </section>

  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Catalogo operacional</h2>
        <p>Cards grandes para revisar produto, link afiliado e midia pronta para social.</p>
      </div>
    </div>

    <?php if (!$ofertas): ?>
      <div class="admin-empty">Nenhuma oferta encontrada para este filtro.</div>
    <?php else: ?>
      <div class="admin-offers-grid">
        <?php foreach ($ofertas as $o): ?>
          <?php $isMeli = strtolower((string) $o['loja']) === 'mercado livre'; ?>
          <?php $isAffiliateOk = $isMeli ? admin_is_meli_affiliate_url($o['url_afiliado']) : false; ?>
          <?php $tagParts = admin_offer_tag_parts($o['tags']); ?>
          <?php $tagChips = array_values(array_filter($tagParts, 'admin_offer_tag_is_not_url')); ?>
          <?php $manualVideoUrl = tag_url_decode($o['tags'] ?? '', 'offer_video_url:'); ?>
          <?php $videoUrl = admin_offer_video_url($o['tags'] ?? ''); ?>
          <?php $hasVideo = $videoUrl !== ''; ?>
          <?php $videoStatusLabel = $manualVideoUrl !== '' ? 'Video manual' : ($hasVideo ? 'Video Shopee' : 'Sem video'); ?>
          <article class="admin-offer-card">
            <div class="admin-offer-layout">
              <div>
                <?php if (!empty($o['imagem_url'])): ?>
                  <img class="admin-offer-thumb" src="<?= h($o['imagem_url']) ?>" alt="<?= h($o['titulo']) ?>">
                <?php else: ?>
                  <div class="admin-thumb-fallback"><?= h(strtoupper(substr((string) $o['loja'], 0, 2) ?: 'OF')) ?></div>
                <?php endif; ?>
              </div>

              <div>
                <div class="admin-card-topline">
                  <div>
                    <h3 class="admin-card-title"><?= h($o['titulo']) ?></h3>
                    <div class="admin-card-subtitle">ID <?= (int) $o['id'] ?> · <?= h($o['loja']) ?> · <?= h($o['categoria']) ?></div>
                  </div>
                </div>

                <div class="admin-preview-price">
                  <span class="admin-price">R$ <?= number_format((float) $o['preco'], 2, ',', '.') ?></span>
                  <?php if ($o['preco_antigo'] !== null && (float) $o['preco_antigo'] > (float) $o['preco']): ?>
                    <span class="admin-price-old">R$ <?= number_format((float) $o['preco_antigo'], 2, ',', '.') ?></span>
                  <?php endif; ?>
                </div>

                <div class="admin-meta-row" style="margin-top: 12px;">
                  <span class="admin-meta-chip"><?= (int) ($o['clicks'] ?? 0) ?> cliques</span>
                  <a class="admin-meta-chip" href="/oferta.php?slug=<?= urlencode((string) $o['slug']) ?>" target="_blank" rel="noopener">Ver pagina</a>
                  <?php if (!empty($o['cupom'])): ?>
                    <span class="admin-meta-chip">cupom <?= h($o['cupom']) ?></span>
                  <?php endif; ?>
                  <?php foreach ($tagChips as $tagChip): ?>
                    <span class="admin-meta-chip admin-meta-chip-soft"><?= h($tagChip) ?></span>
                  <?php endforeach; ?>
                </div>

                <div class="admin-meta-row" style="margin-top: 12px;">
                  <span class="admin-status <?= ((int) $o['ativo'] === 1) ? 'ok' : 'off' ?>"><?= ((int) $o['ativo'] === 1) ? 'Ativa' : 'Inativa' ?></span>
                  <span class="admin-status <?= ((int) $o['destaque'] === 1) ? 'ok' : 'off' ?>"><?= ((int) $o['destaque'] === 1) ? 'Destaque' : 'Normal' ?></span>
                  <span class="admin-status <?= $hasVideo ? 'ok' : 'off' ?>"><?= h($videoStatusLabel) ?></span>
                  <?php if ($isMeli): ?>
                    <span class="admin-status <?= $isAffiliateOk ? 'ok' : 'warn' ?>"><?= $isAffiliateOk ? 'ML afiliado ok' : 'Revisar link ML' ?></span>
                  <?php endif; ?>
                  <span class="admin-meta-chip admin-meta-chip-soft"><?= h((string) $o['atualizado_em']) ?> • <?= h((string) ($o['criado_por_login'] ?: 'nao identificado')) ?></span>
                </div>
              </div>

              <div class="admin-mini-grid">
                <div class="admin-side-card">
                  <strong>Links</strong>
                  <div class="admin-card-actions" style="margin-top: 10px;">
                    <a class="btn-link primary" href="<?= h($o['url_afiliado']) ?>" target="_blank" rel="noopener sponsored nofollow">Abrir link afiliado</a>
                    <a class="btn-link" href="/oferta.php?slug=<?= urlencode((string) $o['slug']) ?>&go=1" target="_blank" rel="noopener sponsored nofollow">Abrir via site</a>
                    <?php if ($hasVideo): ?>
                      <a class="btn-link" href="<?= h($videoUrl) ?>" target="_blank" rel="noopener">Abrir video</a>
                    <?php endif; ?>
                  </div>
                </div>

                <div class="admin-side-card">
                  <strong>Acoes</strong>
                  <div class="admin-card-actions" style="margin-top: 10px;">
                    <a class="btn-link" href="/admin/oferta_editar.php?id=<?= (int) $o['id'] ?>">Editar</a>
                    <form method="post">
                      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
                      <input type="hidden" name="id" value="<?= (int) $o['id'] ?>">
                      <input type="hidden" name="acao" value="toggle_destaque">
                      <button class="badge" type="submit"><?= ((int) $o['destaque'] === 1) ? 'Tirar destaque' : 'Destacar' ?></button>
                    </form>
                    <form method="post">
                      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
                      <input type="hidden" name="id" value="<?= (int) $o['id'] ?>">
                      <input type="hidden" name="acao" value="toggle_ativo">
                      <button class="badge" type="submit"><?= ((int) $o['ativo'] === 1) ? 'Desativar' : 'Ativar' ?></button>
                    </form>
                    <form method="post" onsubmit="return confirm('Deseja excluir esta oferta?');">
                      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
                      <input type="hidden" name="id" value="<?= (int) $o['id'] ?>">
                      <input type="hidden" name="acao" value="excluir">
                      <button class="badge" type="submit">Excluir</button>
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
