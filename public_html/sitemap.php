<?php
require_once __DIR__ . '/inc/site.php';

header('Content-Type: application/xml; charset=UTF-8');

$pdo = db();
$baseUrl = rtrim(SITE_URL, '/');

function xml_escape($value) {
  return htmlspecialchars((string) $value, ENT_XML1 | ENT_QUOTES, 'UTF-8');
}

$staticUrls = [
  ['loc' => $baseUrl . '/', 'priority' => '1.0'],
  ['loc' => $baseUrl . '/sobre', 'priority' => '0.7'],
  ['loc' => $baseUrl . '/contato', 'priority' => '0.6'],
  ['loc' => $baseUrl . '/privacidade', 'priority' => '0.5'],
  ['loc' => $baseUrl . '/termos', 'priority' => '0.5'],
  ['loc' => $baseUrl . '/categoria/geral', 'priority' => '0.8'],
];

$categoryRows = $pdo->query("
  SELECT categoria, MAX(atualizado_em) AS updated_at
  FROM ofertas
  WHERE ativo=1 AND (expira_em IS NULL OR expira_em > NOW())
  GROUP BY categoria
  ORDER BY categoria ASC
")->fetchAll();

$offerRows = $pdo->query("
  SELECT slug, atualizado_em
  FROM ofertas
  WHERE ativo=1 AND (expira_em IS NULL OR expira_em > NOW())
  ORDER BY atualizado_em DESC, criado_em DESC
  LIMIT 500
")->fetchAll();

echo '<?xml version="1.0" encoding="UTF-8"?>';
?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<?php foreach ($staticUrls as $url): ?>
  <url>
    <loc><?= xml_escape($url['loc']) ?></loc>
    <priority><?= xml_escape($url['priority']) ?></priority>
  </url>
<?php endforeach; ?>
<?php foreach ($categoryRows as $row): ?>
  <url>
    <loc><?= xml_escape($baseUrl . '/categoria/' . rawurlencode((string) $row['categoria'])) ?></loc>
    <?php if (!empty($row['updated_at'])): ?>
    <lastmod><?= xml_escape(date('c', strtotime((string) $row['updated_at']))) ?></lastmod>
    <?php endif; ?>
    <priority>0.7</priority>
  </url>
<?php endforeach; ?>
<?php foreach ($offerRows as $row): ?>
  <url>
    <loc><?= xml_escape($baseUrl . '/oferta/' . rawurlencode((string) $row['slug'])) ?></loc>
    <?php if (!empty($row['atualizado_em'])): ?>
    <lastmod><?= xml_escape(date('c', strtotime((string) $row['atualizado_em']))) ?></lastmod>
    <?php endif; ?>
    <priority>0.6</priority>
  </url>
<?php endforeach; ?>
</urlset>
