<?php
$footerWhatsappGroupLink = site_whatsapp_group_link();
$footerWhatsappGroupLabel = site_whatsapp_group_label();
?>
<footer class="footer-shell">
  <div class="container">
    <div class="footer-card footer-card-compact">
      <div class="footer-compact-top">
        <div>
          <strong>Zero Pre&ccedil;o</strong>
          <div class="footer-note">Ofertas organizadas para abrir r&aacute;pido e comprar na loja oficial.</div>
        </div>
        <div class="footer-links footer-links-inline">
          <a href="/">Home</a>
          <a href="/categoria.php?cat=geral">Cat&aacute;logo</a>
          <a href="/contato">Contato</a>
          <a href="/privacidade">Privacidade</a>
          <a href="/termos">Termos</a>
        </div>
      </div>
      <div class="footer-compact-bottom">
        <span>&copy; <?= date('Y') ?> Zero Pre&ccedil;o</span>
        <a href="<?= h($footerWhatsappGroupLink) ?>" target="_blank" rel="noopener noreferrer"><?= h($footerWhatsappGroupLabel) ?></a>
        <a href="mailto:contato@zeropreco.com.br">contato@zeropreco.com.br</a>
      </div>
    </div>
  </div>
</footer>
