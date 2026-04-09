<?php
require_once __DIR__ . '/_init.php';
admin_require_login();

header('Content-Type: application/json; charset=utf-8');

function admin_shopee_video_package_progress_snapshot($elapsedSeconds) {
  $elapsed = max(0, (int) $elapsedSeconds);
  $stages = [
    ['after' => 0, 'percent' => 10, 'label' => 'Separando arquivos do pacote'],
    ['after' => 3, 'percent' => 34, 'label' => 'Baixando e ajustando o video base'],
    ['after' => 10, 'percent' => 68, 'label' => 'Montando o video final'],
    ['after' => 20, 'percent' => 90, 'label' => 'Anexando o video no produto'],
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

$pending = $_SESSION['admin_shopee_video_pending_job'] ?? null;
$requestedJobId = preg_replace('/[^A-Za-z0-9_-]+/', '', (string) ($_GET['job_id'] ?? ''));

if (!is_array($pending) || $requestedJobId === '' || $requestedJobId !== (string) ($pending['job_id'] ?? '')) {
  http_response_code(404);
  echo json_encode(['ok' => false, 'error' => 'Job pendente do Shopee Video nao encontrado.'], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
  exit;
}

$status = admin_python_job_status($requestedJobId);
if (empty($status['ok'])) {
  http_response_code(404);
  echo json_encode($status, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
  exit;
}

$progress = admin_shopee_video_package_progress_snapshot((int) ($status['elapsed_seconds'] ?? 0));
$response = [
  'ok' => true,
  'status' => (string) ($status['status'] ?? 'running'),
  'elapsed_seconds' => (int) ($status['elapsed_seconds'] ?? 0),
  'progress_percent' => (int) ($progress['percent'] ?? 10),
  'progress_label' => (string) ($progress['label'] ?? 'Gerando video final no servidor'),
];

if ($response['status'] === 'running') {
  echo json_encode($response, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
  exit;
}

$payload = is_array($status['payload'] ?? null) ? $status['payload'] : null;
$redirectUrl = (string) ($pending['redirect_url'] ?? '/admin/shopee_video.php?view=drafts');
$draftId = (int) ($pending['draft_id'] ?? 0);
$pdo = db();

if ($response['status'] === 'success' && $payload && is_array($payload['result'] ?? null) && $draftId > 0) {
  $storedPackage = admin_store_shopee_video_package_result($pdo, $draftId, (array) $payload['result']);
  if (($storedPackage['status'] ?? '') === 'ready') {
    admin_flash_set('success', 'Pacote profissional gerado com sucesso para o draft #' . $draftId . '.');
  } elseif (($storedPackage['status'] ?? '') === 'partial') {
    admin_flash_set('warn', 'Pacote do draft #' . $draftId . ' foi gerado parcialmente. ' . (string) ($storedPackage['error'] ?? 'Verifique os avisos do pacote.'));
  } else {
    admin_flash_set('error', 'Pacote do draft #' . $draftId . ' nao gerou o video final. ' . (string) ($storedPackage['error'] ?? ''));
  }
} else {
  $rawError = trim((string) ($status['raw_output'] ?? ''));
  if ($payload && isset($payload['error'])) {
    $rawError = trim((string) $payload['error']);
  }
  if ($draftId > 0) {
    admin_mark_shopee_video_package_error($pdo, $draftId, $rawError !== '' ? $rawError : 'Falha ao gerar o pacote profissional.');
  }
  admin_flash_set('error', $rawError !== '' ? $rawError : 'Falha ao gerar o pacote profissional.');
}

unset($_SESSION['admin_shopee_video_pending_job']);
$response['progress_percent'] = 100;
$response['progress_label'] = $response['status'] === 'success' ? 'Concluido' : 'Falha no pacote';
$response['redirect_url'] = $redirectUrl;

echo json_encode($response, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
