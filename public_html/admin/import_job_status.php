<?php
require_once __DIR__ . '/_init.php';
admin_require_login();

header('Content-Type: application/json; charset=utf-8');

function admin_import_progress_snapshot($kind, $elapsedSeconds) {
  $elapsed = max(0, (int) $elapsedSeconds);
  $kind = trim((string) $kind);

  if ($kind === 'refresh_existing_offers') {
    $stages = [
      ['after' => 0, 'percent' => 10, 'label' => 'Separando ofertas cadastradas'],
      ['after' => 3, 'percent' => 28, 'label' => 'Lendo novamente os links da loja'],
      ['after' => 8, 'percent' => 54, 'label' => 'Atualizando preco, texto e midia'],
      ['after' => 16, 'percent' => 78, 'label' => 'Gravando reimportacao no banco'],
      ['after' => 26, 'percent' => 92, 'label' => 'Finalizando atualizacao da loja'],
    ];
  } elseif ($kind === 'import_shopee_selected') {
    $stages = [
      ['after' => 0, 'percent' => 12, 'label' => 'Separando links selecionados'],
      ['after' => 3, 'percent' => 34, 'label' => 'Lendo os produtos da Shopee'],
      ['after' => 8, 'percent' => 62, 'label' => 'Gravando ofertas selecionadas'],
      ['after' => 15, 'percent' => 86, 'label' => 'Fechando importacao selecionada'],
    ];
  } elseif ($kind === 'repair_shopee_media') {
    $stages = [
      ['after' => 0, 'percent' => 12, 'label' => 'Separando ofertas selecionadas'],
      ['after' => 3, 'percent' => 34, 'label' => 'Lendo novamente imagens e videos da Shopee'],
      ['after' => 8, 'percent' => 62, 'label' => 'Gravando midia na oferta'],
      ['after' => 15, 'percent' => 86, 'label' => 'Finalizando importacao de midia'],
    ];
  } else {
    $stages = [
      ['after' => 0, 'percent' => 10, 'label' => 'Iniciando job da Shopee'],
      ['after' => 3, 'percent' => 28, 'label' => 'Consultando Open API da Shopee'],
      ['after' => 8, 'percent' => 54, 'label' => 'Priorizando produtos e preparando midia'],
      ['after' => 18, 'percent' => 78, 'label' => 'Gravando ofertas no banco'],
      ['after' => 30, 'percent' => 92, 'label' => 'Finalizando job de importacao'],
    ];
  }

  $selected = $stages[0];
  foreach ($stages as $stage) {
    if ($elapsed >= (int) $stage['after']) {
      $selected = $stage;
    }
  }

  return [
    'percent' => (int) $selected['percent'],
    'label' => (string) $selected['label'],
  ];
}

function admin_import_human_error_message($rawError) {
  $message = trim((string) $rawError);
  if ($message === '') {
    return 'Falha ao executar o job de importacao.';
  }

  $lowered = strtolower($message);
  if (strpos($lowered, 'lock wait timeout exceeded') !== false || strpos($lowered, '(1205') !== false) {
    return 'Outra operacao estava usando essas ofertas no banco e a atualizacao do Mercado Livre expirou por bloqueio temporario. Tente novamente em instantes.';
  }
  if (strpos($lowered, 'deadlock found') !== false || strpos($lowered, '(1213') !== false) {
    return 'O banco detectou disputa entre duas atualizacoes ao mesmo tempo. Tente novamente em instantes.';
  }

  return $message;
}

