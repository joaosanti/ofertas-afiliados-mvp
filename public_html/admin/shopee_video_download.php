<?php
require_once __DIR__ . '/_init.php';
admin_require_login();

$pdo = db();
$draftId = max(0, (int) ($_GET['draft_id'] ?? 0));
$offerId = max(0, (int) ($_GET['offer_id'] ?? 0));
$downloadType = trim((string) ($_GET['type'] ?? 'video'));

function shopee_video_download_fail($message, $statusCode = 400) {
  http_response_code((int) $statusCode);
  header('Content-Type: text/plain; charset=utf-8');
  echo (string) $message;
  exit;
}

function shopee_video_download_file_name($title, $url) {
  $slug = slugify((string) $title);
  $extension = strtolower((string) pathinfo((string) parse_url((string) $url, PHP_URL_PATH), PATHINFO_EXTENSION));
  if ($extension === '' || !preg_match('/^[a-z0-9]{2,5}$/i', $extension)) {
    $extension = 'mp4';
  }
  return ($slug !== '' ? $slug : 'shopee-video') . '.' . $extension;
}

function shopee_video_caption_file_name($title) {
  $slug = slugify((string) $title);
  return ($slug !== '' ? $slug : 'shopee-legenda') . '.txt';
}

function shopee_video_short_caption_file_name($title) {
  $slug = slugify((string) $title);
  return ($slug !== '' ? $slug : 'shopee-descricao-curta') . '-descricao-curta.txt';
}

function shopee_video_package_file_name($title) {
  $slug = slugify((string) $title);
  return ($slug !== '' ? $slug : 'shopee-pacote') . '.zip';
}

function shopee_video_try_local_path($url) {
  $path = shopee_video_public_relative_path($url);
  if ($path === null) {
    return null;
  }

  $localPath = dirname(__DIR__) . str_replace('/', DIRECTORY_SEPARATOR, $path);
  if (is_file($localPath)) {
    return $localPath;
  }
  return null;
}

function shopee_video_public_relative_path($url) {
  $parsed = parse_url((string) $url);
  $path = (string) ($parsed['path'] ?? '');
  if ($path === '' || (!str_starts_with($path, '/uploads/') && !str_starts_with($path, '/stories/'))) {
    return null;
  }
  return $path;
}

function shopee_video_public_relative_path_from_local($path) {
  $realPath = realpath((string) $path);
  $publicRoot = realpath(dirname(__DIR__));
  if ($realPath === false || $publicRoot === false) {
    return null;
  }

  $normalizedRealPath = str_replace('\\', '/', $realPath);
  $normalizedRoot = rtrim(str_replace('\\', '/', $publicRoot), '/');
  foreach (['/uploads/', '/stories/'] as $prefix) {
    $fullPrefix = $normalizedRoot . $prefix;
    if (str_starts_with($normalizedRealPath, $fullPrefix)) {
      return substr($normalizedRealPath, strlen($normalizedRoot));
    }
  }
  return null;
}

function shopee_video_content_disposition_header($downloadName, $mode = 'attachment') {
  $safeMode = $mode === 'inline' ? 'inline' : 'attachment';
  $safeName = preg_replace('/[^A-Za-z0-9._-]+/', '-', (string) $downloadName);
  $safeName = trim((string) $safeName, '.-');
  if ($safeName === '') {
    $safeName = 'shopee-video.mp4';
  }
  return $safeMode . '; filename="' . $safeName . '"; filename*=UTF-8\'\'' . rawurlencode((string) $downloadName);
}

function shopee_video_redirect_to_url($url) {
  header('Cache-Control: private, max-age=0, must-revalidate');
  header('Location: ' . (string) $url, true, 302);
  exit;
}

