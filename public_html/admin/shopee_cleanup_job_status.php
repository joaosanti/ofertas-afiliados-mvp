<?php
require_once __DIR__ . '/_init.php';
admin_require_login();

header('Content-Type: application/json; charset=utf-8');

function admin_shopee_cleanup_progress_snapshot($elapsedSeconds) {
  $elapsed = max(0, (int) $elapsedSeconds);
  $stages = [
    ['after' => 0, 'percent' => 10, 'label' => 'Separando as ofertas mais recentes da Shopee'],
    ['after' => 4, 'percent' => 28, 'label' => 'Podando o excedente fora do limite de 500'],
    ['after' => 10, 'percent' => 52, 'label' => 'Validando links das ofertas mantidas'],
    ['after' => 28, 'percent' => 78, 'label' => 'Removendo links invalidos encontrados'],
    ['after' => 45, 'percent' => 92, 'label' => 'Fechando a limpeza da Shopee'],
  ];

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

$pending = $_SESSION['admin_shopee_cleanup_pending_job'] ?? null;
$requestedJobId = preg_replace('/[^A-Za-z0-9_-]+/', '', (string) ($_GET['job_id'] ?? ''));

if (!is_array($pending) || $requestedJobId === '' || $requestedJobId !== (string) ($pending['job_id'] ?? '')) {
  http_response_code(404);
  echo json_encode(['ok' => false, 'error' => 'Job de limpeza da Shopee nao encontrado.'], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
  exit;
}

$status = admin_python_job_status($requestedJobId);
if (empty($status['ok'])) {
  http_response_code(404);
  echo json_encode($status, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
  exit;
}

$progress = admin_shopee_cleanup_progress_snapshot((int) ($status['elapsed_seconds'] ?? 0));
$response = [
  'ok' => true,
  'status' => (string) ($status['status'] ?? 'running'),
  'elapsed_seconds' => (int) ($status['elapsed_seconds'] ?? 0),
  'progress_percent' => (int) ($progress['percent'] ?? 10),
  'progress_label' => (string) ($progress['label'] ?? 'Processando limpeza da Shopee no servidor'),
];

if ($response['status'] === 'running') {
  echo json_encode($response, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
  exit;
}

$payload = is_array($status['payload'] ?? null) ? $status['payload'] : null;
$redirectUrl = (string) ($pending['redirect_url'] ?? '/admin/auditoria_links.php');

if ($response['status'] === 'success' && $payload) {
  $summary = admin_shopee_cleanup_summary_from_result($payload);
  $processed = (int) ($summary['processed_total'] ?? 0);
  $kept = (int) ($summary['kept_count'] ?? 0);
  $trimmed = (int) ($summary['trimmed_deleted'] ?? 0);
  $checked = (int) ($summary['checked_links'] ?? 0);
  $invalid = (int) ($summary['invalid_deleted'] ?? 0);
  admin_flash_set(
    'success',
    "Limpeza da Shopee concluida: {$processed} processados, {$kept} mantidos, {$trimmed} apagados por excesso, {$checked} links checados, {$invalid} apagados por link invalido."
  );
} else {
  $rawError = trim((string) ($status['raw_output'] ?? ''));
  if ($payload && isset($payload['error'])) {
    $rawError = trim((string) $payload['error']);
  }
  admin_flash_set('error', $rawError !== '' ? $rawError : 'Falha ao executar a limpeza da Shopee.');
}

unset($_SESSION['admin_shopee_cleanup_pending_job']);
$response['progress_percent'] = 100;
$response['progress_label'] = $response['status'] === 'success' ? 'Concluido' : 'Falha na limpeza';
$response['redirect_url'] = $redirectUrl;

echo json_encode($response, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