function admin_import_result_summary_from_payload($payload) {
  $summary = is_array($payload['result'] ?? null) ? $payload['result'] : [];
  if (isset($summary['processed']) || isset($summary['created']) || isset($summary['updated']) || isset($summary['skipped']) || isset($summary['invalid'])) {
    return [
      'processed' => (int) ($summary['processed'] ?? 0),
      'created' => (int) ($summary['created'] ?? 0),
      'updated' => (int) ($summary['updated'] ?? 0),
      'skipped' => (int) ($summary['skipped'] ?? 0),
      'invalid' => (int) ($summary['invalid'] ?? 0),
      'selected' => (int) ($summary['offers_selected'] ?? 0),
      'limit_requested' => (int) ($summary['limit_requested'] ?? 0),
      'keyword' => (string) ($summary['keyword'] ?? ''),
      'store' => (string) ($summary['store'] ?? ''),
      'with_video' => (int) ($summary['with_video'] ?? 0),
      'without_video' => (int) ($summary['without_video'] ?? 0),
      'blocked' => !empty($summary['blocked']),
      'blocked_message' => (string) ($summary['blocked_message'] ?? ''),
    ];
  }

  $items = is_array($summary['items'] ?? null) ? $summary['items'] : [];
  $processed = 0;
  $created = 0;
  $updated = 0;
  $skipped = 0;
  $invalid = 0;
  $selected = 0;
  $limitRequested = 0;
  $keyword = '';
  $store = '';
  $withVideo = 0;
  $withoutVideo = 0;
  foreach ($items as $item) {
    if (!is_array($item)) {
      continue;
    }
    $processed += (int) ($item['processed'] ?? $item['imported'] ?? 0);
    $created += (int) ($item['created'] ?? 0);
    $updated += (int) ($item['updated'] ?? 0);
    $skipped += (int) ($item['skipped'] ?? 0);
    $invalid += (int) ($item['invalid'] ?? 0);
    $selected += (int) ($item['offers_selected'] ?? 0);
    $limitRequested = max($limitRequested, (int) ($item['limit_requested'] ?? 0));
    $withVideo += (int) ($item['with_video'] ?? 0);
    $withoutVideo += (int) ($item['without_video'] ?? 0);
    if ($keyword === '' && !empty($item['keyword'])) {
      $keyword = trim((string) $item['keyword']);
    }
    if ($store === '' && !empty($item['store'])) {
      $store = trim((string) $item['store']);
    }
  }

  return [
    'processed' => $processed,
    'created' => $created,
    'updated' => $updated,
    'skipped' => $skipped,
    'invalid' => $invalid,
    'selected' => $selected,
    'limit_requested' => $limitRequested,
    'keyword' => $keyword,
    'store' => $store,
    'with_video' => $withVideo,
    'without_video' => $withoutVideo,
    'blocked' => false,
    'blocked_message' => '',
  ];
}

$requestedJobId = preg_replace('/[^A-Za-z0-9_-]+/', '', (string) ($_GET['job_id'] ?? ''));
$pending = $_SESSION['admin_import_pending_job'] ?? null;
$jobMeta = $requestedJobId !== '' ? admin_read_python_job_meta($requestedJobId) : null;

