<?php
require_once __DIR__ . '/inc/site.php';

$pdo = db();
$data = site_fetch_instagram_landing_data($pdo);
$recentOffers = $data['recent_offers'];
$topClicked = $data['top_clicked'];
$categories = $data['categories'];
$categorySections = $data['category_sections'];
$siteHeaderCurrent = 'shopee';
$siteHeaderSearchPlaceholder = 'Buscar produto';
?>
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <?php require __DIR__ . '/inc/site_head_analytics.php'; ?>
  <title>Ofertas do Instagram | Zero Preço</title>
  <meta name="description" content="Landing do Instagram com as ofertas mais recentes e categorias quentes do Zero Preço.">
  <link rel="stylesheet" href="/assets/css/style.css">
</head>
<body>
  <?php require __DIR__ . '/inc/site_header.php'; ?>

  <main class="page-shell">
    <div class="container">
      <section class="section-panel instagram-hero">
        <div class="instagram-hero-grid">
          <div class="instagram-hero-copy">
            <span class="eyebrow">Link da bio</span>
            <h1>Ofertas quentes para abrir rápido e comprar na loja oficial.</h1>
            <p>Esta página foi pensada para quem veio do Instagram. Escolha uma oferta, veja os detalhes e siga para o link da loja parceira.</p>
            <div class="cta-row" style="justify-content:flex-start; flex-wrap:wrap; margin-top:20px;">
              <a class="button button-primary" href="#recentes">Ver ofertas recentes</a>
              <a class="button button-secondary" href="#categorias">Explorar categorias</a>
            </div>
          </div>
          <div class="instagram-hero-side">
            <div class="instagram-mini-stats">
              <div class="stats-card">
                <strong><?= count($recentOffers) ?></strong>
                <span>ofertas recentes</span>
              </div>
              <div class="stats-card">
                <strong><?= count($categories) ?></strong>
                <span>categorias quentes</span>
              </div>
              <div class="stats-card">
                <strong><?= count($topClicked) ?></strong>
                <span>mais clicadas</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section class="section-panel" id="recentes">
        <div class="section-heading">
          <div>
            <h2>Ofertas recentes</h2>
            <div class="section-copy">Seleção pronta para quem quer bater o olho e abrir o produto sem perder tempo.</div>
          </div>
        </div>

        <div class="grid">
          <?php foreach ($recentOffers as $offer): ?>
            <?php $discount = site_discount_percent($offer['preco'], $offer['preco_antigo']); ?>
            <article class="card">
              <a class="card-media" href="<?= h(site_offer_href($offer['slug'])) ?>">
                <img src="<?= h($offer['imagem_url'] ?: '/assets/img/sem-img.png') ?>" alt="">
                <div class="card-badges">
                  <?php if ($discount !== null): ?>
                    <span class="flag flag-sale">-<?= $discount ?>%</span>
                  <?php endif; ?>
                  <?php if ((int) $offer['destaque'] === 1): ?>
                    <span class="flag flag-dark">Destaque</span>
                  <?php endif; ?>
                </div>
              </a>
              <div class="card-body">
                <div class="kicker"><?= h(site_store_label($offer['loja'])) ?> &bull; <?= h(site_category_label($offer['categoria'])) ?></div>
                <div class="card-title"><?= h($offer['titulo']) ?></div>
                <div class="price-row">
                  <span class="price-now"><?= h(site_money($offer['preco'])) ?></span>
                  <?php if (!empty($offer['preco_antigo'])): ?>
                    <span class="price-old"><?= h(site_money($offer['preco_antigo'])) ?></span>
                  <?php endif; ?>
                </div>
                <div class="card-footer">
                  <span class="meta-chip"><?= h(site_category_label($offer['categoria'])) ?></span>
                  <a class="btn-link primary" href="<?= h(site_offer_href($offer['slug'])) ?>">Comprar no site</a>
                </div>
              </div>
            </article>
          <?php endforeach; ?>
        </div>
      </section>

      <section class="section-panel" id="categorias">
        <div class="section-heading">
          <div>
            <h2>Categorias quentes</h2>
            <div class="section-copy">Atalhos para as linhas com mais volume e mais chance de clique agora.</div>
          </div>
        </div>

        <div class="filters">
          <?php foreach ($categories as $category): ?>
            <a class="menu-chip" href="<?= h(site_category_href($category['categoria'])) ?>"><?= h(site_category_label($category['categoria'])) ?> <strong><?= (int) $category['total'] ?></strong></a>
          <?php endforeach; ?>
        </div>
      </section>

      <?php if ($topClicked): ?>
        <section class="section-panel" id="mais-clicadas">
          <div class="section-heading">
            <div>
              <h2>Mais clicadas</h2>
              <div class="section-copy">O que mais puxou interesse recente dentro do site.</div>
            </div>
          </div>

          <div class="instagram-list">
            <?php foreach ($topClicked as $offer): ?>
              <a class="instagram-list-card" href="<?= h(site_offer_href($offer['slug'])) ?>">
                <img src="<?= h($offer['imagem_url'] ?: '/assets/img/sem-img.png') ?>" alt="">
                <div>
                  <div class="kicker"><?= h(site_store_label($offer['loja'])) ?> &bull; <?= h(site_category_label($offer['categoria'])) ?></div>
                  <div class="instagram-list-title"><?= h($offer['titulo']) ?></div>
                  <div class="price-row" style="margin-bottom:0;">
                    <span class="price-now"><?= h(site_money($offer['preco'])) ?></span>
                    <span class="meta-chip"><?= (int) ($offer['clicks'] ?? 0) ?> cliques</span>
                  </div>
                </div>
              </a>
            <?php endforeach; ?>
          </div>
        </section>
      <?php endif; ?>

      <?php foreach (array_slice($categorySections, 0, 2) as $section): ?>
        <section class="section-panel">
          <div class="section-heading">
            <div>
              <h2><?= h(site_category_label($section['name'])) ?></h2>
              <div class="section-copy">Atalho rápido para abrir mais ofertas dessa categoria.</div>
            </div>
            <a class="cta-link" href="<?= h(site_category_href($section['name'])) ?>">Ver categoria</a>
          </div>

          <div class="grid grid-tight">
            <?php foreach ($section['offers'] as $offer): ?>
              <article class="card compact-card">
                <a class="card-media compact-media" href="<?= h(site_offer_href($offer['slug'])) ?>">
                  <img src="<?= h($offer['imagem_url'] ?: '/assets/img/sem-img.png') ?>" alt="">
                </a>
                <div class="card-body compact-body">
                  <div class="kicker"><?= h(site_store_label($offer['loja'])) ?></div>
                  <div class="card-title compact-title"><?= h($offer['titulo']) ?></div>
                  <div class="price-row compact-price-row">
                    <span class="price-now"><?= h(site_money($offer['preco'])) ?></span>
                  </div>
                  <div class="card-footer compact-footer">
                    <span class="meta-chip"><?= h(site_category_label($offer['categoria'])) ?></span>
                    <a class="btn-link primary" href="<?= h(site_offer_href($offer['slug'])) ?>">Comprar no site</a>
                  </div>
                </div>
              </article>
            <?php endforeach; ?>
          </div>
        </section>
      <?php endforeach; ?>
    </div>
  </main>

  <?php require __DIR__ . '/inc/site_footer.php'; ?>
  <?php require __DIR__ . '/inc/site_footer_scripts.php'; ?>
</body>
</html>
