<?php
require_once __DIR__ . '/db.php';
require_once __DIR__ . '/funcoes.php';

function site_tags_to_list($tags) {
  $items = array_filter(array_map('trim', explode(',', (string) $tags)));
  return array_values(array_unique($items));
}

function site_offer_preferred_affiliate_url($offer) {
  $store = strtolower(trim((string) ($offer['loja'] ?? '')));
  $affiliateUrl = trim((string) ($offer['url_afiliado'] ?? ''));
  if ($store !== 'mercado livre') {
    return $affiliateUrl;
  }

  foreach (site_tags_to_list($offer['tags'] ?? '') as $tag) {
    if (!str_starts_with($tag, 'meli_social_url:')) {
      continue;
    }

    $encoded = substr($tag, strlen('meli_social_url:'));
    if ($encoded === '') {
      continue;
    }

    $padding = strlen($encoded) % 4;
    if ($padding > 0) {
      $encoded .= str_repeat('=', 4 - $padding);
    }

    $decoded = base64_decode(strtr($encoded, '-_', '+/'), true);
    if ($decoded !== false && str_contains((string) $decoded, '/social/')) {
      return trim((string) $decoded);
    }
  }

  return $affiliateUrl;
}

function site_whatsapp_group_link() {
  $value = trim((string) getenv('WHATSAPP_GROUP_LINK'));
  if ($value !== '') {
    return $value;
  }
  return 'https://chat.whatsapp.com/IavSEP6OPh5ISM4WHluOax?mode=gi_t';
}

function site_whatsapp_group_label() {
  $value = trim((string) getenv('WHATSAPP_GROUP_LABEL'));
  return $value !== '' ? $value : 'Grupo de WhatsApp';
}

function site_whatsapp_group_qr_url() {
  $value = trim((string) getenv('WHATSAPP_GROUP_QR_URL'));
  if ($value !== '') {
    return $value;
  }
  return 'https://quickchart.io/qr?size=420&text=' . rawurlencode(site_whatsapp_group_link());
}

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

  $displayMap = [
    'utilidades domesticas' => 'Utilidades Domésticas',
    'escovas eletricas' => 'Escovas Elétricas',
    'panelas eletricas' => 'Panelas Elétricas',
    'caixas acusticas' => 'Caixas Acústicas',
    'fritadeiras eletricas' => 'Fritadeiras Elétricas',
    'cadeiras de escritorio' => 'Cadeiras de Escritório',
    'moveis' => 'Móveis',
    'eletroportateis' => 'Eletroportáteis',
    'calcados' => 'Calçados',
    'bebe' => 'Bebê',
    'caçarolas e caldeiroes' => 'Caçarolas e Caldeirões',
    'panelas de oleo' => 'Panelas de Óleo',
    'difusores de aromas eletricos' => 'Difusores de Aromas Elétricos',
    'cama e banho' => 'Cama e Banho',
    'fones de ouvido' => 'Fones de Ouvido',
    'pet shop' => 'Pet Shop',
    'smart tvs' => 'Smart TVs',
  ];

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

  $normalized = strtolower(str_replace(['-', '_'], ' ', $value));
  if (isset($displayMap[$normalized])) {
    return $displayMap[$normalized];
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
    'MLB456045' => 'Fritadeiras Elétricas',
    'MLB48666' => 'Panelas Elétricas',
    'MLB11507' => 'Caixas Acústicas',
    'MLB418472' => 'Teclados',
  ];

  if (isset($overrides[$value])) {
    return $overrides[$value];
  }

  return site_category_label($category);
}

