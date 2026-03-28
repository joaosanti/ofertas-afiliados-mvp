<?php
require_once __DIR__ . '/_init.php';
admin_require_login();

function admin_click_location_label($entry) {
  $parts = [];
  foreach ([
    (string) ($entry['city_name'] ?? ''),
    (string) ($entry['region_name'] ?? ''),
    (string) ($entry['country_name'] ?? ''),
    (string) ($entry['country_code'] ?? ''),
  ] as $part) {
    $clean = trim($part);
    if ($clean !== '' && !in_array($clean, $parts, true)) {
      $parts[] = $clean;
    }
  }

  return $parts ? implode(' / ', $parts) : 'nao disponivel';
}

function admin_click_query(array $overrides = []) {
  $params = [
    'q' => trim((string) ($_GET['q'] ?? '')),
    'loja' => trim((string) ($_GET['loja'] ?? '')),
    'traffic' => trim((string) ($_GET['traffic'] ?? 'human')),
    'day' => trim((string) ($_GET['day'] ?? '')),
    'limit' => (string) ((int) ($_GET['limit'] ?? 100)),
  ];

  foreach ($overrides as $key => $value) {
    if ($value === null) {
      unset($params[$key]);
      continue;
    }
    $params[$key] = (string) $value;
  }

  $params = array_filter($params, static function ($value, $key) {
    if ($key === 'traffic') {
      return $value !== '' && $value !== 'human';
    }
    if ($key === 'limit') {
      return $value !== '' && $value !== '100';
    }
    return $value !== '';
  }, ARRAY_FILTER_USE_BOTH);

  $query = http_build_query($params);
  return '/admin/ofertas_cliques.php' . ($query !== '' ? '?' . $query : '');
}

$flash = admin_flash_get();
$pdo = db();
$search = trim((string) ($_GET['q'] ?? ''));
$storeFilter = trim((string) ($_GET['loja'] ?? ''));
$trafficFilter = trim((string) ($_GET['traffic'] ?? 'human'));
$dayFilter = trim((string) ($_GET['day'] ?? ''));
$limit = (int) ($_GET['limit'] ?? 100);
$limit = max(20, min(250, $limit));
if (!in_array($trafficFilter, ['human', 'bot', 'all'], true)) {
  $trafficFilter = 'human';
}
if ($dayFilter !== '' && !preg_match('/^\d{4}-\d{2}-\d{2}$/', $dayFilter)) {
  $dayFilter = '';
}

$storeRows = $pdo->query('SELECT DISTINCT loja FROM ofertas ORDER BY loja ASC')->fetchAll();
$stores = array_values(array_filter(array_map(static function ($row) {
  return trim((string) ($row['loja'] ?? ''));
}, $storeRows)));

$rawEntries = admin_read_click_log_entries(max($limit * 10, 1500));
$entries = [];
$uniqueOfferIds = [];
$recent24h = 0;
$lastTimestamp = '';
$now = time();
$hiddenBotCount = 0;
$humanPoolCount = 0;
$botPoolCount = 0;
$dailyCounts = [];

