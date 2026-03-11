<?php
require_once __DIR__ . '/_init.php';
require_once __DIR__ . '/../inc/site.php';
admin_require_login();

$flash = admin_flash_get();

$pdo = db();
$feedback = '';
$errorLines = [];

function ml_bulk_extract_product_id($url) {
  $value = (string) $url;
  if (preg_match('~/p/(MLB\d+)~i', $value, $match)) {
    return strtoupper((string) $match[1]);
  }
  return null;
}

function ml_bulk_is_profile_social_url($url) {
  $value = (string) $url;
  return str_contains($value, '/social/') && ml_bulk_extract_product_id($value) === null;
}

function ml_bulk_is_product_specific_affiliate_url($url) {
  return admin_is_meli_affiliate_url($url) && ml_bulk_extract_product_id($url) !== null;
}

function ml_bulk_parse_lines($raw) {
  $lines = preg_split('/\r\n|\r|\n/', (string) $raw) ?: [];
  $pairs = [];
  $errors = [];

  foreach ($lines as $index => $line) {
    $clean = trim((string) $line);
    if ($clean === '') {
      continue;
    }

    $parts = preg_split('/\s*\|\s*|\s*;\s*|\t+/', $clean, 2);
    if (!$parts || count($parts) < 2) {
      $errors[] = 'Linha ' . ($index + 1) . ': use o formato `ID | URL oficial`.';
      continue;
    }

    $id = (int) trim((string) $parts[0]);
    $url = trim((string) $parts[1]);
    if ($id <= 0 || $url === '') {
      $errors[] = 'Linha ' . ($index + 1) . ': ID ou URL invalido.';
      continue;
    }

    $pairs[$id] = $url;
  }

  return [$pairs, $errors];
}

