<?php
require_once __DIR__ . '/inc/site.php';

$pdo = db();
$data = site_fetch_home_data($pdo);
$selectionMix = $data['selection_mix'];
$meliTrending = $data['meli_trending'];
$shopeeTrending = $data['shopee_trending'];
$amazonTrending = $data['amazon_trending'];
$categorySections = $data['sections_by_category'];
$siteHeaderCurrent = 'selection';
$siteHeaderSearchPlaceholder = 'Buscar produto';
?>
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Zero Preço | Comparador moderno com links afiliados</title>
  <meta name="description" content="Seleção diária de ofertas e vitrines por marketplace com acesso rápido ao produto certo.">
  <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-8314124298799437" crossorigin="anonymous"></script>
  <?php require __DIR__ . '/inc/site_head_analytics.php'; ?>
  <link rel="stylesheet" href="/assets/css/style.css">
</head>
<body>
  <?php require __DIR__ . '/inc/site_header.php'; ?>

  <main class="page-shell" style="padding-top:18px;">
    <div class="container">
      <section class="section-panel" id="selecao-dia">
        <div class="section-heading">
          <div>
            <h2>Seleção do dia</h2>
            <div class="section-copy">As ofertas mais fortes do momento, balanceadas entre as lojas com melhor chance de saída.</div>
          </div>
        </div>

        <?php if ($selectionMix): ?>
          <div class="selection-columns">
            <?php foreach (array_chunk($selectionMix, 3) as $column): ?>
              <div class="selection-column">
                <?php foreach ($column as $offer): ?>
                  <article class="offer-spotlight">
                    <img src="<?= h($offer['imagem_url'] ?: '/assets/img/sem-img.png') ?>" alt="">
                    <div>
                      <div class="kicker"><?= h(site_store_label($offer['loja'])) ?></div>
                      <div class="spotlight-title"><?= h($offer['titulo']) ?></div>
                      <div class="price-row" style="margin-bottom:8px;">
                        <span class="price-now"><?= h(site_money($offer['preco'])) ?></span>
                        <?php if (!empty($offer['preco_antigo'])): ?>
                          <span class="coupon-tag">-<?= site_discount_percent($offer['preco'], $offer['preco_antigo']) ?>%</span>
                        <?php endif; ?>
                      </div>
                      <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Comprar no site</a>
                    </div>
                  </article>
                <?php endforeach; ?>
              </div>
            <?php endforeach; ?>
          </div>
        <?php else: ?>
          <div class="empty-state">Sem ofertas ainda para montar a seleção do dia.</div>
        <?php endif; ?>
      </section>

      <section class="section-panel" id="shopee-alta">
        <div class="section-heading">
          <div>
            <h2>Shopee em alta agora</h2>
            <div class="section-copy">Produtos da Shopee priorizados por potencial de compra e força da oferta.</div>
          </div>
          <a class="cta-link" href="/categoria.php?cat=geral&amp;store=Shopee">Ver catálogo completo</a>
        </div>

        <?php if ($shopeeTrending): ?>
          <div class="grid">
            <?php foreach ($shopeeTrending as $offer): ?>
              <?php $discount = site_discount_percent($offer['preco'], $offer['preco_antigo']); ?>
              <article class="card">
                <a class="card-media" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">
                  <img src="<?= h($offer['imagem_url'] ?: '/assets/img/sem-img.png') ?>" alt="">
                  <div class="card-badges">
                    <span class="flag flag-dark">Shopee</span>
                    <?php if ($discount !== null): ?>
                      <span class="flag flag-sale">-<?= $discount ?>%</span>
                    <?php endif; ?>
                  </div>
                </a>
                <div class="card-body">
                  <div class="kicker">Shopee</div>
                  <div class="card-title"><?= h($offer['titulo']) ?></div>
                  <div class="price-row">
                    <span class="price-now"><?= h(site_money($offer['preco'])) ?></span>
                    <?php if (!empty($offer['preco_antigo'])): ?>
                      <span class="price-old"><?= h(site_money($offer['preco_antigo'])) ?></span>
                    <?php endif; ?>
                  </div>
                  <div class="card-footer compact-footer">
                    <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Comprar no site</a>
                  </div>
                </div>
              </article>
            <?php endforeach; ?>
          </div>
        <?php else: ?>
          <div class="empty-state">Sem ofertas da Shopee ainda para montar esta vitrine.</div>
        <?php endif; ?>
      </section>

      <section class="section-panel" id="mercado-livre-alta">
        <div class="section-heading">
          <div>
            <h2>Mercado Livre em alta agora</h2>
            <div class="section-copy">Produtos do Mercado Livre ordenados pelos sinais mais fortes de venda e saída.</div>
          </div>
          <a class="cta-link" href="/categoria.php?cat=geral&amp;store=Mercado%20Livre">Ver catálogo completo</a>
        </div>

        <?php if ($meliTrending): ?>
          <div class="grid">
            <?php foreach ($meliTrending as $offer): ?>
              <?php $discount = site_discount_percent($offer['preco'], $offer['preco_antigo']); ?>
              <article class="card">
                <a class="card-media" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">
                  <img src="<?= h($offer['imagem_url'] ?: '/assets/img/sem-img.png') ?>" alt="">
                  <div class="card-badges">
                    <span class="flag flag-dark">Mercado Livre</span>
                    <?php if ($discount !== null): ?>
                      <span class="flag flag-sale">-<?= $discount ?>%</span>
                    <?php endif; ?>
                  </div>
                </a>
                <div class="card-body">
                  <div class="kicker">Mercado Livre</div>
                  <div class="card-title"><?= h($offer['titulo']) ?></div>
                  <div class="price-row">
                    <span class="price-now"><?= h(site_money($offer['preco'])) ?></span>
                    <?php if (!empty($offer['preco_antigo'])): ?>
                      <span class="price-old"><?= h(site_money($offer['preco_antigo'])) ?></span>
                    <?php endif; ?>
                  </div>
                  <div class="card-footer compact-footer">
                    <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Comprar no site</a>
                  </div>
                </div>
              </article>
            <?php endforeach; ?>
          </div>
        <?php else: ?>
          <div class="empty-state">Sem ofertas do Mercado Livre no momento.</div>
        <?php endif; ?>
      </section>

      <section class="section-panel" id="amazon-alta">
        <div class="section-heading">
          <div>
            <h2>Amazon em alta agora</h2>
            <div class="section-copy">Seleção da Amazon com ofertas fortes para clique rápido e compra direta.</div>
          </div>
          <a class="cta-link" href="/categoria.php?cat=geral&amp;store=Amazon">Ver catálogo completo</a>
        </div>

        <?php if ($amazonTrending): ?>
          <div class="grid">
            <?php foreach ($amazonTrending as $offer): ?>
              <?php $discount = site_discount_percent($offer['preco'], $offer['preco_antigo']); ?>
              <article class="card">
                <a class="card-media" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">
                  <img src="<?= h($offer['imagem_url'] ?: '/assets/img/sem-img.png') ?>" alt="">
                  <div class="card-badges">
                    <span class="flag flag-dark">Amazon</span>
                    <?php if ($discount !== null): ?>
                      <span class="flag flag-sale">-<?= $discount ?>%</span>
                    <?php endif; ?>
                  </div>
                </a>
                <div class="card-body">
                  <div class="kicker">Amazon</div>
                  <div class="card-title"><?= h($offer['titulo']) ?></div>
                  <div class="price-row">
                    <span class="price-now"><?= h(site_money($offer['preco'])) ?></span>
                    <?php if (!empty($offer['preco_antigo'])): ?>
                      <span class="price-old"><?= h(site_money($offer['preco_antigo'])) ?></span>
                    <?php endif; ?>
                  </div>
                  <div class="card-footer compact-footer">
                    <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Comprar no site</a>
                  </div>
                </div>
              </article>
            <?php endforeach; ?>
          </div>
        <?php else: ?>
          <div class="empty-state">Sem ofertas da Amazon no momento.</div>
        <?php endif; ?>
      </section>

      <?php foreach ($categorySections as $section): ?>
        <section class="section-panel">
          <div class="section-heading">
            <div>
              <h2><?= h(site_public_category_label($section['name'])) ?></h2>
              <div class="section-copy"><?= (int) $section['total'] ?> ofertas ativas nesta categoria.</div>
            </div>
            <a class="cta-link" href="<?= h(site_category_href($section['name'])) ?>">Ver mais</a>
          </div>

          <div class="grid grid-tight">
            <?php foreach ($section['offers'] as $offer): ?>
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
                  <div class="card-footer compact-footer">
                    <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Comprar no site</a>
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
