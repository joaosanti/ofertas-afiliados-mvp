<?php
require_once __DIR__ . '/_init.php';
admin_require_login();

$flash = admin_flash_get();
$pdo = db();
$youtubeCutAnalysis = $_SESSION['admin_youtube_cuts_analysis'] ?? null;
$youtubeCutsProcess = $_SESSION['admin_youtube_cuts_process'] ?? null;
$youtubeLastPublish = $_SESSION['admin_youtube_cuts_last_publish'] ?? null;
$youtubeTrendIdeas = $_SESSION['admin_youtube_trend_ideas'] ?? null;
$pendingYoutubeJob = $_SESSION['admin_youtube_cuts_pending_job'] ?? null;
$selectedChannelProfileId = (int) ($_SESSION['admin_youtube_cuts_channel_profile_id'] ?? 0);
$youtubeTab = (string) ($_GET['tab'] ?? 'gerar');
if (!in_array($youtubeTab, ['gerar', 'historico'], true)) {
  $youtubeTab = 'gerar';
}
$youtubeForm = $_SESSION['admin_youtube_cuts_form'] ?? [
  'url' => '',
  'mode' => 'short',
  'selection_strategy' => 'openai_heuristica',
  'risk_profile' => 'default',
  'channel_profile_id' => $selectedChannelProfileId,
  'burn_subtitles' => true,
];

function admin_youtube_reset_profile_view_state($channelProfileId = 0) {
  $normalizedProfileId = max(0, (int) $channelProfileId);
  $freshForm = [
    'url' => '',
    'mode' => 'short',
    'selection_strategy' => 'openai_heuristica',
    'risk_profile' => 'default',
    'channel_profile_id' => $normalizedProfileId,
    'burn_subtitles' => true,
  ];

  $_SESSION['admin_youtube_cuts_analysis'] = null;
  $_SESSION['admin_youtube_cuts_process'] = null;
  $_SESSION['admin_youtube_cuts_last_publish'] = null;
  $_SESSION['admin_youtube_trend_ideas'] = null;
  $_SESSION['admin_youtube_cuts_pending_job'] = null;
  $_SESSION['admin_youtube_cuts_form'] = $freshForm;
  $_SESSION['admin_youtube_cuts_channel_profile_id'] = $normalizedProfileId;

  return $freshForm;
}

function admin_youtube_cuts_tab_url($tab, $params = []) {
  $normalizedTab = in_array($tab, ['gerar', 'historico'], true) ? $tab : 'gerar';
  $query = array_merge(['tab' => $normalizedTab], is_array($params) ? $params : []);
  return '/admin/youtube_cortes.php?' . http_build_query($query);
}

