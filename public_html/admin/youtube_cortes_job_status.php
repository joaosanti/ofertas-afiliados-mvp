<?php
require_once __DIR__ . '/_init.php';
admin_require_login();

header('Content-Type: application/json; charset=utf-8');

function admin_youtube_cuts_compact_process_result_payload($result) {
  if (!is_array($result)) {
    return null;
  }
  $cuts = [];
  foreach ((array) ($result['cuts'] ?? []) as $item) {
    if (!is_array($item)) {
      continue;
    }
    $cuts[] = [
      'job_id' => (string) ($item['job_id'] ?? $result['job_id'] ?? ''),
      'cut_id' => (int) ($item['cut_id'] ?? 0),
      'mode' => (string) ($item['mode'] ?? $result['mode'] ?? 'short'),
      'title' => (string) ($item['title'] ?? ''),
      'hook' => (string) ($item['hook'] ?? ''),
      'score' => (int) ($item['score'] ?? 0),
      'duration_label' => (string) ($item['duration_label'] ?? ''),
      'video_filename' => (string) ($item['video_filename'] ?? ''),
      'risk_profile' => (string) ($item['risk_profile'] ?? $result['risk_profile'] ?? 'default'),
      'risk_notes' => array_values(array_filter((array) ($item['risk_notes'] ?? []), static function ($value) {
        return is_string($value) && $value !== '';
      })),
      'first_frame_text' => (string) ($item['first_frame_text'] ?? ''),
      'title_variants' => array_values(array_filter((array) ($item['title_variants'] ?? []), static function ($value) {
        return is_string($value) && $value !== '';
      })),
      'packaging_notes' => array_values(array_filter((array) ($item['packaging_notes'] ?? []), static function ($value) {
        return is_string($value) && $value !== '';
      })),
      'opening_score' => (int) ($item['opening_score'] ?? 0),
      'opening_visual_score' => (int) ($item['opening_visual_score'] ?? 0),
      'opening_speaker_score' => (int) ($item['opening_speaker_score'] ?? 0),
      'opening_focus_zone' => (string) ($item['opening_focus_zone'] ?? ''),
      'opening_speaker_detected' => !empty($item['opening_speaker_detected']),
      'publish_allowed' => !array_key_exists('publish_allowed', $item) || !empty($item['publish_allowed']),
      'publish_block_reason' => (string) ($item['publish_block_reason'] ?? ''),
      'crop_override' => (string) ($item['crop_override'] ?? 'auto'),
      'publish_draft' => is_array($item['publish_draft'] ?? null) ? [
        'channel_profile_id' => (int) (($item['publish_draft']['channel_profile_id'] ?? 0)),
        'channel_profile_name' => (string) (($item['publish_draft']['channel_profile_name'] ?? '')),
      ] : [],
    ];
  }
  return [
    'job_id' => (string) ($result['job_id'] ?? ''),
    'mode' => (string) ($result['mode'] ?? 'short'),
    'risk_profile' => (string) ($result['risk_profile'] ?? 'default'),
    'target_channel_profile_id' => (int) ($result['target_channel_profile_id'] ?? 0),
    'target_channel_profile_name' => (string) ($result['target_channel_profile_name'] ?? ''),
    'cuts' => $cuts,
  ];
}

