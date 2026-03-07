<?php
$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH);
$fullPath = __DIR__ . '/public_html' . $path;

if ($path !== '/' && is_file($fullPath)) {
  return false;
}

if ($path === '/' || $path === '') {
  require __DIR__ . '/public_html/index.php';
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
