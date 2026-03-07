<?php
require_once __DIR__ . '/inc/site.php';

$pdo = db();
$data = site_fetch_home_data($pdo);
$featuredOffers = $data['featured'];
$latestOffers = $data['latest'];
$topClickedOffers = $data['top_clicked'];
$couponOffers = $data['coupon_offers'];
$meliTrending = $data['meli_trending'];
$categorySections = $data['sections_by_category'];
$storeRows = $data['store_rows'];
$filters = $data['filters'];

?>
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Zero Preço | Comparador moderno com links afiliados</title>
  <meta name="description" content="Melhores ofertas do dia, top produtos, Mercado Livre em alta e cupons de desconto em uma vitrine limpa e direta.">
  <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-8314124298799437" crossorigin="anonymous"></script>
  <script async src="https://www.googletagmanager.com/gtag/js?id=AW-975222683"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){dataLayer.push(arguments);}
    gtag('js', new Date());
    gtag('config', 'AW-975222683');
  </script>
  <link rel="stylesheet" href="/assets/css/style.css">
</head>
<body>
  <div class="topbar">
    <div class="container topbar-row">
      <div>Ofertas do dia, cupons e destaques para comprar rápido.</div>
      <div class="hidden-mobile">Mercado Livre, Shopee, Amazon e TikTok Shop.</div>
    </div>
  </div>

  <header class="main-header">
    <div class="container">
      <div class="main-nav">
        <a class="brand" href="/">
          <span class="brand-badge">ZP</span>
          <span class="brand-copy">
            <strong>Zero Preço</strong>
            <span>Achados reais, sem enrolação</span>
          </span>
        </a>

        <button class="mobile-toggle" type="button" aria-label="Abrir menu" aria-expanded="false" data-menu-toggle>
          <span class="mobile-toggle-line" aria-hidden="true"></span>
        </button>

        <nav class="nav-links">
          <a class="pill" href="#selecao-dia">Seleção do dia</a>
          <a class="pill" href="#mais-vendidos">Top produtos</a>
          <a class="pill" href="#premium-destaque">Premium</a>
          <a class="pill" href="#mercado-livre-alta">Mercado Livre</a>
          <a class="pill" href="#cupons-dia">Cupons</a>
        </nav>

        <div class="mobile-panel" data-mobile-panel>
          <a class="pill" href="#selecao-dia">Seleção do dia</a>
          <a class="pill" href="#mais-vendidos">Top produtos</a>
          <a class="pill" href="#premium-destaque">Premium</a>
          <a class="pill" href="#mercado-livre-alta">Mercado Livre</a>
          <a class="pill" href="#cupons-dia">Cupons</a>
          <a class="button button-primary" href="/categoria.php?cat=geral">Ver catálogo</a>
        </div>
      </div>
    </div>
  </header>

  <main class="page-shell">
    <div class="container">
      <section class="affiliate-note" aria-label="Aviso de afiliados">
        <div class="affiliate-note-badge">Aviso</div>
        <div class="affiliate-note-copy">
          O Zero Preço pode receber comissão por parte dos links exibidos no site. Isso não altera o valor pago pelo usuário.
        </div>
        <a class="affiliate-note-link" href="/privacidade">Saiba mais</a>
      </section>

      <section class="section-panel" id="selecao-dia">
        <div class="best-offers-grid">
          <div class="best-offers-main">
            <span class="eyebrow">Seleção do dia</span>
            <h2>Ofertas grandes para quem quer comprar agora.</h2>
            <p>Aqui ficam as oportunidades mais fortes do dia, com linguagem simples, cupom em destaque e desconto fácil de entender.</p>
            <div class="cta-row" style="justify-content:flex-start; flex-wrap:wrap; margin-top:22px;">
              <a class="button button-primary" href="#cupons-dia">Ver cupons do dia</a>
              <a class="button button-secondary" href="#mercado-livre-alta">Ver Mercado Livre em alta</a>
            </div>
          </div>

          <div class="best-offers-side">
            <?php foreach (array_slice($couponOffers ?: $meliTrending, 0, 3) as $offer): ?>
              <article class="offer-spotlight">
                <img src="<?= h($offer['imagem_url'] ?: '/assets/img/sem-img.png') ?>" alt="">
                <div>
                  <div class="kicker"><?= h(site_store_label($offer['loja'])) ?></div>
                  <div style="font-weight:800; margin:8px 0; color:#0a2a67;"><?= h($offer['titulo']) ?></div>
                  <div class="price-row" style="margin-bottom:8px;">
                    <span class="price-now"><?= h(site_money($offer['preco'])) ?></span>
                    <?php if (!empty($offer['cupom'])): ?>
                      <span class="coupon-tag">Cupom <?= h($offer['cupom']) ?></span>
                    <?php elseif (!empty($offer['preco_antigo'])): ?>
                      <span class="coupon-tag">-<?= site_discount_percent($offer['preco'], $offer['preco_antigo']) ?>%</span>
                    <?php endif; ?>
                  </div>
                  <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Ver oferta na loja</a>
                </div>
              </article>
            <?php endforeach; ?>
          </div>
        </div>
      </section>

      <section class="section-panel" id="mais-vendidos">
        <div class="section-heading">
          <div>
            <h2>Top produtos e mais clicados</h2>
            <div class="section-copy">Ranking para mostrar o que está chamando mais atenção e gerando mais interesse no site.</div>
          </div>
          <a class="cta-link" href="/categoria.php?cat=geral">Ver catálogo completo</a>
        </div>

        <?php if ($topClickedOffers): ?>
          <div class="split-grid">
            <div class="list-board">
              <?php foreach ($topClickedOffers as $index => $offer): ?>
                <a class="list-card" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">
                  <div class="list-rank"><?= $index + 1 ?></div>
                  <div>
                    <div class="kicker"><?= h(site_store_label($offer['loja'])) ?> &bull; <?= h(site_category_label($offer['categoria'])) ?></div>
                    <div style="font-weight:800; color:#10213a; margin:6px 0;"><?= h($offer['titulo']) ?></div>
                    <div class="meta-row">
                      <span class="meta-chip"><?= h(site_money($offer['preco'])) ?></span>
                      <?php if (!empty($offer['clicks'])): ?>
                        <span class="meta-chip"><?= (int) $offer['clicks'] ?> cliques</span>
                      <?php endif; ?>
                    </div>
                  </div>
                  <span class="btn-link primary">Ver preço na loja</span>
                </a>
              <?php endforeach; ?>
            </div>

            <div class="grid grid-tight">
              <?php foreach (array_slice($latestOffers, 0, 4) as $offer): ?>
                <?php $discount = site_discount_percent($offer['preco'], $offer['preco_antigo']); ?>
                <article class="card">
                  <a class="card-media" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">
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
                    <div class="kicker"><?= h(site_store_label($offer['loja'])) ?></div>
                    <div class="card-title"><?= h($offer['titulo']) ?></div>
                    <div class="price-row">
                      <span class="price-now"><?= h(site_money($offer['preco'])) ?></span>
                      <?php if (!empty($offer['preco_antigo'])): ?>
                        <span class="price-old"><?= h(site_money($offer['preco_antigo'])) ?></span>
                      <?php endif; ?>
                    </div>
                    <div class="card-footer">
                      <span class="meta-chip"><?= h(site_category_label($offer['categoria'])) ?></span>
                      <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Ver preço na loja</a>
                    </div>
                  </div>
                </article>
              <?php endforeach; ?>
            </div>
          </div>
        <?php else: ?>
          <div class="empty-state">Sem ofertas ainda para montar o ranking.</div>
        <?php endif; ?>
      </section>

      <?php if ($featuredOffers): ?>
        <section class="section-panel" id="premium-destaque">
          <div class="section-heading">
            <div>
              <h2>Seleção premium em destaque</h2>
              <div class="section-copy">Produtos que merecem mais visibilidade e empurram a compra com mais força.</div>
            </div>
          </div>

          <div class="grid">
            <?php foreach ($featuredOffers as $offer): ?>
              <?php $discount = site_discount_percent($offer['preco'], $offer['preco_antigo']); ?>
              <article class="card">
                <a class="card-media" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">
                  <img src="<?= h($offer['imagem_url'] ?: '/assets/img/sem-img.png') ?>" alt="">
                  <div class="card-badges">
                    <span class="flag flag-top">Premium</span>
                    <?php if ($discount !== null): ?>
                      <span class="flag flag-sale">-<?= $discount ?>%</span>
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
                  <div class="offer-meta-row">
                    <?php if (!empty($offer['cupom'])): ?>
                      <span class="meta-chip">Cupom <?= h($offer['cupom']) ?></span>
                    <?php endif; ?>
                    <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Comprar na loja</a>
                  </div>
                </div>
              </article>
            <?php endforeach; ?>
          </div>
        </section>
      <?php endif; ?>

      <section class="section-panel" id="mercado-livre-alta">
        <div class="section-heading">
          <div>
            <h2>Mercado Livre em alta agora</h2>
            <div class="section-copy">Produtos do Mercado Livre com visual direto e pronto para navegar mais no site.</div>
          </div>
        </div>

        <?php if ($meliTrending): ?>
          <div class="grid">
            <?php foreach ($meliTrending as $offer): ?>
              <?php $discount = site_discount_percent($offer['preco'], $offer['preco_antigo']); ?>
              <article class="card">
                <a class="card-media" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">
                  <img src="<?= h($offer['imagem_url'] ?: '/assets/img/sem-img.png') ?>" alt="">
                  <div class="card-badges">
                    <span class="flag flag-dark">ML em alta</span>
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
                  <div class="card-footer">
                    <span class="meta-chip">Compra em alta</span>
                    <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Comprar na loja</a>
                  </div>
                </div>
              </article>
            <?php endforeach; ?>
          </div>
        <?php endif; ?>
      </section>

      <section class="section-panel" id="cupons-dia">
        <div class="section-heading">
          <div>
            <h2>Cupons do dia e descontos quentes</h2>
            <div class="section-copy">Cupom e desconto continuam como bloco forte porque o pessoal realmente compra por isso.</div>
          </div>
        </div>

        <div class="coupon-grid">
          <div class="coupon-board">
            <article class="coupon-feature">
              <strong>Cupons do dia</strong>
              <div class="coupon-big">CUPOM</div>
              <div class="coupon-note">Quando a oferta tiver cupom salvo no banco, ele aparece em destaque. Se não tiver, o sistema usa o desconto real do preço antigo.</div>
            </article>
          </div>

          <div class="coupon-list">
            <?php if ($couponOffers): ?>
              <?php foreach ($couponOffers as $offer): ?>
                <article class="coupon-item">
                  <img src="<?= h($offer['imagem_url'] ?: '/assets/img/sem-img.png') ?>" alt="">
                  <div>
                    <div class="kicker"><?= h(site_store_label($offer['loja'])) ?></div>
                    <div style="font-weight:800; color:#0a2a67; margin:8px 0;"><?= h($offer['titulo']) ?></div>
                    <div class="price-row" style="margin-bottom:0;">
                      <span class="price-now"><?= h(site_money($offer['preco'])) ?></span>
                      <span class="coupon-tag">Cupom <?= h($offer['cupom']) ?></span>
                    </div>
                  </div>
                  <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Usar cupom</a>
                </article>
              <?php endforeach; ?>
            <?php else: ?>
              <?php foreach (array_slice($meliTrending, 0, 4) as $offer): ?>
                <?php $discount = site_discount_percent($offer['preco'], $offer['preco_antigo']); ?>
                <article class="coupon-item">
                  <img src="<?= h($offer['imagem_url'] ?: '/assets/img/sem-img.png') ?>" alt="">
                  <div>
                    <div class="kicker">Mercado Livre</div>
                    <div style="font-weight:800; color:#0a2a67; margin:8px 0;"><?= h($offer['titulo']) ?></div>
                    <div class="price-row" style="margin-bottom:0;">
                      <span class="price-now"><?= h(site_money($offer['preco'])) ?></span>
                      <span class="coupon-tag"><?= $discount !== null ? '-' . $discount . '%' : 'Desconto do dia' ?></span>
                    </div>
                  </div>
                  <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Ver oferta</a>
                </article>
              <?php endforeach; ?>
            <?php endif; ?>
          </div>
        </div>
      </section>

      <?php foreach ($categorySections as $section): ?>
        <section class="section-panel">
          <div class="section-heading">
            <div>
              <h2><?= h(site_category_label($section['name'])) ?></h2>
              <div class="section-copy"><?= (int) $section['total'] ?> ofertas nessa linha.</div>
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
                  <div class="card-footer">
                    <span class="meta-chip"><?= !empty($offer['cupom']) ? 'Cupom ' . h($offer['cupom']) : h(site_category_label($offer['categoria'])) ?></span>
                    <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Ver preço na loja</a>
                  </div>
                </div>
              </article>
            <?php endforeach; ?>
          </div>
        </section>
      <?php endforeach; ?>

      <section class="section-panel">
        <div class="section-heading">
          <div>
            <h2>Radar por loja</h2>
            <div class="section-copy">Leitura rápida do peso de cada marketplace dentro da vitrine.</div>
          </div>
        </div>
        <div class="filters">
          <?php foreach ($storeRows as $store): ?>
            <span class="menu-chip"><?= h(site_store_label($store['loja'])) ?> <strong><?= (int) $store['total'] ?> ofertas</strong></span>
          <?php endforeach; ?>
        </div>
      </section>
    </div>
  </main>

  <footer class="footer-shell">
    <div class="container">
      <div class="footer-card">
        <div class="footer-grid">
          <div>
            <h3>Zero Preço</h3>
            <p class="section-copy">Vitrine limpa, forte e feita para destacar ofertas, cupom e clique rápido.</p>
          </div>
          <div>
            <h3>Navegação</h3>
            <div class="footer-links">
              <a href="/">Home</a>
              <a href="/categoria.php?cat=geral">Catálogo</a>
              <a href="/sobre">Sobre</a>
              <a href="/contato">Contato</a>
              <a href="/privacidade">Privacidade</a>
              <a href="/termos">Termos</a>
            </div>
          </div>
          <div>
            <h3>Transparência</h3>
            <p class="section-copy">Parte dos links exibidos no site é de afiliados. O Zero Preço pode receber comissão sem custo adicional para o usuário.</p>
          </div>
        </div>
      </div>
    </div>
  </footer>

  <script>
    (function () {
      var links = document.querySelectorAll('a[href*="go=1"]');
      if (!links.length || typeof window.gtag !== 'function') return;

      links.forEach(function (link) {
        link.addEventListener('click', function () {
          var scope = link.closest('article, .list-card, .detail-panel') || document;
          var titleNode = scope.querySelector('h1, .card-title');
          var storeNode = scope.querySelector('.kicker');
          var label = titleNode ? titleNode.textContent.trim() : link.textContent.trim();
          var store = storeNode ? storeNode.textContent.trim() : '';
          var href = link.getAttribute('href') || '';

          gtag('event', 'click_out', {
            event_category: 'affiliate',
            event_label: label || href,
            affiliate_store: store,
            affiliate_target: href,
            page_path: window.location.pathname,
            transport_type: 'beacon'
          });

          gtag('event', 'conversion', {
            send_to: 'AW-975222683/41lzCO6H2M4ZEJvvgtED',
            transaction_id: ''
          });

          window.dataLayer = window.dataLayer || [];
          window.dataLayer.push({
            event: 'click_out',
            click_out_label: label || href,
            click_out_store: store,
            click_out_target: href,
            click_out_path: window.location.pathname
          });
        });
      });
    }());

    document.querySelectorAll('.nav-links a[href^="#"], .mobile-panel a[href^="#"]').forEach(function (anchor) {
      anchor.addEventListener('click', function () {
        window.setTimeout(function () {
          anchor.blur();
        }, 0);
      });
    });

    (function () {
      var panel = document.querySelector('[data-mobile-panel]');
      var toggles = document.querySelectorAll('[data-menu-toggle]');
      if (!panel || !toggles.length) return;

      toggles.forEach(function (toggle) {
        toggle.addEventListener('click', function () {
          var isOpen = panel.classList.toggle('is-open');
          toggles.forEach(function (button) {
            button.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
          });
        });
      });

      panel.querySelectorAll('a').forEach(function (link) {
        link.addEventListener('click', function () {
          panel.classList.remove('is-open');
          toggles.forEach(function (button) {
            button.setAttribute('aria-expanded', 'false');
          });
        });
      });
    }());
  </script>
</body>
</html>