function shopee_video_detect_content_type($path, $fallback = 'application/octet-stream') {
  $extension = strtolower((string) pathinfo((string) $path, PATHINFO_EXTENSION));
  $contentTypes = [
    'mp4' => 'video/mp4',
    'mov' => 'video/quicktime',
    'm4v' => 'video/mp4',
    'webm' => 'video/webm',
    'jpg' => 'image/jpeg',
    'jpeg' => 'image/jpeg',
    'png' => 'image/png',
    'json' => 'application/json',
    'txt' => 'text/plain; charset=utf-8',
    'srt' => 'application/x-subrip; charset=utf-8',
  ];
  return $contentTypes[$extension] ?? (string) $fallback;
}

function shopee_video_stream_local_file($path, $downloadName, $forcedContentType = null, $disposition = 'attachment') {
  if (!is_file($path)) {
    shopee_video_download_fail('Arquivo local nao encontrado para download.', 404);
  }
  $contentType = $forcedContentType ?: shopee_video_detect_content_type($path);
  header('Content-Type: ' . $contentType);
  header('Content-Length: ' . (string) filesize($path));
  header('Accept-Ranges: bytes');
  header('Content-Disposition: ' . shopee_video_content_disposition_header($downloadName, $disposition));
  header('Cache-Control: private, max-age=0, must-revalidate');
  readfile($path);
  exit;
}

function shopee_video_fetch_remote_file($url) {
  if (!preg_match('~^https?://~i', (string) $url)) {
    shopee_video_download_fail('URL de video invalida.', 400);
  }

  $ch = curl_init((string) $url);
  if ($ch === false) {
    shopee_video_download_fail('Nao foi possivel iniciar o download do arquivo.', 500);
  }

  curl_setopt_array($ch, [
    CURLOPT_FOLLOWLOCATION => true,
    CURLOPT_FAILONERROR => false,
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_HEADER => false,
    CURLOPT_CONNECTTIMEOUT => 20,
    CURLOPT_TIMEOUT => 0,
    CURLOPT_USERAGENT => 'ZeroPreco-ShopeeVideoDownloader/2.0',
    CURLOPT_HEADERFUNCTION => static function ($curl, $headerLine) {
      $line = trim((string) $headerLine);
      $length = strlen($headerLine);
      if ($line === '' || !str_contains($line, ':')) {
        return $length;
      }
      [$name, $value] = explode(':', $line, 2);
      $normalized = strtolower(trim((string) $name));
      $value = trim((string) $value);
      if ($normalized === 'content-type' && $value !== '') {
        $GLOBALS['shopee_video_remote_content_type'] = $value;
      }
      if ($normalized === 'content-length' && ctype_digit($value)) {
        $GLOBALS['shopee_video_remote_content_length'] = (int) $value;
      }
      return $length;
    },
  ]);

  $body = curl_exec($ch);
  $httpCode = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
  $error = curl_error($ch);
  $contentType = (string) ($GLOBALS['shopee_video_remote_content_type'] ?? 'application/octet-stream');
  $contentLength = (int) ($GLOBALS['shopee_video_remote_content_length'] ?? 0);
  curl_close($ch);
  unset($GLOBALS['shopee_video_remote_content_type'], $GLOBALS['shopee_video_remote_content_length']);

  if ($body === false || $httpCode >= 400) {
    shopee_video_download_fail($error !== '' ? $error : 'Falha ao baixar o arquivo remoto.', $httpCode >= 400 ? $httpCode : 502);
  }

  return [
    'content' => (string) $body,
    'content_type' => $contentType !== '' ? $contentType : 'application/octet-stream',
    'content_length' => $contentLength > 0 ? $contentLength : strlen((string) $body),
  ];
}

function shopee_video_stream_remote_file($url, $downloadName, $disposition = 'attachment') {
  $payload = shopee_video_fetch_remote_file($url);
  header('Content-Type: ' . (string) $payload['content_type']);
  header('Content-Length: ' . (string) $payload['content_length']);
  header('Accept-Ranges: bytes');
  header('Content-Disposition: ' . shopee_video_content_disposition_header($downloadName, $disposition));
  header('Cache-Control: private, max-age=0, must-revalidate');
  echo (string) $payload['content'];
  exit;
}

