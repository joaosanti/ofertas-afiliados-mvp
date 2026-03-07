<?php
require_once __DIR__ . '/db.php';
require_once __DIR__ . '/funcoes.php';

function site_store_slug($store) {
  $value = strtolower(trim((string) $store));
  $value = preg_replace('/[^a-z0-9]+/', '-', $value);
  return trim((string) $value, '-') ?: 'loja';
}

function site_store_label($store) {
  $value = trim((string) $store);
  if ($value === '') {
    return 'Loja';
  }

  $map = [
    'mercado livre' => 'Mercado Livre',
    'shopee' => 'Shopee',
    'amazon' => 'Amazon',
    'tiktok' => 'TikTok Shop',
  ];

  $lower = strtolower($value);
  return $map[$lower] ?? ucwords($value);
}

function site_category_label($category) {
  $value = trim((string) $category);
  if ($value === '' || strtolower($value) === 'geral') {
    return 'Todas as categorias';
  }
  return ucwords(str_replace(['-', '_'], ' ', $value));
}

function site_money($value) {
  return 'R$ ' . number_format((float) $value, 2, ',', '.');
}

function site_discount_percent($price, $oldPrice) {
  $price = (float) $price;
  $oldPrice = (float) $oldPrice;
  if ($oldPrice <= 0 || $price <= 0 || $oldPrice <= $price) {
    return null;
  }
  return (int) round((($oldPrice - $price) / $oldPrice) * 100);
}

function site_tags_to_list($tags) {
  $items = array_filter(array_map('trim', explode(',', (string) $tags)));
  return array_values(array_unique($items));
}

function site_extract_sold_count($tags) {
  foreach (site_tags_to_list($tags) as $tag) {
    if (str_starts_with($tag, 'sold:')) {
      return (int) substr($tag, 5);
    }
  }
  return 0;
}

function site_offer_href($slug) {
  return '/oferta.php?slug=' . rawurlencode((string) $slug);
}

function site_offer_redirect_href($slug) {
  return site_offer_href($slug) . '&go=1';
}

function site_category_href($category) {
  return '/categoria.php?cat=' . rawurlencode((string) $category);
}

