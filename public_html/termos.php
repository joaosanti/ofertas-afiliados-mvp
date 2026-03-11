<?php
require_once __DIR__ . '/inc/site.php';
$siteLogoWebPath = '/assets/img/logo-zp.png';
$siteLogoFilePath = __DIR__ . '/assets/img/logo-zp.png';
$siteHasLogo = is_file($siteLogoFilePath);
?>
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Termos de Uso | Zero Preço</title>
  <meta name="description" content="Termos de uso do Zero Preço para navegação, conteúdo e redirecionamento para lojas parceiras.">
  <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-8314124298799437" crossorigin="anonymous"></script>
  <link rel="stylesheet" href="/assets/css/style.css">
</head>
<body>
  <div class="topbar">
    <div class="container topbar-row">
      <div>Termos de Uso do Zero Preço.</div>
      <div class="hidden-mobile">Condições gerais para uso do site.</div>
    </div>
  </div>

  <header class="main-header">
    <div class="container">
      <div class="main-nav">
        <a class="brand" href="/">
          <?php if ($siteHasLogo): ?>
            <span class="brand-media">
              <img class="brand-logo" src="<?= h($siteLogoWebPath) ?>" alt="Zero Preco">
            </span>
          <?php else: ?>
            <span class="brand-badge">ZP</span>
          <?php endif; ?>
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
          <a class="pill" href="/sobre">Sobre</a>
          <a class="pill" href="/contato">Contato</a>
          <a class="pill" href="/privacidade">Privacidade</a>
        </nav>

        <div class="mobile-panel" data-mobile-panel>
          <a class="pill" href="/">Home</a>
          <a class="pill" href="/sobre">Sobre</a>
          <a class="pill" href="/contato">Contato</a>
          <a class="pill" href="/privacidade">Privacidade</a>
        </div>
      </div>
    </div>
  </header>

  <main class="page-shell" style="padding-top:28px;">
    <div class="container">
      <section class="section-panel">
        <div class="section-heading">
          <div>
            <h1 style="margin:0; color:#0a2a67;">Termos de Uso</h1>
            <div class="section-copy">Ao navegar no Zero Preço, o usuário concorda com os termos abaixo.</div>
          </div>
        </div>

        <div class="surface">
          <h2 style="margin-top:0; color:#0a2a67;">1. Natureza do serviço</h2>
          <p class="section-copy">O Zero Preço é um site de curadoria e divulgação de ofertas. Não realiza venda direta, não processa pagamento e não intermedeia entrega, troca ou garantia.</p>

          <h2 style="color:#0a2a67;">2. Informações sobre produtos</h2>
          <p class="section-copy">Os preços, disponibilidade, frete, parcelamento e demais condições podem mudar a qualquer momento. A confirmação final sempre ocorre na loja parceira.</p>

          <h2 style="color:#0a2a67;">3. Responsabilidade sobre compras</h2>
          <p class="section-copy">Toda compra realizada após redirecionamento é de responsabilidade da loja parceira e do usuário comprador, conforme as regras dessa plataforma.</p>

          <h2 style="color:#0a2a67;">4. Links de afiliados e publicidade</h2>
          <p class="section-copy">O site pode utilizar links afiliados e exibir publicidade de terceiros como forma de monetização.</p>

          <h2 style="color:#0a2a67;">5. Alterações</h2>
          <p class="section-copy">Os termos podem ser atualizados a qualquer momento para refletir mudanças no site, na legislação aplicável ou na operação da plataforma.</p>
        </div>
      </section>
    </div>
  </main>

  <footer class="footer-shell">
    <div class="container">
      <div class="footer-card">
        <div class="footer-grid">
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
            <h3>Operação</h3>
            <p class="section-copy">O Zero Preço organiza ofertas de marketplaces parceiros e redireciona o usuário para a página oficial de compra.</p>
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
