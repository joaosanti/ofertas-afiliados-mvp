<?php
require_once __DIR__ . '/inc/site.php';

$pdo = db();
$data = site_fetch_deals_of_day_data($pdo);
$bestDeals = $data['best_deals'];
$budgetDeals = $data['budget_deals'];
$budgetStrictCount = (int) ($data['budget_strict_count'] ?? count($budgetDeals));
$couponDeals = $data['coupon_deals'];
$topClicked = $data['top_clicked'];
$activeOfferCount = $data['active_offer_count'];
$siteHeaderCurrent = 'deals';
$siteHeaderSearchPlaceholder = 'Buscar oferta com desconto';
?>
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Ofertas do Dia | Zero Preco</title>
  <meta name="description" content="Pagina rapida com as melhores ofertas do dia, produtos baratos para girar e atalhos com cupom ativo.">
  <link rel="icon" type="image/png" href="/assets/img/logo-zp.png">
  <?php require __DIR__ . '/inc/site_head_analytics.php'; ?>
  <link rel="stylesheet" href="/assets/css/style.css">
</head>
<body>
  <?php require __DIR__ . '/inc/site_header.php'; ?>

  <main class="page-shell" style="padding-top:18px;">
    <div class="container">
      <section class="section-panel deals-hero-panel">
        <div class="deals-hero-copy">
          <span class="eyebrow">Ofertas do Dia</span>
          <h1>Melhores ofertas do dia</h1>
          <div class="deals-hero-links">
            <a class="hero-chip-link" href="#melhores-ofertas">Ver ofertas</a>
            <a class="hero-chip-link" href="#ofertas-ate-150">Até R$ 150</a>
            <?php if ($couponDeals): ?>
              <a class="hero-chip-link" href="#cupons">Com cupom</a>
            <?php endif; ?>
            <?php if ($topClicked): ?>
              <a class="hero-chip-link" href="#mais-clicadas">Mais clicadas</a>
            <?php endif; ?>
          </div>
        </div>

      </section>

      <section class="section-panel" id="melhores-ofertas">
        <div class="section-heading">
          <div>
            <h2>Melhores ofertas do dia</h2>
          </div>
        </div>

        <?php if ($bestDeals): ?>
          <div class="grid">
            <?php foreach ($bestDeals as $offer): ?>
              <?php $discount = site_discount_percent($offer['preco'], $offer['preco_antigo']); ?>
              <article class="card">
                <a class="card-media" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">
                  <img src="<?= h($offer['imagem_url'] ?: '/assets/img/sem-img.png') ?>" alt="">
                  <div class="card-badges">
                    <?php if ($discount !== null): ?>
                      <span class="flag flag-sale">-<?= $discount ?>%</span>
                    <?php endif; ?>
                    <?php if (!empty($offer['cupom'])): ?>
                      <span class="flag flag-dark">Cupom</span>
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
                    <?php if (!empty($offer['cupom'])): ?>
                      <span class="meta-chip">Cupom ativo</span>
                    <?php endif; ?>
                    <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Ver promoção</a>
                  </div>
                </div>
              </article>
            <?php endforeach; ?>
          </div>
        <?php else: ?>
          <div class="empty-state">Sem ofertas suficientes para montar a vitrine do dia ainda.</div>
        <?php endif; ?>
      </section>

      <section class="section-panel" id="ofertas-ate-150">
        <div class="section-heading">
          <div>
            <h2><?= $budgetStrictCount >= count($budgetDeals) ? 'Ofertas até R$ 150' : 'Ofertas em conta' ?></h2>
          </div>
        </div>

        <?php if ($budgetDeals): ?>
          <div class="grid grid-tight">
            <?php foreach ($budgetDeals as $offer): ?>
              <?php $discount = site_discount_percent($offer['preco'], $offer['preco_antigo']); ?>
              <article class="card compact-card">
                <a class="card-media compact-media" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">
                  <img src="<?= h($offer['imagem_url'] ?: '/assets/img/sem-img.png') ?>" alt="">
                  <div class="card-badges">
                    <?php if ($discount !== null): ?>
                      <span class="flag flag-sale">-<?= $discount ?>%</span>
                    <?php endif; ?>
                  </div>
                </a>
                <div class="card-body compact-body">
                  <div class="kicker"><?= h(site_store_label($offer['loja'])) ?></div>
                  <div class="card-title compact-title"><?= h($offer['titulo']) ?></div>
                  <div class="price-row compact-price-row">
                    <span class="price-now"><?= h(site_money($offer['preco'])) ?></span>
                  </div>
                  <div class="card-footer compact-footer">
                    <span class="meta-chip">Baixo ticket</span>
                    <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Abrir oferta</a>
                  </div>
                </div>
              </article>
            <?php endforeach; ?>
          </div>
        <?php else: ?>
          <div class="empty-state">Sem ofertas baratas suficientes no momento.</div>
        <?php endif; ?>
      </section>

      <?php if ($couponDeals): ?>
        <section class="section-panel" id="cupons">
          <div class="section-heading">
            <div>
              <h2>Com cupom ativo</h2>
            </div>
          </div>
          <div class="coupon-list">
            <?php foreach ($couponDeals as $offer): ?>
              <div class="coupon-item">
                <img src="<?= h($offer['imagem_url'] ?: '/assets/img/sem-img.png') ?>" alt="">
                <div>
                  <div class="kicker"><?= h(site_store_label($offer['loja'])) ?></div>
                  <div class="spotlight-title"><?= h($offer['titulo']) ?></div>
                  <div class="price-row">
                    <span class="price-now"><?= h(site_money($offer['preco'])) ?></span>
                    <span class="coupon-tag"><?= h($offer['cupom']) ?></span>
                  </div>
                </div>
                <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Usar cupom</a>
              </div>
            <?php endforeach; ?>
          </div>
        </section>
      <?php endif; ?>

      <?php if ($topClicked): ?>
        <section class="section-panel" id="mais-clicadas">
          <div class="section-heading">
            <div>
              <h2>Mais clicadas</h2>
            </div>
          </div>
          <div class="instagram-list">
            <?php foreach ($topClicked as $offer): ?>
              <a class="instagram-list-card" href="<?= h(site_offer_href($offer['slug'])) ?>">
                <img src="<?= h($offer['imagem_url'] ?: '/assets/img/sem-img.png') ?>" alt="">
                <div>
                  <div class="kicker"><?= h(site_store_label($offer['loja'])) ?></div>
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
    </div>
  </main>

  <?php require __DIR__ . '/inc/site_footer.php'; ?>
  <?php require __DIR__ . '/inc/site_footer_scripts.php'; ?>
</body>
</html>
