<?php
$googleAdsTagId = 'AW-975222683';
$googleAnalyticsId = 'G-YFBB12F3YL';
?>
  <script async src="https://www.googletagmanager.com/gtag/js?id=<?= h($googleAdsTagId) ?>"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){dataLayer.push(arguments);}
    gtag('js', new Date());
    gtag('config', '<?= h($googleAdsTagId) ?>');
    gtag('config', '<?= h($googleAnalyticsId) ?>');
  </script>
