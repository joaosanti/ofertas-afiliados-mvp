<?php
require_once __DIR__ . '/_init.php';
admin_require_login();

$pdo = db();
$flash = admin_flash_get();
$recentRuns = admin_fetch_recent_runs($pdo, 'import', 3);
$resultPayload = null;
$adminCssVersion = (string) @filemtime(__DIR__ . '/../assets/css/admin.css');
$currentAdminLogin = admin_current_login_name();
$shopeeJobLimits = [1, 5, 10, 25, 50, 100];
$refreshBatchLimits = [25, 50, 100];
$pendingImportJob = $_SESSION['admin_import_pending_job'] ?? null;
$importView = trim((string) ($_GET['view'] ?? 'shopee_search'));
$allowedImportViews = ['shopee_search', 'shopee_with_video', 'shopee_without_video', 'amazon_update', 'mercadolivre_update', 'short_links'];
if (!in_array($importView, $allowedImportViews, true)) {
  $importView = 'shopee_search';
}
$previewKeyword = trim((string) ($_GET['shopee_q'] ?? ''));
$previewPage = max(1, (int) ($_GET['shopee_page'] ?? 1));
$previewLimit = max(1, min((int) ($_GET['shopee_preview_limit'] ?? 12), 24));
$inventoryPage = max(1, (int) ($_GET['inventory_page'] ?? 1));
$inventoryLimit = max(1, min((int) ($_GET['inventory_limit'] ?? 24), 48));
$previewPayload = null;
$previewItems = [];
$previewHasMore = false;
$previewError = '';
$shortLinkProvider = trim((string) ($_REQUEST['short_provider'] ?? 'amazon'));
if (!in_array($shortLinkProvider, ['amazon', 'mercadolivre'], true)) {
  $shortLinkProvider = 'amazon';
}
$shortLinkPageUrl = trim((string) ($_REQUEST['short_page_url'] ?? ''));
$shortLinkLimit = max(1, min((int) ($_REQUEST['short_limit'] ?? 10), 100));
$shortLinkExtraOnly = !empty($_REQUEST['short_extra_only']);
$shortLinkBestSellerOnly = !empty($_REQUEST['short_best_seller_only']);
$shortLinkHelperPayload = null;

function admin_import_query(array $overrides = []) {
  global $importView, $previewKeyword, $previewPage, $previewLimit, $inventoryPage, $inventoryLimit, $shortLinkProvider, $shortLinkPageUrl, $shortLinkLimit, $shortLinkExtraOnly, $shortLinkBestSellerOnly;
  $params = [
    'view' => $importView,
    'shopee_q' => $previewKeyword,
    'shopee_page' => $previewPage,
    'shopee_preview_limit' => $previewLimit,
    'inventory_page' => $inventoryPage,
    'inventory_limit' => $inventoryLimit,
  ];
  if ($importView === 'short_links') {
    $params['short_provider'] = $shortLinkProvider;
    $params['short_page_url'] = $shortLinkPageUrl;
    $params['short_limit'] = $shortLinkLimit;
    $params['short_extra_only'] = $shortLinkExtraOnly ? 1 : 0;
    $params['short_best_seller_only'] = $shortLinkBestSellerOnly ? 1 : 0;
  }
  foreach ($overrides as $key => $value) {
    $params[$key] = $value;
  }
  return http_build_query(array_filter($params, static function ($value) {
    return $value !== '' && $value !== null;
  }));
}

function admin_import_result_summary($resultPayload) {
  $summary = is_array($resultPayload['result'] ?? null) ? $resultPayload['result'] : [];
  if (isset($summary['processed']) || isset($summary['created']) || isset($summary['updated']) || isset($summary['skipped'])) {
    return [
      'processed' => (int) ($summary['processed'] ?? 0),
      'created' => (int) ($summary['created'] ?? 0),
      'updated' => (int) ($summary['updated'] ?? 0),
      'skipped' => (int) ($summary['skipped'] ?? 0),
      'selected' => (int) ($summary['offers_selected'] ?? 0),
      'limit_requested' => (int) ($summary['limit_requested'] ?? 0),
      'keyword' => (string) ($summary['keyword'] ?? ''),
      'without_video' => (int) ($summary['imported_without_video_count'] ?? 0),
      'drafts_created' => (int) ($summary['shopee_video_drafts_created'] ?? 0),
      'drafts_updated' => (int) ($summary['shopee_video_drafts_updated'] ?? 0),
      'without_video_titles' => array_values(array_filter(array_map('strval', (array) ($summary['imported_without_video_titles'] ?? [])))),
    ];
  }

  $items = is_array($summary['items'] ?? null) ? $summary['items'] : [];
  $processed = 0;
  $created = 0;
  $updated = 0;
  $skipped = 0;
  $selected = 0;
  $limitRequested = 0;
  $keyword = '';
  $withoutVideo = 0;
  $draftsCreated = 0;
  $draftsUpdated = 0;
  $withoutVideoTitles = [];
  foreach ($items as $item) {
    if (!is_array($item)) {
      continue;
    }
    $processed += (int) ($item['processed'] ?? $item['imported'] ?? 0);
    $created += (int) ($item['created'] ?? 0);
    $updated += (int) ($item['updated'] ?? 0);
    $skipped += (int) ($item['skipped'] ?? 0);
    $selected += (int) ($item['offers_selected'] ?? 0);
    $limitRequested = max($limitRequested, (int) ($item['limit_requested'] ?? 0));
    $withoutVideo += (int) ($item['imported_without_video_count'] ?? 0);
    $draftsCreated += (int) ($item['shopee_video_drafts_created'] ?? 0);
    $draftsUpdated += (int) ($item['shopee_video_drafts_updated'] ?? 0);
    if ($keyword === '' && !empty($item['keyword'])) {
      $keyword = trim((string) $item['keyword']);
    }
    if (!$withoutVideoTitles && !empty($item['imported_without_video_titles']) && is_array($item['imported_without_video_titles'])) {
      $withoutVideoTitles = array_values(array_filter(array_map('strval', $item['imported_without_video_titles'])));
    }
  }

  return [
    'processed' => $processed,
    'created' => $created,
    'updated' => $updated,
    'skipped' => $skipped,
    'selected' => $selected,
    'limit_requested' => $limitRequested,
    'keyword' => $keyword,
    'without_video' => $withoutVideo,
    'drafts_created' => $draftsCreated,
    'drafts_updated' => $draftsUpdated,
    'without_video_titles' => $withoutVideoTitles,
  ];
}

function admin_import_offer_has_video(array $offer): bool {
  $tags = (string) ($offer['tags'] ?? '');
  if (strpos($tags, 'offer_video_url:') !== false || strpos($tags, 'shopee_video_url:') !== false) {
    return true;
  }
  $videoUrls = admin_shopee_video_decode_url_list($offer['video_urls_json'] ?? []);
  return !empty($videoUrls);
}

function admin_import_inventory_query(array $overrides = []): string {
  return '/admin/importar.php?' . admin_import_query($overrides);
}

function admin_import_view_label(string $view): string {
  $labels = [
    'shopee_search' => 'Buscar Shopee',
    'shopee_with_video' => 'Shopee com video',
    'shopee_without_video' => 'Shopee sem video',
    'amazon_update' => 'Atualizar Amazon',
    'mercadolivre_update' => 'Atualizar Mercado Livre',
    'short_links' => 'Links curtos',
  ];
  return (string) ($labels[$view] ?? 'Importar');
}

function admin_short_link_provider_label(string $provider): string {
  return $provider === 'mercadolivre' ? 'Mercado Livre' : 'Amazon';
}

function admin_build_amazon_short_links_command(string $pageUrl, int $limit): string {
  $escapedUrl = '"' . addcslashes($pageUrl, "\\\"") . '"';
  $outputName = 'amazon-short-links-' . max(1, min($limit, 10)) . '.txt';
  return '.\\automacao_ofertas\\.venv\\Scripts\\python .\\scripts\\amazon_short_links_playwright.py --start-url ' . $escapedUrl . ' --limit ' . max(1, min($limit, 10)) . ' --manual-login --output .\\' . $outputName;
}

