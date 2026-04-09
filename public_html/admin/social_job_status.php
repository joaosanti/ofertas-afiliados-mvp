<?php
require_once __DIR__ . '/_init.php';
admin_require_login();

header('Content-Type: application/json; charset=utf-8');

function admin_social_progress_snapshot($platform, $mode, $elapsedSeconds) {
  $platform = strtolower(trim((string) $platform));
  $mode = strtolower(trim((string) $mode));
  $elapsed = max(0, (int) $elapsedSeconds);

  if ($platform === 'whatsapp') {
    $stages = [
      ['after' => 0, 'percent' => 12, 'label' => 'Separando ofertas selecionadas'],
      ['after' => 3, 'percent' => 34, 'label' => 'Montando legenda e links'],
      ['after' => 7, 'percent' => 62, 'label' => 'Preparando imagens para envio'],
      ['after' => 11, 'percent' => 86, 'label' => 'Salvando preview do WhatsApp'],
    ];
  } elseif ($mode === 'feed_story_reel') {
    $stages = [
      ['after' => 0, 'percent' => 8, 'label' => 'Separando ofertas selecionadas'],
      ['after' => 4, 'percent' => 22, 'label' => 'Gerando cards, stories e assets de reel'],
      ['after' => 10, 'percent' => 40, 'label' => 'Publicando feed'],
      ['after' => 18, 'percent' => 58, 'label' => 'Publicando stories'],
      ['after' => 28, 'percent' => 78, 'label' => 'Publicando reels com video'],
      ['after' => 42, 'percent' => 94, 'label' => 'Fechando job social'],
    ];
  } elseif ($mode === 'reel_story') {
    $stages = [
      ['after' => 0, 'percent' => 8, 'label' => 'Separando ofertas selecionadas'],
      ['after' => 4, 'percent' => 26, 'label' => 'Preparando stories e assets de reel'],
      ['after' => 12, 'percent' => 52, 'label' => 'Publicando stories'],
      ['after' => 24, 'percent' => 78, 'label' => 'Publicando reels com video'],
      ['after' => 38, 'percent' => 94, 'label' => 'Fechando job social'],
    ];
  } elseif ($mode === 'reel') {
    $stages = [
      ['after' => 0, 'percent' => 10, 'label' => 'Separando ofertas selecionadas'],
      ['after' => 4, 'percent' => 28, 'label' => 'Gerando assets do reel'],
      ['after' => 12, 'percent' => 54, 'label' => 'Enviando midia para a plataforma'],
      ['after' => 24, 'percent' => 78, 'label' => 'Publicando reel e confirmando retorno'],
      ['after' => 36, 'percent' => 92, 'label' => 'Fechando job social'],
    ];
  } elseif ($mode === 'story') {
    $stages = [
      ['after' => 0, 'percent' => 10, 'label' => 'Separando ofertas selecionadas'],
      ['after' => 4, 'percent' => 30, 'label' => 'Preparando arte para story'],
      ['after' => 10, 'percent' => 58, 'label' => 'Enviando imagem para publicacao'],
      ['after' => 18, 'percent' => 82, 'label' => 'Confirmando story no destino'],
    ];
  } else {
    $stages = [
      ['after' => 0, 'percent' => 10, 'label' => 'Separando ofertas selecionadas'],
      ['after' => 4, 'percent' => 26, 'label' => 'Gerando cards e legendas'],
      ['after' => 10, 'percent' => 46, 'label' => 'Enviando imagens para publicacao'],
      ['after' => 18, 'percent' => 68, 'label' => 'Publicando no Facebook'],
      ['after' => 28, 'percent' => 84, 'label' => 'Publicando no Instagram'],
      ['after' => 40, 'percent' => 94, 'label' => 'Fechando job social'],
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

function admin_social_success_message($result, $pending) {
  $result = is_array($result) ? $result : [];
  $pending = is_array($pending) ? $pending : [];

  $count = (int) ($result['count'] ?? 0);
  $facebookCount = (int) ($result['facebook_count'] ?? 0);
  $instagramCount = (int) ($result['instagram_count'] ?? 0);
  $instagramFeedCount = (int) ($result['instagram_feed_count'] ?? 0);
  $instagramStoryCount = (int) ($result['instagram_story_count'] ?? 0);
  $facebookReelCount = (int) ($result['facebook_reel_count'] ?? 0);
  $errors = is_array($result['errors'] ?? null) ? $result['errors'] : [];
  $warnings = is_array($result['warnings'] ?? null) ? $result['warnings'] : [];
  $platform = strtolower(trim((string) ($pending['platform'] ?? $result['platform'] ?? 'social')));
  $mode = strtolower(trim((string) ($pending['mode'] ?? $result['mode'] ?? 'feed')));

  $parts = [];
  if ($platform === 'whatsapp') {
    $parts[] = $mode === 'web'
      ? "Preview do WhatsApp preparado com {$count} item(ns)."
      : "Envio para WhatsApp concluido com {$count} item(ns).";
  } else {
    $parts[] = "Publicacao social concluida com {$count} item(ns).";
  }

  if ($facebookCount > 0) {
    $parts[] = "Facebook: {$facebookCount}.";
  } elseif ($facebookReelCount > 0) {
    $parts[] = "Facebook reels: {$facebookReelCount}.";
  }

  if ($instagramCount > 0) {
    $parts[] = "Instagram: {$instagramCount}.";
  }
  if ($instagramFeedCount > 0 && in_array($mode, ['feed_story', 'feed_story_reel'], true)) {
    $parts[] = "Feed IG: {$instagramFeedCount}.";
  }
  if ($instagramStoryCount > 0 && in_array($mode, ['story', 'reel_story', 'feed_story', 'feed_story_reel'], true)) {
    $parts[] = "Stories IG: {$instagramStoryCount}.";
  }
  if ($facebookReelCount > 0 && in_array($mode, ['reel', 'reel_story', 'feed_story_reel'], true)) {
    $parts[] = "Reels FB: {$facebookReelCount}.";
  }

  if ($warnings) {
    $warning = trim((string) (($warnings[0]['warning'] ?? $warnings[0]['error'] ?? '') ?: ''));
    if ($warning !== '') {
      $parts[] = "Aviso: {$warning}";
    }
  }

  if ($errors) {
    $rawError = trim((string) (($errors[0]['error'] ?? '') ?: ''));
    $lowerError = strtolower($rawError);
    $error = $rawError;
    if ($lowerError !== '' && (strpos($lowerError, 'video download failed') !== false || strpos($lowerError, 'fwdproxy failed to fetch headers') !== false)) {
      $error = 'A Meta concluiu parte da publicacao, mas falhou ao baixar um video remoto para outra etapa. Isso costuma afetar reel ou story em video e geralmente e temporario.';
    }
    $parts[] = $error !== '' ? "Algumas etapas falharam: {$error}" : 'Algumas etapas falharam. Confira o historico abaixo.';
  }

  return trim(implode(' ', $parts));
}

$pending = $_SESSION['admin_social_pending_job'] ?? null;
$requestedJobId = preg_replace('/[^A-Za-z0-9_-]+/', '', (string) ($_GET['job_id'] ?? ''));

if (!is_array($pending) || $requestedJobId === '' || $requestedJobId !== (string) ($pending['job_id'] ?? '')) {
  http_response_code(404);
  echo json_encode(['ok' => false, 'error' => 'Job social pendente nao encontrado.'], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
  exit;
}

$status = admin_python_job_status($requestedJobId);
if (empty($status['ok'])) {
  http_response_code(404);
  echo json_encode($status, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
  exit;
}

$progress = admin_social_progress_snapshot(
  (string) ($pending['platform'] ?? ''),
  (string) ($pending['mode'] ?? ''),
  (int) ($status['elapsed_seconds'] ?? 0)
);
$response = [
  'ok' => true,
  'status' => (string) ($status['status'] ?? 'running'),
  'elapsed_seconds' => (int) ($status['elapsed_seconds'] ?? 0),
  'progress_percent' => (int) ($progress['percent'] ?? 10),
  'progress_label' => (string) ($progress['label'] ?? 'Processando no servidor'),
];

if ($response['status'] === 'running') {
  echo json_encode($response, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
  exit;
}

$payload = is_array($status['payload'] ?? null) ? $status['payload'] : null;
$redirectUrl = (string) ($pending['redirect_url'] ?? '/admin/social.php');

if ($response['status'] === 'success' && $payload && is_array($payload['result'] ?? null)) {
  $result = (array) $payload['result'];
  $_SESSION['admin_social_preview'] = null;
  if (($result['platform'] ?? '') === 'whatsapp') {
    $_SESSION['admin_social_preview'] = $result;
  }
  admin_flash_set('success', admin_social_success_message($result, $pending));
} else {
  $_SESSION['admin_social_preview'] = null;
  $rawError = trim((string) ($status['raw_output'] ?? ''));
  if ($payload && isset($payload['error'])) {
    $rawError = trim((string) $payload['error']);
  } elseif (is_array($payload['result'] ?? null)) {
    $result = (array) $payload['result'];
    $rawError = trim((string) ($result['error_summary'] ?? $result['warning_summary'] ?? ''));
  }
  admin_flash_set('error', $rawError !== '' ? $rawError : 'Falha ao executar o job social.');
}

unset($_SESSION['admin_social_pending_job']);
$response['progress_percent'] = 100;
$response['progress_label'] = $response['status'] === 'success' ? 'Concluido' : 'Falha na execucao';
$response['redirect_url'] = $redirectUrl;

echo json_encode($response, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