foreach ($rawEntries as $entry) {
  $entryStore = trim((string) ($entry['store'] ?? ''));
  $haystack = strtolower(implode(' ', [
    (string) ($entry['offer_id'] ?? ''),
    (string) ($entry['slug'] ?? ''),
    (string) ($entry['title'] ?? ''),
    (string) ($entry['target_url'] ?? ''),
    (string) ($entry['referer'] ?? ''),
    (string) ($entry['user_agent'] ?? ''),
    (string) ($entry['country_name'] ?? ''),
    (string) ($entry['region_name'] ?? ''),
    (string) ($entry['city_name'] ?? ''),
  ]));

  if ($storeFilter !== '' && strcasecmp($entryStore, $storeFilter) !== 0) {
    continue;
  }
  if ($search !== '' && !str_contains($haystack, strtolower($search))) {
    continue;
  }

  $timestamp = trim((string) ($entry['timestamp'] ?? ''));
  if ($lastTimestamp === '' && $timestamp !== '') {
    $lastTimestamp = $timestamp;
  }

  $entryDay = '';
  $parsedTime = $timestamp !== '' ? strtotime($timestamp) : false;
  if ($parsedTime) {
    $entryDay = gmdate('Y-m-d', $parsedTime);
    if (!isset($dailyCounts[$entryDay])) {
      $dailyCounts[$entryDay] = ['all' => 0, 'human' => 0, 'bot' => 0];
    }
    $dailyCounts[$entryDay]['all']++;
  }

  $profile = click_request_profile(
    (string) ($entry['user_agent'] ?? ''),
    (string) ($entry['request_method'] ?? 'GET'),
    (string) ($entry['referer'] ?? '')
  );
  $isBot = array_key_exists('is_bot', $entry) ? !empty($entry['is_bot']) : !empty($profile['is_bot']);
  $trafficType = trim((string) ($entry['traffic_type'] ?? ''));
  if ($trafficType === '') {
    $trafficType = $isBot ? 'bot' : 'human';
  }
  $entry['is_bot'] = $isBot;
  $entry['traffic_type'] = $trafficType;
  $entry['bot_reason'] = trim((string) ($entry['bot_reason'] ?? '')) ?: (string) ($profile['reason'] ?? '');
  $entry['day'] = $entryDay;

  if ($entryDay !== '') {
    $dailyCounts[$entryDay][$isBot ? 'bot' : 'human']++;
  }

  if ($dayFilter !== '' && $entryDay !== $dayFilter) {
    continue;
  }

  if ($parsedTime && ($now - $parsedTime) <= 86400) {
    $recent24h++;
  }

  if ($isBot) {
    $botPoolCount++;
  } else {
    $humanPoolCount++;
  }

  if ($trafficFilter === 'human' && $isBot) {
    $hiddenBotCount++;
    continue;
  }
  if ($trafficFilter === 'bot' && !$isBot) {
    continue;
  }

  $offerId = (int) ($entry['offer_id'] ?? 0);
  if ($offerId > 0) {
    $uniqueOfferIds[$offerId] = true;
  }

  if (count($entries) < $limit) {
    $entries[] = $entry;
  }
}

$dayOptions = array_keys($dailyCounts);
rsort($dayOptions, SORT_STRING);

$trafficLabels = [
  'human' => 'reais',
  'bot' => 'bots',
  'all' => 'totais',
];

$adminCssVersion = (string) @filemtime(__DIR__ . '/../assets/css/admin.css');
?>
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Admin - Cliques detalhados</title>
  <link rel="icon" type="image/png" href="/assets/img/logo-zp.png">
  <link rel="stylesheet" href="/assets/css/style.css">
  <link rel="stylesheet" href="/assets/css/admin.css?v=<?= urlencode($adminCssVersion) ?>">
</head>
<body class="admin-page">
<?php admin_render_header('ofertas'); ?>