function admin_build_mercadolivre_short_links_snippet(int $limit, bool $extraOnly, bool $bestSellerOnly): string {
  $limit = max(1, min($limit, 100));
  $linkPredicate = $extraOnly ? "href.includes('extra_comm=true')" : "href.includes('mercadolivre.com.br') || href.includes('produto.mercadolivre.com.br')";
  $bestSellerPredicate = $bestSellerOnly ? '      .filter((card) => ((card?.innerText || "").toLowerCase().includes("mais vendido")))' . "\n" : '';
  return <<<JAVASCRIPT
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const MAX_PRODUCTS = {$limit};

  const found = [];
  const foundSet = new Set();
  const clickedButtons = new Set();

  const extractShortUrls = (payload) => {
    const urls = Array.isArray(payload?.urls) ? payload.urls : [];
    for (const item of urls) {
      const shortUrl = String(item?.short_url || "").trim();
      if (shortUrl && !foundSet.has(shortUrl)) {
        foundSet.add(shortUrl);
        found.push(shortUrl);
      }
    }
  };

  const originalFetch = window.fetch;
  window.fetch = async (...args) => {
    const res = await originalFetch(...args);
    try {
      const reqUrl = String(args?.[0]?.url || args?.[0] || "");
      if (reqUrl.includes("/affiliate-program/api/v2/affiliates/createLink")) {
        const clone = res.clone();
        const text = await clone.text();
        extractShortUrls(JSON.parse(text));
      }
    } catch {}
    return res;
  };

  const originalOpen = XMLHttpRequest.prototype.open;
  const originalSend = XMLHttpRequest.prototype.send;

  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__url = url;
    return originalOpen.call(this, method, url, ...rest);
  };

  XMLHttpRequest.prototype.send = function (...args) {
    this.addEventListener("load", function () {
      try {
        const reqUrl = String(this.__url || "");
        if (reqUrl.includes("/affiliate-program/api/v2/affiliates/createLink")) {
          extractShortUrls(JSON.parse(this.responseText));
        }
      } catch {}
    });
    return originalSend.apply(this, args);
  };

  const getEligibleButtons = () => {
    const cards = [...document.querySelectorAll("a[href]")]
      .filter((a) => {
        const href = String(a.getAttribute("href") || "");
        return {$linkPredicate};
      })
      .map((a) => a.closest("li, article, div"))
      .filter(Boolean);

    const uniqueCards = [...new Set(cards)];
{$bestSellerPredicate}    return uniqueCards
      .map((card) => [...card.querySelectorAll("button")].find((btn) => btn.innerText?.trim() === "Compartilhar"))
      .filter(Boolean);
  };

  let idleRounds = 0;

  while (found.length < MAX_PRODUCTS && idleRounds < 5) {
    const buttons = getEligibleButtons().filter((btn) => !clickedButtons.has(btn));
    if (!buttons.length) {
      idleRounds += 1;
      window.scrollBy(0, Math.floor(window.innerHeight * 0.9));
      await sleep(1800);
      continue;
    }

    idleRounds = 0;

    for (const btn of buttons) {
      if (found.length >= MAX_PRODUCTS) break;

      clickedButtons.add(btn);
      btn.scrollIntoView({ block: "center" });
      await sleep(400);
      btn.click();
      await sleep(1400);

      const copyBtn = document.querySelector("#copy_link");
      if (copyBtn) {
        copyBtn.click();
        await sleep(1200);
      }

      const closeBtn =
        document.querySelector(".share-wrapper .andes-modal__header button") ||
        document.querySelector(".andes-modal__header button");

      if (closeBtn) {
        closeBtn.click();
        await sleep(500);
      } else {
        document.dispatchEvent(
          new KeyboardEvent("keydown", { key: "Escape", bubbles: true })
        );
        await sleep(500);
      }
    }

    window.scrollBy(0, Math.floor(window.innerHeight * 0.9));
    await sleep(1800);
  }

  await sleep(1500);

  window.fetch = originalFetch;
  XMLHttpRequest.prototype.open = originalOpen;
  XMLHttpRequest.prototype.send = originalSend;

  const content = found.slice(0, MAX_PRODUCTS).join("\\n");
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const fileUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = fileUrl;
  a.download = "meli-short-links-helper.txt";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(fileUrl);

  console.log(found.slice(0, MAX_PRODUCTS));
  alert("Baixei " + Math.min(found.length, MAX_PRODUCTS) + " short_url(s) em meli-short-links-helper.txt");
})();
JAVASCRIPT;
}

function admin_import_fetch_inventory(PDO $pdo, string $store, int $page = 1, int $limit = 24, string $videoState = 'all'): array {
  $page = max(1, $page);
  $limit = max(1, min($limit, 48));
  $where = ['LOWER(o.loja) = LOWER(?)'];
  $params = [$store];

  if (strtolower($store) === 'shopee') {
    $videoSql = "(o.tags LIKE '%offer_video_url:%' OR o.tags LIKE '%shopee_video_url:%' OR (o.video_urls_json IS NOT NULL AND o.video_urls_json <> '' AND o.video_urls_json <> '[]'))";
    if ($videoState === 'with') {
      $where[] = $videoSql;
    } elseif ($videoState === 'without') {
      $where[] = "NOT {$videoSql}";
    }
  }

  $whereSql = implode(' AND ', $where);
  $countStmt = $pdo->prepare("SELECT COUNT(*) FROM ofertas o WHERE {$whereSql}");
  $countStmt->execute($params);
  $total = (int) $countStmt->fetchColumn();
  $pages = max(1, (int) ceil($total / $limit));
  $page = min($page, $pages);
  $offset = ($page - 1) * $limit;

  $sql = "
    SELECT
      o.id,
      o.titulo,
      o.slug,
      o.preco,
      o.preco_antigo,
      o.loja,
      o.categoria,
      o.url_afiliado,
      o.imagem_url,
      o.imagem_urls_json,
      o.video_urls_json,
      o.tags,
      o.cupom,
      o.ativo,
      o.atualizado_em,
      d.id AS draft_id,
      d.status AS draft_status
    FROM ofertas o
    LEFT JOIN (
      SELECT MAX(id) AS latest_id, oferta_id
      FROM shopee_video_drafts
      GROUP BY oferta_id
    ) draft_latest
      ON draft_latest.oferta_id = o.id
    LEFT JOIN shopee_video_drafts d
      ON d.id = draft_latest.latest_id
    WHERE {$whereSql}
    ORDER BY o.atualizado_em DESC, o.id DESC
    LIMIT {$limit} OFFSET {$offset}
  ";
  $stmt = $pdo->prepare($sql);
  $stmt->execute($params);
  $items = $stmt->fetchAll() ?: [];

  return [
    'items' => $items,
    'total' => $total,
    'page' => $page,
    'pages' => $pages,
    'limit' => $limit,
  ];
}