function site_build_filters(PDO $pdo) {
  $categories = $pdo->query("
    SELECT categoria, COUNT(*) AS total
    FROM ofertas
    WHERE ativo=1 AND (expira_em IS NULL OR expira_em > NOW())
    GROUP BY categoria
    ORDER BY total DESC, categoria ASC
    LIMIT 12
  ")->fetchAll();

  $stores = $pdo->query("
    SELECT loja, COUNT(*) AS total
    FROM ofertas
    WHERE ativo=1 AND (expira_em IS NULL OR expira_em > NOW())
    GROUP BY loja
    ORDER BY total DESC, loja ASC
    LIMIT 8
  ")->fetchAll();

  return [
    'categories' => $categories,
    'stores' => $stores,
  ];
}

function site_fetch_home_data(PDO $pdo) {
  $heroOffers = $pdo->query("
    SELECT *
    FROM ofertas
    WHERE ativo=1 AND (expira_em IS NULL OR expira_em > NOW())
    ORDER BY destaque DESC, atualizado_em DESC, criado_em DESC
    LIMIT 8
  ")->fetchAll();

  $featured = $pdo->query("
    SELECT *
    FROM ofertas
    WHERE ativo=1 AND (expira_em IS NULL OR expira_em > NOW()) AND destaque=1
    ORDER BY atualizado_em DESC, criado_em DESC
    LIMIT 6
  ")->fetchAll();

  $latest = $pdo->query("
    SELECT *
    FROM ofertas
    WHERE ativo=1 AND (expira_em IS NULL OR expira_em > NOW())
    ORDER BY atualizado_em DESC, criado_em DESC
    LIMIT 12
  ")->fetchAll();

  $topClicked = $pdo->query("
    SELECT o.*, COUNT(c.id) AS clicks
    FROM ofertas o
    LEFT JOIN cliques c ON c.oferta_id = o.id
    WHERE o.ativo=1 AND (o.expira_em IS NULL OR o.expira_em > NOW())
    GROUP BY o.id
    ORDER BY clicks DESC, o.destaque DESC, o.atualizado_em DESC
    LIMIT 8
  ")->fetchAll();

  $couponOffers = $pdo->query("
    SELECT *
    FROM ofertas
    WHERE ativo=1
      AND (expira_em IS NULL OR expira_em > NOW())
      AND cupom IS NOT NULL
      AND cupom <> ''
    ORDER BY destaque DESC, atualizado_em DESC, criado_em DESC
    LIMIT 8
  ")->fetchAll();

  $meliTrending = $pdo->query("
    SELECT *
    FROM ofertas
    WHERE ativo=1
      AND (expira_em IS NULL OR expira_em > NOW())
      AND loja = 'Mercado Livre'
    ORDER BY destaque DESC, atualizado_em DESC, criado_em DESC
    LIMIT 12
  ")->fetchAll();

  $categoryRows = $pdo->query("
    SELECT categoria, COUNT(*) AS total
    FROM ofertas
    WHERE ativo=1 AND (expira_em IS NULL OR expira_em > NOW())
    GROUP BY categoria
    ORDER BY total DESC, categoria ASC
    LIMIT 6
  ")->fetchAll();

  $sectionsByCategory = [];
  $categoryStmt = $pdo->prepare("
    SELECT *
    FROM ofertas
    WHERE ativo=1
      AND (expira_em IS NULL OR expira_em > NOW())
      AND categoria = ?
    ORDER BY destaque DESC, atualizado_em DESC, criado_em DESC
    LIMIT 4
  ");

  foreach ($categoryRows as $row) {
    $categoryStmt->execute([$row['categoria']]);
    $sectionsByCategory[] = [
      'name' => $row['categoria'],
      'total' => (int) $row['total'],
      'offers' => $categoryStmt->fetchAll(),
    ];
  }

  $storeRows = $pdo->query("
    SELECT loja, COUNT(*) AS total
    FROM ofertas
    WHERE ativo=1 AND (expira_em IS NULL OR expira_em > NOW())
    GROUP BY loja
    ORDER BY total DESC, loja ASC
    LIMIT 4
  ")->fetchAll();

  return [
    'hero_offers' => $heroOffers,
    'featured' => $featured,
    'latest' => $latest,
    'top_clicked' => $topClicked,
    'coupon_offers' => $couponOffers,
    'meli_trending' => $meliTrending,
    'sections_by_category' => $sectionsByCategory,
    'store_rows' => $storeRows,
    'filters' => site_build_filters($pdo),
  ];
}

function site_fetch_category_data(PDO $pdo, $category) {
  $normalizedCategory = trim((string) $category);
  $stmt = $pdo->prepare("
    SELECT *
    FROM ofertas
    WHERE ativo=1
      AND (expira_em IS NULL OR expira_em > NOW())
      AND (categoria = ? OR ? = 'geral')
    ORDER BY destaque DESC, atualizado_em DESC, criado_em DESC
    LIMIT 120
  ");
  $stmt->execute([$normalizedCategory, $normalizedCategory]);
  $offers = $stmt->fetchAll();

  $topByStoreStmt = $pdo->prepare("
    SELECT loja, COUNT(*) AS total
    FROM ofertas
    WHERE ativo=1
      AND (expira_em IS NULL OR expira_em > NOW())
      AND (categoria = ? OR ? = 'geral')
    GROUP BY loja
    ORDER BY total DESC, loja ASC
    LIMIT 8
  ");
  $topByStoreStmt->execute([$normalizedCategory, $normalizedCategory]);

  return [
    'offers' => $offers,
    'stores' => $topByStoreStmt->fetchAll(),
    'filters' => site_build_filters($pdo),
  ];
}

function site_fetch_related_offers(PDO $pdo, $offer, $limit = 4) {
  $stmt = $pdo->prepare("
    SELECT *
    FROM ofertas
    WHERE ativo=1
      AND slug <> ?
      AND (expira_em IS NULL OR expira_em > NOW())
      AND (categoria = ? OR loja = ?)
    ORDER BY destaque DESC, atualizado_em DESC, criado_em DESC
    LIMIT ?
  ");
  $stmt->bindValue(1, $offer['slug']);
  $stmt->bindValue(2, $offer['categoria']);
  $stmt->bindValue(3, $offer['loja']);
  $stmt->bindValue(4, (int) $limit, PDO::PARAM_INT);
  $stmt->execute();
  return $stmt->fetchAll();
}
