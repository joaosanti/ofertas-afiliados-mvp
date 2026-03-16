<?php
require_once __DIR__ . '/inc/site.php';

$category = $_GET['cat'] ?? 'geral';
$pdo = db();
$data = site_fetch_category_data($pdo, $category);
$offers = $data['offers'];
$stores = $data['stores'];
$selectedStore = $data['store'];
$categoryLabel = site_public_category_label($category);
$categoryDescription = $selectedStore !== ''
  ? 'Confira ofertas atualizadas de ' . site_store_label($selectedStore) . ' nesta seleção de produtos.'
  : site_category_description($category);
$pageHeading = 'Produtos';
if ($selectedStore !== '') {
  $pageHeading = site_store_label($selectedStore);
} elseif (trim((string) $category) !== '' && strtolower(trim((string) $category)) !== 'geral') {
  $pageHeading = $categoryLabel;
}
$siteHeaderCurrent = 'categories';
$siteHeaderSearchPlaceholder = 'Buscar oferta com desconto';
?>
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title><?= h($categoryLabel) ?> | Zero Preço</title>
  <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-8314124298799437" crossorigin="anonymous"></script>
  <?php require __DIR__ . '/inc/site_head_analytics.php'; ?>
  <link rel="stylesheet" href="/assets/css/style.css">
</head>
<body>
  <?php require __DIR__ . '/inc/site_header.php'; ?>

  <main class="page-shell" style="padding-top:18px;">
    <div class="container">
      <section class="section-panel category-hero-panel">
        <div class="section-heading">
          <div>
            <h2><?= h($pageHeading) ?></h2>
            <div class="section-copy"><?= h($categoryDescription) ?></div>
          </div>
          <a class="button button-secondary" href="/ofertas-do-dia.php">Ir para Ofertas do Dia</a>
        </div>
      </section>

      <section class="section-panel" id="produtos">
        <div class="section-heading">
          <div>
            <h2>Ofertas disponíveis</h2>
          </div>
        </div>

        <?php if ($offers): ?>
          <div class="grid">
            <?php foreach ($offers as $offer): ?>
              <?php $discount = site_discount_percent($offer['preco'], $offer['preco_antigo']); ?>
              <?php $soldCount = site_extract_sold_count($offer['tags'] ?? ''); ?>
              <article class="card">
                <a class="card-media" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">
                  <img src="<?= h($offer['imagem_url'] ?: '/assets/img/sem-img.png') ?>" alt="">
                  <div class="card-badges">
                    <?php if ($discount !== null): ?>
                      <span class="flag flag-sale">-<?= $discount ?>%</span>
                    <?php endif; ?>
                    <?php if ($soldCount > 0): ?>
                      <span class="flag flag-top"><?= (int) $soldCount ?> vendidos</span>
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
                  <div class="card-footer compact-footer">
                    <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Ver promoção</a>
                  </div>
                </div>
              </article>
            <?php endforeach; ?>
          </div>
        <?php else: ?>
          <div class="empty-state">Nenhuma oferta ativa nesta categoria no momento.</div>
        <?php endif; ?>
      </section>
    </div>
  </main>

  <?php require __DIR__ . '/inc/site_footer.php'; ?>
  <?php require __DIR__ . '/inc/site_footer_scripts.php'; ?>
</body>
</html>