function admin_import_inventory_counts(PDO $pdo): array {
  $queries = [
    'shopee_with_video' => "SELECT COUNT(*) FROM ofertas WHERE LOWER(loja) = 'shopee' AND (tags LIKE '%offer_video_url:%' OR tags LIKE '%shopee_video_url:%' OR (video_urls_json IS NOT NULL AND video_urls_json <> '' AND video_urls_json <> '[]'))",
    'shopee_without_video' => "SELECT COUNT(*) FROM ofertas WHERE LOWER(loja) = 'shopee' AND NOT (tags LIKE '%offer_video_url:%' OR tags LIKE '%shopee_video_url:%' OR (video_urls_json IS NOT NULL AND video_urls_json <> '' AND video_urls_json <> '[]'))",
    'amazon_update' => "SELECT COUNT(*) FROM ofertas WHERE LOWER(loja) = LOWER('Amazon')",
    'mercadolivre_update' => "SELECT COUNT(*) FROM ofertas WHERE LOWER(loja) = LOWER('Mercado Livre')",
  ];
  $counts = [];
  foreach ($queries as $key => $sql) {
    try {
      $counts[$key] = (int) $pdo->query($sql)->fetchColumn();
    } catch (Throwable $e) {
      $counts[$key] = 0;
    }
  }
  return $counts;
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
  admin_csrf_check_or_die();
  $action = (string) ($_POST['acao'] ?? '');

  if ($action === 'import_file') {
    if (empty($_FILES['arquivo']['tmp_name']) || !is_uploaded_file($_FILES['arquivo']['tmp_name'])) {
      admin_flash_set('error', 'Envie um arquivo para importar.');
      header('Location: /admin/importar.php');
      exit;
    }

    $kind = trim((string) ($_POST['kind'] ?? ''));
    $tmpDir = sys_get_temp_dir();
    $target = $tmpDir . DIRECTORY_SEPARATOR . 'zp-import-' . bin2hex(random_bytes(8)) . '-' . basename((string) $_FILES['arquivo']['name']);
    if (!move_uploaded_file($_FILES['arquivo']['tmp_name'], $target)) {
      admin_flash_set('error', 'Nao foi possivel mover o arquivo enviado.');
      header('Location: /admin/importar.php');
      exit;
    }

    try {
      $args = ['import-file', '--kind', $kind, '--input-file', $target];
      if ($currentAdminLogin !== '') {
        $args[] = '--actor-user-id';
        $args[] = (string) admin_user_id();
        $args[] = '--actor-login';
        $args[] = $currentAdminLogin;
      }
      $resultPayload = admin_run_python_job($args);
    } finally {
      @unlink($target);
    }
  } elseif ($action === 'import_links') {
    $content = trim((string) ($_POST['links'] ?? ''));
    if ($content === '') {
      admin_flash_set('error', 'Cole pelo menos um link.');
      header('Location: /admin/importar.php');
      exit;
    }

    $tmpDir = sys_get_temp_dir();
    $target = $tmpDir . DIRECTORY_SEPARATOR . 'zp-links-' . bin2hex(random_bytes(8)) . '.txt';
    file_put_contents($target, $content);
    try {
      $args = ['import-links', '--input-file', $target];
      if ($currentAdminLogin !== '') {
        $args[] = '--actor-user-id';
        $args[] = (string) admin_user_id();
        $args[] = '--actor-login';
        $args[] = $currentAdminLogin;
      }
      $resultPayload = admin_run_python_job($args);
    } finally {
      @unlink($target);
    }
  } elseif ($action === 'import_shopee_job') {
    $jobLimit = (int) ($_POST['job_limit'] ?? 25);
    if (!in_array($jobLimit, $shopeeJobLimits, true)) {
      $jobLimit = 25;
    }
    $jobKeyword = trim((string) ($_POST['job_keyword'] ?? ''));
    $args = ['import', '--provider', 'shopee', '--limit', (string) $jobLimit];
    if ($jobKeyword !== '') {
      $args[] = '--keyword';
      $args[] = $jobKeyword;
    }
    $redirectUrl = '/admin/importar.php';
    $queryString = admin_import_query([
      'shopee_q' => $jobKeyword !== '' ? $jobKeyword : $previewKeyword,
      'shopee_page' => 1,
    ]);
    if ($queryString !== '') {
      $redirectUrl .= '?' . $queryString;
    }
    $started = admin_start_python_job_async($args, [
      'kind' => 'import_shopee_job',
      'target_tab' => 'importar',
      'keyword' => $jobKeyword,
      'limit_requested' => $jobLimit,
    ]);
    if (empty($started['ok'])) {
      admin_flash_set('error', (string) ($started['error'] ?? 'Falha ao iniciar job Shopee.'));
      header('Location: ' . $redirectUrl);
      exit;
    }
    $_SESSION['admin_import_pending_job'] = [
      'job_id' => (string) ($started['job_id'] ?? ''),
      'kind' => 'import_shopee_job',
      'keyword' => $jobKeyword,
      'limit_requested' => $jobLimit,
      'redirect_url' => $redirectUrl,
    ];
    header('Location: ' . $redirectUrl);
    exit;
  } elseif ($action === 'import_shopee_selected') {
    $selectedLinks = array_values(array_unique(array_filter(array_map('trim', (array) ($_POST['selected_links'] ?? [])))));
    if (!$selectedLinks) {
      admin_flash_set('error', 'Selecione pelo menos um produto da lista da Shopee para importar.');
      header('Location: /admin/importar.php?' . admin_import_query());
      exit;
    }

    $previewPayloadEncoded = trim((string) ($_POST['preview_payload'] ?? ''));
    $previewPayloadItems = [];
    if ($previewPayloadEncoded !== '') {
      $decodedPayload = base64_decode($previewPayloadEncoded, true);
      if (is_string($decodedPayload) && $decodedPayload !== '') {
        $parsedPayload = json_decode($decodedPayload, true);
        if (is_array($parsedPayload)) {
          $previewPayloadItems = $parsedPayload;
        }
      }
    }

    $runtimeDir = admin_python_job_runtime_dir();
    if (!$runtimeDir || !is_dir($runtimeDir)) {
      admin_flash_set('error', 'Nao foi possivel preparar a fila de importacao do admin.');
      header('Location: /admin/importar.php?' . admin_import_query());
      exit;
    }

    $jobKeyword = trim((string) ($_POST['job_keyword'] ?? ''));
    $previewItemsByUrl = [];
    foreach ($previewPayloadItems as $previewItem) {
      if (!is_array($previewItem)) {
        continue;
      }
      $previewUrl = trim((string) ($previewItem['url'] ?? ''));
      if ($previewUrl === '') {
        continue;
      }
      $previewItem['store'] = 'Shopee';
      $previewItemsByUrl[$previewUrl] = $previewItem;
    }

    $selectedItems = [];
    foreach ($selectedLinks as $selectedLink) {
      if (isset($previewItemsByUrl[$selectedLink])) {
        $selectedItems[] = $previewItemsByUrl[$selectedLink];
      }
    }

    if (!$selectedItems) {
      admin_flash_set('error', 'Nao consegui recuperar os produtos selecionados da busca atual. Pesquise novamente e tente importar.');
      header('Location: /admin/importar.php?' . admin_import_query());
      exit;
    }

    $target = $runtimeDir . DIRECTORY_SEPARATOR . 'import-shopee-selected-' . gmdate('YmdHis') . '-' . bin2hex(random_bytes(4)) . '.json';
    file_put_contents($target, json_encode($selectedItems, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES));

    $args = ['import-shopee-selected', '--input-file', $target];
    if ($currentAdminLogin !== '') {
      $args[] = '--actor-user-id';
      $args[] = (string) admin_user_id();
      $args[] = '--actor-login';
      $args[] = $currentAdminLogin;
    }
    $redirectUrl = '/admin/importar.php';
    $queryString = admin_import_query([
      'shopee_q' => $jobKeyword !== '' ? $jobKeyword : $previewKeyword,
      'shopee_page' => $previewPage,
    ]);
    if ($queryString !== '') {
      $redirectUrl .= '?' . $queryString;
    }
    $started = admin_start_python_job_async($args, [
      'kind' => 'import_shopee_selected',
      'target_tab' => 'importar',
      'keyword' => $jobKeyword,
      'selected_count' => count($selectedLinks),
      'cleanup_path' => $target,
    ]);
    if (empty($started['ok'])) {
      @unlink($target);
      admin_flash_set('error', (string) ($started['error'] ?? 'Falha ao iniciar importacao selecionada da Shopee.'));
      header('Location: ' . $redirectUrl);
      exit;
    }
    $_SESSION['admin_import_pending_job'] = [
      'job_id' => (string) ($started['job_id'] ?? ''),
      'kind' => 'import_shopee_selected',
      'keyword' => $jobKeyword,
      'selected_count' => count($selectedLinks),
      'cleanup_path' => $target,
      'redirect_url' => $redirectUrl,
    ];
    header('Location: ' . $redirectUrl);
    exit;
  } elseif ($action === 'refresh_existing_offers') {
    $targetStore = trim((string) ($_POST['target_store'] ?? ''));
    $singleOfferId = (int) ($_POST['single_offer_id'] ?? 0);
    $selectedOfferIds = array_values(array_unique(array_filter(array_map('intval', (array) ($_POST['selected_offer_ids'] ?? [])))));
    if ($singleOfferId > 0) {
      $selectedOfferIds = [$singleOfferId];
    }
    $batchLimit = (int) ($_POST['batch_limit'] ?? 25);
    if (!in_array($batchLimit, $refreshBatchLimits, true)) {
      $batchLimit = 25;
    }
    $shopeeVideoState = trim((string) ($_POST['shopee_video_state'] ?? 'all'));
    if (!in_array($shopeeVideoState, ['all', 'with', 'without'], true)) {
      $shopeeVideoState = 'all';
    }
    if (!in_array($targetStore, ['shopee', 'amazon', 'mercadolivre'], true)) {
      admin_flash_set('error', 'Loja invalida para atualizacao.');
      header('Location: ' . admin_import_inventory_query());
      exit;
    }

    $args = [
      'refresh-existing-offers',
      '--store',
      $targetStore,
      '--limit',
      (string) $batchLimit,
      '--max-images',
      '5',
    ];
    if ($targetStore === 'shopee') {
      $args[] = '--shopee-video-state';
      $args[] = $shopeeVideoState;
    }
    foreach ($selectedOfferIds as $offerId) {
      $args[] = '--offer-id';
      $args[] = (string) $offerId;
    }

    $redirectUrl = admin_import_inventory_query(['inventory_page' => 1]);
    $started = admin_start_python_job_async($args, [
      'kind' => 'refresh_existing_offers',
      'target_tab' => 'importar',
      'store' => $targetStore,
      'selected_count' => count($selectedOfferIds),
      'shopee_video_state' => $shopeeVideoState,
      'redirect_url' => $redirectUrl,
      'limit_requested' => $batchLimit,
    ]);
    if (empty($started['ok'])) {
      admin_flash_set('error', (string) ($started['error'] ?? 'Falha ao iniciar a atualizacao da loja.'));
      header('Location: ' . $redirectUrl);
      exit;
    }
    $_SESSION['admin_import_pending_job'] = [
      'job_id' => (string) ($started['job_id'] ?? ''),
      'kind' => 'refresh_existing_offers',
      'store' => $targetStore,
      'selected_count' => count($selectedOfferIds),
      'shopee_video_state' => $shopeeVideoState,
      'limit_requested' => $batchLimit,
      'redirect_url' => $redirectUrl,
    ];
    header('Location: ' . $redirectUrl);
    exit;
  } elseif ($action === 'refresh_all_store_offers') {
    $targetStore = trim((string) ($_POST['target_store'] ?? ''));
    $inventoryTotal = max(0, (int) ($_POST['inventory_total'] ?? 0));
    $shopeeVideoState = trim((string) ($_POST['shopee_video_state'] ?? 'all'));
    if (!in_array($shopeeVideoState, ['all', 'with', 'without'], true)) {
      $shopeeVideoState = 'all';
    }
    if (!in_array($targetStore, ['shopee', 'amazon', 'mercadolivre'], true)) {
      admin_flash_set('error', 'Loja invalida para atualizacao completa.');
      header('Location: ' . admin_import_inventory_query());
      exit;
    }
    if ($inventoryTotal <= 0) {
      admin_flash_set('error', 'Nenhum produto encontrado para atualizar nesta aba.');
      header('Location: ' . admin_import_inventory_query());
      exit;
    }

    $args = [
      'refresh-existing-offers',
      '--store',
      $targetStore,
      '--limit',
      (string) $inventoryTotal,
      '--max-images',
      '5',
    ];
    if ($targetStore === 'shopee') {
      $args[] = '--shopee-video-state';
      $args[] = $shopeeVideoState;
    }

    $redirectUrl = admin_import_inventory_query(['inventory_page' => 1]);
    $started = admin_start_python_job_async($args, [
      'kind' => 'refresh_existing_offers',
      'target_tab' => 'importar',
      'store' => $targetStore,
      'selected_count' => 0,
      'all_products' => 1,
      'shopee_video_state' => $shopeeVideoState,
      'redirect_url' => $redirectUrl,
      'limit_requested' => $inventoryTotal,
    ]);
    if (empty($started['ok'])) {
      admin_flash_set('error', (string) ($started['error'] ?? 'Falha ao iniciar a atualizacao completa da loja.'));
      header('Location: ' . $redirectUrl);
      exit;
    }
    $_SESSION['admin_import_pending_job'] = [
      'job_id' => (string) ($started['job_id'] ?? ''),
      'kind' => 'refresh_existing_offers',
      'store' => $targetStore,
      'selected_count' => 0,
      'all_products' => 1,
      'shopee_video_state' => $shopeeVideoState,
      'limit_requested' => $inventoryTotal,
      'redirect_url' => $redirectUrl,
    ];
    header('Location: ' . $redirectUrl);
    exit;
  } elseif ($action === 'repair_shopee_media') {
    $singleOfferId = (int) ($_POST['single_offer_id'] ?? 0);
    $offerIds = array_values(array_unique(array_filter(array_map('intval', (array) ($_POST['selected_offer_ids'] ?? [])))));
    if ($singleOfferId > 0) {
      $offerIds = [$singleOfferId];
    }
    if (!$offerIds) {
      admin_flash_set('error', 'Selecione pelo menos uma oferta Shopee para importar midia.');
      header('Location: ' . admin_import_inventory_query());
      exit;
    }

    $args = ['repair-shopee-media'];
    foreach ($offerIds as $offerId) {
      $args[] = '--offer-id';
      $args[] = (string) $offerId;
    }

    $redirectUrl = admin_import_inventory_query(['inventory_page' => 1]);
    $started = admin_start_python_job_async($args, [
      'kind' => 'repair_shopee_media',
      'target_tab' => 'importar',
      'store' => 'shopee',
      'selected_count' => count($offerIds),
      'redirect_url' => $redirectUrl,
      'limit_requested' => count($offerIds),
    ]);
    if (empty($started['ok'])) {
      admin_flash_set('error', (string) ($started['error'] ?? 'Falha ao iniciar a importacao de midia da Shopee.'));
      header('Location: ' . $redirectUrl);
      exit;
    }
    $_SESSION['admin_import_pending_job'] = [
      'job_id' => (string) ($started['job_id'] ?? ''),
      'kind' => 'repair_shopee_media',
      'store' => 'shopee',
      'selected_count' => count($offerIds),
      'limit_requested' => count($offerIds),
      'redirect_url' => $redirectUrl,
    ];
    header('Location: ' . $redirectUrl);
    exit;
  } elseif ($action === 'create_shopee_video_drafts') {
    $singleOfferId = (int) ($_POST['single_offer_id'] ?? 0);
    $offerIds = array_values(array_unique(array_filter(array_map('intval', (array) ($_POST['selected_offer_ids'] ?? [])))));
    if ($singleOfferId > 0) {
      $offerIds = [$singleOfferId];
    }
    if (!$offerIds) {
      admin_flash_set('error', 'Selecione pelo menos uma oferta Shopee sem video.');
      header('Location: ' . admin_import_inventory_query());
      exit;
    }
    foreach ($offerIds as $offerId) {
      admin_upsert_shopee_video_draft($pdo, $offerId, 'manual', admin_user_id(), $currentAdminLogin);
    }
    admin_flash_set('success', count($offerIds) . ' rascunho(s) de Shopee Video gerados/atualizados.');
    header('Location: ' . admin_import_inventory_query());
    exit;
  } elseif ($action === 'build_short_links_helper') {
    if ($shortLinkPageUrl === '') {
      admin_flash_set('error', 'Cole a URL da pagina que sera usada para gerar os links curtos.');
      header('Location: /admin/importar.php?' . admin_import_query(['view' => 'short_links']));
      exit;
    }
    $pageUrlValid = filter_var($shortLinkPageUrl, FILTER_VALIDATE_URL) && preg_match('#^https?://#i', $shortLinkPageUrl);
    if (!$pageUrlValid) {
      admin_flash_set('error', 'Informe uma URL valida para a pagina de ofertas.');
      header('Location: /admin/importar.php?' . admin_import_query(['view' => 'short_links']));
      exit;
    }
    if ($shortLinkProvider === 'amazon' && stripos($shortLinkPageUrl, 'amazon.') === false) {
      admin_flash_set('error', 'Use uma URL da Amazon para o helper da Amazon.');
      header('Location: /admin/importar.php?' . admin_import_query(['view' => 'short_links']));
      exit;
    }
    if ($shortLinkProvider === 'mercadolivre' && stripos($shortLinkPageUrl, 'mercadolivre.') === false) {
      admin_flash_set('error', 'Use uma URL do Mercado Livre para o helper do Mercado Livre.');
      header('Location: /admin/importar.php?' . admin_import_query(['view' => 'short_links']));
      exit;
    }

    if ($shortLinkProvider === 'amazon') {
      $shortLinkHelperPayload = [
        'provider' => 'amazon',
        'page_url' => $shortLinkPageUrl,
        'limit' => max(1, min($shortLinkLimit, 10)),
        'command' => admin_build_amazon_short_links_command($shortLinkPageUrl, $shortLinkLimit),
      ];
    } else {
      $shortLinkHelperPayload = [
        'provider' => 'mercadolivre',
        'page_url' => $shortLinkPageUrl,
        'limit' => $shortLinkLimit,
        'script' => admin_build_mercadolivre_short_links_snippet($shortLinkLimit, $shortLinkExtraOnly, $shortLinkBestSellerOnly),
      ];
    }
  }

  if ($resultPayload !== null) {
    if (!empty($resultPayload['ok'])) {
      $summary = admin_import_result_summary($resultPayload);
      $processed = (int) ($summary['processed'] ?? 0);
      $created = (int) ($summary['created'] ?? 0);
      $updated = (int) ($summary['updated'] ?? 0);
      $skipped = (int) ($summary['skipped'] ?? 0);
      $selected = (int) ($summary['selected'] ?? 0);
      $limitRequested = (int) ($summary['limit_requested'] ?? 0);
      $keywordLabel = trim((string) ($summary['keyword'] ?? ''));
      $keywordSuffix = $keywordLabel !== '' ? " Busca: {$keywordLabel}." : '';
      $withoutVideo = (int) ($summary['without_video'] ?? 0);
      $draftsCreated = (int) ($summary['drafts_created'] ?? 0);
      $draftsUpdated = (int) ($summary['drafts_updated'] ?? 0);
      $withoutVideoTitles = array_slice((array) ($summary['without_video_titles'] ?? []), 0, 3);
      $draftSuffix = '';
      if ($withoutVideo > 0) {
        $draftSuffix = " Sem video: {$withoutVideo}. Rascunhos criados/atualizados: {$draftsCreated}/{$draftsUpdated}.";
        if ($withoutVideoTitles) {
          $draftSuffix .= ' Lista: ' . implode(' | ', $withoutVideoTitles) . '.';
        }
      }

      if (($created + $updated) > 0) {
        if ($action === 'import_shopee_job' && $limitRequested > 0) {
          admin_flash_set('success', "Job Shopee concluido: lote {$limitRequested}, {$selected} selecionada(s), {$created} criada(s), {$updated} atualizada(s), {$skipped} pulada(s).{$keywordSuffix}{$draftSuffix}");
        } else {
          admin_flash_set('success', "Importacao concluida: {$created} criada(s), {$updated} atualizada(s), {$skipped} pulada(s).");
        }
      } else {
        if ($action === 'import_shopee_job' && $limitRequested > 0) {
          admin_flash_set('error', "Job Shopee concluido sem gravar ofertas: lote {$limitRequested}, {$processed} processada(s), {$skipped} pulada(s).{$keywordSuffix}");
        } else {
          admin_flash_set('error', "Importacao concluida sem gravar ofertas: {$processed} processada(s), {$skipped} pulada(s).");
        }
      }
    } else {
      admin_flash_set('error', (string) ($resultPayload['error'] ?? 'Falha ao executar importacao.'));
    }
    $redirectUrl = '/admin/importar.php';
    $queryString = admin_import_query();
    if ($queryString !== '') {
      $redirectUrl .= '?' . $queryString;
    }
    header('Location: ' . $redirectUrl);
    exit;
  }
}

