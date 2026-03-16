<?php
require_once __DIR__ . '/_init.php';
admin_require_login();

$flash = admin_flash_get();

$pdo = db();
$filter = trim((string) ($_GET['loja'] ?? ''));
$mode = trim((string) ($_GET['modo'] ?? ''));
$search = trim((string) ($_GET['q'] ?? ''));
$limit = 30;

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

  $queryParams = [];
  if ($filter !== '') {
    $queryParams['loja'] = $filter;
  }
  if ($mode !== '') {
    $queryParams['modo'] = $mode;
  }
  if ($search !== '') {
    $queryParams['q'] = $search;
  }
  header('Location: /admin/ofertas.php' . ($queryParams ? '?' . http_build_query($queryParams) : ''));
  exit;
}

$sql = 'SELECT o.id, o.titulo, o.slug, o.preco, o.preco_antigo, o.loja, o.categoria, o.destaque, o.ativo, o.criado_em, o.atualizado_em, o.url_afiliado,
               o.criado_por_login,
               o.imagem_url, o.cupom, o.tags,
               COUNT(c.id) AS clicks
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
}

if ($where) {
  $sql .= ' WHERE ' . implode(' AND ', $where);
}

$sql .= ' GROUP BY o.id, o.titulo, o.slug, o.preco, o.preco_antigo, o.loja, o.categoria, o.destaque, o.ativo, o.criado_em, o.atualizado_em, o.url_afiliado, o.criado_por_login, o.imagem_url, o.cupom, o.tags';
$sql .= ' ORDER BY o.atualizado_em DESC, o.criado_em DESC, o.id DESC LIMIT ' . $limit;