function admin_youtube_cuts_progress_snapshot($kind, $elapsedSeconds) {
  $kind = (string) $kind;
  $elapsed = max(0, (int) $elapsedSeconds);
  if ($kind === 'analyze_video') {
    $stages = [
        ['after' => 0, 'percent' => 12, 'label' => 'Preparando analise do video'],
        ['after' => 3, 'percent' => 34, 'label' => 'Buscando metadados do YouTube'],
        ['after' => 8, 'percent' => 58, 'label' => 'Lendo transcricao e contexto'],
        ['after' => 15, 'percent' => 84, 'label' => 'Fechando sugestoes finais'],
      ];
  } elseif ($kind === 'auto_cut_publish') {
    $stages = [
      ['after' => 0, 'percent' => 8, 'label' => 'Preparando auto job do canal'],
      ['after' => 4, 'percent' => 22, 'label' => 'Carregando radar do canal'],
      ['after' => 12, 'percent' => 38, 'label' => 'Escolhendo o melhor video do radar'],
      ['after' => 24, 'percent' => 56, 'label' => 'Analisando e gerando os cortes'],
      ['after' => 52, 'percent' => 76, 'label' => 'Escolhendo o melhor corte gerado'],
      ['after' => 70, 'percent' => 92, 'label' => 'Publicando o video no YouTube'],
    ];
  } elseif ($kind === 'private_test') {
    $stages = [
      ['after' => 0, 'percent' => 10, 'label' => 'Preparando teste privado'],
      ['after' => 4, 'percent' => 26, 'label' => 'Baixando video do YouTube'],
      ['after' => 12, 'percent' => 46, 'label' => 'Filtrando cortes com preset de risco menor'],
      ['after' => 30, 'percent' => 70, 'label' => 'Renderizando o melhor corte'],
      ['after' => 52, 'percent' => 90, 'label' => 'Enviando video privado ao YouTube'],
    ];
  } else {
    $stages = [
        ['after' => 0, 'percent' => 10, 'label' => 'Preparando geracao dos cortes'],
        ['after' => 4, 'percent' => 24, 'label' => 'Baixando video do YouTube'],
        ['after' => 12, 'percent' => 42, 'label' => 'Tentando recuperar legenda e audio'],
        ['after' => 24, 'percent' => 58, 'label' => 'Escolhendo os melhores trechos'],
        ['after' => 40, 'percent' => 76, 'label' => 'Renderizando videos e overlays'],
        ['after' => 58, 'percent' => 90, 'label' => 'Salvando arquivos finais'],
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

$pending = $_SESSION['admin_youtube_cuts_pending_job'] ?? null;
$requestedJobId = preg_replace('/[^A-Za-z0-9_-]+/', '', (string) ($_GET['job_id'] ?? ''));

if (!is_array($pending) || $requestedJobId === '' || $requestedJobId !== (string) ($pending['job_id'] ?? '')) {
  http_response_code(404);
  echo json_encode(['ok' => false, 'error' => 'Job pendente nao encontrado.'], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
  exit;
}

$status = admin_python_job_status($requestedJobId);
if (empty($status['ok'])) {
  http_response_code(404);
  echo json_encode($status, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
  exit;
}

$kind = (string) ($pending['kind'] ?? 'generate_cuts');
$targetTab = (string) ($pending['target_tab'] ?? 'gerar');
$progress = admin_youtube_cuts_progress_snapshot($kind, (int) ($status['elapsed_seconds'] ?? 0));
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
if ($response['status'] === 'success' && $payload) {
  if ($kind === 'analyze_video') {
    $_SESSION['admin_youtube_cuts_analysis'] = is_array($payload['result'] ?? null) ? $payload['result'] : null;
    admin_flash_set('success', 'Video analisado com sucesso. Confira as sugestoes logo abaixo.');
    $targetTab = 'gerar';
  } elseif ($kind === 'generate_cuts') {
    $_SESSION['admin_youtube_cuts_process'] = admin_youtube_cuts_compact_process_result_payload($payload['result'] ?? null);
    admin_flash_set('success', 'Cortes gerados com sucesso. Agora voce pode revisar e publicar no YouTube.');
    $targetTab = 'historico';
  } elseif ($kind === 'private_test') {
    $result = is_array($payload['result'] ?? null) ? $payload['result'] : [];
    $_SESSION['admin_youtube_cuts_process'] = admin_youtube_cuts_compact_process_result_payload($result['process_result'] ?? null);
    $_SESSION['admin_youtube_cuts_last_publish'] = is_array($result['publish_result'] ?? null) ? $result['publish_result'] : null;
    $youtubeUrl = (string) (($result['publish_result'] ?? [])['youtube_url'] ?? '');
    admin_flash_set(
      'success',
      $youtubeUrl !== '' ? "Teste privado concluido com sucesso. Link: {$youtubeUrl}" : 'Teste privado concluido com sucesso no YouTube.'
    );
    $targetTab = 'historico';
  } elseif ($kind === 'auto_cut_publish') {
    $_SESSION['admin_youtube_cuts_last_publish'] = is_array($payload['result'] ?? null) ? $payload['result'] : null;
    $youtubeUrl = (string) (($payload['result'] ?? [])['youtube_url'] ?? '');
    admin_flash_set(
      'success',
      $youtubeUrl !== '' ? "Auto job concluido com sucesso. Link: {$youtubeUrl}" : 'Auto job concluido com sucesso no YouTube.'
    );
    $targetTab = 'gerar';
  }
} else {
  $rawError = trim((string) ($status['raw_output'] ?? ''));
  if ($payload && isset($payload['error'])) {
    $rawError = trim((string) $payload['error']);
  }
  admin_flash_set('error', $rawError !== '' ? $rawError : 'Falha ao executar o job de YouTube cortes.');
}

unset($_SESSION['admin_youtube_cuts_pending_job']);
$response['progress_percent'] = 100;
$response['progress_label'] = $response['status'] === 'success' ? 'Concluido' : 'Falha na execucao';
$response['redirect_url'] = '/admin/youtube_cortes.php?tab=' . rawurlencode($targetTab);

echo json_encode($response, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
