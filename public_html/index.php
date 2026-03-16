<?php
require_once __DIR__ . '/inc/site.php';

$pdo = db();
$data = site_fetch_home_data($pdo);
$selectionMix = $data['selection_mix'];
$topClicked = $data['top_clicked'];
$dealRush = $data['deal_rush'];
$meliTrending = $data['meli_trending'];
$shopeeTrending = $data['shopee_trending'];
$amazonTrending = $data['amazon_trending'];
$categorySections = $data['sections_by_category'];
$activeOfferCount = $data['active_offer_count'];
$siteHeaderCurrent = 'selection';
$siteHeaderSearchPlaceholder = 'Buscar oferta com desconto';
$whatsappGroupLink = site_whatsapp_group_link();
$whatsappGroupLabel = site_whatsapp_group_label();
?>
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Zero Preço | Comparador moderno com links afiliados</title>
  <meta name="description" content="Seleção diária de ofertas e vitrines por marketplace com acesso rápido ao produto certo.">
  <link rel="icon" type="image/png" href="/assets/img/logo-zp.png">
  <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-8314124298799437" crossorigin="anonymous"></script>
  <?php require __DIR__ . '/inc/site_head_analytics.php'; ?>
  <link rel="stylesheet" href="/assets/css/style.css">
</head>
<body>
  <?php require __DIR__ . '/inc/site_header.php'; ?>

  <main class="page-shell" style="padding-top:18px;">
    <div class="container">
      <section class="section-panel home-conversion-hero">
        <div class="home-conversion-grid">
          <div class="home-conversion-copy">
            <span class="eyebrow">Zero Preço</span>
            <h1>Ofertas com preço direto e acesso rápido para a loja.</h1>
            <div class="cta-row" style="justify-content:flex-start; flex-wrap:wrap; margin-top:20px;">
              <a class="button button-primary" href="/ofertas-do-dia.php">Abrir Ofertas do Dia</a>
              <a class="button button-secondary" href="<?= h($whatsappGroupLink) ?>" target="_blank" rel="noopener noreferrer">Entrar no WhatsApp</a>
            </div>
          </div>
        </div>
      </section>

      <?php if ($dealRush): ?>
        <section class="section-panel" id="giro-rapido">
          <div class="section-heading">
            <div>
              <h2>Giro Rápido</h2>
            </div>
            <a class="cta-link" href="/ofertas-do-dia.php#ofertas-ate-150">Ver até R$ 150</a>
          </div>

          <div class="rush-grid" id="giro-rapido-grid">
            <?php foreach ($dealRush as $index => $offer): ?>
              <?php $discount = site_discount_percent($offer['preco'], $offer['preco_antigo']); ?>
              <article class="card compact-card" data-load-more-item>
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
                    <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Ver promoção</a>
                  </div>
                </div>
              </article>
            <?php endforeach; ?>
          </div>

          <?php if (count($dealRush) > 8): ?>
            <div class="rush-more-wrap">
              <button class="button button-secondary" type="button" data-load-more="#giro-rapido-grid" data-load-more-step="row" data-load-more-initial="2row">Mostrar mais</button>
            </div>
          <?php endif; ?>
        </section>
      <?php endif; ?>

      <section class="section-panel" id="selecao-dia">
        <div class="section-heading">
          <div>
            <h2>Publicados no Facebook e Instagram</h2>
          </div>
          <a class="cta-link" href="/ofertas-do-dia.php">Ir para Ofertas do Dia</a>
        </div>

        <?php if ($selectionMix): ?>
          <div class="selection-columns">
            <?php foreach (array_chunk($selectionMix, 7) as $column): ?>
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
                      <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Ver promoção</a>
                    </div>
                  </article>
                <?php endforeach; ?>
              </div>
            <?php endforeach; ?>
          </div>
        <?php else: ?>
          <div class="empty-state">Sem publicacoes em redes sociais ainda para montar a seleção do dia.</div>
        <?php endif; ?>
      </section>

      <section class="whatsapp-banner">
        <div class="whatsapp-banner-copy">
          <span class="whatsapp-banner-kicker">Canal direto</span>
          <h2>Receba ofertas no WhatsApp</h2>
          <p>Entre no <?= h($whatsappGroupLabel) ?> para receber promocoes com mais chance de giro e abrir o link da oferta sem ficar procurando no site inteiro.</p>
        </div>
        <div class="whatsapp-banner-actions">
          <a class="button button-primary" href="<?= h($whatsappGroupLink) ?>" target="_blank" rel="noopener noreferrer">Entrar no grupo</a>
        </div>
      </section>

      <section class="section-panel" id="shopee-alta">
        <div class="section-heading">
          <div>
            <h2>Shopee</h2>
          </div>
          <a class="cta-link" href="/categoria.php?cat=geral&amp;store=Shopee">Ver mais</a>
        </div>

        <?php if ($shopeeTrending): ?>
          <div class="grid" id="shopee-home-grid">
            <?php foreach ($shopeeTrending as $offer): ?>
              <?php $discount = site_discount_percent($offer['preco'], $offer['preco_antigo']); ?>
              <article class="card" data-load-more-item>
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
                    <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Ver promoção</a>
                  </div>
                </div>
              </article>
            <?php endforeach; ?>
          </div>
          <?php if (count($shopeeTrending) > 1): ?>
            <div class="rush-more-wrap">
              <button class="button button-secondary" type="button" data-load-more="#shopee-home-grid" data-load-more-step="row" data-load-more-initial="2row">Mostrar mais</button>
            </div>
          <?php endif; ?>
        <?php else: ?>
          <div class="empty-state">Sem ofertas da Shopee ainda para montar esta vitrine.</div>
        <?php endif; ?>
      </section>

      <section class="section-panel" id="mercado-livre-alta">
        <div class="section-heading">
          <div>
            <h2>Mercado Livre</h2>
          </div>
          <a class="cta-link" href="/categoria.php?cat=geral&amp;store=Mercado%20Livre">Ver mais</a>
        </div>

        <?php if ($meliTrending): ?>
          <div class="grid" id="meli-home-grid">
            <?php foreach ($meliTrending as $offer): ?>
              <?php $discount = site_discount_percent($offer['preco'], $offer['preco_antigo']); ?>
              <article class="card" data-load-more-item>
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
                    <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Ver promoção</a>
                  </div>
                </div>
              </article>
            <?php endforeach; ?>
          </div>
          <?php if (count($meliTrending) > 1): ?>
            <div class="rush-more-wrap">
              <button class="button button-secondary" type="button" data-load-more="#meli-home-grid" data-load-more-step="row" data-load-more-initial="2row">Mostrar mais</button>
            </div>
          <?php endif; ?>
        <?php else: ?>
          <div class="empty-state">Sem ofertas do Mercado Livre no momento.</div>
        <?php endif; ?>
      </section>

      <section class="section-panel" id="amazon-alta">
        <div class="section-heading">
          <div>
            <h2>Amazon</h2>
          </div>
          <a class="cta-link" href="/categoria.php?cat=geral&amp;store=Amazon">Ver mais</a>
        </div>

        <?php if ($amazonTrending): ?>
          <div class="grid" id="amazon-home-grid">
            <?php foreach ($amazonTrending as $offer): ?>
              <?php $discount = site_discount_percent($offer['preco'], $offer['preco_antigo']); ?>
              <article class="card" data-load-more-item>
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
                    <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Ver promoção</a>
                  </div>
                </div>
              </article>
            <?php endforeach; ?>
          </div>
          <?php if (count($amazonTrending) > 1): ?>
            <div class="rush-more-wrap">
              <button class="button button-secondary" type="button" data-load-more="#amazon-home-grid" data-load-more-step="row" data-load-more-initial="2row">Mostrar mais</button>
            </div>
          <?php endif; ?>
        <?php else: ?>
          <div class="empty-state">Sem ofertas da Amazon no momento.</div>
        <?php endif; ?>
      </section>

      <?php foreach ($categorySections as $sectionIndex => $section): ?>
        <section class="section-panel">
          <div class="section-heading">
            <div>
              <h2><?= h(site_public_category_label($section['name'])) ?></h2>
            </div>
            <a class="cta-link" href="<?= h(site_category_href($section['name'])) ?>">Ver mais</a>
          </div>

          <div class="grid grid-tight" id="category-home-grid-<?= (int) $sectionIndex ?>">
            <?php foreach ($section['offers'] as $offer): ?>
              <?php $discount = site_discount_percent($offer['preco'], $offer['preco_antigo']); ?>
              <article class="card" data-load-more-item>
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
                    <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Ver promoção</a>
                  </div>
                </div>
              </article>
            <?php endforeach; ?>
          </div>
          <?php if (count($section['offers']) > 1): ?>
            <div class="rush-more-wrap">
              <button class="button button-secondary" type="button" data-load-more="#category-home-grid-<?= (int) $sectionIndex ?>" data-load-more-step="row" data-load-more-initial="row">Mostrar mais</button>
            </div>
          <?php endif; ?>
        </section>
      <?php endforeach; ?>
    </div>
  </main>

  <?php require __DIR__ . '/inc/site_footer.php'; ?>
  <?php require __DIR__ . '/inc/site_footer_scripts.php'; ?>
</body>
</html>