if ($importView === 'shopee_search' && $previewKeyword !== '') {
  $previewPayload = admin_run_python_job([
    'shopee-preview',
    '--keyword',
    $previewKeyword,
    '--page',
    (string) $previewPage,
    '--limit',
    (string) $previewLimit,
  ]);
  if (!empty($previewPayload['ok']) && is_array($previewPayload['result'] ?? null)) {
    $previewResult = (array) $previewPayload['result'];
    $previewItems = is_array($previewResult['items'] ?? null) ? $previewResult['items'] : [];
    $previewHasMore = !empty($previewResult['has_more']);
  } else {
    $previewError = trim((string) ($previewPayload['error'] ?? 'Falha ao pesquisar produtos da Shopee.'));
  }
}

$importViewsMeta = [
  'shopee_search' => [
    'label' => 'Buscar Shopee',
    'kicker' => 'Importacao assistida',
    'title' => 'Importar e reimportar ofertas',
    'description' => 'Busque na Shopee, rode jobs oficiais e importe arquivo ou links manualmente.',
  ],
  'shopee_with_video' => [
    'label' => 'Shopee com video',
    'kicker' => 'Shopee reimportacao',
    'title' => 'Shopee importados com video',
    'description' => 'Lista as ofertas da Shopee que ja tem video salvo. Reimporte em lotes de 25, 50 ou 100 mantendo no maximo 5 imagens.',
  ],
  'shopee_without_video' => [
    'label' => 'Shopee sem video',
    'kicker' => 'Shopee reimportacao',
    'title' => 'Shopee importados sem video',
    'description' => 'Reimporte os cadastrados, detecte video nativo durante o refresh e gere rascunhos para o fluxo do Shopee Video quando ainda faltar video.',
  ],
  'amazon_update' => [
    'label' => 'Atualizar Amazon',
    'kicker' => 'Atualizacao por loja',
    'title' => 'Atualizar ofertas Amazon',
    'description' => 'Reimporta produtos ja cadastrados da Amazon para atualizar preco, titulo, texto e imagens salvas.',
  ],
  'mercadolivre_update' => [
    'label' => 'Atualizar Mercado Livre',
    'kicker' => 'Atualizacao por loja',
    'title' => 'Atualizar ofertas Mercado Livre',
    'description' => 'Reimporta os produtos cadastrados do Mercado Livre para atualizar preco, texto, imagem principal e novas imagens quando a origem trouxer.',
  ],
  'short_links' => [
    'label' => 'Links curtos',
    'kicker' => 'Helper local',
    'title' => 'Gerar links curtos de afiliado',
    'description' => 'Monte um helper para Amazon ou Mercado Livre usando a pagina que voce quer abrir no navegador e depois cole os links curtos aqui para importar.',
  ],
];
$currentViewMeta = $importViewsMeta[$importView] ?? $importViewsMeta['shopee_search'];
$inventoryCounts = admin_import_inventory_counts($pdo);
$inventoryStore = '';
$inventoryVideoState = 'all';
$inventoryTitle = '';
$inventoryDescription = '';
$inventoryEmptyMessage = '';
$inventoryActionHelp = '';
$inventoryItemsPayload = ['items' => [], 'total' => 0, 'page' => 1, 'pages' => 1, 'limit' => $inventoryLimit];

