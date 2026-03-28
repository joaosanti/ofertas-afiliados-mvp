<?php
require_once __DIR__ . '/_init.php';
admin_require_login();

admin_youtube_cuts_cleanup_expired();

$jobId = trim((string) ($_GET['job'] ?? ''));
$filename = trim((string) ($_GET['file'] ?? ''));
$download = (int) ($_GET['download'] ?? 0) === 1;
$path = admin_youtube_cuts_asset_path($jobId, $filename);

if (!$path) {
  http_response_code(404);
  header('Content-Type: text/plain; charset=utf-8');
  echo 'Arquivo do corte nao encontrado.';
  exit;
}

$extension = strtolower(pathinfo($path, PATHINFO_EXTENSION));
$mime = '';
if (function_exists('mime_content_type')) {
  $mime = (string) @mime_content_type($path);
}
if ($mime === '' || $mime === 'application/octet-stream') {
  $map = [
    'mp4' => 'video/mp4',
    'png' => 'image/png',
    'jpg' => 'image/jpeg',
    'jpeg' => 'image/jpeg',
    'ass' => 'text/plain; charset=utf-8',
    'json' => 'application/json; charset=utf-8',
    'vtt' => 'text/vtt; charset=utf-8',
    'mp3' => 'audio/mpeg',
  ];
  $mime = $map[$extension] ?? 'application/octet-stream';
}

$disposition = $download ? 'attachment' : 'inline';
header('Content-Type: ' . $mime);
header('Content-Length: ' . (string) filesize($path));
header('Content-Disposition: ' . $disposition . '; filename="' . basename($path) . '"');
header('X-Content-Type-Options: nosniff');
header('Cache-Control: private, max-age=300');

while (ob_get_level() > 0) {
  ob_end_clean();
}

readfile($path);
exit;