function shopee_video_stream_text_file($downloadName, $content) {
  $body = trim((string) $content) . "\n";
  header('Content-Type: text/plain; charset=utf-8');
  header('Content-Length: ' . (string) strlen($body));
  header('Content-Disposition: attachment; filename="' . rawurlencode((string) $downloadName) . '"; filename*=UTF-8\'\'' . rawurlencode((string) $downloadName));
  header('Cache-Control: private, max-age=0, must-revalidate');
  echo $body;
  exit;
}

function shopee_video_package_files($packagePayload) {
  return is_array($packagePayload['files'] ?? null) ? $packagePayload['files'] : [];
}

function shopee_video_package_file_entry($packagePayload, $key) {
  $files = shopee_video_package_files($packagePayload);
  $entry = $files[$key] ?? null;
  return is_array($entry) ? $entry : null;
}

function shopee_video_ready_video_keys() {
  return ['reel_video_final', 'reel_video_tts_subtitled', 'reel_video_tts', 'reel_video', 'source_video'];
}

function shopee_video_ready_video_entry($packagePayload) {
  foreach (shopee_video_ready_video_keys() as $key) {
    $entry = shopee_video_package_file_entry($packagePayload, $key);
    if (is_array($entry)) {
      return [$key, $entry];
    }
  }
  return [null, null];
}

