<?php
$siteHeaderCurrent = $siteHeaderCurrent ?? '';
$siteHeaderSearchValue = $siteHeaderSearchValue ?? '';
$siteHeaderSearchPlaceholder = $siteHeaderSearchPlaceholder ?? 'Buscar produto';
$siteHeaderMenuCategories = $siteHeaderMenuCategories ?? null;
$siteHeaderLogoWebPath = '/assets/img/logo-zp.png';
$siteHeaderLogoFilePath = __DIR__ . '/../assets/img/logo-zp.png';
$siteHeaderHasLogo = is_file($siteHeaderLogoFilePath);

if ($siteHeaderMenuCategories === null) {
    $siteHeaderPdo = isset($pdo) && $pdo instanceof PDO ? $pdo : db();
    $siteHeaderMenuCategories = site_build_filters($siteHeaderPdo)['categories'];
}

$siteHeaderMenuChunks = array_chunk(
    $siteHeaderMenuCategories,
    max(1, (int) ceil(max(1, count($siteHeaderMenuCategories)) / 3))
);

$siteHeaderNavItems = [
    ['key' => 'selection', 'label' => 'Seleção', 'href' => '/#selecao-dia'],
    ['key' => 'shopee', 'label' => 'Shopee', 'href' => '/#shopee-alta'],
    ['key' => 'mercado-livre', 'label' => 'Mercado Livre', 'href' => '/#mercado-livre-alta'],
    ['key' => 'amazon', 'label' => 'Amazon', 'href' => '/#amazon-alta'],
];
?>
<header class="main-header main-header-inline">
  <div class="container">
    <div class="header-brand-row">
      <a class="brand brand-mark-only" href="/" aria-label="Zero Preço">
        <?php if ($siteHeaderHasLogo): ?>
          <span class="brand-media">
            <img class="brand-logo" src="<?= h($siteHeaderLogoWebPath) ?>" alt="Zero Preco">
          </span>
        <?php else: ?>
          <span class="brand-badge">ZP</span>
        <?php endif; ?>
      </a>

      <form class="header-search-form header-search-form-mobile search-box-form" action="/busca.php" method="get" autocomplete="off">
        <div class="search-box-row">
          <input
            class="search-box-input"
            type="search"
            name="q"
            value="<?= h($siteHeaderSearchValue) ?>"
            placeholder="<?= h($siteHeaderSearchPlaceholder) ?>"
            aria-label="Buscar produto"
          >
        </div>
      </form>

      <button class="mobile-toggle" type="button" aria-label="Abrir menu" aria-expanded="false" data-menu-toggle>
        <span class="mobile-toggle-line" aria-hidden="true"></span>
      </button>
    </div>

    <div class="header-nav-row">
      <nav class="nav-links nav-links-desktop">
        <?php foreach ($siteHeaderNavItems as $item): ?>
          <a class="nav-link<?= ($item['key'] !== 'selection' && $siteHeaderCurrent === $item['key']) ? ' is-current' : '' ?>" href="<?= h($item['href']) ?>"><?= h($item['label']) ?></a>
        <?php endforeach; ?>
        <div class="nav-item nav-dropdown">
          <a class="nav-link<?= $siteHeaderCurrent === 'categories' ? ' is-current' : '' ?>" href="/categoria.php?cat=geral">
            Categorias
            <span class="nav-caret" aria-hidden="true"></span>
          </a>
          <div class="nav-dropdown-panel">
            <div class="nav-dropdown-top">
              <div>
                <div class="nav-dropdown-title">Categorias do site</div>
                <p class="nav-dropdown-copy">Navegue pelas categorias principais e abra as páginas do catálogo com menos cliques.</p>
              </div>
              <a class="nav-dropdown-cta" href="/categoria.php?cat=geral">Ver catálogo</a>
            </div>
            <div class="nav-dropdown-grid">
              <?php foreach ($siteHeaderMenuChunks as $chunk): ?>
                <div class="nav-dropdown-column">
                  <?php foreach ($chunk as $cat): ?>
                    <a class="nav-dropdown-link" href="<?= h(site_category_href($cat['categoria'])) ?>"><?= h(site_public_category_label($cat['categoria'])) ?></a>
                  <?php endforeach; ?>
                </div>
              <?php endforeach; ?>
            </div>
          </div>
        </div>
      </nav>

      <form class="header-search-form search-box-form" action="/busca.php" method="get" autocomplete="off" data-search-form>
        <div class="search-box-row">
          <input
            class="search-box-input"
            type="search"
            name="q"
            value="<?= h($siteHeaderSearchValue) ?>"
            placeholder="<?= h($siteHeaderSearchPlaceholder) ?>"
            aria-label="Buscar produto"
            data-search-input
          >
          <button class="search-box-button" type="submit">Pesquisar</button>
        </div>
        <div class="search-suggest-panel" data-search-suggest hidden>
          <div class="search-suggest-list" data-search-suggest-list></div>
          <a class="search-suggest-more" href="/busca.php" data-search-submit-link>Ver todos os resultados</a>
        </div>
      </form>
    </div>

    <div class="mobile-panel" data-mobile-panel>
      <?php foreach ($siteHeaderNavItems as $item): ?>
        <a class="pill" href="<?= h($item['href']) ?>"><?= h($item['label']) ?></a>
      <?php endforeach; ?>
      <a class="pill" href="/categoria.php?cat=geral">Categorias</a>
    </div>
  </div>
</header>