if ($importView === 'shopee_with_video') {
  $inventoryStore = 'Shopee';
  $inventoryVideoState = 'with';
  $inventoryTitle = 'Shopee importados com video';
  $inventoryDescription = 'Esses produtos ja tem video salvo na oferta. Se forem reimportados e perderem o video de origem, o video atual continua preservado.';
  $inventoryEmptyMessage = 'Nenhuma oferta Shopee com video foi encontrada.';
  $inventoryActionHelp = 'Sem selecao, o sistema atualiza o proximo lote da Shopee com video usando o limite escolhido.';
  $inventoryItemsPayload = admin_import_fetch_inventory($pdo, 'Shopee', $inventoryPage, $inventoryLimit, 'with');
} elseif ($importView === 'shopee_without_video') {
  $inventoryStore = 'Shopee';
  $inventoryVideoState = 'without';
  $inventoryTitle = 'Shopee importados sem video';
  $inventoryDescription = 'Produtos sem video ficam aqui. Quando ganham video no refresh ou no Shopee Video, saem desta lista automaticamente.';
  $inventoryEmptyMessage = 'Nenhuma oferta Shopee sem video ficou pendente.';
  $inventoryActionHelp = 'Sem selecao, o sistema reimporta o proximo lote sem video. Use o botao de Shopee Video para gerar rascunhos do que continuar sem video.';
  $inventoryItemsPayload = admin_import_fetch_inventory($pdo, 'Shopee', $inventoryPage, $inventoryLimit, 'without');
} elseif ($importView === 'amazon_update') {
  $inventoryStore = 'Amazon';
  $inventoryTitle = 'Atualizar cadastrados da Amazon';
  $inventoryDescription = 'Atualiza novamente os links ja salvos da Amazon para puxar preco, titulo, descricao e imagens mais recentes.';
  $inventoryEmptyMessage = 'Nenhuma oferta Amazon cadastrada foi encontrada.';
  $inventoryActionHelp = 'Sem selecao, o sistema atualiza o proximo lote da Amazon usando o limite escolhido.';
  $inventoryItemsPayload = admin_import_fetch_inventory($pdo, 'Amazon', $inventoryPage, $inventoryLimit);
} elseif ($importView === 'mercadolivre_update') {
  $inventoryStore = 'Mercado Livre';
  $inventoryTitle = 'Atualizar cadastrados do Mercado Livre';
  $inventoryDescription = 'Atualiza os produtos ja cadastrados do Mercado Livre. Se a origem trouxer imagens extras, elas entram respeitando o limite maximo de 5 imagens.';
  $inventoryEmptyMessage = 'Nenhuma oferta Mercado Livre cadastrada foi encontrada.';
  $inventoryActionHelp = 'Sem selecao, o sistema atualiza o proximo lote do Mercado Livre usando o limite escolhido.';
  $inventoryItemsPayload = admin_import_fetch_inventory($pdo, 'Mercado Livre', $inventoryPage, $inventoryLimit);
}

$inventoryItems = (array) ($inventoryItemsPayload['items'] ?? []);
$inventoryTotal = (int) ($inventoryItemsPayload['total'] ?? 0);
$inventoryPage = (int) ($inventoryItemsPayload['page'] ?? $inventoryPage);
$inventoryPages = (int) ($inventoryItemsPayload['pages'] ?? 1);
$inventoryLimit = (int) ($inventoryItemsPayload['limit'] ?? $inventoryLimit);

$pendingImportTitle = 'Operacao em andamento';
$pendingImportText = 'O job esta rodando no servidor. Pode aguardar nesta tela.';
$pendingProgressLabel = 'Iniciando job da Shopee...';
if (is_array($pendingImportJob)) {
  $pendingKind = (string) ($pendingImportJob['kind'] ?? '');
  if ($pendingKind === 'refresh_existing_offers') {
    $pendingStore = strtolower(trim((string) ($pendingImportJob['store'] ?? '')));
    $pendingStoreLabel = $pendingStore === 'mercadolivre' ? 'Mercado Livre' : ($pendingStore === 'amazon' ? 'Amazon' : ($pendingStore === 'shopee' ? 'Shopee' : 'loja'));
    $pendingImportTitle = 'Atualizacao em andamento';
    $pendingImportText = $pendingStore !== ''
      ? 'A reimportacao de ' . $pendingStoreLabel . ' esta rodando no servidor.'
      : 'A reimportacao da loja esta rodando no servidor.';
    $pendingProgressLabel = 'Iniciando atualizacao da loja...';
  } elseif ($pendingKind === 'repair_shopee_media') {
    $pendingImportTitle = 'Importacao de midia em andamento';
    $pendingImportText = 'As imagens e videos das ofertas selecionadas da Shopee estao sendo reenriquecidos no servidor.';
    $pendingProgressLabel = 'Iniciando importacao de midia da Shopee...';
  } elseif ($pendingKind === 'import_shopee_selected') {
    $pendingImportTitle = 'Importacao selecionada em andamento';
    $pendingImportText = 'Os produtos escolhidos da Shopee estao sendo importados no servidor.';
    $pendingProgressLabel = 'Iniciando importacao selecionada...';
  }
}
?>
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Admin - Importar</title>
  <link rel="icon" type="image/png" href="/assets/img/logo-zp.png">
  <link rel="stylesheet" href="/assets/css/style.css">
  <link rel="stylesheet" href="/assets/css/admin.css?v=<?= urlencode($adminCssVersion) ?>">
</head>
<body class="admin-page">
<?php admin_render_header('importar'); ?>

