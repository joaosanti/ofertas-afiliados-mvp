<?php
require_once __DIR__ . '/_init.php';

header('Content-Type: text/html; charset=utf-8');

function youtube_oauth_callback_absolute_url($path) {
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

function youtube_oauth_callback_render_page($title, $message, $status = 'info', $extraHtml = '') {
  $titleText = h((string) $title);
  $messageText = nl2br(h((string) $message));
  $panelClass = $status === 'error' ? 'admin-alert error' : 'admin-alert success';
  ?>
  <!doctype html>
  <html lang="pt-br">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title><?= $titleText ?></title>
    <link rel="icon" type="image/png" href="/assets/img/logo-zp.png">
    <link rel="stylesheet" href="/assets/css/style.css">
    <link rel="stylesheet" href="/assets/css/admin.css?v=<?= urlencode((string) @filemtime(__DIR__ . '/../assets/css/admin.css')) ?>">
  </head>
  <body class="admin-page">
    <main class="container admin-shell" style="padding-top:40px; padding-bottom:40px;">
      <section class="admin-panel">
        <div class="<?= h($panelClass) ?>" style="margin-bottom:16px;"><?= $titleText ?></div>
        <p style="font-size:18px; line-height:1.6;"><?= $messageText ?></p>
        <?php if ($extraHtml !== ''): ?>
          <div style="margin-top:16px;"><?= $extraHtml ?></div>
        <?php endif; ?>
        <div class="admin-card-actions" style="margin-top:24px;">
          <a class="btn-link primary" href="/admin/youtube_cortes.php">Voltar para YouTube cortes</a>
        </div>
      </section>
    </main>
  </body>
  </html>
  <?php
}

function youtube_oauth_callback_post_form($url, array $fields) {
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

function youtube_oauth_callback_get_json($url, array $headers = []) {
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
      throw new RuntimeException('Falha HTTP ao consultar dados do canal: ' . $error);
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
    throw new RuntimeException('Falha HTTP ao consultar dados do canal.');
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

$error = trim((string) ($_GET['error'] ?? ''));
$errorDescription = trim((string) ($_GET['error_description'] ?? ''));
$state = trim((string) ($_GET['state'] ?? ''));
$code = trim((string) ($_GET['code'] ?? ''));

if ($error !== '') {
  youtube_oauth_callback_render_page(
    'OAuth YouTube falhou',
    $error . ($errorDescription !== '' ? "\n" . $errorDescription : ''),
    'error'
  );
  exit;
}

if ($code === '') {
  youtube_oauth_callback_render_page('OAuth YouTube incompleto', 'O Google nao enviou o code de autorizacao.', 'error');
  exit;
}

if ($state === '') {
  youtube_oauth_callback_render_page('OAuth YouTube invalido', 'O callback nao recebeu o state esperado.', 'error');
  exit;
}

$pdo = db();
$redirectUri = youtube_oauth_callback_absolute_url('/admin/youtube_oauth_callback.php');

try {
  $stmt = $pdo->prepare("
    SELECT id, name, client_id, client_secret, redirect_uri, refresh_token
    FROM youtube_channel_profiles
    WHERE oauth_state = ?
    LIMIT 1
  ");
  $stmt->execute([$state]);
  $profile = $stmt->fetch();

  if (!$profile) {
    youtube_oauth_callback_render_page('OAuth YouTube recusado', 'O state informado nao corresponde a nenhum perfil ativo.', 'error');
    exit;
  }

  $clientId = trim((string) ($profile['client_id'] ?? ''));
  $clientSecret = trim((string) ($profile['client_secret'] ?? ''));
  if ($clientId === '' || $clientSecret === '') {
    youtube_oauth_callback_render_page(
      'Configuracao incompleta',
      'Esse perfil nao tem Client ID e Client Secret suficientes para concluir o OAuth do YouTube.',
      'error'
    );
    exit;
  }

  if ($redirectUri === '') {
    youtube_oauth_callback_render_page('Configuracao incompleta', 'Nao foi possivel montar a URL publica do callback.', 'error');
    exit;
  }

  $tokenResponse = youtube_oauth_callback_post_form('https://oauth2.googleapis.com/token', [
    'code' => $code,
    'client_id' => $clientId,
    'client_secret' => $clientSecret,
    'redirect_uri' => $redirectUri,
    'grant_type' => 'authorization_code',
  ]);
  $tokenPayload = json_decode((string) $tokenResponse['body'], true);
  if ((int) ($tokenResponse['status'] ?? 0) >= 400 || !is_array($tokenPayload)) {
    $detail = is_array($tokenPayload) ? json_encode($tokenPayload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) : (string) $tokenResponse['body'];
    youtube_oauth_callback_render_page('Falha ao trocar o code', $detail !== '' ? $detail : 'Resposta invalida do Google.', 'error');
    exit;
  }

  $accessToken = trim((string) ($tokenPayload['access_token'] ?? ''));
  $refreshToken = trim((string) ($tokenPayload['refresh_token'] ?? ''));
  $expiresIn = (int) ($tokenPayload['expires_in'] ?? 0);
  $tokenExpiresAt = $expiresIn > 0 ? (time() + $expiresIn) : null;
  $storedRefreshToken = $refreshToken !== '' ? $refreshToken : trim((string) ($profile['refresh_token'] ?? ''));

  if ($accessToken === '') {
    youtube_oauth_callback_render_page('Falha OAuth', 'O Google nao retornou access_token para esse perfil.', 'error');
    exit;
  }

  $channelResponse = youtube_oauth_callback_get_json(
    'https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true',
    ['Authorization: Bearer ' . $accessToken]
  );
  $channelPayload = json_decode((string) $channelResponse['body'], true);
  $channelItem = is_array($channelPayload) && !empty($channelPayload['items'][0]) && is_array($channelPayload['items'][0])
    ? $channelPayload['items'][0]
    : [];
  $snippet = is_array($channelItem['snippet'] ?? null) ? $channelItem['snippet'] : [];
  $thumbnails = is_array($snippet['thumbnails'] ?? null) ? $snippet['thumbnails'] : [];
  $thumbnailUrl = '';
  foreach (['high', 'medium', 'default'] as $thumbKey) {
    if (!empty($thumbnails[$thumbKey]['url'])) {
      $thumbnailUrl = (string) $thumbnails[$thumbKey]['url'];
      break;
    }
  }

  $update = $pdo->prepare("
    UPDATE youtube_channel_profiles
    SET access_token = ?,
        refresh_token = ?,
        token_expires_at = ?,
        oauth_state = '',
        redirect_uri = ?,
        channel_id = ?,
        channel_title = ?,
        channel_custom_url = ?,
        channel_thumbnail_url = ?
    WHERE id = ?
    LIMIT 1
  ");
  $update->execute([
    $accessToken !== '' ? $accessToken : null,
    $storedRefreshToken !== '' ? $storedRefreshToken : null,
    $tokenExpiresAt,
    $redirectUri,
    trim((string) ($channelItem['id'] ?? '')) !== '' ? trim((string) $channelItem['id']) : null,
    trim((string) ($snippet['title'] ?? '')) !== '' ? trim((string) $snippet['title']) : null,
    trim((string) ($snippet['customUrl'] ?? '')) !== '' ? trim((string) $snippet['customUrl']) : null,
    $thumbnailUrl !== '' ? $thumbnailUrl : null,
    (int) ($profile['id'] ?? 0),
  ]);

  $profileName = trim((string) ($profile['name'] ?? 'Canal'));
  $channelTitle = trim((string) ($snippet['title'] ?? 'canal autenticado'));
  youtube_oauth_callback_render_page(
    'YouTube conectado',
    "Conta autorizada com sucesso para o perfil: {$profileName}\nCanal autenticado: {$channelTitle}",
    'success'
  );
  exit;
} catch (Throwable $e) {
  youtube_oauth_callback_render_page('Falha no callback do YouTube', $e->getMessage(), 'error');
  exit;
}
