<?php
$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH);
$fullPath = __DIR__ . '/public_html' . $path;

if ($path !== '/' && is_file($fullPath)) {
  $ext = strtolower((string) pathinfo($fullPath, PATHINFO_EXTENSION));
  if ($ext !== 'php') {
    $mimeTypes = [
      'css' => 'text/css; charset=UTF-8',
      'js' => 'application/javascript; charset=UTF-8',
      'json' => 'application/json; charset=UTF-8',
      'png' => 'image/png',
      'jpg' => 'image/jpeg',
      'jpeg' => 'image/jpeg',
      'gif' => 'image/gif',
      'svg' => 'image/svg+xml',
      'webp' => 'image/webp',
      'ico' => 'image/x-icon',
      'txt' => 'text/plain; charset=UTF-8',
      'xml' => 'application/xml; charset=UTF-8',
      'pdf' => 'application/pdf',
    ];

    if (isset($mimeTypes[$ext])) {
      header('Content-Type: ' . $mimeTypes[$ext]);
    } elseif (function_exists('mime_content_type')) {
      $mime = mime_content_type($fullPath);
      if ($mime) {
        header('Content-Type: ' . $mime);
      }
    }

    header('Content-Length: ' . (string) filesize($fullPath));
    readfile($fullPath);
    return true;
  }

  require $fullPath;
  return true;
}

if ($path === '/' || $path === '') {
  require __DIR__ . '/public_html/index.php';
  return true;
}

if (in_array($path, ['/admin', '/admin/'], true)) {
  require __DIR__ . '/public_html/admin/index.php';
  return true;
}

if (preg_match('#^/categoria/([a-z0-9\-_%]+?)/?$#i', $path, $matches)) {
  $_GET['cat'] = rawurldecode($matches[1]);
  require __DIR__ . '/public_html/categoria.php';
  return true;
}

if (preg_match('#^/oferta/([a-z0-9\-_%]+?)/?$#i', $path, $matches)) {
  $_GET['slug'] = rawurldecode($matches[1]);
  require __DIR__ . '/public_html/oferta.php';
  return true;
}

if (in_array($path, ['/instagram', '/instagram/'], true)) {
  require __DIR__ . '/public_html/instagram.php';
  return true;
}

if (in_array($path, ['/ofertas-do-dia', '/ofertas-do-dia/'], true)) {
  require __DIR__ . '/public_html/ofertas-do-dia.php';
  return true;
}

if (in_array($path, ['/sobre', '/sobre/'], true)) {
  require __DIR__ . '/public_html/sobre.php';
  return true;
}

if (in_array($path, ['/contato', '/contato/'], true)) {
  require __DIR__ . '/public_html/contato.php';
  return true;
}

if (in_array($path, ['/privacidade', '/privacidade/'], true)) {
  require __DIR__ . '/public_html/privacidade.php';
  return true;
}

if (in_array($path, ['/termos', '/termos/'], true)) {
  require __DIR__ . '/public_html/termos.php';
  return true;
}

if ($path === '/sitemap.xml') {
  require __DIR__ . '/public_html/sitemap.php';
  return true;
}

$fallback = __DIR__ . '/public_html' . ($path === '/' ? '/index.php' : $path);
if (is_file($fallback)) {
  require $fallback;
  return true;
}

http_response_code(404);
echo 'Pagina nao encontrada';