function shopee_video_resolve_payload(PDO $pdo, $draftId, $offerId) {
  if ($draftId > 0) {
    $stmt = $pdo->prepare("
      SELECT d.id, d.title_snapshot, d.video_source_url, d.caption, d.creative_payload_json, d.package_payload_json
      FROM shopee_video_drafts d
      WHERE d.id = ?
      LIMIT 1
    ");
    $stmt->execute([$draftId]);
    $draft = $stmt->fetch();
    if (!$draft) {
      shopee_video_download_fail('Rascunho do Shopee Video nao encontrado.', 404);
    }
    return [
      'title' => (string) ($draft['title_snapshot'] ?? ''),
      'video_url' => trim((string) ($draft['video_source_url'] ?? '')),
      'caption' => (string) ($draft['caption'] ?? ''),
      'short_caption' => (string) ((admin_shopee_video_json_decode($draft['creative_payload_json'] ?? '')['short_caption'] ?? '')),
      'creative_payload' => admin_shopee_video_json_decode($draft['creative_payload_json'] ?? ''),
      'package_payload' => admin_shopee_video_json_decode($draft['package_payload_json'] ?? ''),
    ];
  }

  if ($offerId > 0) {
    $stmt = $pdo->prepare("
      SELECT id, titulo, preco, preco_antigo, preco_pix, frete_texto, parcelas_texto, cupom, categoria, tags
      FROM ofertas
      WHERE id = ?
        AND loja = 'Shopee'
      LIMIT 1
    ");
    $stmt->execute([$offerId]);
    $offer = $stmt->fetch();
    if (!$offer) {
      shopee_video_download_fail('Oferta Shopee nao encontrada.', 404);
    }
    return [
      'title' => (string) ($offer['titulo'] ?? ''),
      'video_url' => admin_shopee_video_offer_video_url($offer),
      'caption' => admin_shopee_video_default_caption($offer),
      'short_caption' => admin_shopee_video_short_caption($offer),
      'creative_payload' => admin_shopee_video_build_creative_payload($offer),
      'package_payload' => null,
    ];
  }

  shopee_video_download_fail('Informe um draft_id ou offer_id para baixar o arquivo.', 400);
}

function shopee_video_stream_package_zip($title, $payload) {
  if (!class_exists('ZipArchive')) {
    shopee_video_download_fail('ZipArchive nao esta disponivel neste servidor.', 500);
  }

  $zipName = shopee_video_package_file_name($title);
  $tmpZip = tempnam(sys_get_temp_dir(), 'svp_');
  if ($tmpZip === false) {
    shopee_video_download_fail('Nao foi possivel preparar o pacote para download.', 500);
  }

  $zip = new ZipArchive();
  if ($zip->open($tmpZip, ZipArchive::OVERWRITE) !== true) {
    @unlink($tmpZip);
    shopee_video_download_fail('Nao foi possivel criar o arquivo ZIP.', 500);
  }

  $packagePayload = $payload['package_payload'] ?? null;
  if (is_array($packagePayload)) {
    foreach (shopee_video_package_files($packagePayload) as $entry) {
      $path = trim((string) ($entry['path'] ?? ''));
      $filename = trim((string) ($entry['filename'] ?? ''));
      if ($path === '' || $filename === '' || !is_file($path)) {
        continue;
      }
      $zip->addFile($path, $filename);
    }
  } else {
    $captionName = shopee_video_caption_file_name($title);
    $zip->addFromString($captionName, trim((string) ($payload['caption'] ?? '')) . "\n");
    $shortCaption = trim((string) ($payload['short_caption'] ?? ''));
    if ($shortCaption !== '') {
      $zip->addFromString(shopee_video_short_caption_file_name($title), $shortCaption . "\n");
    }
    $videoUrl = trim((string) ($payload['video_url'] ?? ''));
    if ($videoUrl !== '') {
      $videoName = shopee_video_download_file_name($title, $videoUrl);
      $localPath = shopee_video_try_local_path($videoUrl);
      if ($localPath !== null) {
        $zip->addFile($localPath, $videoName);
      } else {
        $remotePayload = shopee_video_fetch_remote_file($videoUrl);
        $zip->addFromString($videoName, (string) $remotePayload['content']);
      }
    }
  }

  $zip->close();

  header('Content-Type: application/zip');
  header('Content-Length: ' . (string) filesize($tmpZip));
  header('Content-Disposition: attachment; filename="' . rawurlencode((string) $zipName) . '"; filename*=UTF-8\'\'' . rawurlencode((string) $zipName));
  header('Cache-Control: private, max-age=0, must-revalidate');
  readfile($tmpZip);
  @unlink($tmpZip);
  exit;
}

$payload = shopee_video_resolve_payload($pdo, $draftId, $offerId);
$title = (string) ($payload['title'] ?? '');
$videoUrl = trim((string) ($payload['video_url'] ?? ''));
$caption = (string) ($payload['caption'] ?? '');
$shortCaption = trim((string) ($payload['short_caption'] ?? (($payload['creative_payload']['short_caption'] ?? ''))));
$packagePayload = $payload['package_payload'] ?? null;
$socialAsset = $offerId > 0 ? admin_fetch_recent_social_reel_asset($pdo, $offerId) : null;
$preferInlineVideo = ((string) ($_GET['download'] ?? '')) !== '1';
$forceAttachmentTypes = ['ready_video', 'reel_video', 'reel_video_tts', 'reel_video_tts_subtitled', 'reel_video_final', 'source_video', 'video', 'social_video'];
if (in_array($downloadType, $forceAttachmentTypes, true)) {
  $preferInlineVideo = false;
}

if ($downloadType === 'caption') {
  shopee_video_stream_text_file(shopee_video_caption_file_name($title), $caption);
}

if ($downloadType === 'caption_short') {
  shopee_video_stream_text_file(shopee_video_short_caption_file_name($title), $shortCaption);
}

if ($downloadType === 'package') {
  shopee_video_stream_package_zip($title, $payload);
}

if ($downloadType === 'social_video') {
  if (!is_array($socialAsset)) {
    shopee_video_download_fail('Este item ainda nao possui reel gerado pelo social.', 404);
  }
  $socialPath = trim((string) ($socialAsset['social_reel_local_path'] ?? ''));
  if ($socialPath === '' || !is_file($socialPath)) {
    shopee_video_download_fail('Arquivo do reel social nao encontrado no servidor.', 404);
  }
  $publicPath = $preferInlineVideo ? shopee_video_public_relative_path_from_local($socialPath) : null;
  if ($publicPath !== null) {
    shopee_video_redirect_to_url($publicPath);
  }
  $downloadName = trim((string) ($socialAsset['social_reel_file'] ?? ''));
  if ($downloadName === '') {
    $downloadName = shopee_video_download_file_name($title, '.mp4');
  }
  shopee_video_stream_local_file(
    $socialPath,
    $downloadName,
    shopee_video_detect_content_type($socialPath, 'video/mp4'),
    $preferInlineVideo ? 'inline' : 'attachment'
  );
}

if (in_array($downloadType, ['brief', 'checklist', 'voiceover', 'metadata', 'poster', 'square_card', 'ready_video', 'reel_video', 'tts_audio', 'reel_video_tts', 'subtitle_srt', 'reel_video_tts_subtitled', 'music_bed', 'reel_video_final', 'source_video', 'caption_short'], true)) {
  if (!is_array($packagePayload)) {
    shopee_video_download_fail('Gere o pacote profissional deste draft antes de baixar este arquivo.', 404);
  }
  $resolvedType = $downloadType;
  if ($downloadType === 'ready_video') {
    [$resolvedType, $entry] = shopee_video_ready_video_entry($packagePayload);
  } else {
    $entry = shopee_video_package_file_entry($packagePayload, $downloadType);
  }
  if (!$entry) {
    shopee_video_download_fail('Arquivo solicitado nao existe neste pacote.', 404);
  }
  $path = trim((string) ($entry['path'] ?? ''));
  $filename = trim((string) ($entry['filename'] ?? ''));
  if ($path === '' || !is_file($path)) {
    shopee_video_download_fail('Arquivo do pacote nao encontrado no servidor.', 404);
  }
  $entryContentType = (string) ($entry['content_type'] ?? 'application/octet-stream');
  $isVideoAsset = str_starts_with(strtolower($entryContentType), 'video/');
  $publicPath = $preferInlineVideo && $isVideoAsset ? shopee_video_public_relative_path_from_local($path) : null;
  if ($publicPath !== null) {
    shopee_video_redirect_to_url($publicPath);
  }
  shopee_video_stream_local_file(
    $path,
    $filename !== '' ? $filename : basename($path),
    $entryContentType,
    ($preferInlineVideo && $isVideoAsset) ? 'inline' : 'attachment'
  );
}

if ($videoUrl === '') {
  shopee_video_download_fail('Esta oferta ainda nao possui video cadastrado.', 404);
}

$downloadName = shopee_video_download_file_name($title, $videoUrl);
$localPath = shopee_video_try_local_path($videoUrl);

if ($downloadType === 'video') {
  if (is_array($packagePayload)) {
    [, $readyEntry] = shopee_video_ready_video_entry($packagePayload);
    if (is_array($readyEntry)) {
      $path = trim((string) ($readyEntry['path'] ?? ''));
      $filename = trim((string) ($readyEntry['filename'] ?? ''));
      if ($path !== '' && is_file($path)) {
        $publicPath = $preferInlineVideo ? shopee_video_public_relative_path_from_local($path) : null;
        if ($publicPath !== null) {
          shopee_video_redirect_to_url($publicPath);
        }
        shopee_video_stream_local_file(
          $path,
          $filename !== '' ? $filename : basename($path),
          (string) ($readyEntry['content_type'] ?? 'video/mp4'),
          $preferInlineVideo ? 'inline' : 'attachment'
        );
      }
    }
  }

  $publicPath = $preferInlineVideo ? shopee_video_public_relative_path($videoUrl) : null;
  if ($publicPath !== null) {
    shopee_video_redirect_to_url($publicPath);
  }

  if ($localPath !== null) {
    shopee_video_stream_local_file($localPath, $downloadName, 'video/mp4', $preferInlineVideo ? 'inline' : 'attachment');
  }
}

if ($localPath !== null) {
  shopee_video_stream_local_file($localPath, $downloadName, 'video/mp4', $preferInlineVideo ? 'inline' : 'attachment');
}

if ($preferInlineVideo) {
  shopee_video_redirect_to_url($videoUrl);
}

shopee_video_stream_remote_file($videoUrl, $downloadName, 'attachment');
