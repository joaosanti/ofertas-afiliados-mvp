<?php
require_once __DIR__ . '/inc/site.php';

$query = $_GET['q'] ?? '';
$pdo = db();
$data = site_search_offers($pdo, $query, 72);
$offers = $data['offers'];
$stores = $data['stores'];
$categories = $data['categories'];
$siteHeaderCurrent = 'categories';
$siteHeaderSearchValue = trim((string) $query);
$siteHeaderSearchPlaceholder = 'Buscar produto';
$pageTitle = trim((string) $query) !== '' ? 'Busca por ' . trim((string) $query) : 'Buscar produtos';
?>
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <?php require __DIR__ . '/inc/site_head_analytics.php'; ?>
  <title><?= h($pageTitle) ?> | Zero Preço</title>
  <link rel="stylesheet" href="/assets/css/style.css">
</head>
<body>
  <?php require __DIR__ . '/inc/site_header.php'; ?>

  <main class="page-shell" style="padding-top:18px;">
    <div class="container">
      <section class="section-panel" id="resultados">
        <div class="search-results-head">
          <div>
            <h2><?= trim((string) $query) !== '' ? 'Resultados para "' . h(trim((string) $query)) . '"' : 'Buscar produtos' ?></h2>
            <div class="section-copy">
              <?= trim((string) $query) !== '' ? (int) $data['total'] . ' produto(s) encontrado(s) com maior chance de bater com sua busca.' : 'Digite o nome do produto para ver as ofertas mais prováveis.' ?>
            </div>
          </div>
        </div>

        <?php if ($stores || $categories): ?>
          <div class="search-summary-grid">
            <?php if ($stores): ?>
              <div class="surface search-summary-card">
                <h4>Lojas mais presentes</h4>
                <div class="check-grid">
                  <?php foreach (array_slice($stores, 0, 5, true) as $label => $total): ?>
                    <span class="meta-chip"><?= h($label) ?> · <?= (int) $total ?></span>
                  <?php endforeach; ?>
                </div>
              </div>
            <?php endif; ?>
            <?php if ($categories): ?>
              <div class="surface search-summary-card">
                <h4>Categorias mais encontradas</h4>
                <div class="check-grid">
                  <?php foreach (array_slice($categories, 0, 6, true) as $label => $total): ?>
                    <span class="meta-chip"><?= h($label) ?> · <?= (int) $total ?></span>
                  <?php endforeach; ?>
                </div>
              </div>
            <?php endif; ?>
          </div>
        <?php endif; ?>

        <?php if ($offers): ?>
          <div class="grid">
            <?php foreach ($offers as $offer): ?>
              <?php $discount = site_discount_percent($offer['preco'], $offer['preco_antigo']); ?>
              <article class="card">
                <a class="card-media" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">
                  <img src="<?= h($offer['imagem_url'] ?: '/assets/img/sem-img.png') ?>" alt="">
                  <div class="card-badges">
                    <?php if ($discount !== null): ?>
                      <span class="flag flag-sale">-<?= $discount ?>%</span>
                    <?php endif; ?>
                  </div>
                </a>
                <div class="card-body">
                  <div class="kicker"><?= h(site_store_label($offer['loja'])) ?></div>
                  <div class="card-title"><?= h($offer['titulo']) ?></div>
                  <div class="price-row">
                    <span class="price-now"><?= h(site_money($offer['preco'])) ?></span>
                    <?php if (!empty($offer['preco_antigo'])): ?>
                      <span class="price-old"><?= h(site_money($offer['preco_antigo'])) ?></span>
                    <?php endif; ?>
                  </div>
                  <div class="offer-meta-row">
                    <span class="meta-chip"><?= h(site_public_category_label($offer['categoria'])) ?></span>
                  </div>
                  <div class="card-footer">
                    <span class="meta"><?= h(site_store_label($offer['loja'])) ?></span>
                    <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Comprar no site</a>
                  </div>
                </div>
              </article>
            <?php endforeach; ?>
          </div>
        <?php else: ?>
          <div class="empty-state">Nenhum produto encontrado para esta busca. Tente outro nome ou abra uma categoria do menu.</div>
        <?php endif; ?>
      </section>
    </div>
  </main>

  <?php require __DIR__ . '/inc/site_footer.php'; ?>
  <?php require __DIR__ . '/inc/site_footer_scripts.php'; ?>
</body>
</html>
