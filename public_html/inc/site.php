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

  $meliCategoryMap = [
    'MLB1055' => 'Celulares e Smartphones',
    'MLB1714' => 'Mouses',
    'MLB135384' => 'Smartwatches',
    'MLB7457' => 'Fones e Kits Viva Voz',
    'MLB264715' => 'Escovas Elétricas',
    'MLB120425' => 'Umidificadores',
    'MLB456045' => 'Ar-Condicionado',
    'MLB48666' => 'Panelas Elétricas',
    'MLB120373' => 'Panela de Arroz',
    'MLB196208' => 'Fones de Ouvido',
    'MLB3843' => 'Caixas Bluetooth',
    'MLB268503' => 'Difusores de Aromas Elétricos',
    'MLB11507' => 'Caixas Acústicas',
    'MLB271858' => 'Smartbands',
    'MLB439402' => 'Panelas a Vapor',
    'MLB433422' => 'Escovas Alisadoras para Barba',
    'MLB264184' => 'Cadeiras de Banho',
    'MLB31682' => 'Panelas de Óleo',
    'MLB107501' => 'Caçarolas e Caldeirões',
    'MLB1664' => 'Fones',
  ];

  if (isset($meliCategoryMap[$value])) {
    return $meliCategoryMap[$value];
  }

  if (preg_match('/^MLB\d+$/', $value)) {
    return 'Categoria Mercado Livre';
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

function site_store_catalog_href($store, $category = 'geral') {
  return '/categoria.php?cat=' . rawurlencode((string) $category) . '&store=' . rawurlencode((string) $store);
}

function site_public_category_label($category) {
  $value = trim((string) $category);
  $overrides = [
    'MLB456045' => 'Fritadeiras Eletricas',
    'MLB48666' => 'Panelas Eletricas',
    'MLB11507' => 'Caixas Acusticas',
    'MLB418472' => 'Teclados',
  ];

  if (isset($overrides[$value])) {
    return $overrides[$value];
  }

  return site_category_label($category);
}

function site_offer_rank_score($offer) {
  $clicks = (int) ($offer['clicks'] ?? 0);
  $sold = site_extract_sold_count($offer['tags'] ?? '');
  $price = (float) ($offer['preco'] ?? 0);
  $oldPrice = (float) ($offer['preco_antigo'] ?? 0);
  $discount = site_discount_percent($price, $oldPrice) ?? 0;
  $featured = !empty($offer['destaque']) ? 1 : 0;
  $coupon = !empty($offer['cupom']) ? 1 : 0;

  return ($sold * 8) + ($clicks * 5) + ($discount * 3) + ($featured * 40) + ($coupon * 18);
}

function site_sort_offers_by_rank(array $offers) {
  usort($offers, static function ($a, $b) {
    $scoreA = site_offer_rank_score($a);
    $scoreB = site_offer_rank_score($b);
    if ($scoreA === $scoreB) {
      return strcmp((string) ($b['atualizado_em'] ?? ''), (string) ($a['atualizado_em'] ?? ''));
    }
    return $scoreB <=> $scoreA;
  });
  return $offers;
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

function site_mix_home_offers(array $offers, $limit = 6) {
  $limit = max(1, (int) $limit);
  $grouped = [];
  $storeOrder = [];

  foreach ($offers as $offer) {
    $storeKey = strtolower(trim((string) ($offer['loja'] ?? 'loja')));
    if (!isset($grouped[$storeKey])) {
      $grouped[$storeKey] = [];
      $storeOrder[] = $storeKey;
    }
    $grouped[$storeKey][] = $offer;
  }

  $mixed = [];
  while (count($mixed) < $limit) {
    $progress = false;
    foreach ($storeOrder as $storeKey) {
      if (empty($grouped[$storeKey])) {
        continue;
      }
      $mixed[] = array_shift($grouped[$storeKey]);
      $progress = true;
      if (count($mixed) >= $limit) {
        break;
      }
    }
    if (!$progress) {
      break;
    }
  }

  return $mixed;
}

function site_fetch_selection_candidates(PDO $pdo, $limit = 24) {
  $limit = max(6, min((int) $limit, 48));
  $stmt = $pdo->query("
    SELECT
      o.*,
      COUNT(c.id) AS clicks,
      (
        CASE WHEN o.destaque = 1 THEN 100 ELSE 0 END +
        CASE WHEN o.cupom IS NOT NULL AND o.cupom <> '' THEN 30 ELSE 0 END +
        CASE WHEN o.preco_antigo IS NOT NULL AND o.preco_antigo > o.preco THEN 20 ELSE 0 END +
        LEAST(COUNT(c.id), 20) * 5
      ) AS home_score
    FROM ofertas o
    LEFT JOIN cliques c ON c.oferta_id = o.id
    WHERE o.ativo = 1
      AND (o.expira_em IS NULL OR o.expira_em > NOW())
    GROUP BY o.id
    ORDER BY home_score DESC, o.atualizado_em DESC, o.criado_em DESC
    LIMIT {$limit}
  ");

  return $stmt->fetchAll();
}

function site_fetch_selection_candidates_balanced(PDO $pdo, $perStore = 12, $maxStores = 4) {
  $perStore = max(3, min((int) $perStore, 24));
  $maxStores = max(1, min((int) $maxStores, 6));

  $stores = $pdo->query("
    SELECT loja, COUNT(*) AS total
    FROM ofertas
    WHERE ativo = 1
      AND (expira_em IS NULL OR expira_em > NOW())
    GROUP BY loja
    ORDER BY total DESC, loja ASC
    LIMIT {$maxStores}
  ")->fetchAll();

  $stmt = $pdo->prepare("
    SELECT
      o.*,
      COUNT(c.id) AS clicks,
      (
        CASE WHEN o.destaque = 1 THEN 100 ELSE 0 END +
        CASE WHEN o.cupom IS NOT NULL AND o.cupom <> '' THEN 30 ELSE 0 END +
        CASE WHEN o.preco_antigo IS NOT NULL AND o.preco_antigo > o.preco THEN 20 ELSE 0 END +
        LEAST(COUNT(c.id), 20) * 5
      ) AS home_score
    FROM ofertas o
    LEFT JOIN cliques c ON c.oferta_id = o.id
    WHERE o.ativo = 1
      AND (o.expira_em IS NULL OR o.expira_em > NOW())
      AND o.loja = ?
    GROUP BY o.id
    ORDER BY home_score DESC, o.atualizado_em DESC, o.criado_em DESC
    LIMIT {$perStore}
  ");

  $rows = [];
  foreach ($stores as $store) {
    $stmt->execute([$store['loja']]);
    $rows = array_merge($rows, $stmt->fetchAll());
  }

  return $rows;
}

function site_fetch_store_trending(PDO $pdo, $store, $limit = 6) {
  $limit = max(1, min((int) $limit, 24));
  $stmt = $pdo->prepare("
    SELECT
      o.*,
      COUNT(c.id) AS clicks
    FROM ofertas o
    LEFT JOIN cliques c ON c.oferta_id = o.id
    WHERE o.ativo = 1
      AND (o.expira_em IS NULL OR o.expira_em > NOW())
      AND o.loja = ?
    GROUP BY o.id
    ORDER BY o.atualizado_em DESC, o.criado_em DESC
    LIMIT 36
  ");
  $stmt->execute([$store]);
  return array_slice(site_sort_offers_by_rank($stmt->fetchAll()), 0, $limit);
}

function site_pick_home_categories(PDO $pdo, $preferred = [], $limit = 4) {
  $preferred = array_values(array_filter(array_map('trim', $preferred)));
  $rows = $pdo->query("
    SELECT categoria, COUNT(*) AS total
    FROM ofertas
    WHERE ativo = 1
      AND (expira_em IS NULL OR expira_em > NOW())
    GROUP BY categoria
    ORDER BY total DESC, categoria ASC
    LIMIT 16
  ")->fetchAll();

  $indexed = [];
  foreach ($rows as $row) {
    $indexed[$row['categoria']] = $row;
  }

  $selected = [];
  foreach ($preferred as $category) {
    if (isset($indexed[$category])) {
      $selected[] = $indexed[$category];
      unset($indexed[$category]);
    }
    if (count($selected) >= $limit) {
      return $selected;
    }
  }

  foreach ($indexed as $row) {
    $selected[] = $row;
    if (count($selected) >= $limit) {
      break;
    }
  }

  return $selected;
}

function site_fetch_home_data(PDO $pdo) {
  $selectionMix = site_mix_home_offers(site_fetch_selection_candidates_balanced($pdo, 12, 4), 6);
  $meliTrending = site_fetch_store_trending($pdo, 'Mercado Livre', 8);
  $shopeeTrending = site_fetch_store_trending($pdo, 'Shopee', 8);
  $amazonTrending = site_fetch_store_trending($pdo, 'Amazon', 8);

  $categoryRows = site_pick_home_categories($pdo, [
    'MLB1714',
    'MLB1055',
    'MLB135384',
    'MLB7457',
  ], 4);

  $sectionsByCategory = [];
  $categoryStmt = $pdo->prepare("
    SELECT *
    FROM ofertas
    WHERE ativo=1
      AND (expira_em IS NULL OR expira_em > NOW())
      AND categoria = ?
    ORDER BY atualizado_em DESC, criado_em DESC
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
  return [
    'selection_mix' => $selectionMix,
    'meli_trending' => $meliTrending,
    'shopee_trending' => $shopeeTrending,
    'amazon_trending' => $amazonTrending,
    'sections_by_category' => $sectionsByCategory,
    'filters' => site_build_filters($pdo),
  ];
}

function site_fetch_category_data(PDO $pdo, $category) {
  $normalizedCategory = trim((string) $category);
  $store = trim((string) ($_GET['store'] ?? ''));
  $hasStore = $store !== '';
  $stmt = $pdo->prepare("
    SELECT *
    FROM ofertas
    WHERE ativo=1
      AND (expira_em IS NULL OR expira_em > NOW())
      AND (categoria = ? OR ? = 'geral')
      AND (? = '' OR loja = ?)
    ORDER BY atualizado_em DESC, criado_em DESC
    LIMIT 120
  ");
  $stmt->execute([$normalizedCategory, $normalizedCategory, $store, $store]);
  $offers = $stmt->fetchAll();

  $topByStoreStmt = $pdo->prepare("
    SELECT loja, COUNT(*) AS total
    FROM ofertas
    WHERE ativo=1
      AND (expira_em IS NULL OR expira_em > NOW())
      AND (categoria = ? OR ? = 'geral')
      AND (? = '' OR loja = ?)
    GROUP BY loja
    ORDER BY total DESC, loja ASC
    LIMIT 8
  ");
  $topByStoreStmt->execute([$normalizedCategory, $normalizedCategory, $store, $store]);

  return [
    'offers' => $offers,
    'stores' => $topByStoreStmt->fetchAll(),
    'filters' => site_build_filters($pdo),
    'store' => $store,
    'has_store' => $hasStore,
  ];
}

function site_search_offers(PDO $pdo, $query, $limit = 60) {
  $term = trim((string) $query);
  if ($term === '') {
    return [
      'query' => '',
      'offers' => [],
      'stores' => [],
      'categories' => [],
      'total' => 0,
    ];
  }

  $like = '%' . $term . '%';
  $limit = max(1, min((int) $limit, 100));

  $stmt = $pdo->prepare("
    SELECT *,
      CASE
        WHEN titulo LIKE ? THEN 120
        WHEN titulo LIKE ? THEN 90
        WHEN categoria LIKE ? THEN 55
        WHEN tags LIKE ? THEN 40
        WHEN descricao LIKE ? THEN 20
        ELSE 0
      END AS search_score
    FROM ofertas
    WHERE ativo=1
      AND (expira_em IS NULL OR expira_em > NOW())
      AND (
        titulo LIKE ?
        OR descricao LIKE ?
        OR categoria LIKE ?
        OR tags LIKE ?
        OR slug LIKE ?
      )
    ORDER BY search_score DESC, destaque DESC, atualizado_em DESC, criado_em DESC
    LIMIT {$limit}
  ");
  $stmt->execute([
    $term,
    $term . '%',
    $like,
    $like,
    $like,
    $like,
    $like,
    $like,
    $like,
    $like,
  ]);
  $offers = $stmt->fetchAll();

  $stores = [];
  $categories = [];
  foreach ($offers as $offer) {
    $storeLabel = site_store_label($offer['loja'] ?? '');
    $categoryLabel = site_public_category_label($offer['categoria'] ?? '');
    $stores[$storeLabel] = ($stores[$storeLabel] ?? 0) + 1;
    $categories[$categoryLabel] = ($categories[$categoryLabel] ?? 0) + 1;
  }

  arsort($stores);
  arsort($categories);

  return [
    'query' => $term,
    'offers' => $offers,
    'stores' => $stores,
    'categories' => $categories,
    'total' => count($offers),
  ];
}

function site_search_suggestions(PDO $pdo, $query, $limit = 8) {
  $term = trim((string) $query);
  if (strlen($term) < 2) {
    return [];
  }

  $like = '%' . $term . '%';
  $limit = max(1, min((int) $limit, 12));

  $stmt = $pdo->prepare("
    SELECT
      slug,
      titulo,
      preco,
      imagem_url,
      categoria,
      loja,
      CASE
        WHEN titulo LIKE ? THEN 120
        WHEN titulo LIKE ? THEN 90
        WHEN categoria LIKE ? THEN 55
        WHEN tags LIKE ? THEN 40
        ELSE 0
      END AS search_score
    FROM ofertas
    WHERE ativo=1
      AND (expira_em IS NULL OR expira_em > NOW())
      AND (
        titulo LIKE ?
        OR categoria LIKE ?
        OR tags LIKE ?
        OR slug LIKE ?
      )
    ORDER BY search_score DESC, destaque DESC, atualizado_em DESC, criado_em DESC
    LIMIT {$limit}
  ");
  $stmt->execute([
    $term,
    $term . '%',
    $like,
    $like,
    $like,
    $like,
    $like,
    $like,
  ]);

  return array_map(static function ($row) {
    return [
      'slug' => $row['slug'],
      'title' => $row['titulo'],
      'price' => (float) ($row['preco'] ?? 0),
      'image' => $row['imagem_url'] ?: '/assets/img/sem-img.png',
      'category' => site_public_category_label($row['categoria'] ?? ''),
      'store' => site_store_label($row['loja'] ?? ''),
      'offer_url' => site_offer_href($row['slug']),
    ];
  }, $stmt->fetchAll());
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

function site_fetch_instagram_landing_data(PDO $pdo) {
  $recentOffers = $pdo->query("
    SELECT *
    FROM ofertas
    WHERE ativo=1
      AND (expira_em IS NULL OR expira_em > NOW())
    ORDER BY destaque DESC, atualizado_em DESC, criado_em DESC
    LIMIT 8
  ")->fetchAll();

  $topClicked = $pdo->query("
    SELECT o.*, COUNT(c.id) AS clicks
    FROM ofertas o
    LEFT JOIN cliques c ON c.oferta_id = o.id
    WHERE o.ativo=1
      AND (o.expira_em IS NULL OR o.expira_em > NOW())
    GROUP BY o.id
    ORDER BY clicks DESC, o.destaque DESC, o.atualizado_em DESC
    LIMIT 4
  ")->fetchAll();

  $categoryRows = $pdo->query("
    SELECT categoria, COUNT(*) AS total
    FROM ofertas
    WHERE ativo=1
      AND (expira_em IS NULL OR expira_em > NOW())
    GROUP BY categoria
    ORDER BY total DESC, categoria ASC
    LIMIT 6
  ")->fetchAll();

  $categorySections = [];
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
    $categorySections[] = [
      'name' => $row['categoria'],
      'total' => (int) $row['total'],
      'offers' => $categoryStmt->fetchAll(),
    ];
  }

  return [
    'recent_offers' => $recentOffers,
    'top_clicked' => $topClicked,
    'categories' => $categoryRows,
    'category_sections' => $categorySections,
  ];
}
