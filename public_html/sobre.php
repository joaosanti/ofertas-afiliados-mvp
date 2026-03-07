<?php
require_once __DIR__ . '/inc/site.php';
?>
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Sobre | Zero Preço</title>
  <meta name="description" content="Saiba como o Zero Preço organiza ofertas, cupons e links afiliados para facilitar sua decisão de compra.">
  <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-8314124298799437" crossorigin="anonymous"></script>
  <link rel="stylesheet" href="/assets/css/style.css">
</head>
<body>
  <div class="topbar">
    <div class="container topbar-row">
      <div>Informações sobre o Zero Preço e como o site funciona.</div>
      <div class="hidden-mobile">Transparência, curadoria e links afiliados.</div>
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
          <a class="pill" href="/">Home</a>
          <a class="pill" href="/categoria/geral">Catálogo</a>
          <a class="pill" href="/privacidade">Privacidade</a>
          <a class="pill" href="/contato">Contato</a>
        </nav>

        <div class="mobile-panel" data-mobile-panel>
          <a class="pill" href="/">Home</a>
          <a class="pill" href="/categoria/geral">Catálogo</a>
          <a class="pill" href="/privacidade">Privacidade</a>
          <a class="pill" href="/contato">Contato</a>
        </div>
      </div>
    </div>
  </header>

  <main class="page-shell" style="padding-top:28px;">
    <div class="container">
      <section class="section-panel">
        <div class="section-heading">
          <div>
            <h1 style="margin:0; color:#0a2a67;">Sobre o Zero Preço</h1>
            <div class="section-copy">O Zero Preço é uma vitrine de ofertas criada para organizar produtos, descontos e cupons em uma experiência simples e rápida.</div>
          </div>
        </div>

        <div class="grid">
          <article class="card">
            <div class="card-body">
              <div class="card-title">Como o site funciona</div>
              <p class="section-copy">Nós reunimos ofertas de diferentes marketplaces, mostramos o preço atual, desconto e eventuais cupons, e levamos o usuário para a loja oficial do produto quando ele decide comprar.</p>
            </div>
          </article>

          <article class="card">
            <div class="card-body">
              <div class="card-title">Modelo de monetização</div>
              <p class="section-copy">Parte dos links exibidos no site é de afiliados. Isso significa que o Zero Preço pode receber comissão quando uma compra é realizada a partir desses links, sem custo adicional para o usuário.</p>
            </div>
          </article>

          <article class="card">
            <div class="card-body">
              <div class="card-title">Compromisso editorial</div>
              <p class="section-copy">Nosso foco é destacar oportunidades relevantes e facilitar a comparação inicial. Preços, estoque, frete e condições finais são sempre confirmados na página oficial da loja parceira.</p>
            </div>
          </article>
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
            <p class="section-copy">Site independente de curadoria de ofertas com links afiliados e foco em navegação simples.</p>
          </div>
          <div>
            <h3>Institucional</h3>
            <div class="footer-links">
              <a href="/sobre">Sobre</a>
              <a href="/contato">Contato</a>
              <a href="/privacidade">Privacidade</a>
              <a href="/termos">Termos</a>
            </div>
          </div>
          <div>
            <h3>Aviso</h3>
            <p class="section-copy">Preços e disponibilidade podem mudar sem aviso. Sempre confira a condição final na loja oficial.</p>
          </div>
        </div>
      </div>
    </div>
  </footer>

  <script>
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
    }());
  </script>
</body>
</html>
