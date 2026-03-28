<?php
require_once __DIR__ . '/inc/site.php';

$pdo = db();
$data = site_fetch_home_data($pdo);
$heroCarousel = $data['hero_carousel'];
$heroCarouselMode = (string) ($data['hero_carousel_mode'] ?? 'cards');
$heroVideoItems = array_values(array_filter($heroCarousel, static function ($item) {
  return !empty($item['has_video']) && !empty($item['video_url']);
}));
$heroHighlightedVideoItems = array_values(array_filter($heroVideoItems, static function ($item) {
  return !empty($item['destaque']);
}));
$heroTopVideoItems = $heroHighlightedVideoItems ?: $heroVideoItems;
$heroFeaturedVideo = $heroTopVideoItems[0] ?? null;
$heroCarouselItems = $heroCarousel;
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
  <title>Zero Pre&ccedil;o | Comparador moderno com links afiliados</title>
  <meta name="description" content="Sele&ccedil;&atilde;o diaria de ofertas e vitrines por marketplace com acesso rapido ao produto certo.">
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
        <div class="home-conversion-toolbar">
          <span class="eyebrow">Sele&ccedil;&atilde;o do momento</span>
          <div class="cta-row home-conversion-actions">
            <a class="button button-primary" href="/ofertas-do-dia.php">Abrir Ofertas do Dia</a>
            <a class="button button-secondary" href="<?= h($whatsappGroupLink) ?>" target="_blank" rel="noopener noreferrer">Entrar no WhatsApp</a>
          </div>
        </div>
        <?php if ($heroFeaturedVideo): ?>
          <?php
            $heroVideoPlaylist = [];
            foreach ($heroTopVideoItems as $videoItem) {
              $heroVideoPlaylist[] = [
                'title' => (string) $videoItem['titulo'],
                'store' => (string) site_store_label($videoItem['loja']),
                'price' => (string) site_money($videoItem['preco']),
                'old_price' => !empty($videoItem['preco_antigo']) ? (string) site_money($videoItem['preco_antigo']) : '',
                'discount' => site_discount_percent($videoItem['preco'], $videoItem['preco_antigo']),
                'href' => (string) site_offer_redirect_href($videoItem['slug']),
                'poster' => (string) ($videoItem['imagem_url'] ?: '/assets/img/sem-img.png'),
                'video_url' => (string) $videoItem['video_url'],
              ];
            }
            $featuredDiscount = site_discount_percent($heroFeaturedVideo['preco'], $heroFeaturedVideo['preco_antigo']);
          ?>
          <div class="hero-featured-video-shell" data-home-video-player>
            <button class="hero-featured-video-nav hero-featured-video-nav-prev" type="button" data-home-video-prev aria-label="Video anterior" title="Video anterior">
              <span aria-hidden="true">&#10094;</span>
            </button>
            <section class="hero-featured-video">
              <div class="hero-featured-video-media">
                <button class="hero-featured-video-sound" type="button" data-home-video-sound aria-label="Ativar som" title="Ativar som">
                  <span aria-hidden="true" data-home-video-sound-icon>&#128266;</span>
                </button>
                <video
                  controls
                  muted
                  autoplay
                  playsinline
                  preload="metadata"
                  poster="<?= h($heroFeaturedVideo['imagem_url'] ?: '/assets/img/sem-img.png') ?>"
                  data-home-video-element
                >
                  <source src="<?= h((string) $heroFeaturedVideo['video_url']) ?>" type="video/mp4">
                </video>
              </div>
              <div class="hero-featured-video-copy">
                <div class="kicker" data-home-video-store><?= h(site_store_label($heroFeaturedVideo['loja'])) ?></div>
                <h2 data-home-video-title><?= h($heroFeaturedVideo['titulo']) ?></h2>
                <div class="hero-media-price-row">
                  <span class="hero-media-price-now" data-home-video-price><?= h(site_money($heroFeaturedVideo['preco'])) ?></span>
                  <span class="hero-media-price-old<?= empty($heroFeaturedVideo['preco_antigo']) ? ' is-hidden' : '' ?>" data-home-video-old-price><?= !empty($heroFeaturedVideo['preco_antigo']) ? h(site_money($heroFeaturedVideo['preco_antigo'])) : '' ?></span>
                  <span class="coupon-tag<?= $featuredDiscount === null ? ' is-hidden' : '' ?>" data-home-video-discount><?= $featuredDiscount !== null ? '-' . (int) $featuredDiscount . '%' : '' ?></span>
                </div>
                <div class="hero-featured-video-actions">
                  <a class="button button-primary" href="<?= h(site_offer_redirect_href($heroFeaturedVideo['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow" data-home-video-link>Abrir oferta</a>
                </div>
              </div>
            </section>
            <button class="hero-featured-video-nav hero-featured-video-nav-next" type="button" data-home-video-next aria-label="Proximo video" title="Proximo video">
              <span aria-hidden="true">&#10095;</span>
            </button>
            <script type="application/json" data-home-video-playlist><?= json_encode($heroVideoPlaylist, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) ?></script>
          </div>
        <?php endif; ?>
        <?php if ($heroCarouselItems): ?>
          <div class="hero-media-rail">
            <div class="hero-media-track" data-auto-carousel data-auto-carousel-speed="0.7">
              <?php foreach (array_merge($heroCarouselItems, $heroCarouselItems) as $offer): ?>
                <?php $discount = site_discount_percent($offer['preco'], $offer['preco_antigo']); ?>
                <a class="hero-media-card" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">
                  <div class="hero-media-frame">
                    <?php if (!empty($offer['has_video']) && !empty($offer['video_url'])): ?>
                      <video muted autoplay loop playsinline preload="metadata" poster="<?= h($offer['imagem_url'] ?: '/assets/img/sem-img.png') ?>">
                        <source src="<?= h((string) $offer['video_url']) ?>" type="video/mp4">
                      </video>
                      <span class="hero-media-badge">Video Shopee</span>
                    <?php else: ?>
                      <img src="<?= h($offer['imagem_url'] ?: '/assets/img/sem-img.png') ?>" alt="">
                      <span class="hero-media-badge">Oferta em alta</span>
                    <?php endif; ?>
                  </div>
                  <div class="hero-media-body">
                    <div class="kicker"><?= h(site_store_label($offer['loja'])) ?></div>
                    <div class="hero-media-title"><?= h($offer['titulo']) ?></div>
                    <div class="hero-media-price-row">
                      <span class="hero-media-price-now"><?= h(site_money($offer['preco'])) ?></span>
                      <?php if (!empty($offer['preco_antigo'])): ?>
                        <span class="hero-media-price-old"><?= h(site_money($offer['preco_antigo'])) ?></span>
                      <?php endif; ?>
                      <?php if ($discount !== null): ?>
                        <span class="coupon-tag">-<?= $discount ?>%</span>
                      <?php endif; ?>
                    </div>
                  </div>
                </a>
              <?php endforeach; ?>
            </div>
          </div>
        <?php endif; ?>
      </section>

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
                      <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Ver promo&ccedil;&atilde;o</a>
                    </div>
                  </article>
                <?php endforeach; ?>
              </div>
            <?php endforeach; ?>
          </div>
        <?php else: ?>
          <div class="empty-state">Sem publica&ccedil;&otilde;es em redes sociais ainda para montar a sele&ccedil;&atilde;o do dia.</div>
        <?php endif; ?>
      </section>

      <?php if ($dealRush): ?>
        <section class="section-panel" id="giro-rapido">
          <div class="section-heading">
            <div>
              <h2>Giro R&aacute;pido</h2>
            </div>
            <a class="cta-link" href="/ofertas-do-dia.php#ofertas-ate-150">Ver at&eacute; R$ 150</a>
          </div>

          <div class="rush-grid" id="giro-rapido-grid">
            <?php foreach ($dealRush as $offer): ?>
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
                    <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Ver promo&ccedil;&atilde;o</a>
                  </div>
                </div>
              </article>
            <?php endforeach; ?>
          </div>

          <?php if (count($dealRush) > 4): ?>
            <div class="rush-more-wrap">
              <button class="button button-secondary" type="button" data-load-more="#giro-rapido-grid" data-load-more-step="row" data-load-more-initial="row">Mostrar mais</button>
            </div>
          <?php endif; ?>
        </section>
      <?php endif; ?>

      <section class="whatsapp-banner">
        <div class="whatsapp-banner-copy">
          <span class="whatsapp-banner-kicker">Canal direto</span>
          <h2>Receba ofertas no WhatsApp</h2>
          <p>Entre no <?= h($whatsappGroupLabel) ?> para receber promo&ccedil;&otilde;es com mais chance de giro e abrir o link da oferta sem ficar procurando no site inteiro.</p>
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
                    <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Ver promo&ccedil;&atilde;o</a>
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
                    <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Ver promo&ccedil;&atilde;o</a>
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
                    <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Ver promo&ccedil;&atilde;o</a>
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
                    <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Ver promo&ccedil;&atilde;o</a>
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
