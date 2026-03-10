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
  <title>Política de Privacidade | Zero Preço</title>
  <meta name="description" content="Política de Privacidade do Zero Preço. Saiba como dados de navegação e cliques podem ser tratados no site.">
  <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-8314124298799437" crossorigin="anonymous"></script>
  <link rel="stylesheet" href="/assets/css/style.css">
</head>
<body>
  <div class="topbar">
    <div class="container topbar-row">
      <div>Política de Privacidade do Zero Preço.</div>
      <div class="hidden-mobile">Informações sobre coleta e uso de dados.</div>
    </div>
  </div>

  <header class="main-header">
    <div class="container">
      <div class="main-nav">
        <a class="brand" href="/">
          <?php if ($siteHasLogo): ?>
            <span class="brand-media">
              <img class="brand-logo" src="<?= h($siteLogoWebPath) ?>" alt="Zero PreÃ§o">
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
          <a class="pill" href="/termos">Termos</a>
        </nav>

        <div class="mobile-panel" data-mobile-panel>
          <a class="pill" href="/">Home</a>
          <a class="pill" href="/sobre">Sobre</a>
          <a class="pill" href="/contato">Contato</a>
          <a class="pill" href="/termos">Termos</a>
        </div>
      </div>
    </div>
  </header>

  <main class="page-shell" style="padding-top:28px;">
    <div class="container">
      <section class="section-panel">
        <div class="section-heading">
          <div>
            <h1 style="margin:0; color:#0a2a67;">Política de Privacidade</h1>
            <div class="section-copy">Esta política explica de forma resumida como o Zero Preço pode tratar informações de navegação e cliques no site.</div>
          </div>
        </div>

        <div class="surface">
          <h2 style="margin-top:0; color:#0a2a67;">1. Dados de navegação</h2>
          <p class="section-copy">O site pode registrar dados técnicos básicos, como páginas acessadas, horário da visita, navegador utilizado e cliques em ofertas, para fins de funcionamento, segurança, estatísticas e melhoria da experiência.</p>

          <h2 style="color:#0a2a67;">2. Cookies e tecnologias semelhantes</h2>
          <p class="section-copy">Parceiros de publicidade e análise, como o Google, podem utilizar cookies para exibir anúncios, medir desempenho e personalizar a experiência. O usuário pode gerenciar cookies diretamente nas configurações do navegador.</p>

          <h2 style="color:#0a2a67;">3. Links de afiliados</h2>
          <p class="section-copy">Ao clicar em alguns links, o usuário pode ser redirecionado para lojas parceiras. Esses redirecionamentos podem conter identificadores de afiliado para permitir a atribuição de comissão ao Zero Preço.</p>

          <h2 style="color:#0a2a67;">4. Compartilhamento</h2>
          <p class="section-copy">O site não vende dados pessoais. Algumas informações técnicas podem ser compartilhadas com fornecedores de hospedagem, analytics, publicidade e plataformas parceiras, sempre dentro do necessário para a operação do serviço.</p>

          <h2 style="color:#0a2a67;">5. Contato</h2>
          <p class="section-copy">Para dúvidas sobre esta política, entre em contato pelo e-mail contato@zeropreco.com.br.</p>
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
            <h3>Afiliados</h3>
            <p class="section-copy">O site pode receber comissão por compras concluídas em links identificados como afiliados.</p>
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