<main class="container admin-shell">
  <?php if ($flash): ?>
    <div class="admin-alert <?= h((string) ($flash['type'] ?? '')) ?>"><?= h((string) ($flash['message'] ?? '')) ?></div>
  <?php endif; ?>

  <?php if (is_array($pendingImportJob) && !empty($pendingImportJob['job_id'])): ?>
    <section class="admin-panel" id="import-job-progress" data-import-job-id="<?= h((string) $pendingImportJob['job_id']) ?>">
      <div class="admin-panel-head">
        <div>
          <h2 class="admin-section-title"><?= h($pendingImportTitle) ?></h2>
          <p><?= h($pendingImportText) ?></p>
        </div>
      </div>
      <div class="admin-help" id="import-job-progress-label"><?= h($pendingProgressLabel) ?></div>
      <div style="margin-top:12px; background:#dbe7ff; border-radius:999px; overflow:hidden; height:14px;">
        <div id="import-job-progress-bar" style="width:8%; height:14px; background:linear-gradient(90deg,#1947d1,#4f7dff); transition:width .3s ease;"></div>
      </div>
    </section>
  <?php endif; ?>

  <section class="admin-hero">
    <div class="admin-hero-head">
      <div class="admin-hero-copy">
        <span class="admin-kicker"><?= h((string) ($currentViewMeta['kicker'] ?? 'Importacao')) ?></span>
        <h1><?= h((string) ($currentViewMeta['title'] ?? 'Importar ofertas')) ?></h1>
        <p><?= h((string) ($currentViewMeta['description'] ?? '')) ?></p>
      </div>
    </div>
  </section>

  <nav class="admin-subnav" aria-label="Submenu Importar">
    <?php foreach ($importViewsMeta as $viewKey => $viewMeta): ?>
      <?php $countLabel = in_array($viewKey, ['shopee_search', 'short_links'], true) ? '' : ' (' . (int) ($inventoryCounts[$viewKey] ?? 0) . ')'; ?>
      <a class="admin-subnav-link <?= $viewKey === $importView ? 'is-active' : '' ?>" href="<?= h(admin_import_inventory_query(['view' => $viewKey, 'inventory_page' => 1])) ?>">
        <?= h((string) ($viewMeta['label'] ?? 'Importar') . $countLabel) ?>
      </a>
    <?php endforeach; ?>
  </nav>

  <?php if ($importView === 'shopee_search'): ?>
  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Job Shopee API</h2>
        <p>Roda o importador oficial da Shopee via Python no DreamHost. Quando encontrar galeria e video, a oferta salva no maximo 5 imagens.</p>
      </div>
    </div>
    <form method="post">
      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
      <input type="hidden" name="acao" value="import_shopee_job">
      <div class="admin-field-grid">
        <div class="admin-field is-full">
          <label for="job_keyword">Pesquisar produto ou colar link da Shopee</label>
          <input id="job_keyword" type="text" name="job_keyword" value="<?= h($previewKeyword) ?>" placeholder="Ex.: fone bluetooth, iphone 13 ou https://shopee.com.br/product/...">
        </div>
        <div class="admin-field">
          <label for="job_limit">Quantidade de produtos</label>
          <select id="job_limit" name="job_limit">
            <?php foreach ($shopeeJobLimits as $jobLimitOption): ?>
              <option value="<?= (int) $jobLimitOption ?>" <?= $jobLimitOption === 25 ? 'selected' : '' ?>><?= (int) $jobLimitOption ?> produto<?= $jobLimitOption === 1 ? '' : 's' ?></option>
            <?php endforeach; ?>
          </select>
        </div>
        <div class="admin-field">
          <label>Execucao</label>
          <div class="admin-help" style="margin-top:12px;">Provider fixo: Shopee. O job aplica enriquecimento de midia e poda a galeria para as 5 primeiras imagens.</div>
        </div>
      </div>
      <div class="admin-form-actions">
        <button class="btn" type="submit">Rodar job Shopee</button>
      </div>
    </form>
  </section>

  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Pesquisar Shopee</h2>
        <p>Busque o produto que voce quer importar, revise a lista e selecione os itens desejados.</p>
      </div>
    </div>
    <form method="get">
      <input type="hidden" name="view" value="shopee_search">
      <div class="admin-field-grid">
        <div class="admin-field is-full">
          <label for="shopee_q">Nome do produto ou link direto da Shopee</label>
          <input id="shopee_q" type="text" name="shopee_q" value="<?= h($previewKeyword) ?>" placeholder="Ex.: iphone 13, fone bluetooth ou https://shopee.com.br/opaanlp/..." required>
        </div>
        <div class="admin-field">
          <label for="shopee_preview_limit">Itens por pagina</label>
          <select id="shopee_preview_limit" name="shopee_preview_limit">
            <?php foreach ([6, 12, 24] as $previewLimitOption): ?>
              <option value="<?= (int) $previewLimitOption ?>" <?= $previewLimitOption === $previewLimit ? 'selected' : '' ?>><?= (int) $previewLimitOption ?> itens</option>
            <?php endforeach; ?>
          </select>
        </div>
        <div class="admin-field">
          <label>&nbsp;</label>
          <input type="hidden" name="shopee_page" value="1">
          <button class="btn" type="submit">Pesquisar</button>
        </div>
      </div>
    </form>

    <?php if ($previewError !== ''): ?>
      <div class="admin-alert error" style="margin-top:16px;"><?= h($previewError) ?></div>
    <?php elseif ($previewKeyword !== ''): ?>
      <div class="admin-help" style="margin-top:16px;">Busca atual: <strong><?= h($previewKeyword) ?></strong> | Pagina <?= (int) $previewPage ?></div>
      <?php if (!$previewItems): ?>
        <div class="admin-empty" style="margin-top:16px;">Nenhum produto encontrado nesta pagina.</div>
      <?php else: ?>
        <form method="post" style="margin-top:16px;">
          <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
          <input type="hidden" name="acao" value="import_shopee_selected">
          <input type="hidden" name="job_keyword" value="<?= h($previewKeyword) ?>">
          <input type="hidden" name="preview_payload" value="<?= h(base64_encode(json_encode($previewItems, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES))) ?>">
          <div class="admin-offers-grid">
            <?php foreach ($previewItems as $item): ?>
              <?php
                $itemTitle = trim((string) ($item['title'] ?? 'Oferta Shopee'));
                $itemUrl = trim((string) ($item['url'] ?? ''));
                $itemImage = trim((string) ($item['image'] ?? ''));
                $itemPrice = isset($item['price']) ? (float) $item['price'] : 0.0;
                $itemSales = (int) ($item['sales'] ?? 0);
                $itemCommission = isset($item['commission_rate']) ? (float) $item['commission_rate'] : 0.0;
              ?>
              <article class="admin-offer-card">
                <div class="admin-meta-row">
                  <label style="display:flex; align-items:center; gap:8px;">
                    <input type="checkbox" name="selected_links[]" value="<?= h($itemUrl) ?>" checked>
                    <span class="admin-meta-chip">Selecionar</span>
                  </label>
                </div>
                <?php if ($itemImage !== ''): ?>
                  <div style="margin-top:12px;">
                    <img src="<?= h($itemImage) ?>" alt="<?= h($itemTitle) ?>" style="width:100%; max-height:220px; object-fit:contain; border-radius:18px; background:#f4f7fb;">
                  </div>
                <?php endif; ?>
                <h3 style="margin-top:14px; font-size:1.05rem; line-height:1.35;"><?= h($itemTitle) ?></h3>
                <div class="admin-meta-row" style="margin-top:12px;">
                  <span class="admin-meta-chip">R$ <?= h(number_format($itemPrice, 2, ',', '.')) ?></span>
                  <span class="admin-meta-chip"><?= (int) $itemSales ?> vendas</span>
                  <span class="admin-meta-chip">comissao <?= h(number_format($itemCommission, 2, ',', '.')) ?></span>
                </div>
                <?php if ($itemUrl !== ''): ?>
                  <div class="admin-form-actions" style="margin-top:12px;">
                    <a class="btn-link" href="<?= h($itemUrl) ?>" target="_blank" rel="noopener">Abrir link</a>
                  </div>
                <?php endif; ?>
              </article>
            <?php endforeach; ?>
          </div>
          <div class="admin-form-actions">
            <button class="btn" type="button" id="toggle-shopee-selection">Selecionar / desmarcar todos</button>
            <button class="btn" type="submit">Importar selecionados</button>
          </div>
        </form>
        <div class="admin-form-actions">
          <?php if ($previewPage > 1): ?>
            <a class="btn-link" href="/admin/importar.php?<?= h(admin_import_query(['shopee_page' => max(1, $previewPage - 1)])) ?>">Pagina anterior</a>
          <?php endif; ?>
          <?php if ($previewHasMore): ?>
            <a class="btn-link primary" href="/admin/importar.php?<?= h(admin_import_query(['shopee_page' => $previewPage + 1])) ?>">Proxima pagina</a>
          <?php endif; ?>
        </div>
      <?php endif; ?>
    <?php endif; ?>
  </section>

  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Importar por arquivo</h2>
        <p>Use CSV da Shopee ou TXT com links da Amazon/Mercado Livre. Os itens novos desta importacao ficam marcados com o login <?= h($currentAdminLogin ?: 'atual') ?>.</p>
      </div>
    </div>
    <form method="post" enctype="multipart/form-data">
      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
      <input type="hidden" name="acao" value="import_file">
      <div class="admin-field-grid">
        <div class="admin-field">
          <label for="kind">Tipo de arquivo</label>
          <select id="kind" name="kind">
            <option value="shopee_csv">Shopee CSV</option>
            <option value="amazon_txt">Amazon TXT</option>
            <option value="mercadolivre_txt">Mercado Livre TXT</option>
          </select>
        </div>
        <div class="admin-field">
          <label for="arquivo">Arquivo</label>
          <input id="arquivo" type="file" name="arquivo" required>
        </div>
      </div>
      <div class="admin-form-actions">
        <button class="btn" type="submit">Importar arquivo</button>
      </div>
    </form>
  </section>

  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Importar por texto e links</h2>
        <p>Cole um link por linha. O Python identifica a loja, tenta ler os dados e grava as ofertas validas com autoria do login atual.</p>
      </div>
    </div>
    <form method="post">
      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
      <input type="hidden" name="acao" value="import_links">
      <div class="admin-field-grid">
        <div class="admin-field is-full">
          <label for="links">Links</label>
          <textarea id="links" name="links" rows="8" placeholder="https://...&#10;https://..."></textarea>
        </div>
      </div>
      <div class="admin-form-actions">
        <button class="btn" type="submit">Importar links</button>
      </div>
    </form>
  </section>
  <?php elseif ($importView === 'short_links'): ?>
  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Montar helper de links curtos</h2>
        <p>Escolha a loja, cole a URL da pagina e monte o helper. Depois voce roda isso no seu navegador ou no seu Windows e cola os links curtos aqui mesmo para importar.</p>
      </div>
    </div>
    <form method="post" action="/admin/importar.php?<?= h(admin_import_query(['view' => 'short_links'])) ?>">
      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
      <input type="hidden" name="acao" value="build_short_links_helper">
      <div class="admin-field-grid">
        <div class="admin-field">
          <label for="short_provider">Loja</label>
          <select id="short_provider" name="short_provider">
            <option value="amazon" <?= $shortLinkProvider === 'amazon' ? 'selected' : '' ?>>Amazon</option>
            <option value="mercadolivre" <?= $shortLinkProvider === 'mercadolivre' ? 'selected' : '' ?>>Mercado Livre</option>
          </select>
        </div>
        <div class="admin-field">
          <label for="short_limit">Limite</label>
          <input id="short_limit" type="number" name="short_limit" min="1" max="100" value="<?= (int) $shortLinkLimit ?>">
        </div>
        <div class="admin-field is-full">
          <label for="short_page_url">URL da pagina</label>
          <input id="short_page_url" type="url" name="short_page_url" value="<?= h($shortLinkPageUrl) ?>" placeholder="https://www.amazon.com.br/deals... ou https://www.mercadolivre.com.br/afiliados/hub..." required>
        </div>
        <div class="admin-field">
          <label style="display:flex; align-items:center; gap:10px; margin-top:34px;">
            <input type="checkbox" name="short_extra_only" value="1" <?= $shortLinkExtraOnly ? 'checked' : '' ?>>
            <span>Mercado Livre: so ganhos extra</span>
          </label>
        </div>
        <div class="admin-field">
          <label style="display:flex; align-items:center; gap:10px; margin-top:34px;">
            <input type="checkbox" name="short_best_seller_only" value="1" <?= $shortLinkBestSellerOnly ? 'checked' : '' ?>>
            <span>Mercado Livre: so mais vendidos</span>
          </label>
        </div>
      </div>
      <div class="admin-form-actions">
        <button class="btn" type="submit">Montar helper</button>
        <?php if ($shortLinkPageUrl !== ''): ?>
          <a class="btn-link" href="<?= h($shortLinkPageUrl) ?>" target="_blank" rel="noopener">Abrir pagina</a>
        <?php endif; ?>
      </div>
    </form>
  </section>

  <?php if (is_array($shortLinkHelperPayload)): ?>
  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Helper pronto</h2>
        <p><?= h(admin_short_link_provider_label((string) ($shortLinkHelperPayload['provider'] ?? 'amazon'))) ?> | pagina base: <?= h((string) ($shortLinkHelperPayload['page_url'] ?? '')) ?></p>
      </div>
    </div>

    <?php if (($shortLinkHelperPayload['provider'] ?? '') === 'amazon'): ?>
      <div class="admin-help">Passo a passo Amazon: 1. abra o PowerShell na pasta do projeto local, 2. rode a preparacao uma vez, 3. rode o comando abaixo, 4. abra o TXT gerado e cole os links curtos na caixa de importacao.</div>
      <div class="admin-field-grid" style="margin-top:16px;">
        <div class="admin-field is-full">
          <label for="short_links_amazon_where">1. Rode dentro da pasta do projeto</label>
          <textarea id="short_links_amazon_where" rows="2" readonly>cd C:\Users\Windows\OneDrive\Documentos\ofertas-afiliados-mvp</textarea>
        </div>
        <div class="admin-field is-full">
          <label for="short_links_amazon_requirements">2. Preparacao local</label>
          <textarea id="short_links_amazon_requirements" rows="4" readonly>pip install playwright