function ml_bulk_fetch_invalid_items(PDO $pdo) {
  $statusFilter = trim((string) ($_GET['status'] ?? ''));
  $stmt = $pdo->query("
    SELECT id, titulo, slug, preco, url_afiliado, atualizado_em, tags, ativo
    FROM ofertas
    WHERE LOWER(loja) = 'mercado livre'
    ORDER BY atualizado_em DESC, id DESC
    LIMIT 600
  ");
  $items = $stmt->fetchAll();
  $items = array_values(array_filter($items, static function ($item) {
    return admin_affiliate_audit('Mercado Livre', $item['url_afiliado'])['severity'] !== 'ok';
  }));
  if ($statusFilter === '') {
    return $items;
  }
  return array_values(array_filter($items, static function ($item) use ($statusFilter) {
    return ml_bulk_link_status($item['url_afiliado']) === $statusFilter;
  }));
}

function ml_bulk_link_status($url) {
  $value = (string) $url;
  $hasWid = str_contains($value, 'wid=');
  $hasSidAffiliates = str_contains($value, 'sid=affiliates');
  $hasSidRecos = str_contains($value, 'sid=recos');
  $hasPolycard = str_contains($value, 'polycard_client=affiliates');
  $hasAffiliateProfile = str_contains($value, 'affiliate-profile');
  $hasMatt = str_contains($value, 'matt_tool=');
  $hasSocial = str_contains($value, '/social/');

  if ($hasSocial) {
    return 'social';
  }
  if ($hasMatt) {
    return 'matt_tool';
  }
  if ($hasWid && $hasSidRecos && $hasAffiliateProfile) {
    return 'wid_recos_affiliate_profile';
  }
  if ($hasWid && $hasSidAffiliates) {
    return 'wid_sid_affiliates';
  }
  if ($hasWid && $hasPolycard) {
    return 'wid_polycard_affiliates';
  }
  if ($hasWid && $hasAffiliateProfile) {
    return 'wid_affiliate_profile';
  }
  if ($hasWid) {
    return 'com_wid_suspeito';
  }
  return 'sem_wid';
}

function ml_bulk_summary(PDO $pdo) {
  $stmt = $pdo->query("
    SELECT url_afiliado
    FROM ofertas
    WHERE LOWER(loja) = 'mercado livre'
  ");
  $rows = $stmt->fetchAll();
  $total = count($rows);
  $invalid = 0;
  foreach ($rows as $row) {
    if (admin_affiliate_audit('Mercado Livre', $row['url_afiliado'])['severity'] !== 'ok') {
      $invalid++;
    }
  }

  return [
    'total' => $total,
    'invalid' => $invalid,
    'valid' => max(0, $total - $invalid),
  ];
}

if (isset($_GET['export']) && in_array($_GET['export'], ['csv', 'txt'], true)) {
  $items = ml_bulk_fetch_invalid_items($pdo);
  $format = (string) $_GET['export'];

  if ($format === 'csv') {
    header('Content-Type: text/csv; charset=utf-8');
    header('Content-Disposition: attachment; filename="ml-links-pendentes.csv"');
    $out = fopen('php://output', 'w');
    fputcsv($out, ['id', 'titulo', 'slug', 'preco', 'status_link_ml', 'url_oferta_site', 'url_atual', 'atualizado_em'], ';');
    foreach ($items as $item) {
      fputcsv($out, [
        (int) $item['id'],
        (string) $item['titulo'],
        (string) $item['slug'],
        number_format((float) $item['preco'], 2, '.', ''),
        ml_bulk_link_status($item['url_afiliado']),
        'https://zeropreco.com.br' . site_offer_href($item['slug']),
        (string) $item['url_afiliado'],
        (string) $item['atualizado_em'],
      ], ';');
    }
    fclose($out);
    exit;
  }

  header('Content-Type: text/plain; charset=utf-8');
  header('Content-Disposition: attachment; filename="ml-links-pendentes.txt"');
  foreach ($items as $item) {
    echo (int) $item['id'] . ' | ' . ml_bulk_link_status($item['url_afiliado']) . ' | ' . (string) $item['titulo'] . ' | https://zeropreco.com.br' . site_offer_href($item['slug']) . ' | ' . (string) $item['url_afiliado'] . PHP_EOL;
  }
  exit;
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
  admin_csrf_check_or_die();

  $mode = (string) ($_POST['mode'] ?? 'form');
  $updates = [];

  if ($mode === 'bulk_text') {
    [$updates, $errorLines] = ml_bulk_parse_lines($_POST['bulk_links'] ?? '');
  } elseif ($mode === 'single') {
    $singleId = (int) ($_POST['single_id'] ?? 0);
    $singleUrl = trim((string) ($_POST['single_url'] ?? ''));
    if ($singleId <= 0 || $singleUrl === '') {
      $errorLines[] = 'Informe uma URL oficial valida para salvar a linha.';
    } else {
      $updates[$singleId] = $singleUrl;
    }
  } else {
    foreach ((array) ($_POST['url_afiliado'] ?? []) as $id => $url) {
      $offerId = (int) $id;
      $cleanUrl = trim((string) $url);
      if ($offerId > 0 && $cleanUrl !== '') {
        $updates[$offerId] = $cleanUrl;
      }
    }
  }

  if (!$errorLines && !$updates) {
    $errorLines[] = 'Nenhuma URL oficial foi informada.';
  }

  if (!$errorLines && $updates) {
    $ids = array_keys($updates);
    $placeholders = implode(',', array_fill(0, count($ids), '?'));
    $stmt = $pdo->prepare("SELECT id, titulo, url_afiliado FROM ofertas WHERE id IN ($placeholders)");
    $stmt->execute($ids);
    $rows = $stmt->fetchAll();
    $existing = [];
    foreach ($rows as $row) {
      $existing[(int) $row['id']] = $row;
    }

    $saved = 0;
    foreach ($updates as $id => $url) {
      if (!isset($existing[$id])) {
        $errorLines[] = "Oferta #$id nao encontrada.";
        continue;
      }
      if (!admin_is_meli_affiliate_url($url)) {
        $errorLines[] = "Oferta #$id: o link informado nao parece oficial de afiliado do Mercado Livre.";
        continue;
      }

      if (ml_bulk_is_profile_social_url($url)) {
        $errorLines[] = "Oferta #$id: use a URL oficial do produto, nao o link geral /social/ do perfil.";
        continue;
      }
      if (!ml_bulk_is_product_specific_affiliate_url($url)) {
        $errorLines[] = "Oferta #$id: use uma URL oficial do produto com /p/MLB..., nao um link generico.";
        continue;
      }

      $currentProductId = ml_bulk_extract_product_id((string) ($existing[$id]['url_afiliado'] ?? ''));
      $newProductId = ml_bulk_extract_product_id($url);
      if ($currentProductId !== null && $newProductId !== null && $currentProductId !== $newProductId) {
        $errorLines[] = "Oferta #$id: o MLB do link informado ($newProductId) nao bate com o produto atual ($currentProductId).";
        continue;
      }

      $pdo->prepare('UPDATE ofertas SET url_afiliado = ?, ativo = 1 WHERE id = ?')->execute([$url, $id]);
      $saved++;
    }

    if ($saved > 0) {
      $feedback = $saved . ' oferta(s) do Mercado Livre atualizada(s) com link oficial e reativada(s).';
    }
    if ($saved === 0 && !$errorLines) {
      $errorLines[] = 'Nenhuma oferta foi atualizada.';
    }
  }
}

$items = ml_bulk_fetch_invalid_items($pdo);

$invalidCount = count($items);
$summary = ml_bulk_summary($pdo);
$activeStatus = trim((string) ($_GET['status'] ?? ''));
$statusOptions = [
  '' => 'Todos',
  'sem_wid' => 'Sem wid',
  'com_wid_suspeito' => 'Com wid suspeito',
  'wid_affiliate_profile' => 'wid + affiliate-profile',
  'wid_recos_affiliate_profile' => 'wid + recos + affiliate-profile',
  'wid_sid_affiliates' => 'wid + sid=affiliates',
  'wid_polycard_affiliates' => 'wid + polycard',
  'matt_tool' => 'matt_tool',
  'social' => 'social',
];
?>
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Admin - Corrigir ML em lote</title>
  <link rel="stylesheet" href="/assets/css/style.css">
  <link rel="stylesheet" href="/assets/css/admin.css">
  <style>
    .admin-wrap { display: grid; gap: 18px; }
    .panel { background: #fff; border: 1px solid #d9e2f2; border-radius: 18px; padding: 18px; }
    .panel h2, .panel h3 { margin: 0 0 8px; color: #10213a; }
    .helper { color: #5d6d89; font-size: 14px; line-height: 1.5; }
    .ok { margin-top: 12px; padding: 12px 14px; border-radius: 12px; background: #eef8f0; border: 1px solid #c9ead3; color: #1d6b39; }
    .err { margin-top: 12px; padding: 12px 14px; border-radius: 12px; background: #fff7e7; border: 1px solid #f0deaf; color: #8a5a00; }
    .err ul { margin: 8px 0 0; padding-left: 18px; }
    textarea, input[type="url"] { width: 100%; border: 1px solid #d1d9e6; border-radius: 12px; padding: 10px 12px; font: inherit; }
    textarea { min-height: 170px; }
    .copy-helper { min-height: 220px; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 12px; }
    .actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }
    .table-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; min-width: 980px; }
    th, td { border-bottom: 1px solid #e7edf7; text-align: left; padding: 12px 10px; vertical-align: top; font-size: 14px; }
    th { color: #42577c; font-size: 12px; text-transform: uppercase; letter-spacing: .06em; }
    .url-box { max-width: 340px; word-break: break-all; color: #435776; font-size: 12px; line-height: 1.45; }
    .meta { color: #6c7c98; font-size: 12px; }
    .field-note { display: block; margin-top: 6px; color: #6c7c98; font-size: 12px; }
    @media (max-width: 900px) {
      .actions { align-items: stretch; }
    }
  </style>
</head>
<body class="admin-page">
<header>
  <div class="container" style="display:flex; align-items:center; justify-content:space-between; gap:10px;">
    <div style="font-weight:700;">Corrigir Mercado Livre em lote</div>
    <div style="display:flex; gap:8px; flex-wrap:wrap;">
      <a class="badge" href="/admin/ofertas.php?modo=ml_invalidos">Voltar para invalidos ML</a>
      <a class="badge" href="/admin/ofertas.php">Todas as ofertas</a>
      <a class="badge" href="/admin/logout.php">Sair</a>
    </div>
  </div>
</header>

<main class="container admin-wrap">
  <?php if ($flash): ?>
    <div class="admin-alert <?= h((string) ($flash['type'] ?? '')) ?>"><?= h((string) ($flash['message'] ?? '')) ?></div>
  <?php endif; ?>
  <section class="panel">
    <h2>Colar em lote</h2>
    <div class="helper">Cole uma linha por oferta no formato `ID | URL oficial`. Neste fluxo, use a URL oficial do produto (`/p/MLB...`) gerada no ambiente do afiliado. Nao use o link geral do perfil `/social/`.</div>
    <div class="actions">
      <span class="badge">ML total: <?= (int) $summary['total'] ?></span>
      <span class="badge">Com link oficial: <?= (int) $summary['valid'] ?></span>
      <span class="badge">Pendentes: <?= (int) $summary['invalid'] ?></span>
    </div>
    <?php if ($feedback !== ''): ?>
      <div class="ok"><?= h($feedback) ?></div>
    <?php endif; ?>
    <?php if ($errorLines): ?>
      <div class="err">
        Erros encontrados:
        <ul>
          <?php foreach ($errorLines as $line): ?>
            <li><?= h($line) ?></li>
          <?php endforeach; ?>
        </ul>
      </div>
    <?php endif; ?>
    <form method="post">
      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
      <input type="hidden" name="mode" value="bulk_text">
      <textarea name="bulk_links" placeholder="123 | https://www.mercadolivre.com.br/produto-exemplo/p/MLB12345678#reco_client=home_affiliate-profile&source=affiliate-profile&wid=MLB1234567890&sid=recos"></textarea>
      <div class="actions">
        <button class="btn" type="submit">Salvar links em lote</button>
        <a class="badge" href="/admin/ml_corrigir_lote.php?export=csv">Exportar CSV pendente</a>
        <a class="badge" href="/admin/ml_corrigir_lote.php?export=txt">Exportar TXT pendente</a>
      </div>
    </form>
  </section>

  <section class="panel">
    <h3>Lista para corrigir</h3>
    <div class="helper"><?= (int) $invalidCount ?> oferta(s) do Mercado Livre ainda sem link oficial detectado. Preencha so as URLs que voce ja gerou no portal do afiliado.</div>
    <div class="actions">
      <?php foreach ($statusOptions as $statusValue => $statusLabel): ?>
        <?php
          $href = '/admin/ml_corrigir_lote.php';
          if ($statusValue !== '') {
            $href .= '?status=' . urlencode($statusValue);
          }
        ?>
        <a class="badge" href="<?= h($href) ?>" style="<?= $activeStatus === $statusValue ? 'background:#10213a;color:#fff;border-color:#10213a;' : '' ?>"><?= h($statusLabel) ?></a>
      <?php endforeach; ?>
    </div>
    <?php if (!$items): ?>
      <div class="ok">Nenhuma oferta invalida do Mercado Livre pendente.</div>
    <?php else: ?>
      <div style="margin-top:14px;">
      <div class="helper">Linhas prontas para copiar e completar com a URL oficial do afiliado. Esta fila agora inclui os links quebrados e os suspeitos vindos da API/automacao.</div>
        <textarea class="copy-helper" readonly><?php foreach ($items as $item): ?><?= (int) $item['id'] ?> | <?= h(ml_bulk_link_status($item['url_afiliado'])) ?> | <?= h($item['titulo']) ?> | https://zeropreco.com.br<?= h(site_offer_href($item['slug'])) ?> | 
<?php endforeach; ?></textarea>
      </div>
      <form method="post">
        <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
        <input type="hidden" name="mode" value="form">
        <div class="table-wrap" style="margin-top:14px;">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Oferta</th>
                <th>URL atual</th>
                <th>Nova URL oficial</th>
              </tr>
            </thead>
            <tbody>
              <?php foreach ($items as $item): ?>
                <tr>
                  <td><?= (int) $item['id'] ?></td>
                  <td>
                    <strong><?= h($item['titulo']) ?></strong>
                    <div class="meta">slug: <?= h($item['slug']) ?></div>
                    <div class="meta">preco: R$ <?= number_format((float) $item['preco'], 2, ',', '.') ?></div>
                    <div class="meta">atualizado em: <?= h((string) $item['atualizado_em']) ?></div>
                    <div class="meta">ativo: <?= ((int) $item['ativo'] === 1) ? 'sim' : 'nao' ?></div>
                    <?php if (!empty($item['tags'])): ?>
                      <div class="meta">tags: <?= h((string) $item['tags']) ?></div>
                    <?php endif; ?>
                  </td>
                  <td>
                    <div class="url-box"><?= h($item['url_afiliado']) ?></div>
                    <div class="meta" style="margin-top:6px;">status: <?= h(ml_bulk_link_status($item['url_afiliado'])) ?></div>
                  </td>
                  <td>
                    <form method="post" style="display:grid; gap:8px;">
                      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
                      <input type="hidden" name="mode" value="single">
                      <input type="hidden" name="single_id" value="<?= (int) $item['id'] ?>">
                      <input type="url" name="single_url" placeholder="Cole aqui a URL oficial do afiliado">
                      <button class="badge" type="submit" style="justify-self:flex-start;">Salvar</button>
                    </form>
                    <span class="field-note">Aceita URL oficial do produto com `/p/MLB...` e sinais do afiliado (`matt_*`, `wid`, `affiliate-profile`). Nao use o `/social/` generico.</span>
                  </td>
                </tr>
              <?php endforeach; ?>
            </tbody>
          </table>
        </div>
        <div class="actions">
          <button class="btn" type="submit">Salvar preenchidos</button>
        </div>
      </form>
    <?php endif; ?>
  </section>
</main>
</body>
</html>