<main class="container admin-shell">
  <?php if ($flash): ?>
    <div class="admin-alert <?= h((string) ($flash['type'] ?? '')) ?>"><?= h((string) ($flash['message'] ?? '')) ?></div>
  <?php endif; ?>

  <section class="admin-hero">
    <div class="admin-hero-head">
      <div class="admin-hero-copy">
        <a class="admin-kicker" href="/admin/ofertas.php">Gerenciador de produtos</a>
        <h1>Cliques detalhados</h1>
        <p>Auditoria das saidas do `go=1`, com foco em trafego humano para comparar melhor com os contadores das lojas.</p>
      </div>
      <div class="admin-hero-actions">
        <a class="btn-link primary" href="/admin/ofertas.php">Voltar ao catalogo</a>
      </div>
    </div>
  </section>

  <?php admin_render_offer_subnav('clicks'); ?>

  <section class="admin-panel">
    <form method="get" class="admin-filter-form">
      <div class="admin-search-toolbar">
        <div class="admin-field admin-field-search">
          <label for="q">Pesquisar clique</label>
          <input id="q" name="q" value="<?= h($search) ?>" placeholder="Oferta, slug, URL de destino, referer, user agent ou localizacao">
        </div>
        <div class="admin-field admin-field-compact">
          <label for="loja">Loja</label>
          <select id="loja" name="loja">
            <option value="">Todas</option>
            <?php foreach ($stores as $store): ?>
              <option value="<?= h($store) ?>" <?= strcasecmp($storeFilter, $store) === 0 ? 'selected' : '' ?>>
                <?= h($store) ?>
              </option>
            <?php endforeach; ?>
          </select>
        </div>
        <div class="admin-field admin-field-compact">
          <label for="traffic">Trafego</label>
          <select id="traffic" name="traffic">
            <option value="human" <?= $trafficFilter === 'human' ? 'selected' : '' ?>>So reais</option>
            <option value="all" <?= $trafficFilter === 'all' ? 'selected' : '' ?>>Todos</option>
            <option value="bot" <?= $trafficFilter === 'bot' ? 'selected' : '' ?>>So bots</option>
          </select>
        </div>
        <div class="admin-field admin-field-compact">
          <label for="day">Dia</label>
          <select id="day" name="day">
            <option value="">Todos</option>
            <?php foreach ($dayOptions as $dayOption): ?>
              <?php $counts = $dailyCounts[$dayOption] ?? ['all' => 0, 'human' => 0, 'bot' => 0]; ?>
              <option value="<?= h($dayOption) ?>" <?= $dayFilter === $dayOption ? 'selected' : '' ?>>
                <?= h($dayOption) ?> (<?= (int) $counts['human'] ?> reais)
              </option>
            <?php endforeach; ?>
          </select>
        </div>
        <div class="admin-field admin-field-compact">
          <label for="limit">Limite</label>
          <select id="limit" name="limit">
            <?php foreach ([50, 100, 150, 250] as $limitOption): ?>
              <option value="<?= $limitOption ?>" <?= $limit === $limitOption ? 'selected' : '' ?>><?= $limitOption ?></option>
            <?php endforeach; ?>
          </select>
        </div>
        <div class="admin-form-actions admin-form-actions-inline">
          <button class="btn-link primary" type="submit">Filtrar</button>
          <a class="badge" href="/admin/ofertas_cliques.php">Limpar</a>
        </div>
      </div>
    </form>

    <div class="admin-filter-row">
      <span class="admin-meta-chip admin-meta-chip-soft"><?= count($entries) ?> cliques <?= h($trafficLabels[$trafficFilter]) ?> exibidos</span>
      <span class="admin-meta-chip admin-meta-chip-soft"><?= count($uniqueOfferIds) ?> ofertas unicas</span>
      <span class="admin-meta-chip admin-meta-chip-soft"><?= $recent24h ?> registros nas ultimas 24h</span>
      <?php if ($trafficFilter === 'human'): ?>
        <span class="admin-meta-chip admin-meta-chip-soft"><?= $hiddenBotCount ?> bots ocultados</span>
      <?php else: ?>
        <span class="admin-meta-chip admin-meta-chip-soft"><?= $humanPoolCount ?> reais / <?= $botPoolCount ?> bots</span>
      <?php endif; ?>
      <?php if ($dayFilter !== ''): ?>
        <span class="admin-meta-chip admin-meta-chip-soft">Dia: <?= h($dayFilter) ?></span>
      <?php endif; ?>
      <span class="admin-meta-chip admin-meta-chip-soft">Ultimo registro: <?= h($lastTimestamp !== '' ? $lastTimestamp : 'ainda sem cliques') ?></span>
    </div>

    <?php if ($dayOptions): ?>
      <div class="admin-filter-row" style="margin-top:10px;">
        <?php foreach ($dayOptions as $dayOption): ?>
          <?php
            $counts = $dailyCounts[$dayOption] ?? ['all' => 0, 'human' => 0, 'bot' => 0];
            $badgeLabel = $dayOption . ' - ' . (int) $counts['human'] . ' reais';
            if ((int) $counts['bot'] > 0) {
              $badgeLabel .= ' / ' . (int) $counts['bot'] . ' bots';
            }
          ?>
          <a class="admin-meta-chip admin-meta-chip-soft" href="<?= h(admin_click_query(['day' => $dayOption])) ?>" style="<?= $dayFilter === $dayOption ? 'background:#1d3c78;color:#fff;border-color:#1d3c78;' : '' ?>">
            <?= h($badgeLabel) ?>
          </a>
        <?php endforeach; ?>
      </div>
    <?php endif; ?>
  </section>

  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Saidas rastreadas</h2>
        <p>Use esta tela para comparar melhor os cliques reais do Zero Preco com as metricas das lojas. Bots e previews ficam fora por padrao.</p>
      </div>
    </div>

    <?php if (!$entries): ?>
      <div class="admin-empty">Nenhum clique encontrado para este filtro. Abra uma oferta do site com `?go=1` e volte aqui.</div>
    <?php else: ?>
      <div class="admin-mini-grid">
        <?php foreach ($entries as $entry): ?>
          <?php
            $slug = trim((string) ($entry['slug'] ?? ''));
            $targetUrl = trim((string) ($entry['target_url'] ?? ''));
            $isBot = !empty($entry['is_bot']);
            $botReason = trim((string) ($entry['bot_reason'] ?? ''));
            $locationLabel = admin_click_location_label($entry);
          ?>
          <article class="admin-side-card">
            <div class="admin-meta-row">
              <span class="admin-meta-chip"><?= h((string) ($entry['timestamp'] ?? 'sem horario')) ?></span>
              <span class="admin-meta-chip admin-meta-chip-soft">Oferta #<?= (int) ($entry['offer_id'] ?? 0) ?></span>
              <span class="admin-meta-chip admin-meta-chip-soft"><?= h((string) ($entry['store'] ?? 'Loja')) ?></span>
              <span class="admin-meta-chip admin-meta-chip-soft"><?= $isBot ? 'bot' : 'real' ?></span>
            </div>

            <strong><?= h((string) ($entry['title'] ?? 'Oferta sem titulo')) ?></strong>
            <div class="admin-card-subtitle"><?= h($slug !== '' ? $slug : 'slug indisponivel') ?></div>

            <div class="admin-mini-grid" style="margin-top:12px;">
              <div>
                <strong>Destino afiliado</strong>
                <div class="admin-url-box"><?= h($targetUrl !== '' ? $targetUrl : 'nao informado') ?></div>
              </div>
              <div>
                <strong>Referer</strong>
                <div class="admin-url-box"><?= h((string) ($entry['referer'] ?? '')) ?: 'direto / vazio' ?></div>
              </div>
              <div>
                <strong>Agente / hash</strong>
                <div class="admin-url-box"><?= h((string) ($entry['user_agent'] ?? '')) ?></div>
                <div class="admin-help" style="margin-top:6px;">
                  IP hash: <?= h((string) ($entry['ip_hash'] ?? '')) ?><?= !empty($entry['remote_addr_suffix']) ? ' | final: ' . h((string) $entry['remote_addr_suffix']) : '' ?>
                </div>
                <?php if ($botReason !== ''): ?>
                  <div class="admin-help" style="margin-top:6px;">Classificacao: <?= h($botReason) ?></div>
                <?php endif; ?>
              </div>
              <div>
                <strong>Localizacao</strong>
                <div class="admin-url-box"><?= h($locationLabel) ?></div>
                <?php if (!empty($entry['locale_hint'])): ?>
                  <div class="admin-help" style="margin-top:6px;">Idioma do navegador: <?= h((string) $entry['locale_hint']) ?></div>
                <?php endif; ?>
              </div>
            </div>

            <div class="admin-card-actions" style="margin-top:14px;">
              <?php if ($slug !== ''): ?>
                <a class="badge" href="/oferta.php?slug=<?= urlencode($slug) ?>" target="_blank" rel="noopener noreferrer">Abrir pagina</a>
                <a class="btn-link primary" href="/oferta.php?slug=<?= urlencode($slug) ?>&go=1" target="_blank" rel="noopener sponsored nofollow">Testar pelo site</a>
              <?php endif; ?>
              <?php if ($targetUrl !== ''): ?>
                <a class="badge" href="<?= h($targetUrl) ?>" target="_blank" rel="noopener sponsored nofollow">Abrir destino</a>
              <?php endif; ?>
            </div>
          </article>
        <?php endforeach; ?>
      </div>
    <?php endif; ?>
  </section>
</main>
</body>
</html>