python -m playwright install chrome</textarea>
        </div>
        <div class="admin-field is-full">
          <label for="short_links_amazon_command">3. Comando para gerar o TXT</label>
          <textarea id="short_links_amazon_command" rows="4" readonly><?= h((string) ($shortLinkHelperPayload['command'] ?? '')) ?></textarea>
        </div>
        <div class="admin-field is-full">
          <label for="short_links_amazon_after">4. O que esperar</label>
          <textarea id="short_links_amazon_after" rows="4" readonly>O script vai abrir o Chrome, pedir login manual se precisar e salvar um arquivo como amazon-short-links-10.txt na pasta do projeto. Depois abra esse TXT e cole os links abaixo em "Importar links gerados".</textarea>
        </div>
      </div>
    <?php else: ?>
      <div class="admin-help">Passo a passo Mercado Livre: 1. clique em Abrir pagina, 2. abra DevTools, 3. cole o script abaixo em Snippets ou no Console, 4. rode e espere o TXT baixar, 5. cole os links aqui embaixo.</div>
      <div class="admin-field-grid" style="margin-top:16px;">
        <div class="admin-field is-full">
          <label for="short_links_ml_where">1. Pagina para abrir</label>
          <textarea id="short_links_ml_where" rows="2" readonly><?= h((string) ($shortLinkHelperPayload['page_url'] ?? '')) ?></textarea>
        </div>
        <div class="admin-field is-full">
          <label for="short_links_ml_script">2. Script pronto</label>
          <textarea id="short_links_ml_script" rows="18" readonly><?= h((string) ($shortLinkHelperPayload['script'] ?? '')) ?></textarea>
        </div>
        <div class="admin-field is-full">
          <label for="short_links_ml_after">3. O que esperar</label>
          <textarea id="short_links_ml_after" rows="4" readonly>O navegador vai baixar um arquivo meli-short-links-helper.txt. Abra esse TXT e cole os meli.la abaixo em "Importar links gerados".</textarea>
        </div>
      </div>
    <?php endif; ?>
  </section>
  <?php endif; ?>

  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Importar links gerados</h2>
        <p>Depois de gerar o TXT ou copiar os links curtos, cole um por linha aqui. O importador ja reconhece Amazon e Mercado Livre automaticamente.</p>
      </div>
    </div>
    <form method="post" action="/admin/importar.php?<?= h(admin_import_query(['view' => 'short_links'])) ?>">
      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
      <input type="hidden" name="acao" value="import_links">
      <div class="admin-field-grid">
        <div class="admin-field is-full">
          <label for="short_links_import_text">Links curtos</label>
          <textarea id="short_links_import_text" name="links" rows="10" placeholder="https://amzn.to/...&#10;https://meli.la/..."></textarea>
        </div>
      </div>
      <div class="admin-form-actions">
        <button class="btn" type="submit">Importar links</button>
      </div>
    </form>
  </section>
  <?php else: ?>
  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title"><?= h($inventoryTitle) ?></h2>
        <p><?= h($inventoryDescription) ?></p>
      </div>
    </div>

    <div class="admin-offers-grid">
      <article class="admin-offer-card">
        <div class="admin-card-subtitle">Total cadastrado nesta fila</div>
        <div style="font-size:2rem; font-weight:800; line-height:1.1; margin-top:12px;"><?= (int) $inventoryTotal ?></div>
        <div class="admin-help" style="margin-top:10px;">Filtro atual: <?= h(admin_import_view_label($importView)) ?></div>
      </article>
      <article class="admin-offer-card">
        <div class="admin-card-subtitle">Lote operacional</div>
        <div style="font-size:2rem; font-weight:800; line-height:1.1; margin-top:12px;">25 / 50 / 100</div>
        <div class="admin-help" style="margin-top:10px;">Reimportacao em partes para o ciclo ficar previsivel.</div>
      </article>
      <article class="admin-offer-card">
        <div class="admin-card-subtitle">Midia salva</div>
        <div style="font-size:2rem; font-weight:800; line-height:1.1; margin-top:12px;">Max. 5 imagens</div>
        <div class="admin-help" style="margin-top:10px;">A galeria fica limitada as 5 primeiras imagens retornadas.</div>
      </article>
    </div>

    <form method="get" style="margin-top:18px;">
      <input type="hidden" name="view" value="<?= h($importView) ?>">
      <div class="admin-field-grid">
        <div class="admin-field">
          <label for="inventory_limit">Itens por pagina</label>
          <select id="inventory_limit" name="inventory_limit">
            <?php foreach ([12, 24, 48] as $inventoryLimitOption): ?>
              <option value="<?= (int) $inventoryLimitOption ?>" <?= $inventoryLimitOption === $inventoryLimit ? 'selected' : '' ?>><?= (int) $inventoryLimitOption ?> itens</option>
            <?php endforeach; ?>
          </select>
        </div>
        <div class="admin-field">
          <label>&nbsp;</label>
          <input type="hidden" name="inventory_page" value="1">
          <button class="btn" type="submit">Atualizar lista</button>
        </div>
      </div>
    </form>

    <form method="post" id="inventory-batch-form" style="margin-top:18px;">
      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
      <input type="hidden" name="acao" value="refresh_existing_offers" data-batch-action>
      <input type="hidden" name="target_store" value="<?= h($inventoryStore === 'Mercado Livre' ? 'mercadolivre' : strtolower($inventoryStore)) ?>">
      <input type="hidden" name="shopee_video_state" value="<?= h($inventoryVideoState) ?>">
      <input type="hidden" name="inventory_total" value="<?= (int) $inventoryTotal ?>">
      <input type="hidden" name="single_offer_id" value="" data-single-offer-id>

      <div class="admin-field-grid">
        <div class="admin-field">
          <label for="batch_limit">Lote de atualizacao</label>
          <select id="batch_limit" name="batch_limit">
            <?php foreach ($refreshBatchLimits as $refreshBatchLimit): ?>
              <option value="<?= (int) $refreshBatchLimit ?>" <?= $refreshBatchLimit === 25 ? 'selected' : '' ?>><?= (int) $refreshBatchLimit ?> ofertas</option>
            <?php endforeach; ?>
          </select>
        </div>
        <div class="admin-field is-full">
          <label>Como funciona</label>
          <div class="admin-help" style="margin-top:12px;"><?= h($inventoryActionHelp) ?></div>
        </div>
      </div>

      <div class="admin-form-actions">
        <button class="btn" type="button" id="toggle-inventory-selection">Selecionar / desmarcar todos</button>
        <button class="btn" type="submit" data-submit-action="refresh_existing_offers">Atualizar agora</button>
        <button class="btn-link" type="submit" data-submit-action="refresh_all_store_offers">Atualizar produtos</button>
        <?php if (strtolower($inventoryStore) === 'shopee'): ?>
          <button class="btn-link" type="submit" data-submit-action="repair_shopee_media">Importar midia Shopee</button>
        <?php endif; ?>
        <?php if ($importView === 'shopee_without_video'): ?>
          <button class="btn-link primary" type="submit" data-submit-action="create_shopee_video_drafts">Gerar video Shopee Video</button>
        <?php endif; ?>
      </div>

      <?php if (!$inventoryItems): ?>
        <div class="admin-empty" style="margin-top:16px;"><?= h($inventoryEmptyMessage) ?></div>
      <?php else: ?>
        <div class="admin-offers-grid" style="margin-top:18px;">
          <?php foreach ($inventoryItems as $offer): ?>
            <?php
              $offerId = (int) ($offer['id'] ?? 0);
              $offerTitle = trim((string) ($offer['titulo'] ?? 'Oferta'));
              $offerImage = trim((string) ($offer['imagem_url'] ?? ''));
              $offerUrl = trim((string) ($offer['url_afiliado'] ?? ''));
              $offerPrice = (float) ($offer['preco'] ?? 0);
              $offerActive = (int) ($offer['ativo'] ?? 0) === 1;
              $offerHasVideo = admin_import_offer_has_video((array) $offer);
              $offerImages = admin_shopee_video_decode_url_list($offer['imagem_urls_json'] ?? []);
              if (!$offerImages && $offerImage !== '') {
                $offerImages = [$offerImage];
              }
              $offerVideos = admin_shopee_video_decode_url_list($offer['video_urls_json'] ?? []);
              $draftId = (int) ($offer['draft_id'] ?? 0);
              $draftStatus = trim((string) ($offer['draft_status'] ?? ''));
              $updatedAt = trim((string) ($offer['atualizado_em'] ?? ''));
            ?>
            <article class="admin-offer-card">
              <div class="admin-meta-row">
                <label style="display:flex; align-items:center; gap:8px;">
                  <input type="checkbox" name="selected_offer_ids[]" value="<?= $offerId ?>">
                  <span class="admin-meta-chip">Oferta #<?= $offerId ?></span>
                </label>
                <span class="admin-status <?= $offerActive ? 'ok' : 'off' ?>"><?= $offerActive ? 'ativa' : 'inativa' ?></span>
              </div>
              <?php if ($offerImage !== ''): ?>
                <div style="margin-top:12px;">
                  <img src="<?= h($offerImage) ?>" alt="<?= h($offerTitle) ?>" style="width:100%; max-height:220px; object-fit:contain; border-radius:18px; background:#f4f7fb;">
                </div>
              <?php endif; ?>
              <h3 style="margin-top:14px; font-size:1.05rem; line-height:1.35;"><?= h($offerTitle) ?></h3>
              <div class="admin-meta-row" style="margin-top:12px;">
                <span class="admin-meta-chip">R$ <?= h(number_format($offerPrice, 2, ',', '.')) ?></span>
                <span class="admin-meta-chip"><?= h((string) ($offer['loja'] ?? '')) ?></span>
                <span class="admin-meta-chip"><?= $offerHasVideo ? 'com video' : 'sem video' ?></span>
              </div>
              <div class="admin-meta-row" style="margin-top:10px;">
                <span class="admin-meta-chip"><?= count($offerImages) ?> imagem(ns)</span>
                <span class="admin-meta-chip"><?= count($offerVideos) ?> video(s)</span>
                <?php if ($draftId > 0): ?>
                  <span class="admin-meta-chip">draft #<?= $draftId ?> <?= h($draftStatus) ?></span>
                <?php endif; ?>
              </div>
              <?php if ($updatedAt !== ''): ?>
                <div class="admin-help" style="margin-top:12px;">Atualizado em <?= h($updatedAt) ?></div>
              <?php endif; ?>
              <div class="admin-form-actions" style="margin-top:12px;">
                <?php if ($offerUrl !== ''): ?>
                  <a class="btn-link" href="<?= h($offerUrl) ?>" target="_blank" rel="noopener">Abrir afiliado</a>
                <?php endif; ?>
                <?php if (strtolower($inventoryStore) === 'shopee'): ?>
                  <button class="btn-link" type="submit" data-submit-action="repair_shopee_media" data-single-offer-id="<?= $offerId ?>">Importar midia Shopee</button>
                  <a class="btn-link" href="/admin/shopee_video.php?view=queue&q=<?= urlencode($offerTitle) ?>&page=1">Abrir Shopee Video</a>
                <?php endif; ?>
                <?php if ($importView === 'shopee_without_video'): ?>
                  <button class="btn-link primary" type="submit" data-submit-action="create_shopee_video_drafts" data-single-offer-id="<?= $offerId ?>">Gerar video Shopee Video</button>
                <?php endif; ?>
              </div>
            </article>
          <?php endforeach; ?>
        </div>
      <?php endif; ?>
    </form>

    <?php if ($inventoryPages > 1): ?>
      <div class="admin-form-actions" style="margin-top:18px;">
        <?php if ($inventoryPage > 1): ?>
          <a class="btn-link" href="<?= h(admin_import_inventory_query(['inventory_page' => max(1, $inventoryPage - 1)])) ?>">Pagina anterior</a>
        <?php endif; ?>
        <span class="admin-meta-chip">Pagina <?= (int) $inventoryPage ?> de <?= (int) $inventoryPages ?></span>
        <?php if ($inventoryPage < $inventoryPages): ?>
          <a class="btn-link primary" href="<?= h(admin_import_inventory_query(['inventory_page' => $inventoryPage + 1])) ?>">Proxima pagina</a>
        <?php endif; ?>
      </div>
    <?php endif; ?>
  </section>
  <?php endif; ?>

  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Historico de importacoes</h2>
        <p>Mostra os jobs de importacao registrados no banco.</p>
      </div>
    </div>
    <?php if (!$recentRuns): ?>
      <div class="admin-empty">Nenhuma importacao registrada ainda.</div>
    <?php else: ?>
      <div class="admin-offers-grid">
        <?php foreach ($recentRuns as $run): ?>
          <article class="admin-offer-card">
            <div class="admin-meta-row">
              <span class="admin-meta-chip">Run #<?= (int) $run['id'] ?></span>
              <span class="admin-status <?= $run['status'] === 'success' ? 'ok' : ($run['status'] === 'running' ? 'warn' : 'off') ?>"><?= h($run['status']) ?></span>
              <span class="admin-meta-chip"><?= h((string) ($run['provider'] ?? '-')) ?></span>
              <span class="admin-meta-chip">processado <?= (int) ($run['processed_count'] ?? 0) ?></span>
            </div>
            <div class="admin-help" style="margin-top:12px;">Criado em <?= h((string) $run['criado_em']) ?></div>
            <?php if (!empty($run['error_message'])): ?>
              <div class="admin-alert error" style="margin-top:12px;"><?= h((string) $run['error_message']) ?></div>
            <?php endif; ?>
          </article>
        <?php endforeach; ?>
      </div>
    <?php endif; ?>
  </section>