function site_category_description($category) {
  $value = trim((string) $category);
  $label = site_public_category_label($category);

  $map = [
    'geral' => 'Confira uma seleção de ofertas atualizadas com produtos de diferentes lojas e faixas de preço.',
    'MLB456045' => 'Veja ofertas de fritadeiras elétricas com diferentes capacidades, marcas e faixas de preço.',
    'MLB48666' => 'Encontre panelas elétricas para arroz, pressão e preparo rápido em ofertas atualizadas.',
    'MLB11507' => 'Explore caixas acústicas e opções de som com preços competitivos e modelos variados.',
    'MLB418472' => 'Compare teclados para trabalho e jogos com ofertas ativas e marcas conhecidas.',
    'utilidades domesticas' => 'Veja utilidades domésticas para cozinha, limpeza e organização com ofertas atualizadas.',
    'cama e banho' => 'Encontre itens de cama e banho com ofertas para renovar conforto, proteção e praticidade.',
    'beleza' => 'Confira produtos de beleza e cuidados pessoais com preços promocionais e marcas populares.',
    'celulares e smartphones' => 'Compare celulares e smartphones com diferentes marcas, memória e faixa de preço.',
    'fones' => 'Veja fones com fio, bluetooth e modelos para uso diário, trabalho e treino.',
    'fones de ouvido' => 'Confira fones de ouvido com preços atualizados, modelos bluetooth e opções com bom custo-benefício.',
    'caixas bluetooth' => 'Explore caixas bluetooth com diferentes potências, tamanhos e autonomia de bateria.',
    'smartwatches' => 'Encontre smartwatches com funções de esporte, notificações e monitoramento do dia a dia.',
    'mouses' => 'Compare mouses para trabalho, estudo e jogos com ofertas ativas e marcas conhecidas.',
  ];

  $normalized = strtolower(str_replace(['_', '-'], ' ', $value));
  $normalizedLabel = strtolower(str_replace(['_', '-'], ' ', $label));

  if (isset($map[$value])) {
    return $map[$value];
  }

  if (isset($map[$normalized])) {
    return $map[$normalized];
  }

  if (isset($map[$normalizedLabel])) {
    return $map[$normalizedLabel];
  }

  return 'Confira ofertas atualizadas de ' . mb_strtolower($label, 'UTF-8') . ' com opções de preço, marcas e modelos variados.';
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

function site_count_active_offers(PDO $pdo) {
  return (int) $pdo->query("
    SELECT COUNT(*)
    FROM ofertas
    WHERE ativo = 1
      AND (expira_em IS NULL OR expira_em > NOW())
  ")->fetchColumn();
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

function site_limit_store_in_selection(array $offers, $store, $maxItems) {
  $normalizedStore = strtolower(trim((string) $store));
  $maxItems = max(1, (int) $maxItems);
  $selected = [];
  $storeCount = 0;

  foreach ($offers as $offer) {
    $offerStore = strtolower(trim((string) ($offer['loja'] ?? '')));
    if ($offerStore === $normalizedStore) {
      if ($storeCount >= $maxItems) {
        continue;
      }
      $storeCount++;
    }
    $selected[] = $offer;
  }

  return $selected;
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
    ORDER BY o.destaque DESC, home_score DESC, o.atualizado_em DESC, o.criado_em DESC
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
    ORDER BY o.destaque DESC, home_score DESC, o.atualizado_em DESC, o.criado_em DESC
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

function site_exclude_offers_by_ids(array $offers, array $excludedIds, $limit = 0) {
  $excludedMap = [];
  foreach ($excludedIds as $offerId) {
    $excludedMap[(int) $offerId] = true;
  }

  $items = [];
  foreach ($offers as $offer) {
    $offerId = (int) ($offer['id'] ?? $offer['offer_id'] ?? 0);
    if ($offerId > 0 && isset($excludedMap[$offerId])) {
      continue;
    }

    $items[] = $offer;
    if ($limit > 0 && count($items) >= $limit) {
      break;
    }
  }

  return $items;
}

function site_fill_store_section(array $offers, array $selectionIds, $limit = 8) {
  $limit = max(1, (int) $limit);
  $primary = site_exclude_offers_by_ids($offers, $selectionIds, $limit);
  if (count($primary) >= $limit) {
    return $primary;
  }

  $selectedIds = [];
  foreach ($primary as $offer) {
    $selectedIds[(int) ($offer['id'] ?? 0)] = true;
  }

  foreach ($offers as $offer) {
    $offerId = (int) ($offer['id'] ?? 0);
    if ($offerId <= 0 || isset($selectedIds[$offerId])) {
      continue;
    }
    $primary[] = $offer;
    $selectedIds[$offerId] = true;
    if (count($primary) >= $limit) {
      break;
    }
  }

  return array_slice($primary, 0, $limit);
}

function site_fetch_social_published_offers(PDO $pdo, $limit = 12) {
  $limit = max(1, min((int) $limit, 24));
  $candidateLimit = max($limit * 4, 40);

  try {
    $runsStmt = $pdo->prepare("
      SELECT id, canal, modo, criado_em, result_json
      FROM automacao_execucoes
      WHERE tipo = 'social'
        AND status = 'success'
        AND canal <> 'whatsapp'
        AND result_json IS NOT NULL
      ORDER BY criado_em DESC, id DESC
      LIMIT 80
    ");
    $runsStmt->execute();
    $runs = $runsStmt->fetchAll();
  } catch (Throwable $e) {
    return [];
  }

  $publishedMap = [];
  foreach ($runs as $run) {
    $payload = json_decode((string) ($run['result_json'] ?? ''), true);
    if (!is_array($payload) || empty($payload['items']) || !is_array($payload['items'])) {
      continue;
    }

    foreach ($payload['items'] as $item) {
      $offerId = (int) ($item['offer_id'] ?? 0);
      if ($offerId <= 0 || isset($publishedMap[$offerId])) {
        continue;
      }

      $publishedMap[$offerId] = [
        'offer_id' => $offerId,
        'canal' => (string) ($run['canal'] ?? ''),
        'modo' => (string) ($run['modo'] ?? ''),
        'published_at' => (string) ($run['criado_em'] ?? ''),
      ];

      if (count($publishedMap) >= $candidateLimit) {
        break 2;
      }
    }
  }

  if (!$publishedMap) {
    return [];
  }

  $offerIds = array_keys($publishedMap);
  $placeholders = implode(',', array_fill(0, count($offerIds), '?'));
  $offerStmt = $pdo->prepare("
    SELECT id, slug, titulo, loja, categoria, preco, preco_antigo, imagem_url, destaque
    FROM ofertas
    WHERE ativo = 1
      AND (expira_em IS NULL OR expira_em > NOW())
      AND id IN ({$placeholders})
  ");
  $offerStmt->execute($offerIds);
  $offers = $offerStmt->fetchAll();

  $offersById = [];
  foreach ($offers as $offer) {
    $offersById[(int) $offer['id']] = $offer;
  }

  $items = [];
  foreach ($publishedMap as $offerId => $meta) {
    if (!isset($offersById[$offerId])) {
      continue;
    }

    $items[] = $offersById[$offerId] + $meta;
    if (count($items) >= $limit) {
      break;
    }
  }

  return $items;
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
  $selectionMix = site_fetch_social_published_offers($pdo, 14);
  $selectionIds = array_map(static fn($offer) => (int) ($offer['id'] ?? $offer['offer_id'] ?? 0), $selectionMix);

  $topClicked = $pdo->query("
    SELECT o.*, COUNT(c.id) AS clicks
    FROM ofertas o
    LEFT JOIN cliques c ON c.oferta_id = o.id
    WHERE o.ativo = 1
      AND (o.expira_em IS NULL OR o.expira_em > NOW())
    GROUP BY o.id
    ORDER BY clicks DESC, o.destaque DESC, o.atualizado_em DESC
    LIMIT 4
  ")->fetchAll();

  $dealRush = $pdo->query("
    SELECT o.*, COUNT(c.id) AS clicks
    FROM ofertas o
    LEFT JOIN cliques c ON c.oferta_id = o.id
    WHERE o.ativo = 1
      AND (o.expira_em IS NULL OR o.expira_em > NOW())
      AND o.preco > 0
      AND o.preco <= 199.90
    GROUP BY o.id
    ORDER BY
      (CASE WHEN o.preco_antigo IS NOT NULL AND o.preco_antigo > o.preco THEN 1 ELSE 0 END) DESC,
      o.destaque DESC,
      clicks DESC,
      o.atualizado_em DESC
    LIMIT 16
  ")->fetchAll();

  $meliTrending = site_fill_store_section(site_fetch_store_trending($pdo, 'Mercado Livre', 60), $selectionIds, 16);
  $shopeeTrending = site_fill_store_section(site_fetch_store_trending($pdo, 'Shopee', 60), $selectionIds, 16);
  $amazonTrending = site_fill_store_section(site_fetch_store_trending($pdo, 'Amazon', 60), $selectionIds, 16);

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
    LIMIT 12
  ");

  foreach ($categoryRows as $row) {
    $categoryStmt->execute([$row['categoria']]);
    $categoryOffers = site_exclude_offers_by_ids($categoryStmt->fetchAll(), $selectionIds, 16);
    if (!$categoryOffers) {
      continue;
    }

    $sectionsByCategory[] = [
      'name' => $row['categoria'],
      'total' => (int) $row['total'],
      'offers' => $categoryOffers,
    ];
  }
  return [
    'selection_mix' => $selectionMix,
    'top_clicked' => $topClicked,
    'deal_rush' => $dealRush,
    'meli_trending' => $meliTrending,
    'shopee_trending' => $shopeeTrending,
    'amazon_trending' => $amazonTrending,
    'sections_by_category' => $sectionsByCategory,
    'filters' => site_build_filters($pdo),
    'active_offer_count' => site_count_active_offers($pdo),
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

function site_fetch_deals_of_day_data(PDO $pdo) {
  $bestDeals = $pdo->query("
    SELECT o.*, COUNT(c.id) AS clicks
    FROM ofertas o
    LEFT JOIN cliques c ON c.oferta_id = o.id
    WHERE o.ativo = 1
      AND (o.expira_em IS NULL OR o.expira_em > NOW())
    GROUP BY o.id
    ORDER BY
      o.destaque DESC,
      (CASE WHEN o.cupom IS NOT NULL AND o.cupom <> '' THEN 1 ELSE 0 END) DESC,
      (CASE WHEN o.preco_antigo IS NOT NULL AND o.preco_antigo > o.preco THEN ((o.preco_antigo - o.preco) / o.preco_antigo) ELSE 0 END) DESC,
      clicks DESC,
      o.atualizado_em DESC
    LIMIT 12
  ")->fetchAll();

  $budgetDeals = $pdo->query("
    SELECT o.*, COUNT(c.id) AS clicks
    FROM ofertas o
    LEFT JOIN cliques c ON c.oferta_id = o.id
    WHERE o.ativo = 1
      AND (o.expira_em IS NULL OR o.expira_em > NOW())
      AND o.preco > 0
      AND o.preco <= 149.90
    GROUP BY o.id
    ORDER BY
      (CASE WHEN o.preco_antigo IS NOT NULL AND o.preco_antigo > o.preco THEN 1 ELSE 0 END) DESC,
      o.destaque DESC,
      clicks DESC,
      o.atualizado_em DESC
    LIMIT 10
  ")->fetchAll();

  $budgetStrictCount = count($budgetDeals);
  if ($budgetStrictCount < 10) {
    $existingIds = array_map(static fn($offer) => (int) ($offer['id'] ?? 0), $budgetDeals);
    $placeholders = implode(',', array_fill(0, max(1, count($existingIds)), '?'));
    $excludedIds = $existingIds ?: [0];
    $fallbackLimit = 10 - $budgetStrictCount;

    $fallbackStmt = $pdo->prepare("
      SELECT o.*, COUNT(c.id) AS clicks
      FROM ofertas o
      LEFT JOIN cliques c ON c.oferta_id = o.id
      WHERE o.ativo = 1
        AND (o.expira_em IS NULL OR o.expira_em > NOW())
        AND o.preco > 149.90
        AND o.preco <= 199.90
        AND o.id NOT IN ({$placeholders})
      GROUP BY o.id
      ORDER BY
        (CASE WHEN o.preco_antigo IS NOT NULL AND o.preco_antigo > o.preco THEN 1 ELSE 0 END) DESC,
        o.destaque DESC,
        clicks DESC,
        o.atualizado_em DESC
      LIMIT {$fallbackLimit}
    ");
    $fallbackStmt->execute($excludedIds);
    $budgetDeals = array_merge($budgetDeals, $fallbackStmt->fetchAll());
  }

  $couponDeals = $pdo->query("
    SELECT o.*, COUNT(c.id) AS clicks
    FROM ofertas o
    LEFT JOIN cliques c ON c.oferta_id = o.id
    WHERE o.ativo = 1
      AND (o.expira_em IS NULL OR o.expira_em > NOW())
      AND o.cupom IS NOT NULL
      AND o.cupom <> ''
    GROUP BY o.id
    ORDER BY o.destaque DESC, clicks DESC, o.atualizado_em DESC
    LIMIT 6
  ")->fetchAll();

  $topClicked = $pdo->query("
    SELECT o.*, COUNT(c.id) AS clicks
    FROM ofertas o
    LEFT JOIN cliques c ON c.oferta_id = o.id
    WHERE o.ativo = 1
      AND (o.expira_em IS NULL OR o.expira_em > NOW())
    GROUP BY o.id
    ORDER BY clicks DESC, o.destaque DESC, o.atualizado_em DESC
    LIMIT 5
  ")->fetchAll();

  return [
    'best_deals' => $bestDeals,
    'budget_deals' => $budgetDeals,
    'budget_strict_count' => $budgetStrictCount,
    'coupon_deals' => $couponDeals,
    'top_clicked' => $topClicked,
    'active_offer_count' => site_count_active_offers($pdo),
  ];
}
