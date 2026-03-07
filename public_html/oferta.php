<?php
require_once __DIR__ . '/inc/site.php';

$slug = $_GET['slug'] ?? '';
$pdo = db();

$stmt = $pdo->prepare("SELECT * FROM ofertas WHERE slug=? AND ativo=1 LIMIT 1");
$stmt->execute([$slug]);
$offer = $stmt->fetch();

if (!$offer) {
  http_response_code(404);
  exit('Oferta não encontrada');
}

if (isset($_GET['go']) && $_GET['go'] === '1') {
  $pdo->prepare("INSERT INTO cliques (oferta_id, ip_hash, user_agent, referer) VALUES (?,?,?,?)")
      ->execute([
        $offer['id'],
        ip_hash(),
        substr($_SERVER['HTTP_USER_AGENT'] ?? '', 0, 255),
        $_SERVER['HTTP_REFERER'] ?? null,
      ]);

  header("Location: " . $offer['url_afiliado']);
  exit;
}

$relatedOffers = site_fetch_related_offers($pdo, $offer, 4);
$discount = site_discount_percent($offer['preco'], $offer['preco_antigo']);
$soldCount = site_extract_sold_count($offer['tags'] ?? '');
?>
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title><?= h($offer['titulo']) ?> | Zero Preço</title>
  <meta name="description" content="<?= h($offer['titulo']) ?> por <?= h(site_money($offer['preco'])) ?> com link direto para a loja.">
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
      <div>Página de detalhe feita para tirar objeções e empurrar o clique no botão principal.</div>
      <div class="hidden-mobile">Ao clicar em "ir para a loja", o sistema registra o clique e redireciona para o link salvo.</div>
    </div>
  </div>

  <header class="main-header">
    <div class="container">
      <div class="main-nav">
        <a class="brand" href="/">
          <span class="brand-badge">ZP</span>
          <span class="brand-copy">
            <strong>Oferta selecionada</strong>
            <span><?= h(site_store_label($offer['loja'])) ?> &bull; <?= h(site_category_label($offer['categoria'])) ?></span>
          </span>
        </a>

        <button class="mobile-toggle" type="button" aria-label="Abrir menu" aria-expanded="false" data-menu-toggle>
          <span class="mobile-toggle-line" aria-hidden="true"></span>
        </button>

        <nav class="nav-links">
          <a class="pill" href="/">Home</a>
          <a class="pill" href="<?= h(site_category_href($offer['categoria'])) ?>">Categoria</a>
          <a class="pill" href="/categoria/geral">Catálogo</a>
        </nav>

        <div class="mobile-panel" data-mobile-panel>
          <a class="pill" href="/">Home</a>
          <a class="pill" href="<?= h(site_category_href($offer['categoria'])) ?>">Categoria</a>
          <a class="pill" href="/categoria/geral">Catálogo</a>
          <a class="button button-primary" href="?slug=<?= urlencode($offer['slug']) ?>&go=1" target="_blank" rel="noopener sponsored nofollow">Comprar na loja oficial</a>
        </div>
      </div>
    </div>
  </header>

  <main class="page-shell" style="padding-top:28px;">
    <div class="container">
      <section class="detail-panel">
        <div class="breadcrumbs">
          <a href="/">Home</a>
          <span>/</span>
          <a href="<?= h(site_category_href($offer['categoria'])) ?>"><?= h(site_category_label($offer['categoria'])) ?></a>
          <span>/</span>
          <span><?= h(site_store_label($offer['loja'])) ?></span>
        </div>

        <div class="detail-grid">
          <div class="detail-media">
            <img src="<?= h($offer['imagem_url'] ?: '/assets/img/sem-img.png') ?>" alt="">
          </div>

          <div class="detail-copy">
            <div class="kicker"><?= h(site_store_label($offer['loja'])) ?> &bull; Oferta com clique rastreado</div>
            <h1><?= h($offer['titulo']) ?></h1>
            <p><?= h($offer['descricao'] ?: 'Produto pronto para divulgação com página de detalhe, preço visível e redirecionamento para a loja.') ?></p>

            <div class="detail-price">
              <div class="price-row">
                <span class="price-now"><?= h(site_money($offer['preco'])) ?></span>
                <?php if (!empty($offer['preco_antigo'])): ?>
                  <span class="price-old"><?= h(site_money($offer['preco_antigo'])) ?></span>
                <?php endif; ?>
                <?php if ($discount !== null): ?>
                  <span class="flag flag-sale">-<?= $discount ?>%</span>
                <?php endif; ?>
              </div>
            </div>

            <div class="detail-stats">
              <div class="detail-stat">
                <strong><?= h(site_store_label($offer['loja'])) ?></strong>
                <span>Marketplace</span>
              </div>
              <div class="detail-stat">
                <strong><?= h(site_category_label($offer['categoria'])) ?></strong>
                <span>Tipo de produto</span>
              </div>
              <?php if (!empty($offer['cupom'])): ?>
                <div class="detail-stat">
                  <strong><?= h($offer['cupom']) ?></strong>
                  <span>Cupom ativo</span>
                </div>
              <?php endif; ?>
              <?php if ($soldCount > 0): ?>
                <div class="detail-stat">
                  <strong><?= (int) $soldCount ?></strong>
                  <span>Vendidos capturados</span>
                </div>
              <?php endif; ?>
            </div>

            <div class="cta-row" style="justify-content:flex-start; flex-wrap:wrap;">
              <a class="button button-primary" href="?slug=<?= urlencode($offer['slug']) ?>&go=1" target="_blank" rel="noopener sponsored nofollow">Comprar na loja oficial</a>
              <a class="button button-secondary" href="<?= h(site_category_href($offer['categoria'])) ?>">Ver categoria</a>
            </div>

            <div class="detail-note">
              O botão principal abre o produto usando o valor salvo em <strong>url_afiliado</strong>.
              Quando esse campo contém seu link afiliado, o clique segue monetizável.
            </div>

            <div class="filters" style="margin-top:22px;">
              <div class="filters-label">Marcações desta oferta</div>
              <span class="menu-chip"><?= h(site_store_label($offer['loja'])) ?></span>
              <span class="menu-chip"><?= h(site_category_label($offer['categoria'])) ?></span>
              <?php foreach (site_tags_to_list($offer['tags'] ?? '') as $tag): ?>
                <span class="menu-chip"><?= h($tag) ?></span>
              <?php endforeach; ?>
            </div>
          </div>
        </div>
      </section>

      <?php if ($relatedOffers): ?>
        <section class="section-panel">
          <div class="section-heading">
            <div>
              <h2>Produtos relacionados</h2>
              <div class="section-copy">Mais opções da mesma categoria ou da mesma loja para aumentar navegação e profundidade da sessão.</div>
            </div>
          </div>

          <div class="grid grid-tight">
            <?php foreach ($relatedOffers as $related): ?>
              <?php $relatedDiscount = site_discount_percent($related['preco'], $related['preco_antigo']); ?>
              <article class="card">
                <a class="card-media" href="<?= h(site_offer_redirect_href($related['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">
                  <img src="<?= h($related['imagem_url'] ?: '/assets/img/sem-img.png') ?>" alt="">
                  <div class="card-badges">
                    <?php if ($relatedDiscount !== null): ?>
                      <span class="flag flag-sale">-<?= $relatedDiscount ?>%</span>
                    <?php endif; ?>
                  </div>
                </a>
                <div class="card-body">
                  <div class="kicker"><?= h(site_store_label($related['loja'])) ?></div>
                  <div class="card-title"><?= h($related['titulo']) ?></div>
                  <div class="price-row">
                    <span class="price-now"><?= h(site_money($related['preco'])) ?></span>
                  </div>
                  <div class="card-footer">
                    <span class="meta-chip"><?= h(site_category_label($related['categoria'])) ?></span>
                    <a class="btn-link primary" href="<?= h(site_offer_redirect_href($related['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Ver preço na loja</a>
                  </div>
                </div>
              </article>
            <?php endforeach; ?>
          </div>
        </section>
      <?php endif; ?>

      <section class="section-panel">
        <div class="section-heading">
          <div>
            <h2>Informações importantes</h2>
            <div class="section-copy">O Zero Preço organiza ofertas e redireciona para lojas parceiras. A condição final de compra deve ser conferida na página oficial do produto.</div>
          </div>
        </div>
        <div class="filters">
          <a class="menu-chip" href="/sobre">Sobre</a>
          <a class="menu-chip" href="/contato">Contato</a>
          <a class="menu-chip" href="/privacidade">Privacidade</a>
          <a class="menu-chip" href="/termos">Termos</a>
        </div>
      </section>
    </div>
  </main>

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
