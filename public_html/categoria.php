<?php
require_once __DIR__ . '/inc/site.php';

$category = $_GET['cat'] ?? 'geral';
$pdo = db();
$data = site_fetch_category_data($pdo, $category);
$offers = $data['offers'];
$stores = $data['stores'];
$filters = $data['filters'];
$categoryLabel = site_category_label($category);
?>
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title><?= h($categoryLabel) ?> | Zero Preço</title>
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
      <div>Catálogo filtrado por categoria, pronto para SEO, anúncios e tráfego de redes sociais.</div>
      <div class="hidden-mobile"><?= count($offers) ?> ofertas disponíveis nesta seleção.</div>
    </div>
  </div>

  <header class="main-header">
    <div class="container">
      <div class="main-nav">
        <a class="brand" href="/">
          <span class="brand-badge">ZP</span>
          <span class="brand-copy">
            <strong><?= h($categoryLabel) ?></strong>
            <span>Curadoria visual por categoria</span>
          </span>
        </a>

        <button class="mobile-toggle" type="button" aria-label="Abrir menu" aria-expanded="false" data-menu-toggle>
          <span class="mobile-toggle-line" aria-hidden="true"></span>
        </button>

        <nav class="nav-links">
          <a class="pill" href="/">Home</a>
          <a class="pill" href="/categoria/geral">Todas as ofertas</a>
          <a class="pill" href="/admin/index.php">Painel</a>
        </nav>

        <div class="mobile-panel" data-mobile-panel>
          <a class="pill" href="/">Home</a>
          <a class="pill" href="/categoria/geral">Todas as ofertas</a>
          <a class="pill" href="/admin/index.php">Painel</a>
          <a class="button button-primary" href="#produtos">Ver produtos</a>
        </div>
      </div>

      <div class="subnav-wrap">
        <div class="subnav">
          <span class="subnav-title">Submenus</span>
          <?php foreach ($filters['categories'] as $cat): ?>
            <a class="badge" href="<?= h(site_category_href($cat['categoria'])) ?>"><?= h(site_category_label($cat['categoria'])) ?></a>
          <?php endforeach; ?>
        </div>
      </div>
    </div>
  </header>

  <section class="hero">
    <div class="container hero-grid">
      <article class="hero-main">
        <span class="eyebrow">Categoria ativa</span>
        <h1><?= h($categoryLabel) ?></h1>
        <p>
          Página com foco em navegação rápida, descoberta por tipo de produto e acesso direto ao detalhe da oferta.
          Ideal para links em bio, campanhas e conteúdo curto.
        </p>
        <div class="stats-grid">
          <div class="stats-card">
            <strong><?= count($offers) ?></strong>
            <span>produtos listados agora</span>
          </div>
          <div class="stats-card">
            <strong><?= count($stores) ?></strong>
            <span>lojas presentes nesta categoria</span>
          </div>
          <div class="stats-card">
            <strong><?= count($filters['categories']) ?></strong>
            <span>submenus disponíveis</span>
          </div>
        </div>
      </article>

      <aside class="hero-side">
        <div class="section-heading" style="margin-bottom:12px;">
          <div>
            <h2 style="color:#edf3ff; font-size:24px;">Lojas por categoria</h2>
            <div class="section-copy">Distribuição atual dos produtos ativos.</div>
          </div>
        </div>

        <div class="filters">
          <?php foreach ($stores as $store): ?>
            <span class="badge"><?= h(site_store_label($store['loja'])) ?> &bull; <?= (int) $store['total'] ?></span>
          <?php endforeach; ?>
        </div>
      </aside>
    </div>
  </section>

  <main class="page-shell">
    <div class="container">
      <section class="surface">
        <div class="section-heading">
          <div>
            <h2>Explorar por categoria</h2>
            <div class="section-copy">Menus e submenus prontos para expandir sua vitrine conforme novas APIs e novos tipos de produtos entrarem.</div>
          </div>
        </div>

        <div class="filters">
          <div class="filters-label">Atalhos principais</div>
          <a class="menu-chip" href="/categoria/geral">Todas as categorias</a>
          <?php foreach ($filters['categories'] as $cat): ?>
            <a class="menu-chip" href="<?= h(site_category_href($cat['categoria'])) ?>"><?= h(site_category_label($cat['categoria'])) ?> <strong><?= (int) $cat['total'] ?></strong></a>
          <?php endforeach; ?>
        </div>
      </section>

      <section class="section-panel" id="produtos">
        <div class="section-heading">
          <div>
            <h2>Produtos em <?= h($categoryLabel) ?></h2>
            <div class="section-copy">Cards redesenhados para valor, desconto, cupom e clique direto no produto.</div>
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
                  <div class="offer-meta-row">
                    <?php if (!empty($offer['cupom'])): ?>
                      <span class="meta-chip">Cupom <?= h($offer['cupom']) ?></span>
                    <?php endif; ?>
                    <span class="meta-chip"><?= h(site_category_label($offer['categoria'])) ?></span>
                  </div>
                  <div class="card-footer">
                    <span class="meta"><?= h(site_store_label($offer['loja'])) ?></span>
                    <a class="btn-link primary" href="<?= h(site_offer_redirect_href($offer['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Ver preço na loja</a>
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

  <footer class="footer-shell">
    <div class="container">
      <div class="footer-card">
        <div class="footer-grid">
          <div>
            <h3>Categoria atual</h3>
            <p class="section-copy">Use esta página como destino de anúncios, links em bio ou menus do próprio site.</p>
          </div>
          <div>
            <h3>Navegar</h3>
            <div class="footer-links">
              <a href="/">Home</a>
              <a href="/categoria/geral">Catálogo completo</a>
              <a href="/sobre">Sobre</a>
              <a href="/contato">Contato</a>
              <a href="/privacidade">Privacidade</a>
              <a href="/termos">Termos</a>
            </div>
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