function admin_fetch_local_youtube_profiles(PDO $pdo) {
  try {
    $stmt = $pdo->query("
      SELECT id, name, handle, channel_title, channel_custom_url, is_default, is_active
      FROM youtube_channel_profiles
      WHERE is_active = 1
      ORDER BY is_default DESC, updated_at DESC, id DESC
    ");
    return $stmt->fetchAll() ?: [];
  } catch (Throwable $e) {
    return [];
  }
}

function admin_fetch_youtube_profile_for_oauth(PDO $pdo, $profileId = 0) {
  try {
    if ((int) $profileId > 0) {
      $stmt = $pdo->prepare("
        SELECT id, name, client_id, redirect_uri
        FROM youtube_channel_profiles
        WHERE id = ? AND is_active = 1
        LIMIT 1
      ");
      $stmt->execute([(int) $profileId]);
      $row = $stmt->fetch();
      if ($row) {
        return $row;
      }
    }

    $stmt = $pdo->query("
      SELECT id, name, client_id, redirect_uri
      FROM youtube_channel_profiles
      WHERE is_active = 1
      ORDER BY is_default DESC, updated_at DESC, id DESC
      LIMIT 1
    ");
    return $stmt->fetch() ?: null;
  } catch (Throwable $e) {
    return null;
  }
}

function admin_fetch_youtube_profile_status(PDO $pdo, $profileId = 0) {
  try {
    if ((int) $profileId > 0) {
      $stmt = $pdo->prepare("
        SELECT id, name, handle, channel_title, channel_custom_url, client_id, client_secret, redirect_uri,
               access_token, refresh_token, token_expires_at, is_default, is_active, updated_at
        FROM youtube_channel_profiles
        WHERE id = ? AND is_active = 1
        LIMIT 1
      ");
      $stmt->execute([(int) $profileId]);
      $row = $stmt->fetch();
      if ($row) {
        return $row;
      }
    }

    $stmt = $pdo->query("
      SELECT id, name, handle, channel_title, channel_custom_url, client_id, client_secret, redirect_uri,
             access_token, refresh_token, token_expires_at, is_default, is_active, updated_at
      FROM youtube_channel_profiles
      WHERE is_active = 1
      ORDER BY is_default DESC, updated_at DESC, id DESC
      LIMIT 1
    ");
    return $stmt->fetch() ?: null;
  } catch (Throwable $e) {
    return null;
  }
}

function admin_build_youtube_status_summary($profile) {
  if (!is_array($profile) || empty($profile['id'])) {
    return [
      'label' => 'Sem perfil',
      'class' => 'warn',
      'message' => 'Nenhum perfil ativo de canal do YouTube foi encontrado.',
      'channel' => '',
      'handle' => '',
      'oauth_ready' => false,
      'refresh_ready' => false,
      'access_ready' => false,
      'token_expired' => true,
    ];
  }

  $hasClientId = trim((string) ($profile['client_id'] ?? '')) !== '';
  $hasClientSecret = trim((string) ($profile['client_secret'] ?? '')) !== '';
  $hasRedirectUri = trim((string) ($profile['redirect_uri'] ?? '')) !== '';
  $hasRefreshToken = trim((string) ($profile['refresh_token'] ?? '')) !== '';
  $hasAccessToken = trim((string) ($profile['access_token'] ?? '')) !== '';
  $channelTitle = trim((string) ($profile['channel_title'] ?? ''));
  $channelHandle = trim((string) ($profile['channel_custom_url'] ?? ($profile['handle'] ?? '')));
  $tokenExpiresAt = (int) ($profile['token_expires_at'] ?? 0);
  $tokenExpired = $tokenExpiresAt <= 0 ? true : ($tokenExpiresAt <= (time() + 120));

  if (!$hasClientId || !$hasClientSecret || !$hasRedirectUri) {
    return [
      'label' => 'Config. incompleta',
      'class' => 'warn',
      'message' => 'Faltam credenciais OAuth no perfil selecionado.',
      'channel' => $channelTitle,
      'handle' => $channelHandle,
      'oauth_ready' => false,
      'refresh_ready' => $hasRefreshToken,
      'access_ready' => $hasAccessToken,
      'token_expired' => $tokenExpired,
    ];
  }

  if (!$hasRefreshToken) {
    return [
      'label' => 'Precisa reconectar',
      'class' => 'warn',
      'message' => 'Esse perfil ainda nao tem refresh token valido do YouTube.',
      'channel' => $channelTitle,
      'handle' => $channelHandle,
      'oauth_ready' => true,
      'refresh_ready' => false,
      'access_ready' => $hasAccessToken,
      'token_expired' => $tokenExpired,
    ];
  }

  return [
    'label' => 'Conectado',
    'class' => 'ok',
    'message' => $tokenExpired
      ? 'Perfil conectado. O access token local expirou, mas o sistema deve renovar sozinho no proximo uso.'
      : 'Perfil conectado e pronto para usar no radar, no auto job e na publicacao.',
    'channel' => $channelTitle,
    'handle' => $channelHandle,
    'oauth_ready' => true,
    'refresh_ready' => true,
    'access_ready' => $hasAccessToken,
    'token_expired' => $tokenExpired,
  ];
}

function admin_build_youtube_auth_url($clientId, $redirectUri, $state) {
  $clientId = trim((string) $clientId);
  $redirectUri = trim((string) $redirectUri);
  $state = trim((string) $state);
  if ($clientId === '' || $redirectUri === '' || $state === '') {
    return '';
  }
  $params = [
    'response_type' => 'code',
    'client_id' => $clientId,
    'redirect_uri' => $redirectUri,
    'scope' => 'https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly',
    'access_type' => 'offline',
    'prompt' => 'consent',
    'include_granted_scopes' => 'true',
    'state' => $state,
  ];
  return 'https://accounts.google.com/o/oauth2/v2/auth?' . http_build_query($params, '', '&', PHP_QUERY_RFC3986);
}

function admin_current_absolute_url($path) {
  $host = trim((string) ($_SERVER['HTTP_HOST'] ?? ''));
  if ($host === '') {
    return '';
  }
  $https = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off')
    || strtolower((string) ($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '')) === 'https';
  $scheme = $https ? 'https' : 'http';
  $normalizedPath = '/' . ltrim((string) $path, '/');
  return $scheme . '://' . $host . $normalizedPath;
}

function admin_youtube_http_post_form($url, array $fields) {
  $payload = http_build_query($fields, '', '&', PHP_QUERY_RFC3986);
  if (function_exists('curl_init')) {
    $ch = curl_init($url);
    curl_setopt_array($ch, [
      CURLOPT_RETURNTRANSFER => true,
      CURLOPT_POST => true,
      CURLOPT_POSTFIELDS => $payload,
      CURLOPT_HTTPHEADER => ['Content-Type: application/x-www-form-urlencoded'],
      CURLOPT_TIMEOUT => 30,
    ]);
    $body = curl_exec($ch);
    $status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $error = curl_error($ch);
    curl_close($ch);
    if ($body === false) {
      throw new RuntimeException('Falha HTTP ao falar com o Google: ' . $error);
    }
    return ['status' => $status, 'body' => (string) $body];
  }

  $context = stream_context_create([
    'http' => [
      'method' => 'POST',
      'header' => "Content-Type: application/x-www-form-urlencoded\r\n",
      'content' => $payload,
      'timeout' => 30,
      'ignore_errors' => true,
    ],
  ]);
  $body = @file_get_contents($url, false, $context);
  if ($body === false) {
    throw new RuntimeException('Falha HTTP ao falar com o Google.');
  }
  $status = 0;
  foreach ((array) ($http_response_header ?? []) as $headerLine) {
    if (preg_match('~^HTTP/\S+\s+(\d{3})~', (string) $headerLine, $matches)) {
      $status = (int) $matches[1];
      break;
    }
  }
  return ['status' => $status, 'body' => (string) $body];
}

function admin_youtube_http_get_json($url, array $headers = []) {
  if (function_exists('curl_init')) {
    $ch = curl_init($url);
    curl_setopt_array($ch, [
      CURLOPT_RETURNTRANSFER => true,
      CURLOPT_HTTPGET => true,
      CURLOPT_TIMEOUT => 30,
      CURLOPT_HTTPHEADER => $headers,
    ]);
    $body = curl_exec($ch);
    $status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $error = curl_error($ch);
    curl_close($ch);
    if ($body === false) {
      throw new RuntimeException('Falha HTTP ao consultar o YouTube: ' . $error);
    }
    return ['status' => $status, 'body' => (string) $body];
  }

  $context = stream_context_create([
    'http' => [
      'method' => 'GET',
      'header' => implode("\r\n", $headers) . "\r\n",
      'timeout' => 30,
      'ignore_errors' => true,
    ],
  ]);
  $body = @file_get_contents($url, false, $context);
  if ($body === false) {
    throw new RuntimeException('Falha HTTP ao consultar o YouTube.');
  }
  $status = 0;
  foreach ((array) ($http_response_header ?? []) as $headerLine) {
    if (preg_match('~^HTTP/\S+\s+(\d{3})~', (string) $headerLine, $matches)) {
      $status = (int) $matches[1];
      break;
    }
  }
  return ['status' => $status, 'body' => (string) $body];
}

function admin_fetch_youtube_profile_full(PDO $pdo, $profileId = 0) {
  try {
    if ((int) $profileId > 0) {
      $stmt = $pdo->prepare("
        SELECT *
        FROM youtube_channel_profiles
        WHERE id = ? AND is_active = 1
        LIMIT 1
      ");
      $stmt->execute([(int) $profileId]);
      $row = $stmt->fetch();
      if ($row) {
        return $row;
      }
    }

    $stmt = $pdo->query("
      SELECT *
      FROM youtube_channel_profiles
      WHERE is_active = 1
      ORDER BY is_default DESC, updated_at DESC, id DESC
      LIMIT 1
    ");
    return $stmt->fetch() ?: null;
  } catch (Throwable $e) {
    return null;
  }
}

function admin_youtube_store_channel_snapshot(PDO $pdo, $profileId, $accessToken, $refreshToken, $tokenExpiresAt, array $channelItem) {
  $snippet = is_array($channelItem['snippet'] ?? null) ? $channelItem['snippet'] : [];
  $thumbnails = is_array($snippet['thumbnails'] ?? null) ? $snippet['thumbnails'] : [];
  $thumbnailUrl = null;
  foreach (['high', 'medium', 'default'] as $thumbKey) {
    if (!empty($thumbnails[$thumbKey]['url'])) {
      $thumbnailUrl = (string) $thumbnails[$thumbKey]['url'];
      break;
    }
  }

  $stmt = $pdo->prepare("
    UPDATE youtube_channel_profiles
    SET access_token = ?,
        refresh_token = ?,
        token_expires_at = ?,
        oauth_state = '',
        channel_id = ?,
        channel_title = ?,
        channel_custom_url = ?,
        channel_thumbnail_url = ?
    WHERE id = ?
    LIMIT 1
  ");
  $stmt->execute([
    $accessToken !== '' ? $accessToken : null,
    $refreshToken !== '' ? $refreshToken : null,
    $tokenExpiresAt ?: null,
    trim((string) ($channelItem['id'] ?? '')) !== '' ? trim((string) ($channelItem['id'] ?? '')) : null,
    trim((string) ($snippet['title'] ?? '')) !== '' ? trim((string) ($snippet['title'] ?? '')) : null,
    trim((string) ($snippet['customUrl'] ?? '')) !== '' ? trim((string) ($snippet['customUrl'] ?? '')) : null,
    $thumbnailUrl,
    (int) $profileId,
  ]);
}

function admin_youtube_test_auth(PDO $pdo, $profileId = 0) {
  $profile = admin_fetch_youtube_profile_full($pdo, $profileId);
  if (!$profile) {
    throw new RuntimeException('Nenhum perfil ativo de canal do YouTube foi encontrado para testar.');
  }

  $clientId = trim((string) ($profile['client_id'] ?? ''));
  $clientSecret = trim((string) ($profile['client_secret'] ?? ''));
  if ($clientId === '' || $clientSecret === '') {
    throw new RuntimeException('O perfil selecionado nao tem Client ID e Client Secret completos.');
  }

  $accessToken = trim((string) ($profile['access_token'] ?? ''));
  $refreshToken = trim((string) ($profile['refresh_token'] ?? ''));
  $tokenExpiresAt = (int) ($profile['token_expires_at'] ?? 0);
  $shouldRefresh = ($accessToken === '') || ($tokenExpiresAt > 0 && $tokenExpiresAt <= (time() + 120));
  $refreshed = false;

  if ($shouldRefresh) {
    if ($refreshToken === '') {
      throw new RuntimeException('Esse perfil nao tem refresh token. Use "Reconectar YouTube".');
    }
    $tokenResponse = admin_youtube_http_post_form('https://oauth2.googleapis.com/token', [
      'refresh_token' => $refreshToken,
      'client_id' => $clientId,
      'client_secret' => $clientSecret,
      'grant_type' => 'refresh_token',
    ]);
    $tokenPayload = json_decode((string) $tokenResponse['body'], true);
    if ((int) ($tokenResponse['status'] ?? 0) >= 400 || !is_array($tokenPayload)) {
      $detail = is_array($tokenPayload) ? json_encode($tokenPayload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) : (string) $tokenResponse['body'];
      if (stripos((string) $detail, 'invalid_grant') !== false || stripos((string) $detail, 'expired or revoked') !== false) {
        $clearStmt = $pdo->prepare("
          UPDATE youtube_channel_profiles
          SET access_token = NULL, refresh_token = NULL, token_expires_at = NULL, oauth_state = ''
          WHERE id = ?
          LIMIT 1
        ");
        $clearStmt->execute([(int) ($profile['id'] ?? 0)]);
        throw new RuntimeException('O refresh token do YouTube expirou ou foi revogado. Use "Reconectar YouTube".');
      }
      throw new RuntimeException($detail !== '' ? $detail : 'Falha ao renovar o token do YouTube.');
    }

    $accessToken = trim((string) ($tokenPayload['access_token'] ?? ''));
    $nextRefreshToken = trim((string) ($tokenPayload['refresh_token'] ?? ''));
    if ($nextRefreshToken !== '') {
      $refreshToken = $nextRefreshToken;
    }
    $expiresIn = (int) ($tokenPayload['expires_in'] ?? 0);
    $tokenExpiresAt = $expiresIn > 0 ? (time() + $expiresIn) : 0;
    $refreshed = true;
  }

  if ($accessToken === '') {
    throw new RuntimeException('Nao foi possivel obter um access token valido para esse perfil.');
  }

  $channelResponse = admin_youtube_http_get_json(
    'https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true',
    ['Authorization: Bearer ' . $accessToken]
  );
  $channelPayload = json_decode((string) $channelResponse['body'], true);
  if ((int) ($channelResponse['status'] ?? 0) >= 400 || !is_array($channelPayload)) {
    $detail = is_array($channelPayload) ? json_encode($channelPayload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) : (string) $channelResponse['body'];
    throw new RuntimeException($detail !== '' ? $detail : 'Falha ao consultar o canal no YouTube.');
  }

  $channelItem = !empty($channelPayload['items'][0]) && is_array($channelPayload['items'][0]) ? $channelPayload['items'][0] : null;
  if (!$channelItem) {
    throw new RuntimeException('O YouTube nao retornou nenhum canal para a conta autenticada.');
  }

  admin_youtube_store_channel_snapshot(
    $pdo,
    (int) ($profile['id'] ?? 0),
    $accessToken,
    $refreshToken,
    $tokenExpiresAt,
    $channelItem
  );

  $snippet = is_array($channelItem['snippet'] ?? null) ? $channelItem['snippet'] : [];
  return [
    'profile_name' => (string) ($profile['name'] ?? 'Canal'),
    'channel_title' => (string) ($snippet['title'] ?? ''),
    'channel_custom_url' => (string) ($snippet['customUrl'] ?? ''),
    'refreshed' => $refreshed,
  ];
}

function admin_youtube_suggestions_for_mode($analysis, $mode) {
  if (!is_array($analysis)) {
    return [];
  }
  if (($mode ?: 'short') === 'long') {
    return (array) ($analysis['long_suggestions'] ?? []);
  }
  return (array) ($analysis['suggestions'] ?? []);
}

function admin_compact_youtube_process_result($result) {
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

function admin_youtube_cuts_read_manifest($jobId) {
  $manifestPath = admin_youtube_cuts_asset_path($jobId, 'manifest.json');
  if (!$manifestPath || !is_file($manifestPath)) {
    $runtimeDir = admin_youtube_cuts_runtime_dir();
    $safeJobId = preg_replace('/[^A-Za-z0-9_-]+/', '', (string) $jobId);
    if (!$runtimeDir || $safeJobId === '') {
      return null;
    }
    $candidate = $runtimeDir . DIRECTORY_SEPARATOR . $safeJobId . DIRECTORY_SEPARATOR . 'manifest.json';
    if (!is_file($candidate)) {
      return null;
    }
    $manifestPath = $candidate;
  }
  $decoded = json_decode((string) @file_get_contents($manifestPath), true);
  return is_array($decoded) ? $decoded : null;
}

function admin_youtube_publish_schedule_defaults() {
  $scheduledTs = time() + 86400;
  return [
    'date' => date('Y-m-d', $scheduledTs),
    'time' => '09:00',
  ];
}

function admin_youtube_profile_requires_person_gate($profileName = '', $profileHandle = '') {
  $values = [
    strtolower(preg_replace('~[^a-z0-9]+~', '', (string) $profileName)),
    strtolower(preg_replace('~[^a-z0-9]+~', '', ltrim((string) $profileHandle, '@'))),
  ];
  foreach ($values as $value) {
    if ($value === 'zerocortespolitica' || strpos($value, 'zerocortespolitica') === 0) {
      return false;
    }
  }
  return false;
}

function admin_youtube_cut_person_status($cut, $mode = 'short', $profileName = '', $profileHandle = '') {
  $normalizedMode = trim((string) $mode);
  if ($normalizedMode !== 'short') {
    return null;
  }
  if (!admin_youtube_profile_requires_person_gate($profileName, $profileHandle)) {
    return null;
  }

  $speakerDetected = !empty($cut['opening_speaker_detected']);
  $publishAllowed = !array_key_exists('publish_allowed', (array) $cut) || !empty($cut['publish_allowed']);
  $speakerScore = (int) ($cut['opening_speaker_score'] ?? 0);
  $reason = trim((string) ($cut['publish_block_reason'] ?? ''));

  if ($speakerDetected) {
    return [
      'label' => 'Pessoa detectada',
      'class' => 'ok',
      'message' => $speakerScore > 0 ? ('Deteccao visual de pessoa falando no inicio do short. Score ' . $speakerScore . '.') : 'Deteccao visual de pessoa falando no inicio do short.',
    ];
  }

  if (!$publishAllowed) {
    return [
      'label' => 'Nao publicar',
      'class' => 'off',
      'message' => $reason !== '' ? $reason : 'O inicio do short nao mostrou uma pessoa falando em quadro.',
    ];
  }

  return [
    'label' => 'Revisar pessoa',
    'class' => 'warn',
    'message' => $reason !== '' ? $reason : 'Revise o enquadramento antes de publicar este short.',
  ];
}

$youtubeProfiles = admin_fetch_local_youtube_profiles($pdo);
if (!$selectedChannelProfileId && $youtubeProfiles) {
  $selectedChannelProfileId = (int) ($youtubeProfiles[0]['id'] ?? 0);
  $youtubeForm['channel_profile_id'] = $selectedChannelProfileId;
}
if (isset($_GET['channel_profile_id'])) {
  $requestedChannelProfileId = max(0, (int) ($_GET['channel_profile_id'] ?? 0));
  $previousChannelProfileId = (int) ($_SESSION['admin_youtube_cuts_channel_profile_id'] ?? 0);
  if ($requestedChannelProfileId !== $previousChannelProfileId) {
    $youtubeForm = admin_youtube_reset_profile_view_state($requestedChannelProfileId);
    $youtubeCutAnalysis = null;
    $youtubeCutsProcess = null;
    $youtubeLastPublish = null;
    $youtubeTrendIdeas = null;
    $pendingYoutubeJob = null;
  }
  $selectedChannelProfileId = $requestedChannelProfileId;
  $youtubeForm['channel_profile_id'] = $requestedChannelProfileId;
  $_SESSION['admin_youtube_cuts_channel_profile_id'] = $requestedChannelProfileId;
  $_SESSION['admin_youtube_cuts_form'] = $youtubeForm;
}
if (!empty($_GET['youtube_url'])) {
  $youtubeTab = 'gerar';
  $youtubeForm['url'] = trim((string) $_GET['youtube_url']);
  $_SESSION['admin_youtube_cuts_form'] = $youtubeForm;
}
$youtubeSelectedProfileStatus = admin_build_youtube_status_summary(
  admin_fetch_youtube_profile_status($pdo, (int) ($youtubeForm['channel_profile_id'] ?? 0))
);

$generateTabUrl = admin_youtube_cuts_tab_url('gerar');
$historyTabUrl = admin_youtube_cuts_tab_url('historico');
$publishScheduleDefaults = admin_youtube_publish_schedule_defaults();
$youtubeRecoveryHint = null;
if (is_array($flash) && (string) ($flash['type'] ?? '') === 'error') {
  $flashMessage = trim((string) ($flash['message'] ?? ''));
  if ($flashMessage !== '' && stripos($flashMessage, 'Reconecte o canal em /manager') !== false) {
    $youtubeRecoveryHint = [
      'title' => 'Reconectar canal do YouTube',
      'message' => $flashMessage,
      'manager_url' => '/manager',
    ];
  }
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
  admin_csrf_check_or_die();
  $action = (string) ($_POST['acao'] ?? '');

  if (in_array($action, ['analyze_video', 'generate_cuts', 'run_private_test'], true)) {
    $youtubeUrl = trim((string) ($_POST['youtube_url'] ?? ''));
    $youtubeMode = trim((string) ($_POST['youtube_mode'] ?? 'short'));
    $youtubeStrategy = trim((string) ($_POST['selection_strategy'] ?? 'openai_heuristica'));
    $youtubeRiskProfile = trim((string) ($_POST['risk_profile'] ?? 'default'));
    if (!in_array($youtubeRiskProfile, ['default', 'conservative'], true)) {
      $youtubeRiskProfile = 'default';
    }
    $channelProfileId = max(0, (int) ($_POST['channel_profile_id'] ?? 0));
    $burnSubtitles = isset($_POST['burn_subtitles']);
    $_SESSION['admin_youtube_cuts_form'] = [
      'url' => $youtubeUrl,
      'mode' => $youtubeMode,
      'selection_strategy' => $youtubeStrategy,
      'risk_profile' => $youtubeRiskProfile,
      'channel_profile_id' => $channelProfileId,
      'burn_subtitles' => $burnSubtitles,
    ];
    $_SESSION['admin_youtube_cuts_channel_profile_id'] = $channelProfileId;

    if ($youtubeUrl === '') {
      admin_flash_set('error', 'Cole um link do YouTube para continuar.');
      header('Location: ' . $generateTabUrl);
      exit;
    }

    if ($action === 'analyze_video') {
      $jobStart = admin_start_python_job_async(
        ['youtube-cuts-analyze', '--url', $youtubeUrl],
        ['kind' => 'analyze_video', 'target_tab' => 'gerar']
      );
      if (!empty($jobStart['ok'])) {
        $_SESSION['admin_youtube_cuts_pending_job'] = [
          'job_id' => (string) ($jobStart['job_id'] ?? ''),
          'kind' => 'analyze_video',
          'target_tab' => 'gerar',
        ];
        admin_flash_set('success', 'Analise iniciada. O servidor vai atualizar esta tela quando terminar.');
      } else {
        admin_flash_set('error', (string) ($jobStart['error'] ?? 'Falha ao iniciar a analise do video do YouTube.'));
      }
      header('Location: ' . $generateTabUrl);
      exit;
    }

    if ($action === 'run_private_test') {
      $args = [
        'youtube-cut-private-test',
        '--url', $youtubeUrl,
        '--limit', '3',
        '--selection-strategy', $youtubeStrategy,
      ];
      if ($channelProfileId > 0) {
        $args[] = '--channel-profile-id';
        $args[] = (string) $channelProfileId;
      }
      if (!$burnSubtitles) {
        $args[] = '--no-burn-subtitles';
      }
      $jobStart = admin_start_python_job_async(
        $args,
        ['kind' => 'private_test', 'target_tab' => 'historico']
      );
      if (!empty($jobStart['ok'])) {
        $_SESSION['admin_youtube_cuts_pending_job'] = [
          'job_id' => (string) ($jobStart['job_id'] ?? ''),
          'kind' => 'private_test',
          'target_tab' => 'historico',
        ];
        admin_flash_set('success', 'Teste privado iniciado com preset de risco menor. Aguarde a geracao e o envio privado.');
      } else {
        admin_flash_set('error', (string) ($jobStart['error'] ?? 'Falha ao iniciar o teste privado do YouTube.'));
      }
      header('Location: ' . $generateTabUrl);
      exit;
    }

    $args = [
      'youtube-cuts-process',
      '--url', $youtubeUrl,
      '--limit', $youtubeMode === 'long' ? '3' : '5',
      '--mode', $youtubeMode,
      '--selection-strategy', $youtubeStrategy,
    ];
    if ($youtubeMode === 'short') {
      $args[] = '--risk-profile';
      $args[] = $youtubeRiskProfile;
    }
    if ($channelProfileId > 0) {
      $args[] = '--channel-profile-id';
      $args[] = (string) $channelProfileId;
    }
    if (!$burnSubtitles) {
      $args[] = '--no-burn-subtitles';
    }
    $jobStart = admin_start_python_job_async(
      $args,
      ['kind' => 'generate_cuts', 'target_tab' => 'historico']
    );
    if (!empty($jobStart['ok'])) {
      $_SESSION['admin_youtube_cuts_pending_job'] = [
        'job_id' => (string) ($jobStart['job_id'] ?? ''),
        'kind' => 'generate_cuts',
        'target_tab' => 'historico',
      ];
      admin_flash_set('success', 'Geracao iniciada. Aguarde o progresso nesta tela.');
      header('Location: ' . $generateTabUrl);
    } else {
      admin_flash_set('error', (string) ($jobStart['error'] ?? 'Falha ao iniciar a geracao dos cortes do YouTube.'));
      header('Location: ' . $generateTabUrl);
    }
    exit;
  }

  if ($action === 'load_trends' || $action === 'run_auto_cut_publish') {
    $channelProfileId = max(0, (int) ($_POST['channel_profile_id'] ?? 0));
    $_SESSION['admin_youtube_cuts_channel_profile_id'] = $channelProfileId;
    if (!empty($_SESSION['admin_youtube_cuts_form']) && is_array($_SESSION['admin_youtube_cuts_form'])) {
      $_SESSION['admin_youtube_cuts_form']['channel_profile_id'] = $channelProfileId;
    }
    if ($action === 'run_auto_cut_publish') {
      $args = [
        'youtube-auto-cut-publish',
          '--recent-limit', '12',
          '--videos-per-topic', '8',
        '--cut-limit', '5',
        '--retry-candidates', '4',
      ];
      if ($channelProfileId > 0) {
        $args[] = '--channel-profile-id';
        $args[] = (string) $channelProfileId;
      }
      $jobStart = admin_start_python_job_async(
        $args,
        ['kind' => 'auto_cut_publish', 'target_tab' => 'gerar']
      );
      if (!empty($jobStart['ok'])) {
        $_SESSION['admin_youtube_cuts_pending_job'] = [
          'job_id' => (string) ($jobStart['job_id'] ?? ''),
          'kind' => 'auto_cut_publish',
          'target_tab' => 'gerar',
        ];
        admin_flash_set('success', 'Auto job iniciado. O progresso do canal escolhido aparece logo abaixo.');
      } else {
        admin_flash_set('error', (string) ($jobStart['error'] ?? 'Falha ao iniciar o auto job do YouTube.'));
      }
    } else {
      $args = [
        'youtube-trends-themes',
          '--recent-limit', '12',
          '--videos-per-topic', '8',
      ];
      if ($channelProfileId > 0) {
        $args[] = '--channel-profile-id';
        $args[] = (string) $channelProfileId;
      }
      $payload = admin_run_python_job($args);
      if (!empty($payload['ok'])) {
        $_SESSION['admin_youtube_trend_ideas'] = is_array($payload['result'] ?? null) ? $payload['result'] : null;
        admin_flash_set('success', 'Radar de videos para cortar carregado com sucesso.');
      } else {
        admin_flash_set('error', (string) ($payload['error'] ?? 'Falha ao carregar o radar de videos.'));
      }
    }
    header('Location: ' . $generateTabUrl);
    exit;
  }

  if ($action === 'reconnect_youtube') {
    $channelProfileId = max(0, (int) ($_POST['channel_profile_id'] ?? 0));
    $_SESSION['admin_youtube_cuts_channel_profile_id'] = $channelProfileId;
    if (!empty($_SESSION['admin_youtube_cuts_form']) && is_array($_SESSION['admin_youtube_cuts_form'])) {
      $_SESSION['admin_youtube_cuts_form']['channel_profile_id'] = $channelProfileId;
    }

    $profile = admin_fetch_youtube_profile_for_oauth($pdo, $channelProfileId);
    if (!$profile) {
      admin_flash_set('error', 'Nenhum perfil ativo de canal do YouTube foi encontrado para reconectar.');
      header('Location: ' . $generateTabUrl);
      exit;
    }

    $state = bin2hex(random_bytes(16));
    $redirectUri = admin_current_absolute_url('/admin/youtube_oauth_callback.php');
    $authUrl = admin_build_youtube_auth_url(
      (string) ($profile['client_id'] ?? ''),
      $redirectUri,
      $state
    );
    if ($authUrl === '') {
      admin_flash_set('error', 'Esse perfil nao tem Client ID configurado ou o site nao conseguiu montar a URL publica do callback.');
      header('Location: ' . $generateTabUrl);
      exit;
    }

    try {
      $stmt = $pdo->prepare("UPDATE youtube_channel_profiles SET oauth_state = ? WHERE id = ? LIMIT 1");
      $stmt->execute([$state, (int) ($profile['id'] ?? 0)]);
    } catch (Throwable $e) {
      admin_flash_set('error', 'Nao foi possivel preparar a reconexao OAuth do YouTube para esse perfil.');
      header('Location: ' . $generateTabUrl);
      exit;
    }

    header('Location: ' . $authUrl);
    exit;
  }

  if ($action === 'test_youtube_auth') {
    $channelProfileId = max(0, (int) ($_POST['channel_profile_id'] ?? 0));
    $_SESSION['admin_youtube_cuts_channel_profile_id'] = $channelProfileId;
    if (!empty($_SESSION['admin_youtube_cuts_form']) && is_array($_SESSION['admin_youtube_cuts_form'])) {
      $_SESSION['admin_youtube_cuts_form']['channel_profile_id'] = $channelProfileId;
    }

    try {
      $result = admin_youtube_test_auth($pdo, $channelProfileId);
      $channelLabel = trim((string) ($result['channel_title'] ?? ''));
      $refreshLabel = !empty($result['refreshed']) ? ' Token renovado com sucesso.' : '';
      admin_flash_set(
        'success',
        'Teste de autenticacao do YouTube OK para o perfil '
        . (string) ($result['profile_name'] ?? 'Canal')
        . ($channelLabel !== '' ? '. Canal: ' . $channelLabel . '.' : '.')
        . $refreshLabel
      );
    } catch (Throwable $e) {
      admin_flash_set('error', 'Falha no teste de autenticacao do YouTube: ' . $e->getMessage());
    }

    header('Location: ' . $generateTabUrl);
    exit;
  }

  if ($action === 'publish_cut') {
    $jobId = trim((string) ($_POST['job_id'] ?? ''));
    $cutId = max(1, (int) ($_POST['cut_id'] ?? 0));
    $mode = trim((string) ($_POST['mode'] ?? 'short'));
    $channelProfileId = max(0, (int) ($_POST['channel_profile_id'] ?? 0));
    if ($channelProfileId <= 0 && $jobId !== '') {
      $manifest = admin_youtube_cuts_read_manifest($jobId);
      $channelProfileId = max(0, (int) (($manifest['target_channel_profile_id'] ?? 0)));
    }
    $privacyStatus = trim((string) ($_POST['privacy_status'] ?? 'private'));
    if (!in_array($privacyStatus, ['public', 'private', 'scheduled'], true)) {
      $privacyStatus = 'public';
    }
    $publishDate = trim((string) ($_POST['publish_date'] ?? ''));
    $publishTime = trim((string) ($_POST['publish_time'] ?? ''));
    $publishAt = '';
    if ($privacyStatus === 'scheduled') {
      if ($publishDate === '' || $publishTime === '') {
        admin_flash_set('error', 'Escolha data e hora para programar a publicacao no YouTube.');
        header('Location: ' . $historyTabUrl);
        exit;
      }
      $publishAt = $publishDate . 'T' . substr($publishTime, 0, 5);
    }
    $args = [
      'youtube-cut-publish',
      '--job-id', $jobId,
      '--cut-id', (string) $cutId,
      '--mode', $mode !== '' ? $mode : 'short',
      '--privacy-status', $privacyStatus,
    ];
    if ($publishAt !== '') {
      $args[] = '--publish-at';
      $args[] = $publishAt;
    }
    if ($channelProfileId > 0) {
      $args[] = '--channel-profile-id';
      $args[] = (string) $channelProfileId;
    }
    $payload = admin_run_python_job($args);
    if (!empty($payload['ok'])) {
      $_SESSION['admin_youtube_cuts_last_publish'] = is_array($payload['result'] ?? null) ? $payload['result'] : null;
      $youtubeUrl = (string) (($payload['result'] ?? [])['youtube_url'] ?? '');
      if ($privacyStatus === 'scheduled') {
        admin_flash_set('success', 'Corte enviado ao YouTube com agendamento salvo com sucesso.');
      } else {
        admin_flash_set('success', $youtubeUrl !== '' ? "Corte publicado com sucesso. Link: {$youtubeUrl}" : 'Corte publicado com sucesso no YouTube.');
      }
    } else {
      admin_flash_set('error', (string) ($payload['error'] ?? 'Falha ao publicar o corte no YouTube.'));
    }
    header('Location: ' . $historyTabUrl);
    exit;
  }

  if ($action === 'rerender_cut') {
    $jobId = trim((string) ($_POST['job_id'] ?? ''));
    $cutId = max(1, (int) ($_POST['cut_id'] ?? 0));
    $framing = trim((string) ($_POST['crop_override'] ?? 'auto'));
    if (!in_array($framing, ['auto', 'esquerda', 'direita'], true)) {
      $framing = 'auto';
    }
    $payload = admin_run_python_job([
      'youtube-cut-rerender',
      '--job-id', $jobId,
      '--cut-id', (string) $cutId,
      '--framing', $framing,
    ]);
    if (!empty($payload['ok'])) {
      if (is_array($youtubeCutsProcess) && (string) ($youtubeCutsProcess['job_id'] ?? '') === $jobId) {
        foreach ((array) ($youtubeCutsProcess['cuts'] ?? []) as $index => $cut) {
          if ((int) ($cut['cut_id'] ?? 0) !== $cutId) {
            continue;
          }
          $youtubeCutsProcess['cuts'][$index]['crop_override'] = $framing;
          $youtubeCutsProcess['cuts'][$index]['opening_focus_zone'] = (string) (($payload['result']['opening_focus_zone'] ?? ''));
          $youtubeCutsProcess['cuts'][$index]['opening_visual_score'] = (int) (($payload['result']['opening_visual_score'] ?? 0));
          break;
        }
        $_SESSION['admin_youtube_cuts_process'] = $youtubeCutsProcess;
      }
      admin_flash_set('success', 'Corte regerado com o novo enquadramento.');
    } else {
      admin_flash_set('error', (string) ($payload['error'] ?? 'Falha ao regerar o corte com o novo enquadramento.'));
    }
    header('Location: ' . $historyTabUrl);
    exit;
  }

  if ($action === 'cleanup_expired') {
    $removed = admin_youtube_cuts_cleanup_expired();
    admin_flash_set('success', $removed > 0 ? "{$removed} job(s) vencido(s) apagado(s)." : 'Nenhum job vencido para apagar agora.');
    header('Location: ' . $historyTabUrl);
    exit;
  }

  if ($action === 'delete_job') {
    $jobId = trim((string) ($_POST['job_id'] ?? ''));
    $deleted = admin_youtube_cuts_delete_job($jobId);
    admin_flash_set($deleted ? 'success' : 'error', $deleted ? 'Job apagado com sucesso.' : 'Nao foi possivel apagar esse job.');
    header('Location: ' . $historyTabUrl);
    exit;
  }
}

$jobs = admin_youtube_cuts_list_jobs(24);
$activeJobs = count($jobs);
$totalCuts = 0;
$totalBytes = 0;
foreach ($jobs as $job) {
  $totalCuts += count((array) ($job['cuts'] ?? []));
  $totalBytes += (int) ($job['total_bytes'] ?? 0);
}
$adminCssVersion = (string) @filemtime(__DIR__ . '/../assets/css/admin.css');

function admin_cuts_format_datetime($timestamp) {
  $value = max(0, (int) $timestamp);
  if ($value <= 0) {
    return '-';
  }
  return date('d/m/Y H:i', $value);
}

function admin_cuts_remaining_label($expiresTs) {
  $seconds = max(0, (int) $expiresTs - time());
  if ($seconds <= 0) {
    return 'vence agora';
  }
  $hours = (int) floor($seconds / 3600);
  $minutes = (int) floor(($seconds % 3600) / 60);
  if ($hours <= 0) {
    return $minutes > 0 ? "{$minutes} min restantes" : 'menos de 1 min';
  }
  return $minutes > 0 ? "{$hours}h {$minutes}min restantes" : "{$hours}h restantes";
}

function admin_cuts_format_bytes($bytes) {
  $value = max(0, (float) $bytes);
  $units = ['B', 'KB', 'MB', 'GB', 'TB'];
  $index = 0;
  while ($value >= 1024 && $index < count($units) - 1) {
    $value /= 1024;
    $index++;
  }
  return number_format($value, $index === 0 ? 0 : 1, ',', '.') . ' ' . $units[$index];
}
?>
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Admin - YouTube cortes</title>
  <link rel="icon" type="image/png" href="/assets/img/logo-zp.png">
  <link rel="stylesheet" href="/assets/css/style.css">
  <link rel="stylesheet" href="/assets/css/admin.css?v=<?= urlencode($adminCssVersion) ?>">
</head>
<body class="admin-page">
<?php admin_render_header('youtube_cortes'); ?>

<main class="container admin-shell">
  <?php if ($flash): ?>
    <div class="admin-alert <?= h((string) ($flash['type'] ?? '')) ?>"><?= h((string) ($flash['message'] ?? '')) ?></div>
  <?php endif; ?>
  <?php if ($youtubeRecoveryHint): ?>
    <section class="admin-panel">
      <div class="admin-panel-head">
        <div>
          <h2 class="admin-section-title"><?= h((string) ($youtubeRecoveryHint['title'] ?? 'Reconectar YouTube')) ?></h2>
          <p><?= h((string) ($youtubeRecoveryHint['message'] ?? 'Abra o manager e reconecte o canal.')) ?></p>
        </div>
        <div class="admin-card-actions">
          <form method="post">
            <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
            <input type="hidden" name="acao" value="reconnect_youtube">
            <input type="hidden" name="channel_profile_id" value="<?= (int) ($youtubeForm['channel_profile_id'] ?? 0) ?>">
            <button class="btn-link primary" type="submit">Reconectar agora</button>
          </form>
        </div>
      </div>
    </section>
  <?php endif; ?>

  <section class="admin-hero">
    <div class="admin-hero-head">
      <div class="admin-hero-copy">
        <span class="admin-kicker">Cortes do YouTube</span>
        <h1>Biblioteca de cortes gerados</h1>
      </div>
      <div class="admin-hero-actions">
        <a class="btn-link" href="/admin/youtube_canais.php">Perfis de canal</a>
        <a class="btn-link primary" href="/admin/social.php">Voltar ao social</a>
        <form method="post">
          <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
          <input type="hidden" name="acao" value="cleanup_expired">
          <button class="badge" type="submit">Limpar vencidos agora</button>
        </form>
      </div>
    </div>
  </section>

  <nav class="admin-subnav" aria-label="Submenu YouTube cortes">
    <a class="admin-subnav-link <?= $youtubeTab === 'gerar' ? 'is-active' : '' ?>" href="<?= h($generateTabUrl) ?>">Gerar cortes</a>
    <a class="admin-subnav-link <?= $youtubeTab === 'historico' ? 'is-active' : '' ?>" href="<?= h($historyTabUrl) ?>">Jobs e historico</a>
    <a class="admin-subnav-link" href="/admin/youtube_canais.php">Cadastro de canais</a>
  </nav>

  <?php if ($youtubeTab === 'gerar'): ?>
  <section class="admin-panel">
    <div class="admin-panel-head admin-radar-head">
      <div>
        <h2 class="admin-section-title">Radar de videos para cortar</h2>
      </div>
      <div class="admin-card-actions admin-radar-actions">
        <form method="post" class="admin-inline-form admin-inline-form-radar" data-current-tab="<?= h((string) $youtubeTab) ?>">
          <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
          <label class="admin-inline-form-field" for="radar_channel_profile_id">
            <span>Canal do radar</span>
            <select id="radar_channel_profile_id" name="channel_profile_id" data-profile-switch-url="/admin/youtube_cortes.php">
              <option value="0">Padrao configurado</option>
              <?php foreach ($youtubeProfiles as $profile): ?>
                <?php $profileId = (int) ($profile['id'] ?? 0); ?>
                <option value="<?= $profileId ?>" <?= (int) ($youtubeForm['channel_profile_id'] ?? 0) === $profileId ? 'selected' : '' ?>>
                  <?= h((string) ($profile['name'] ?? 'Canal')) ?><?= !empty($profile['is_default']) ? ' (padrao)' : '' ?>
                </option>
              <?php endforeach; ?>
            </select>
          </label>
          <button class="btn-link primary" type="submit" name="acao" value="load_trends">Carregar radar</button>
          <button class="btn-link" type="submit" name="acao" value="run_auto_cut_publish" data-confirm-auto-job>Rodar auto job</button>
          <button class="btn-link" type="submit" name="acao" value="test_youtube_auth">Testar autenticacao</button>
          <button class="btn-link" type="submit" name="acao" value="reconnect_youtube">Reconectar YouTube</button>
        </form>
      </div>
    </div>
    <article class="admin-side-card" style="margin-bottom:16px;">
      <div class="admin-panel-head" style="padding:0; margin-bottom:10px;">
        <div>
          <strong>Status do canal selecionado</strong>
          <p class="admin-card-subtitle"><?= h((string) ($youtubeSelectedProfileStatus['message'] ?? '')) ?></p>
        </div>
        <div class="admin-meta-row">
          <span class="admin-status <?= h((string) ($youtubeSelectedProfileStatus['class'] ?? 'warn')) ?>"><?= h((string) ($youtubeSelectedProfileStatus['label'] ?? 'Pendente')) ?></span>
        </div>
      </div>
      <div class="admin-meta-row">
        <span class="admin-meta-chip"><?= h((string) (($youtubeSelectedProfileStatus['channel'] ?? '') !== '' ? $youtubeSelectedProfileStatus['channel'] : 'Canal ainda nao autenticado')) ?></span>
        <?php if (!empty($youtubeSelectedProfileStatus['handle'])): ?>
          <span class="admin-meta-chip admin-meta-chip-soft">@<?= h((string) $youtubeSelectedProfileStatus['handle']) ?></span>
        <?php endif; ?>
        <span class="admin-meta-chip admin-meta-chip-soft">OAuth <?= !empty($youtubeSelectedProfileStatus['oauth_ready']) ? 'ok' : 'pendente' ?></span>
        <span class="admin-meta-chip admin-meta-chip-soft">Refresh token <?= !empty($youtubeSelectedProfileStatus['refresh_ready']) ? 'ok' : 'pendente' ?></span>
        <span class="admin-meta-chip admin-meta-chip-soft">Access token <?= !empty($youtubeSelectedProfileStatus['access_ready']) ? (!empty($youtubeSelectedProfileStatus['token_expired']) ? 'expirado' : 'ativo') : 'vazio' ?></span>
      </div>
    </article>

    <?php if (is_array($youtubeTrendIdeas) && !empty($youtubeTrendIdeas['ideas'])): ?>
      <div class="admin-cut-grid">
        <?php foreach ((array) ($youtubeTrendIdeas['ideas'] ?? []) as $idea): ?>
          <article class="admin-side-card">
            <strong><?= h((string) ($idea['seed_title'] ?? 'Tema sugerido')) ?></strong>
            <p class="admin-card-subtitle">Canal inscrito com uploads recentes para gerar novos cortes.</p>
            <div class="admin-meta-row">
              <?php if (!empty($idea['query'])): ?>
                <span class="admin-meta-chip"><?= h((string) $idea['query']) ?></span>
              <?php endif; ?>
              <span class="admin-meta-chip admin-meta-chip-soft">ultimas 48h</span>
            </div>
            <div style="display:grid; gap:10px; margin-top:12px;">
              <?php foreach ((array) ($idea['videos'] ?? []) as $video): ?>
                <div class="admin-side-card">
                  <strong><?= h((string) ($video['title'] ?? 'Video sugerido')) ?></strong>
                  <div class="admin-card-subtitle">
                    <?= h((string) ($video['channel_title'] ?? 'Canal')) ?>
                    <?php if (!empty($video['duration_label'])): ?> • <?= h((string) $video['duration_label']) ?><?php endif; ?>
                  </div>
                  <div class="admin-meta-row">
                    <?php if (!empty($video['cut_score'])): ?>
                      <span class="admin-meta-chip">Potencial <?= (int) $video['cut_score'] ?>/100</span>
                    <?php endif; ?>
                    <?php if (!empty($video['published_at'])): ?>
                      <span class="admin-meta-chip admin-meta-chip-soft"><?= h((string) $video['published_at']) ?></span>
                    <?php endif; ?>
                  </div>
                  <div class="admin-card-actions" style="margin-top:10px;">
                    <?php if (!empty($video['url'])): ?>
                      <a class="badge" href="<?= h((string) $video['url']) ?>" target="_blank" rel="noopener">Abrir link</a>
                      <a class="btn-link primary" href="/admin/youtube_cortes.php?youtube_url=<?= urlencode((string) $video['url']) ?>&channel_profile_id=<?= (int) ($youtubeForm['channel_profile_id'] ?? 0) ?>">Usar no corte</a>
                    <?php endif; ?>
                  </div>
                </div>
              <?php endforeach; ?>
            </div>
          </article>
        <?php endforeach; ?>
      </div>
    <?php else: ?>
      <div class="admin-empty">Clique em "Carregar radar" para listar videos recentes com potencial de corte.</div>
    <?php endif; ?>
  </section>
  <?php if (is_array($pendingYoutubeJob) && !empty($pendingYoutubeJob['job_id'])): ?>
  <section class="admin-panel admin-progress-card" id="youtube-cuts-progress-card" data-job-id="<?= h((string) $pendingYoutubeJob['job_id']) ?>" data-status-url="/admin/youtube_cortes_job_status.php?job_id=<?= urlencode((string) $pendingYoutubeJob['job_id']) ?>">
    <div class="admin-panel-head">
      <div>
        <?php
          $pendingKind = (string) ($pendingYoutubeJob['kind'] ?? '');
          $progressTitle = 'Gerando cortes';
          if ($pendingKind === 'analyze_video') {
            $progressTitle = 'Analisando video';
          } elseif ($pendingKind === 'auto_cut_publish') {
            $progressTitle = 'Rodando auto job do canal';
          }
        ?>
        <h2 class="admin-section-title"><?= h($progressTitle) ?></h2>
        <p id="youtube-cuts-progress-label">Preparando o processamento no servidor.</p>
      </div>
      <div class="admin-meta-row">
        <span class="admin-meta-chip admin-meta-chip-soft" id="youtube-cuts-progress-time">0s</span>
      </div>
    </div>
    <div class="admin-progress-bar" aria-hidden="true">
      <div class="admin-progress-bar-fill" id="youtube-cuts-progress-fill" style="width: 10%;"></div>
    </div>
    <p class="admin-card-subtitle">A tela nao fica mais presa. No celular, pode deixar aberta que o andamento continua sendo atualizado automaticamente.</p>
  </section>
  <?php endif; ?>
  <?php endif; ?>

  <?php if ($youtubeTab === 'gerar'): ?>
  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Analisar e gerar cortes</h2>
        <p>Use o proprio admin PHP para analisar o video, gerar os cortes e depois publicar no YouTube.</p>
      </div>
    </div>
    <form method="post" class="admin-filter-form">
      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
      <div class="admin-field-grid">
        <div class="admin-field">
          <label for="youtube_mode">Modo de corte</label>
          <select id="youtube_mode" name="youtube_mode">
            <option value="short" <?= ($youtubeForm['mode'] ?? 'short') === 'short' ? 'selected' : '' ?>>Short</option>
            <option value="long" <?= ($youtubeForm['mode'] ?? '') === 'long' ? 'selected' : '' ?>>Corte longo</option>
          </select>
        </div>
        <div class="admin-field">
          <label for="selection_strategy">Selecao dos shorts</label>
          <select id="selection_strategy" name="selection_strategy">
            <option value="openai_heuristica" <?= ($youtubeForm['selection_strategy'] ?? 'openai_heuristica') === 'openai_heuristica' ? 'selected' : '' ?>>OpenAI + Heuristica</option>
            <option value="openai" <?= ($youtubeForm['selection_strategy'] ?? '') === 'openai' ? 'selected' : '' ?>>OpenAI</option>
            <option value="heuristica" <?= ($youtubeForm['selection_strategy'] ?? '') === 'heuristica' ? 'selected' : '' ?>>Heuristica</option>
          </select>
        </div>
        <div class="admin-field">
          <label for="risk_profile">Perfil de risco</label>
          <select id="risk_profile" name="risk_profile">
            <option value="default" <?= ($youtubeForm['risk_profile'] ?? 'default') === 'default' ? 'selected' : '' ?>>Padrao</option>
            <option value="conservative" <?= ($youtubeForm['risk_profile'] ?? '') === 'conservative' ? 'selected' : '' ?>>Risco menor</option>
          </select>
        </div>
        <div class="admin-field">
          <label for="channel_profile_id">Canal do YouTube</label>
          <select id="channel_profile_id" name="channel_profile_id">
            <option value="0">Padrao configurado</option>
            <?php foreach ($youtubeProfiles as $profile): ?>
              <?php $profileId = (int) ($profile['id'] ?? 0); ?>
              <option value="<?= $profileId ?>" <?= (int) ($youtubeForm['channel_profile_id'] ?? 0) === $profileId ? 'selected' : '' ?>>
                <?= h((string) ($profile['name'] ?? 'Canal')) ?><?= !empty($profile['is_default']) ? ' (padrao)' : '' ?>
              </option>
            <?php endforeach; ?>
          </select>
        </div>
        <div class="admin-field">
          <label for="burn_subtitles">Legenda do short</label>
          <div class="admin-check-row admin-check-row-inline">
            <label class="admin-check-chip admin-check-chip-wide">
              <input id="burn_subtitles" type="checkbox" name="burn_subtitles" value="1" <?= !array_key_exists('burn_subtitles', $youtubeForm) || !empty($youtubeForm['burn_subtitles']) ? 'checked' : '' ?>>
              Gerar com legenda
            </label>
          </div>
        </div>
        <div class="admin-field is-full">
          <label for="youtube_url">Link do YouTube</label>
          <input id="youtube_url" type="text" name="youtube_url" value="<?= h((string) ($youtubeForm['url'] ?? '')) ?>" placeholder="https://www.youtube.com/watch?v=...">
        </div>
      </div>
      <div class="admin-form-actions">
        <button class="btn-link primary" type="submit" name="acao" value="analyze_video">Analisar video</button>
        <button class="btn" type="submit" name="acao" value="generate_cuts">Gerar cortes</button>
        <button class="btn" type="submit" name="acao" value="run_private_test">Teste privado risco menor</button>
      </div>
    </form>
  </section>
  <?php endif; ?>

  <?php if ($youtubeTab === 'gerar' && is_array($youtubeCutAnalysis) && !empty($youtubeCutAnalysis['video'])): ?>
    <?php $analysisSuggestions = admin_youtube_suggestions_for_mode($youtubeCutAnalysis, (string) ($youtubeForm['mode'] ?? 'short')); ?>
    <section class="admin-panel">
      <div class="admin-panel-head">
        <div>
          <h2 class="admin-section-title">Analise atual</h2>
          <p><?= h((string) ($youtubeCutAnalysis['video']['title'] ?? 'Video analisado')) ?></p>
        </div>
      </div>
      <div class="admin-mini-grid">
        <div class="admin-side-card">
          <strong>Canal</strong>
          <div class="admin-card-subtitle"><?= h((string) ($youtubeCutAnalysis['video']['author_name'] ?? '-')) ?></div>
        </div>
        <div class="admin-side-card">
          <strong>Perfil editorial</strong>
          <div class="admin-card-subtitle"><?= h((string) (($youtubeCutAnalysis['strategy'] ?? [])['profile'] ?? '-')) ?></div>
        </div>
      </div>
      <?php if ($analysisSuggestions): ?>
        <div class="admin-cut-grid">
          <?php foreach ($analysisSuggestions as $index => $item): ?>
            <article class="admin-side-card">
              <strong><?= h((string) ($item['title'] ?? "Sugestao " . ($index + 1))) ?></strong>
              <p class="admin-card-subtitle"><?= h((string) ($item['hook'] ?? '')) ?></p>
              <div class="admin-meta-row">
                <?php if (!empty($item['duration_label'])): ?>
                  <span class="admin-meta-chip"><?= h((string) $item['duration_label']) ?></span>
                <?php endif; ?>
                <?php if (!empty($item['score'])): ?>
                  <span class="admin-meta-chip admin-meta-chip-soft">score <?= (int) $item['score'] ?></span>
                <?php endif; ?>
              </div>
            </article>
          <?php endforeach; ?>
        </div>
      <?php endif; ?>
    </section>
  <?php endif; ?>

  <?php if ($youtubeTab === 'historico' && is_array($youtubeCutsProcess) && !empty($youtubeCutsProcess['cuts'])): ?>
    <section class="admin-panel">
      <div class="admin-panel-head">
        <div>
          <h2 class="admin-section-title">Ultima geracao de cortes</h2>
          <p>
            job <?= h((string) ($youtubeCutsProcess['job_id'] ?? '')) ?>
            <?php if (!empty($youtubeCutsProcess['target_channel_profile_name'])): ?>
              • <?= h((string) $youtubeCutsProcess['target_channel_profile_name']) ?>
            <?php endif; ?>
          </p>
        </div>
      </div>
      <div class="admin-cut-grid">
          <?php foreach ((array) ($youtubeCutsProcess['cuts'] ?? []) as $item): ?>
          <?php
            $jobId = (string) ($item['job_id'] ?? $youtubeCutsProcess['job_id'] ?? '');
            $videoFilename = (string) ($item['video_filename'] ?? '');
            $videoUrl = $videoFilename !== ''
              ? '/admin/youtube_corte_arquivo.php?job=' . rawurlencode($jobId) . '&file=' . rawurlencode($videoFilename)
              : '';
            $mode = (string) ($item['mode'] ?? $youtubeCutsProcess['mode'] ?? 'short');
            $draft = is_array($item['publish_draft'] ?? null) ? $item['publish_draft'] : [];
            $channelProfileId = (int) (($draft['channel_profile_id'] ?? 0) ?: ($youtubeCutsProcess['target_channel_profile_id'] ?? 0));
            $titleVariants = array_slice((array) ($item['title_variants'] ?? []), 0, 3);
            $packagingNotes = array_slice((array) ($item['packaging_notes'] ?? []), 0, 3);
            $riskNotes = array_slice((array) ($item['risk_notes'] ?? []), 0, 2);
            $cropOverride = (string) ($item['crop_override'] ?? 'auto');
            $profileNameForPersonGate = (string) (($draft['channel_profile_name'] ?? '') !== '' ? $draft['channel_profile_name'] : ($youtubeCutsProcess['target_channel_profile_name'] ?? ''));
            $personStatus = admin_youtube_cut_person_status($item, $mode, $profileNameForPersonGate, '');
            $publishBlocked = $mode === 'short' && admin_youtube_profile_requires_person_gate($profileNameForPersonGate, '') && !empty($personStatus) && (string) ($personStatus['label'] ?? '') === 'Nao publicar';
          ?>
          <article class="admin-side-card">
            <?php if ($videoUrl !== ''): ?>
              <video class="admin-cut-video" controls preload="metadata" src="<?= h($videoUrl) ?>"></video>
            <?php endif; ?>
            <div class="admin-meta-row">
              <?php if (!empty($item['duration_label'])): ?>
                <span class="admin-meta-chip"><?= h((string) $item['duration_label']) ?></span>
              <?php endif; ?>
              <?php if (!empty($item['score'])): ?>
                <span class="admin-meta-chip admin-meta-chip-soft">score <?= (int) $item['score'] ?></span>
              <?php endif; ?>
              <?php if (!empty($item['opening_score'])): ?>
                <span class="admin-meta-chip admin-meta-chip-soft">gancho <?= (int) $item['opening_score'] ?></span>
              <?php endif; ?>
              <?php if (!empty($item['opening_visual_score'])): ?>
                <span class="admin-meta-chip admin-meta-chip-soft">visual <?= (int) $item['opening_visual_score'] ?></span>
              <?php endif; ?>
              <?php if (!empty($item['opening_speaker_score'])): ?>
                <span class="admin-meta-chip admin-meta-chip-soft">pessoa <?= (int) $item['opening_speaker_score'] ?></span>
              <?php endif; ?>
              <?php if (!empty($item['opening_focus_zone'])): ?>
                <span class="admin-meta-chip admin-meta-chip-soft">foco <?= h((string) $item['opening_focus_zone']) ?></span>
              <?php endif; ?>
              <?php if ($personStatus): ?>
                <span class="admin-status <?= h((string) ($personStatus['class'] ?? 'warn')) ?>"><?= h((string) ($personStatus['label'] ?? 'Revisar')) ?></span>
              <?php endif; ?>
              <?php if (!empty($draft['channel_profile_name'])): ?>
                <span class="admin-meta-chip admin-meta-chip-soft"><?= h((string) $draft['channel_profile_name']) ?></span>
              <?php endif; ?>
              <?php if (($item['risk_profile'] ?? ($youtubeCutsProcess['risk_profile'] ?? 'default')) === 'conservative'): ?>
                <span class="admin-meta-chip admin-meta-chip-soft">risco menor</span>
              <?php endif; ?>
            </div>
            <?php if (!empty($item['hook'])): ?>
              <div class="admin-card-subtitle"><?= h((string) $item['hook']) ?></div>
            <?php endif; ?>
            <?php if ($personStatus && !empty($personStatus['message'])): ?>
              <div class="admin-help" style="margin-top:8px;"><?= h((string) $personStatus['message']) ?></div>
            <?php endif; ?>
            <?php if (!empty($item['first_frame_text'])): ?>
              <div class="admin-help" style="margin-top:8px;">Abertura sugerida: <strong><?= h((string) $item['first_frame_text']) ?></strong></div>
            <?php endif; ?>
            <?php if ($titleVariants): ?>
              <div class="admin-help" style="margin-top:8px;">Titulos:
                <?= h(implode(' | ', array_map(static fn($value) => (string) $value, $titleVariants))) ?>
              </div>
            <?php endif; ?>
            <?php if ($packagingNotes): ?>
              <div class="admin-help" style="margin-top:8px;">
                <?= h(implode(' • ', array_map(static fn($value) => (string) $value, $packagingNotes))) ?>
              </div>
            <?php endif; ?>
            <?php if ($riskNotes): ?>
              <div class="admin-help" style="margin-top:8px;">
                Revisao de risco: <?= h(implode(' • ', array_map(static fn($value) => (string) $value, $riskNotes))) ?>
              </div>
            <?php endif; ?>
            <?php if ($mode === 'short'): ?>
              <form method="post" style="margin-top:10px; display:grid; gap:8px;">
                <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
                <input type="hidden" name="acao" value="rerender_cut">
                <input type="hidden" name="job_id" value="<?= h($jobId) ?>">
                <input type="hidden" name="cut_id" value="<?= (int) ($item['cut_id'] ?? 0) ?>">
                <label class="admin-field admin-field-compact">
                  <span>Enquadramento</span>
                  <select name="crop_override">
                    <option value="auto" <?= $cropOverride === 'auto' ? 'selected' : '' ?>>Auto</option>
                    <option value="esquerda" <?= $cropOverride === 'esquerda' ? 'selected' : '' ?>>Esquerda</option>
                    <option value="direita" <?= $cropOverride === 'direita' ? 'selected' : '' ?>>Direita</option>
                  </select>
                </label>
                <button class="btn-link" type="submit">Regerar enquadramento</button>
              </form>
            <?php endif; ?>
            <div class="admin-card-actions">
              <?php if ($videoUrl !== ''): ?>
                <a class="badge" href="<?= h($videoUrl) ?>" target="_blank" rel="noopener">Abrir video</a>
              <?php endif; ?>
              <form method="post" class="admin-publish-form" data-youtube-publish-form>
                <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
                <input type="hidden" name="acao" value="publish_cut">
                <input type="hidden" name="job_id" value="<?= h($jobId) ?>">
                <input type="hidden" name="cut_id" value="<?= (int) ($item['cut_id'] ?? 0) ?>">
                <input type="hidden" name="mode" value="<?= h($mode) ?>">
                <input type="hidden" name="channel_profile_id" value="<?= $channelProfileId ?>">
                <label class="admin-field admin-field-compact">
                  <span>Status no YouTube</span>
                  <select name="privacy_status" data-youtube-publish-privacy>
                    <option value="public">Publicado</option>
                    <option value="private" selected>Privado</option>
                    <option value="scheduled">Programado</option>
                  </select>
                </label>
                <div class="admin-publish-schedule" data-youtube-publish-schedule hidden>
                  <label class="admin-field admin-field-compact">
                    <span>Data</span>
                    <input type="date" name="publish_date" value="<?= h((string) $publishScheduleDefaults['date']) ?>">
                  </label>
                  <label class="admin-field admin-field-compact">
                    <span>Hora</span>
                    <input type="time" name="publish_time" value="<?= h((string) $publishScheduleDefaults['time']) ?>" step="60">
                  </label>
                </div>
                <?php if ($publishBlocked && !empty($personStatus['message'])): ?>
                  <div class="admin-help"><?= h((string) $personStatus['message']) ?></div>
                <?php endif; ?>
                <button class="btn-link primary" type="submit" <?= $publishBlocked ? 'disabled aria-disabled="true"' : '' ?>>
                  <?= $publishBlocked ? 'Bloqueado sem pessoa' : 'Enviar ao YouTube' ?>
                </button>
              </form>
            </div>
          </article>
        <?php endforeach; ?>
      </div>
    </section>
  <?php endif; ?>

  <?php if ($youtubeTab === 'historico' && is_array($youtubeLastPublish) && !empty($youtubeLastPublish['youtube_url'])): ?>
    <section class="admin-panel">
      <div class="admin-panel-head">
        <div>
          <h2 class="admin-section-title">Ultima publicacao</h2>
          <p>O ultimo envio do admin PHP para o YouTube foi concluido com sucesso.</p>
        </div>
      </div>
      <div class="admin-card-actions">
        <span class="admin-meta-chip"><?= h((string) ($youtubeLastPublish['channel_profile_name'] ?? 'Canal')) ?></span>
        <span class="admin-meta-chip admin-meta-chip-soft"><?= h(strtoupper((string) ($youtubeLastPublish['privacy_status'] ?? 'public'))) ?></span>
        <?php if (!empty($youtubeLastPublish['publish_at'])): ?>
          <span class="admin-meta-chip admin-meta-chip-soft">programado <?= h((string) $youtubeLastPublish['publish_at']) ?></span>
        <?php endif; ?>
        <span class="admin-meta-chip admin-meta-chip-soft">video <?= h((string) ($youtubeLastPublish['youtube_video_id'] ?? '')) ?></span>
        <a class="btn-link primary" href="<?= h((string) $youtubeLastPublish['youtube_url']) ?>" target="_blank" rel="noopener">Abrir no YouTube</a>
      </div>
    </section>
  <?php endif; ?>

  <?php if ($youtubeTab === 'historico'): ?>
  <section class="admin-stats-grid">
    <article class="admin-stat-card">
      <div class="admin-stat-label">Jobs ativos</div>
      <div class="admin-stat-value"><?= (int) $activeJobs ?></div>
      <div class="admin-stat-foot">ultimos jobs encontrados no runtime</div>
    </article>
    <article class="admin-stat-card">
      <div class="admin-stat-label">Cortes prontos</div>
      <div class="admin-stat-value"><?= (int) $totalCuts ?></div>
      <div class="admin-stat-foot">videos MP4 disponiveis no momento</div>
    </article>
    <article class="admin-stat-card">
      <div class="admin-stat-label">Espaco usado</div>
      <div class="admin-stat-value"><?= h(admin_cuts_format_bytes($totalBytes)) ?></div>
      <div class="admin-stat-foot">somente arquivos finais dos cortes</div>
    </article>
    <article class="admin-stat-card">
      <div class="admin-stat-label">Retencao no servidor</div>
      <div class="admin-stat-value">12h</div>
      <div class="admin-stat-foot">depois disso a pasta pode ser apagada</div>
    </article>
  </section>

  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Jobs recentes</h2>
        <p>Use esta tela para abrir, baixar e revisar os cortes antes de publicar. Se um job passar de 12 horas, ele pode sumir daqui porque a pasta entra na limpeza automatica.</p>
      </div>
    </div>

    <?php if (!$jobs): ?>
      <div class="admin-empty">Nenhum corte encontrado agora. Gere os videos no dashboard Python e eles passam a aparecer aqui enquanto a pasta estiver ativa.</div>
    <?php else: ?>
      <div class="admin-offers-grid">
        <?php foreach ($jobs as $job): ?>
          <?php
            $video = is_array($job['video'] ?? null) ? $job['video'] : [];
            $transcript = is_array($job['transcript'] ?? null) ? $job['transcript'] : [];
            $cuts = (array) ($job['cuts'] ?? []);
            $warning = trim((string) ($transcript['warning'] ?? ''));
          ?>
          <article class="admin-offer-card">
            <div class="admin-panel-head">
              <div style="min-width:0;">
                <div class="admin-card-topline">
                  <div>
                    <h3 class="admin-card-title"><?= h((string) ($video['title'] ?? 'Video base sem titulo')) ?></h3>
                    <p class="admin-card-subtitle">
                      <?= h((string) ($video['author_name'] ?? 'Canal nao informado')) ?>
                      • <?= h(strtoupper((string) ($job['mode'] ?? 'short'))) ?>
                      • criado em <?= h(admin_cuts_format_datetime((int) ($job['created_ts'] ?? 0))) ?>
                      • expira em <?= h(admin_cuts_format_datetime((int) ($job['expires_ts'] ?? 0))) ?>
                    </p>
                  </div>
                  <span class="admin-status <?= ((int) ($job['expires_ts'] ?? 0) - time()) < 3600 ? 'warn' : 'ok' ?>">
                    <?= h(admin_cuts_remaining_label((int) ($job['expires_ts'] ?? 0))) ?>
                  </span>
                </div>
                <div class="admin-meta-row">
                  <span class="admin-meta-chip">job <?= h((string) ($job['job_id'] ?? '')) ?></span>
                  <span class="admin-meta-chip"><?= count($cuts) ?> corte(s)</span>
                  <?php if (!empty($job['target_channel_profile_name'])): ?>
                    <span class="admin-meta-chip"><?= h((string) $job['target_channel_profile_name']) ?></span>
                  <?php endif; ?>
                  <?php if (!empty($job['selection_strategy'])): ?>
                    <span class="admin-meta-chip admin-meta-chip-soft">selecao <?= h((string) $job['selection_strategy']) ?></span>
                  <?php endif; ?>
                  <span class="admin-meta-chip admin-meta-chip-soft"><?= h(admin_cuts_format_bytes((int) ($job['total_bytes'] ?? 0))) ?></span>
                </div>
              </div>
              <div class="admin-card-actions">
                <?php if (!empty($video['url'])): ?>
                  <a class="badge" href="<?= h((string) $video['url']) ?>" target="_blank" rel="noopener">Video fonte</a>
                <?php endif; ?>
                <form method="post" onsubmit="return confirm('Apagar este job e todos os arquivos dele agora?');">
                  <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
                  <input type="hidden" name="acao" value="delete_job">
                  <input type="hidden" name="job_id" value="<?= h((string) ($job['job_id'] ?? '')) ?>">
                  <button class="btn-link" type="submit">Apagar job</button>
                </form>
              </div>
            </div>

            <?php if ($warning !== ''): ?>
              <div class="admin-alert"><?= h($warning) ?></div>
            <?php endif; ?>

            <div class="admin-cut-grid">
              <?php foreach ($cuts as $cut): ?>
                <?php
                  $jobId = (string) ($job['job_id'] ?? '');
                  $videoFilename = (string) ($cut['video_filename'] ?? '');
                  $subtitleFilename = (string) ($cut['subtitle_filename'] ?? '');
                  $titleVariants = array_slice((array) ($cut['title_variants'] ?? []), 0, 3);
                  $packagingNotes = array_slice((array) ($cut['packaging_notes'] ?? []), 0, 3);
                  $cropOverride = (string) ($cut['crop_override'] ?? 'auto');
                  $streamUrl = '/admin/youtube_corte_arquivo.php?job=' . rawurlencode($jobId) . '&file=' . rawurlencode($videoFilename);
                  $downloadUrl = $streamUrl . '&download=1';
                  $subtitleUrl = $subtitleFilename !== ''
                    ? '/admin/youtube_corte_arquivo.php?job=' . rawurlencode($jobId) . '&file=' . rawurlencode($subtitleFilename) . '&download=1'
                    : '';
                  $cutMode = (string) ($cut['mode'] ?? $job['mode'] ?? 'short');
                  $profileNameForPersonGate = (string) ($job['target_channel_profile_name'] ?? '');
                  $personStatus = admin_youtube_cut_person_status($cut, $cutMode, $profileNameForPersonGate, '');
                  $publishBlocked = $cutMode === 'short' && admin_youtube_profile_requires_person_gate($profileNameForPersonGate, '') && !empty($personStatus) && (string) ($personStatus['label'] ?? '') === 'Nao publicar';
                ?>
                <article class="admin-side-card">
                  <video class="admin-cut-video" controls preload="metadata" src="<?= h($streamUrl) ?>"></video>
                  <div class="admin-meta-row">
                    <span class="admin-meta-chip"><?= h((string) ($cut['duration_label'] ?? '-')) ?></span>
                    <?php if (!empty($cut['scorecard']['overall'])): ?>
                      <span class="admin-meta-chip admin-meta-chip-soft">score <?= (int) $cut['scorecard']['overall'] ?></span>
                    <?php endif; ?>
                    <?php if (!empty($cut['opening_score'])): ?>
                      <span class="admin-meta-chip admin-meta-chip-soft">gancho <?= (int) $cut['opening_score'] ?></span>
                    <?php endif; ?>
                    <?php if (!empty($cut['opening_visual_score'])): ?>
                      <span class="admin-meta-chip admin-meta-chip-soft">visual <?= (int) $cut['opening_visual_score'] ?></span>
                    <?php endif; ?>
                    <?php if (!empty($cut['opening_speaker_score'])): ?>
                      <span class="admin-meta-chip admin-meta-chip-soft">pessoa <?= (int) $cut['opening_speaker_score'] ?></span>
                    <?php endif; ?>
                    <?php if (!empty($cut['opening_focus_zone'])): ?>
                      <span class="admin-meta-chip admin-meta-chip-soft">foco <?= h((string) $cut['opening_focus_zone']) ?></span>
                    <?php endif; ?>
                    <?php if ($personStatus): ?>
                      <span class="admin-status <?= h((string) ($personStatus['class'] ?? 'warn')) ?>"><?= h((string) ($personStatus['label'] ?? 'Revisar')) ?></span>
                    <?php endif; ?>
                    <?php if (!empty($cut['series_label'])): ?>
                      <span class="admin-meta-chip admin-meta-chip-soft"><?= h((string) $cut['series_label']) ?></span>
                    <?php endif; ?>
                  </div>
                  <?php if (!empty($cut['hook'])): ?>
                    <div class="admin-card-subtitle"><?= h((string) $cut['hook']) ?></div>
                  <?php endif; ?>
                  <?php if ($personStatus && !empty($personStatus['message'])): ?>
                    <div class="admin-help" style="margin-top:8px;"><?= h((string) $personStatus['message']) ?></div>
                  <?php endif; ?>
                  <?php if (!empty($cut['first_frame_text'])): ?>
                    <div class="admin-help" style="margin-top:8px;">Abertura sugerida: <strong><?= h((string) $cut['first_frame_text']) ?></strong></div>
                  <?php endif; ?>
                  <?php if ($titleVariants): ?>
                    <div class="admin-help" style="margin-top:8px;">Titulos:
                      <?= h(implode(' | ', array_map(static fn($value) => (string) $value, $titleVariants))) ?>
                    </div>
                  <?php endif; ?>
                  <?php if ($packagingNotes): ?>
                    <div class="admin-help" style="margin-top:8px;">
                      <?= h(implode(' • ', array_map(static fn($value) => (string) $value, $packagingNotes))) ?>
                    </div>
                  <?php endif; ?>
                  <?php if ($cutMode === 'short'): ?>
                    <form method="post" style="margin-top:10px; display:grid; gap:8px;">
                      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
                      <input type="hidden" name="acao" value="rerender_cut">
                      <input type="hidden" name="job_id" value="<?= h($jobId) ?>">
                      <input type="hidden" name="cut_id" value="<?= (int) ($cut['cut_id'] ?? 0) ?>">
                      <label class="admin-field admin-field-compact">
                        <span>Enquadramento</span>
                        <select name="crop_override">
                          <option value="auto" <?= $cropOverride === 'auto' ? 'selected' : '' ?>>Auto</option>
                          <option value="esquerda" <?= $cropOverride === 'esquerda' ? 'selected' : '' ?>>Esquerda</option>
                          <option value="direita" <?= $cropOverride === 'direita' ? 'selected' : '' ?>>Direita</option>
                        </select>
                      </label>
                      <button class="btn-link" type="submit">Regerar enquadramento</button>
                    </form>
                  <?php endif; ?>
                  <div class="admin-card-actions">
                    <a class="btn-link primary" href="<?= h($streamUrl) ?>" target="_blank" rel="noopener">Abrir video</a>
                    <a class="badge" href="<?= h($downloadUrl) ?>">Baixar MP4</a>
                    <?php if ($subtitleUrl !== ''): ?>
                      <a class="badge" href="<?= h($subtitleUrl) ?>">Legenda ASS</a>
                    <?php endif; ?>
                    <form method="post" class="admin-publish-form" data-youtube-publish-form>
                      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
                      <input type="hidden" name="acao" value="publish_cut">
                      <input type="hidden" name="job_id" value="<?= h($jobId) ?>">
                      <input type="hidden" name="cut_id" value="<?= (int) ($cut['cut_id'] ?? 0) ?>">
                      <input type="hidden" name="mode" value="<?= h($cutMode) ?>">
                      <input type="hidden" name="channel_profile_id" value="<?= (int) ($cut['channel_profile_id'] ?? $job['target_channel_profile_id'] ?? 0) ?>">
                      <label class="admin-field admin-field-compact">
                        <span>Status no YouTube</span>
                        <select name="privacy_status" data-youtube-publish-privacy>
                          <option value="public">Publicado</option>
                          <option value="private" selected>Privado</option>
                          <option value="scheduled">Programado</option>
                        </select>
                      </label>
                      <div class="admin-publish-schedule" data-youtube-publish-schedule hidden>
                        <label class="admin-field admin-field-compact">
                          <span>Data</span>
                          <input type="date" name="publish_date" value="<?= h((string) $publishScheduleDefaults['date']) ?>">
                        </label>
                        <label class="admin-field admin-field-compact">
                          <span>Hora</span>
                          <input type="time" name="publish_time" value="<?= h((string) $publishScheduleDefaults['time']) ?>" step="60">
                        </label>
                      </div>
                      <?php if ($publishBlocked && !empty($personStatus['message'])): ?>
                        <div class="admin-help"><?= h((string) $personStatus['message']) ?></div>
                      <?php endif; ?>
                      <button class="btn-link" type="submit" <?= $publishBlocked ? 'disabled aria-disabled="true"' : '' ?>>
                        <?= $publishBlocked ? 'Bloqueado sem pessoa' : 'Enviar ao YouTube' ?>
                      </button>
                    </form>
                  </div>
                </article>
              <?php endforeach; ?>
            </div>
          </article>
        <?php endforeach; ?>
      </div>
    <?php endif; ?>
  </section>
  <?php endif; ?>
</main>

<script>
  document.querySelector('[data-admin-menu-toggle]')?.addEventListener('click', function () {
    const expanded = this.getAttribute('aria-expanded') === 'true';
    this.setAttribute('aria-expanded', expanded ? 'false' : 'true');
    document.body.classList.toggle('admin-menu-open', !expanded);
  });

  (function () {
    const progressCard = document.getElementById('youtube-cuts-progress-card');
    if (!progressCard) {
      return;
    }

    const statusUrl = progressCard.getAttribute('data-status-url');
    const fill = document.getElementById('youtube-cuts-progress-fill');
    const label = document.getElementById('youtube-cuts-progress-label');
    const elapsed = document.getElementById('youtube-cuts-progress-time');
    let finished = false;

    function formatElapsed(seconds) {
      const total = Math.max(0, Number(seconds) || 0);
      if (total < 60) {
        return `${total}s`;
      }
      const minutes = Math.floor(total / 60);
      const rest = total % 60;
      return `${minutes}m ${rest}s`;
    }

    async function pollStatus() {
      if (finished || !statusUrl) {
        return;
      }
      try {
        const response = await fetch(statusUrl, { credentials: 'same-origin', cache: 'no-store' });
        const payload = await response.json();
        if (!payload || !payload.ok) {
          return;
        }
        if (fill) {
          fill.style.width = `${Math.max(8, Math.min(100, Number(payload.progress_percent) || 10))}%`;
        }
        if (label && payload.progress_label) {
          label.textContent = payload.progress_label;
        }
        if (elapsed) {
          elapsed.textContent = formatElapsed(payload.elapsed_seconds);
        }
        if (payload.status === 'success' || payload.status === 'error') {
          finished = true;
          window.location.href = payload.redirect_url || '/admin/youtube_cortes.php';
          return;
        }
      } catch (error) {
      }
      window.setTimeout(pollStatus, 2500);
    }

    window.setTimeout(pollStatus, 1200);
  })();

  (function () {
    const forms = document.querySelectorAll('[data-youtube-publish-form]');
    if (!forms.length) {
      return;
    }

    forms.forEach((form) => {
      const privacySelect = form.querySelector('[data-youtube-publish-privacy]');
      const scheduleBox = form.querySelector('[data-youtube-publish-schedule]');
      if (!privacySelect || !scheduleBox) {
        return;
      }

      const syncVisibility = () => {
        scheduleBox.hidden = privacySelect.value !== 'scheduled';
      };

      privacySelect.addEventListener('change', syncVisibility);
      syncVisibility();
    });
  })();

  (function () {
    const radarForm = document.querySelector('.admin-inline-form-radar');
    const autoJobButton = radarForm?.querySelector('[data-confirm-auto-job]');
    const channelSelect = radarForm?.querySelector('#radar_channel_profile_id');
    if (!radarForm || !channelSelect) {
      return;
    }

    channelSelect.addEventListener('change', function () {
      const targetUrl = channelSelect.dataset.profileSwitchUrl || '/admin/youtube_cortes.php';
      const nextUrl = new URL(targetUrl, window.location.origin);
      nextUrl.searchParams.set('tab', radarForm.dataset.currentTab || 'gerar');
      nextUrl.searchParams.set('channel_profile_id', channelSelect.value || '0');
      window.location.href = nextUrl.toString();
    });

    if (!autoJobButton) {
      return;
    }

    autoJobButton.addEventListener('click', function (event) {
      const option = channelSelect.options[channelSelect.selectedIndex];
      const channelName = option && option.text ? option.text.trim() : 'este canal';
      const confirmed = window.confirm(`Voce quer rodar o auto job agora para ${channelName}?`);
      if (!confirmed) {
        event.preventDefault();
      }
    });
  })();
</script>
</body>
</html>