if ($requestedJobId === '') {
  http_response_code(404);
  echo json_encode(['ok' => false, 'error' => 'Job de importacao pendente nao encontrado.'], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
  exit;
}

if (!is_array($pending) || $requestedJobId !== (string) ($pending['job_id'] ?? '')) {
  if (!is_array($jobMeta) || (string) ($jobMeta['target_tab'] ?? '') !== 'importar') {
    http_response_code(404);
    echo json_encode(['ok' => false, 'error' => 'Job de importacao pendente nao encontrado.'], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
  }
  $pending = $jobMeta;
}

$status = admin_python_job_status($requestedJobId);
if (empty($status['ok'])) {
  http_response_code(404);
  echo json_encode($status, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
  exit;
}

$progress = admin_import_progress_snapshot((string) ($pending['kind'] ?? ''), (int) ($status['elapsed_seconds'] ?? 0));
$response = [
  'ok' => true,
  'status' => (string) ($status['status'] ?? 'running'),
  'elapsed_seconds' => (int) ($status['elapsed_seconds'] ?? 0),
  'progress_percent' => (int) ($progress['percent'] ?? 10),
  'progress_label' => (string) ($progress['label'] ?? 'Processando importacao no servidor'),
];

if ($response['status'] === 'running') {
  echo json_encode($response, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
  exit;
}

$payload = is_array($status['payload'] ?? null) ? $status['payload'] : null;
$redirectUrl = (string) ($pending['redirect_url'] ?? '/admin/importar.php');
$cleanupPath = trim((string) ($pending['cleanup_path'] ?? ''));
if ($cleanupPath !== '' && is_file($cleanupPath)) {
  @unlink($cleanupPath);
}

if ($response['status'] === 'success' && $payload) {
  $summary = admin_import_result_summary_from_payload($payload);
  $processed = (int) ($summary['processed'] ?? 0);
  $created = (int) ($summary['created'] ?? 0);
  $updated = (int) ($summary['updated'] ?? 0);
  $skipped = (int) ($summary['skipped'] ?? 0);
  $invalid = (int) ($summary['invalid'] ?? 0);
  $selected = (int) ($summary['selected'] ?? 0);
  $limitRequested = (int) ($summary['limit_requested'] ?? 0);
  $keyword = trim((string) ($summary['keyword'] ?? $pending['keyword'] ?? ''));
  $store = trim((string) ($summary['store'] ?? $pending['store'] ?? ''));
  $withVideo = (int) ($summary['with_video'] ?? 0);
  $withoutVideo = (int) ($summary['without_video'] ?? 0);
  $blocked = !empty($summary['blocked']);
  $blockedMessage = trim((string) ($summary['blocked_message'] ?? ''));
  $keywordSuffix = $keyword !== '' ? " Busca: {$keyword}." : '';
  $blockedSuffix = ($blocked && $blockedMessage !== '') ? " {$blockedMessage}" : '';

  if (($pending['kind'] ?? '') === 'refresh_existing_offers') {
    $selectedCount = (int) ($pending['selected_count'] ?? 0);
    $allProducts = !empty($pending['all_products']);
    $pendingStore = strtolower(trim((string) ($pending['store'] ?? '')));
    $storeLabel = $store !== '' ? $store : ($pendingStore === 'mercadolivre' ? 'Mercado Livre' : ($pendingStore === 'shopee' ? 'Shopee' : ($pendingStore === 'amazon' ? 'Amazon' : 'Loja')));
    $selectionSuffix = $selectedCount > 0 ? " selecao {$selectedCount}" : ($allProducts ? " todos {$limitRequested}" : " lote {$limitRequested}");
    $videoSuffix = '';
    if (strtolower($storeLabel) === 'shopee' || $pendingStore === 'shopee') {
      $videoSuffix = " Com video: {$withVideo}. Sem video: {$withoutVideo}.";
    }
    if ($updated > 0) {
      admin_flash_set('success', "Atualizacao de {$storeLabel} concluida:{$selectionSuffix}, {$updated} atualizada(s), {$skipped} pulada(s), {$invalid} invalida(s).{$videoSuffix}{$blockedSuffix}");
    } else {
      admin_flash_set('error', "Atualizacao de {$storeLabel} concluida sem alterar ofertas:{$selectionSuffix}, {$processed} processada(s), {$skipped} pulada(s), {$invalid} invalida(s).{$videoSuffix}{$blockedSuffix}");
    }
  } elseif (($pending['kind'] ?? '') === 'repair_shopee_media') {
    $selectedCount = (int) ($pending['selected_count'] ?? 0);
    if (($created + $updated) > 0) {
      admin_flash_set('success', "Importacao de midia Shopee concluida: selecao {$selectedCount}, {$updated} atualizada(s), {$skipped} pulada(s), {$invalid} invalida(s). Com video: {$withVideo}. Sem video: {$withoutVideo}.{$blockedSuffix}");
    } else {
      admin_flash_set('error', "Importacao de midia Shopee concluida sem alterar ofertas: selecao {$selectedCount}, {$processed} processada(s), {$skipped} pulada(s), {$invalid} invalida(s). Com video: {$withVideo}. Sem video: {$withoutVideo}.{$blockedSuffix}");
    }
  } elseif (($created + $updated) > 0) {
    if (($pending['kind'] ?? '') === 'import_shopee_selected') {
      $selectedCount = (int) ($pending['selected_count'] ?? 0);
      admin_flash_set('success', "Importacao selecionada da Shopee concluida: {$selectedCount} link(s), {$created} criada(s), {$updated} atualizada(s), {$skipped} pulada(s).{$keywordSuffix}");
    } else {
      admin_flash_set('success', "Job Shopee concluido: lote {$limitRequested}, {$selected} selecionada(s), {$created} criada(s), {$updated} atualizada(s), {$skipped} pulada(s).{$keywordSuffix}");
    }
  } else {
    if (($pending['kind'] ?? '') === 'import_shopee_selected') {
      $selectedCount = (int) ($pending['selected_count'] ?? 0);
      admin_flash_set('error', "Importacao selecionada da Shopee concluida sem gravar ofertas: {$selectedCount} link(s), {$processed} processada(s), {$skipped} pulada(s).{$keywordSuffix}");
    } else {
      admin_flash_set('error', "Job Shopee concluido sem gravar ofertas: lote {$limitRequested}, {$processed} processada(s), {$skipped} pulada(s).{$keywordSuffix}");
    }
  }
} else {
  $rawError = trim((string) ($status['raw_output'] ?? ''));
  if ($payload && isset($payload['error'])) {
    $rawError = trim((string) $payload['error']);
  }
  admin_flash_set('error', admin_import_human_error_message($rawError));
}

unset($_SESSION['admin_import_pending_job']);
$response['progress_percent'] = 100;
$response['progress_label'] = $response['status'] === 'success' ? 'Concluido' : 'Falha na importacao';
$response['redirect_url'] = $redirectUrl;

echo json_encode($response, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