</main>
<script>
  (function () {
    var toggle = document.querySelector('[data-admin-menu-toggle]');
    var menu = document.querySelector('[data-admin-menu]');
    if (!toggle || !menu) {
      return;
    }

    function syncMenuState() {
      if (window.innerWidth > 640) {
        document.body.classList.remove('admin-menu-open');
        toggle.setAttribute('aria-expanded', 'false');
      }
    }

    toggle.addEventListener('click', function () {
      var isOpen = document.body.classList.toggle('admin-menu-open');
      toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    });

    window.addEventListener('resize', syncMenuState);
    syncMenuState();
  })();

  (function () {
    var toggleAllButton = document.getElementById('toggle-shopee-selection');
    if (!toggleAllButton) {
      return;
    }
    toggleAllButton.addEventListener('click', function () {
      var checkboxes = document.querySelectorAll('input[name="selected_links[]"]');
      if (!checkboxes.length) {
        return;
      }
      var shouldCheck = false;
      checkboxes.forEach(function (checkbox) {
        if (!checkbox.checked) {
          shouldCheck = true;
        }
      });
      checkboxes.forEach(function (checkbox) {
        checkbox.checked = shouldCheck;
      });
    });
  })();

  (function () {
    var batchForm = document.getElementById('inventory-batch-form');
    if (!batchForm) {
      return;
    }

    var actionInput = batchForm.querySelector('[data-batch-action]');
    var singleOfferInput = batchForm.querySelector('[data-single-offer-id]');
    var submitButtons = batchForm.querySelectorAll('[data-submit-action]');

    submitButtons.forEach(function (button) {
      button.addEventListener('click', function () {
        if (actionInput) {
          actionInput.value = button.getAttribute('data-submit-action') || 'refresh_existing_offers';
        }
        if (singleOfferInput) {
          singleOfferInput.value = button.getAttribute('data-single-offer-id') || '';
        }
      });
    });

    var toggleInventoryButton = document.getElementById('toggle-inventory-selection');
    if (toggleInventoryButton) {
      toggleInventoryButton.addEventListener('click', function () {
        var checkboxes = batchForm.querySelectorAll('input[name="selected_offer_ids[]"]');
        if (!checkboxes.length) {
          return;
        }
        var shouldCheck = false;
        checkboxes.forEach(function (checkbox) {
          if (!checkbox.checked) {
            shouldCheck = true;
          }
        });
        checkboxes.forEach(function (checkbox) {
          checkbox.checked = shouldCheck;
        });
      });
    }
  })();

  (function () {
    var progressRoot = document.getElementById('import-job-progress');
    if (!progressRoot) {
      return;
    }
    var jobId = progressRoot.getAttribute('data-import-job-id');
    var bar = document.getElementById('import-job-progress-bar');
    var label = document.getElementById('import-job-progress-label');
    if (!jobId || !bar || !label) {
      return;
    }

    function applyProgress(payload) {
      var percent = Math.max(4, Math.min(100, parseInt(payload.progress_percent || 0, 10) || 0));
      bar.style.width = percent + '%';
      label.textContent = payload.progress_label || 'Processando no servidor';
      if (payload.status === 'success' || payload.status === 'error') {
        if (payload.redirect_url) {
          window.location.href = payload.redirect_url;
          return;
        }
        window.location.reload();
      }
    }

    function poll() {
      fetch('/admin/import_job_status.php?job_id=' + encodeURIComponent(jobId), {
        credentials: 'same-origin'
      })
        .then(function (response) { return response.json(); })
        .then(function (payload) {
          if (!payload || payload.ok !== true) {
            label.textContent = payload && payload.error ? payload.error : 'Falha ao consultar o andamento do job.';
            bar.style.width = '100%';
            return;
          }
          applyProgress(payload);
          if (payload.status === 'running') {
            window.setTimeout(poll, 2000);
          }
        })
        .catch(function () {
          label.textContent = 'Falha ao consultar o andamento do job.';
          bar.style.width = '100%';
        });
    }

    window.setTimeout(poll, 1200);
  })();
</script>
</body>
</html>
