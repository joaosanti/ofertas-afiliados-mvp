<?php
require_once __DIR__ . '/_init.php';
admin_require_login();

$flash = admin_flash_get();

$pdo = db();
$filter = trim((string) ($_GET['loja'] ?? ''));
$mode = trim((string) ($_GET['modo'] ?? ''));

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
  admin_csrf_check_or_die();
  $acao = (string) ($_POST['acao'] ?? '');
  $id = (int) ($_POST['id'] ?? 0);

  if ($id > 0 && in_array($acao, ['toggle_ativo', 'toggle_destaque'], true)) {
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
  }

  $query = [];
  if ($filter !== '') {
    $query['loja'] = $filter;
  }
  if ($mode !== '') {
    $query['modo'] = $mode;
  }

  header('Location: /admin/ofertas.php' . ($query ? '?' . http_build_query($query) : ''));
  exit;
}

$sql = 'SELECT o.id, o.titulo, o.slug, o.preco, o.preco_antigo, o.loja, o.categoria, o.destaque, o.ativo, o.atualizado_em, o.url_afiliado,
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

$sql .= ' GROUP BY o.id, o.titulo, o.slug, o.preco, o.preco_antigo, o.loja, o.categoria, o.destaque, o.ativo, o.atualizado_em, o.url_afiliado, o.imagem_url, o.cupom, o.tags';
$sql .= ' ORDER BY clicks DESC, o.atualizado_em DESC, o.id DESC LIMIT 300';

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
?>
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Admin - Ofertas</title>
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
        <strong>Zero Preco Admin</strong>
        <span>Catalogo, afiliados e curadoria em um painel mais visual.</span>
      </div>
    </div>
    <div class="admin-header-actions">
      <a class="badge" href="/admin/oferta_editar.php">+ Nova oferta</a>
      <a class="badge" href="/admin/importar.php">Importar</a>
      <a class="badge" href="/admin/social.php">Social</a>
      <a class="badge" href="/admin/auditoria_links.php">Auditoria de links</a>
      <a class="badge" href="/admin/ml_corrigir_lote.php">Corrigir ML em lote</a>
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
        <span class="admin-kicker">Gerenciador de produtos</span>
        <h1>Ofertas com visual mais limpo, foto forte e leitura rapida do afiliado.</h1>
        <p>O fluxo continua o mesmo, mas agora o catalogo fica mais facil de revisar: preco, imagem, cupom, status, cliques, slug e link afiliado aparecem no mesmo card sem quebrar a operacao atual.</p>
      </div>
      <div class="admin-hero-actions">
        <a class="btn-link primary" href="/admin/oferta_editar.php">Criar oferta</a>
        <a class="badge" href="/admin/auditoria_links.php">Abrir auditoria</a>
      </div>
    </div>
  </section>

  <section class="admin-stats-grid">
    <article class="admin-stat-card">
      <div class="admin-stat-label">Ofertas nesta visao</div>
      <div class="admin-stat-value"><?= (int) $visibleCount ?></div>
      <div class="admin-stat-foot"><?= $filter !== '' ? 'Filtro por loja ativo.' : 'Ate 300 itens mais relevantes.' ?></div>
    </article>
    <article class="admin-stat-card">
      <div class="admin-stat-label">Ativas</div>
      <div class="admin-stat-value"><?= (int) $activeCount ?></div>
      <div class="admin-stat-foot"><?= (int) $featuredCount ?> em destaque neste recorte.</div>
    </article>
    <article class="admin-stat-card">
      <div class="admin-stat-label">Cliques somados</div>
      <div class="admin-stat-value"><?= number_format((int) $visibleClicks, 0, ',', '.') ?></div>
      <div class="admin-stat-foot">Ordenacao prioriza clique e atualizacao.</div>
    </article>
    <article class="admin-stat-card">
      <div class="admin-stat-label">ML para revisar</div>
      <div class="admin-stat-value"><?= (int) $invalidMeliCount ?></div>
      <div class="admin-stat-foot">Links sem marcador oficial de afiliado.</div>
    </article>
  </section>

  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Filtros rapidos</h2>
        <p>Mercado Livre precisa usar link oficial de afiliado, como <code>/social/</code>, <code>matt_*</code>, URL com <code>wid</code> e marcadores <code>affiliates</code> ou links do fluxo <code>affiliate-profile</code>.</p>
      </div>
    </div>
    <div class="admin-filter-row">
      <a class="badge" href="/admin/ofertas.php">Todas</a>
      <a class="badge" href="/admin/ofertas.php?modo=ml_invalidos">Somente ML invalidos (<?= $invalidMeliCount ?>)</a>
      <?php foreach ($lojas as $loja): ?>
        <a class="badge" href="/admin/ofertas.php?loja=<?= urlencode($loja['loja']) ?>"><?= h($loja['loja']) ?> (<?= (int) $loja['total'] ?>)</a>
      <?php endforeach; ?>
    </div>
  </section>

  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Catalogo operacional</h2>
        <p>Cards grandes para revisar produto, conversao e integridade do link sem perder as acoes rapidas.</p>
      </div>
    </div>

    <?php if (!$ofertas): ?>
      <div class="admin-empty">Nenhuma oferta encontrada para este filtro.</div>
    <?php else: ?>
      <div class="admin-offers-grid">
        <?php foreach ($ofertas as $o): ?>
          <?php $isMeli = strtolower((string) $o['loja']) === 'mercado livre'; ?>
          <?php $isAffiliateOk = $isMeli ? admin_is_meli_affiliate_url($o['url_afiliado']) : false; ?>
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
                  <span class="admin-meta-chip">slug: <?= h($o['slug']) ?></span>
                  <?php if (!empty($o['cupom'])): ?>
                    <span class="admin-meta-chip">cupom <?= h($o['cupom']) ?></span>
                  <?php endif; ?>
                  <?php if (!empty($o['tags'])): ?>
                    <span class="admin-meta-chip"><?= h($o['tags']) ?></span>
                  <?php endif; ?>
                </div>

                <div class="admin-meta-row" style="margin-top: 12px;">
                  <span class="admin-status <?= ((int) $o['ativo'] === 1) ? 'ok' : 'off' ?>"><?= ((int) $o['ativo'] === 1) ? 'Ativa' : 'Inativa' ?></span>
                  <span class="admin-status <?= ((int) $o['destaque'] === 1) ? 'ok' : 'off' ?>"><?= ((int) $o['destaque'] === 1) ? 'Destaque' : 'Normal' ?></span>
                  <?php if ($isMeli): ?>
                    <span class="admin-status <?= $isAffiliateOk ? 'ok' : 'warn' ?>"><?= $isAffiliateOk ? 'ML afiliado ok' : 'Revisar link ML' ?></span>
                  <?php endif; ?>
                </div>

                <div class="admin-help" style="margin-top: 12px;">Atualizado em <?= h((string) $o['atualizado_em']) ?></div>
              </div>

              <div class="admin-mini-grid">
                <div class="admin-side-card">
                  <strong>URL afiliado</strong>
                  <div class="admin-url-box"><?= h($o['url_afiliado']) ?></div>
                </div>

                <div class="admin-side-card">
                  <strong>Acoes</strong>
                  <div class="admin-card-actions" style="margin-top: 10px;">
                    <a class="btn-link" href="/admin/oferta_editar.php?id=<?= (int) $o['id'] ?>">Editar</a>
                    <a class="btn-link primary" href="<?= h($o['url_afiliado']) ?>" target="_blank" rel="noopener sponsored nofollow">Testar link</a>
                    <a class="btn-link" href="/oferta.php?slug=<?= urlencode((string) $o['slug']) ?>" target="_blank" rel="noopener">Ver pagina</a>
                    <a class="btn-link" href="/oferta.php?slug=<?= urlencode((string) $o['slug']) ?>&go=1" target="_blank" rel="noopener sponsored nofollow">Ir via site</a>
                    <form method="post">
                      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
                      <input type="hidden" name="id" value="<?= (int) $o['id'] ?>">
                      <input type="hidden" name="acao" value="toggle_ativo">
                      <button class="badge" type="submit"><?= ((int) $o['ativo'] === 1) ? 'Desativar' : 'Ativar' ?></button>
                    </form>
                    <form method="post">
                      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
                      <input type="hidden" name="id" value="<?= (int) $o['id'] ?>">
                      <input type="hidden" name="acao" value="toggle_destaque">
                      <button class="badge" type="submit"><?= ((int) $o['destaque'] === 1) ? 'Remover destaque' : 'Destacar' ?></button>
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
</body>
</html>

