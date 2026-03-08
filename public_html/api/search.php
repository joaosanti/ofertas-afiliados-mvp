<?php
require_once __DIR__ . '/../inc/site.php';

header('Content-Type: application/json; charset=utf-8');

$query = $_GET['q'] ?? '';

try {
  $pdo = db();
  $items = site_search_suggestions($pdo, $query, 8);
  echo json_encode([
    'ok' => true,
    'query' => trim((string) $query),
    'count' => count($items),
    'items' => $items,
  ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
} catch (Throwable $e) {
  http_response_code(500);
  echo json_encode([
    'ok' => false,
    'error' => $e->getMessage(),
  ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
}