$stmt = $pdo->prepare($sql);
$stmt->execute($params);
$ofertas = $stmt->fetchAll();
$lojas = $pdo->query('SELECT loja, COUNT(*) AS total FROM ofertas GROUP BY loja ORDER BY total DESC, loja ASC')->fetchAll();
$visibleCount = count($ofertas);
$activeCount = 0;
$featuredCount = 0;
$visibleClicks = 0;
foreach ($ofertas as $item) {
  $activeCount += ((int) $item['ativo'] === 1) ? 1 : 0;
  $featuredCount += ((int) $item['destaque'] === 1) ? 1 : 0;
  $visibleClicks += (int) ($item['clicks'] ?? 0);
}
$invalidMeliCount = (int) $pdo->query("
  SELECT COUNT(*)
  FROM ofertas
  WHERE LOWER(loja) = 'mercado livre'
    AND (
      url_afiliado NOT LIKE '%/social/%'
      AND url_afiliado NOT LIKE '%matt_tool=%'
      AND url_afiliado NOT LIKE '%affiliate-profile%'
      AND url_afiliado NOT LIKE '%polycard_client=affiliates%'
      AND (
        url_afiliado NOT LIKE '%wid=%'
        OR url_afiliado NOT LIKE '%sid=affiliates%'
      )
    )
")->fetchColumn();
$adminCssVersion = (string) @filemtime(__DIR__ . '/../assets/css/admin.css');

function admin_offer_tag_parts($rawTags) {
  $text = trim((string) $rawTags);
  if ($text === '') {
    return [];
  }

  $parts = preg_split('/[\r\n,]+/', $text) ?: [];
  $clean = [];

  foreach ($parts as $part) {
    $value = trim((string) $part);
    if ($value === '') {
      continue;
    }
    if (!in_array($value, $clean, true)) {
      $clean[] = $value;
    }
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
<header>
  <div class="container admin-header">
    <div class="admin-brand">
      <a class="admin-brand-link" href="/admin/ofertas.php">
        <div class="admin-brand-mark">
          <img src="/assets/img/logo-zp.png" alt="Zero Preco">
        </div>
      </a>
      <div class="admin-brand-copy">
        <strong>Zero Preço Admin</strong>
        <span>Catálogo, afiliados e curadoria em um painel mais visual.</span>
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
      <a class="badge" href="/admin/oferta_editar.php">+ Nova oferta</a>
      <a class="badge" href="/admin/importar.php">Importar</a>
      <a class="badge" href="/admin/social.php">Social</a>
      <a class="badge" href="/">Ver site</a>
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
        <a class="admin-kicker" href="/admin/ofertas.php">Gerenciador de produtos</a>
        <h1>Catálogo de ofertas</h1>
      </div>
      <div class="admin-hero-actions">
        <a class="btn-link primary" href="/admin/oferta_editar.php">Criar oferta</a>
      </div>
    </div>
  </section>

  <section class="admin-stats-grid">
    <article class="admin-stat-card">
      <div class="admin-stat-label">Ofertas nesta visao</div>
      <div class="admin-stat-value"><?= (int) $visibleCount ?></div>
      <div class="admin-stat-foot"><?= $filter !== '' ? 'Filtro por loja ativo com exibição dos 30 mais recentes.' : 'Catálogo operacional travado nos 30 itens mais recentes.' ?></div>
    </article>
    <article class="admin-stat-card">
      <div class="admin-stat-label">Ativas</div>
      <div class="admin-stat-value"><?= (int) $activeCount ?></div>
      <div class="admin-stat-foot"><?= (int) $featuredCount ?> em destaque neste recorte.</div>
    </article>
    <article class="admin-stat-card">
      <div class="admin-stat-label">Cliques somados</div>
      <div class="admin-stat-value"><?= number_format((int) $visibleClicks, 0, ',', '.') ?></div>
      <div class="admin-stat-foot">Ordenação prioriza atualização e cadastro recente.</div>
    </article>
    <article class="admin-stat-card">
      <div class="admin-stat-label">ML para revisar</div>
      <div class="admin-stat-value"><?= (int) $invalidMeliCount ?></div>
      <div class="admin-stat-foot">Links sem marcador oficial de afiliado.</div>
    </article>
  </section>

  <section class="admin-panel">
    <form method="get" class="admin-filter-form">
      <div class="admin-search-toolbar">
        <div class="admin-field admin-field-search">
          <label for="q">Pesquisar produto</label>
          <input id="q" name="q" value="<?= h($search) ?>" placeholder="Título, slug, categoria, tags ou loja">
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
        <div class="admin-form-actions admin-form-actions-inline">
          <button class="btn-link primary" type="submit">Pesquisar</button>
          <a class="badge" href="/admin/ofertas.php">Limpar</a>
        </div>
      </div>
      <?php if ($mode !== ''): ?>
        <input type="hidden" name="modo" value="<?= h($mode) ?>">
      <?php endif; ?>
    </form>
    <div class="admin-filter-row">
      <span class="admin-meta-chip admin-meta-chip-soft">Exibindo sempre os 30 últimos itens</span>
      <?php foreach ($lojas as $loja): ?>
        <a class="badge" href="/admin/ofertas.php?<?= http_build_query(['loja' => $loja['loja']]) ?>"><?= h($loja['loja']) ?> (<?= (int) $loja['total'] ?>)</a>
      <?php endforeach; ?>
    </a>
  </section>

  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Catálogo operacional</h2>
        <p>Cards grandes para revisar produto, conversão e integridade do link sem perder as ações rápidas.</p>
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
          <?php $tagChips = array_values(array_filter($tagParts, static fn($item) => !admin_offer_is_url($item))); ?>
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
                  <a class="admin-meta-chip" href="/oferta.php?slug=<?= urlencode((string) $o['slug']) ?>" target="_blank" rel="noopener">Ver p&aacute;gina</a>
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
                  </div>
                </div>

                <div class="admin-side-card">
                  <strong>Ações</strong>
                  <div class="admin-card-actions" style="margin-top: 10px;">
                    <a class="btn-link" href="/admin/oferta_editar.php?id=<?= (int) $o['id'] ?>">Editar</a>
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


