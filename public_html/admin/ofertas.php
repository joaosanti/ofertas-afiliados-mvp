<?php
require_once __DIR__ . '/_init.php';
admin_require_login();

$pdo = db();
$filter = trim((string) ($_GET['loja'] ?? ''));
$mode = trim((string) ($_GET['modo'] ?? ''));

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
  admin_csrf_check_or_die();
  $acao = (string) ($_POST['acao'] ?? '');
  $id = (int) ($_POST['id'] ?? 0);

  if ($id > 0 && in_array($acao, ['toggle_ativo', 'toggle_destaque'], true)) {
    if ($acao === 'toggle_ativo') {
      $pdo->prepare('UPDATE ofertas SET ativo = IF(ativo=1, 0, 1) WHERE id=?')->execute([$id]);
    }
    if ($acao === 'toggle_destaque') {
      $pdo->prepare('UPDATE ofertas SET destaque = IF(destaque=1, 0, 1) WHERE id=?')->execute([$id]);
    }
  }

  $query = [];
  if ($filter !== '') {
    $query['loja'] = $filter;
  }
  if ($mode !== '') {
    $query['modo'] = $mode;
  }

  header('Location: /admin/ofertas.php' . ($query ? '?' . http_build_query($query) : ''));
  exit;
}

$sql = 'SELECT id, titulo, slug, preco, loja, categoria, destaque, ativo, atualizado_em, url_afiliado
        FROM ofertas';
$where = [];
$params = [];

if ($filter !== '') {
  $where[] = 'loja = ?';
  $params[] = $filter;
}

if ($mode === 'ml_invalidos') {
  $where[] = "LOWER(loja) = 'mercado livre'";
  $where[] = "(url_afiliado NOT LIKE '%wid=%' OR url_afiliado NOT LIKE '%sid=affiliates%')";
}

if ($where) {
  $sql .= ' WHERE ' . implode(' AND ', $where);
}

$sql .= ' ORDER BY atualizado_em DESC, id DESC LIMIT 300';

$stmt = $pdo->prepare($sql);
$stmt->execute($params);
$ofertas = $stmt->fetchAll();
$lojas = $pdo->query('SELECT loja, COUNT(*) AS total FROM ofertas GROUP BY loja ORDER BY total DESC, loja ASC')->fetchAll();
$invalidMeliCount = (int) $pdo->query("
  SELECT COUNT(*)
  FROM ofertas
  WHERE LOWER(loja) = 'mercado livre'
    AND (url_afiliado NOT LIKE '%wid=%' OR url_afiliado NOT LIKE '%sid=affiliates%')
")->fetchColumn();
?>
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Admin - Ofertas</title>
  <link rel="stylesheet" href="/assets/css/style.css">
  <style>
    .admin-wrap { display: grid; gap: 18px; }
    .toolbar, .panel { background: #fff; border: 1px solid #d9e2f2; border-radius: 18px; padding: 18px; }
    .toolbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
    .filters { display: flex; gap: 10px; flex-wrap: wrap; }
    .table-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; min-width: 1150px; }
    th, td { border-bottom: 1px solid #e7edf7; text-align: left; padding: 12px 10px; vertical-align: top; font-size: 14px; }
    th { color: #42577c; font-size: 12px; text-transform: uppercase; letter-spacing: .06em; }
    .actions form { display: inline-block; margin: 4px 6px 0 0; }
    .status { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; padding: 5px 10px; border-radius: 999px; border: 1px solid #d8e2f2; color: #324564; margin: 0 6px 6px 0; }
    .status.ok { background: #eef8f0; color: #1d6b39; border-color: #c9ead3; }
    .status.warn { background: #fff7e7; color: #8a5a00; border-color: #f0deaf; }
    .status.off { background: #f5f7fb; color: #5c6d8a; }
    .url-box { max-width: 360px; word-break: break-all; color: #435776; font-size: 12px; line-height: 1.45; }
    .title-cell strong { display: block; margin-bottom: 6px; color: #10213a; }
    .meta-line { color: #6c7c98; font-size: 12px; }
    .btn-link { display: inline-flex; align-items: center; gap: 6px; padding: 9px 12px; border-radius: 999px; border: 1px solid #d8e2f2; background: #fff; color: #164a9f; font-size: 12px; font-weight: 700; text-decoration: none; }
    .btn-link.primary { background: #164a9f; border-color: #164a9f; color: #fff; }
    @media (max-width: 840px) {
      .toolbar { align-items: flex-start; }
    }
  </style>
</head>
<body>
<header>
  <div class="container" style="display:flex; align-items:center; justify-content:space-between; gap:10px;">
    <div style="font-weight:700;">Admin de Ofertas</div>
    <div style="display:flex; gap:8px; flex-wrap:wrap;">
      <a class="badge" href="/admin/oferta_editar.php">+ Nova oferta</a>
      <a class="badge" href="/">Ver site</a>
      <a class="badge" href="/admin/logout.php">Sair</a>
    </div>
  </div>
</header>

<main class="container admin-wrap">
  <section class="toolbar">
    <div>
      <div style="font-size:12px; text-transform:uppercase; letter-spacing:.06em; color:#6c7c98;">Auditoria de links</div>
      <div style="font-weight:700; color:#10213a;">Confira rapidamente se o Mercado Livre está saindo com `wid` e `sid=affiliates`.</div>
    </div>

    <div class="filters">
      <a class="badge" href="/admin/ofertas.php">Todas</a>
      <a class="badge" href="/admin/ofertas.php?modo=ml_invalidos">Somente ML inválidos (<?= $invalidMeliCount ?>)</a>
      <?php foreach ($lojas as $loja): ?>
        <a class="badge" href="/admin/ofertas.php?loja=<?= urlencode($loja['loja']) ?>"><?= h($loja['loja']) ?> (<?= (int) $loja['total'] ?>)</a>
      <?php endforeach; ?>
    </div>
  </section>

  <section class="panel table-wrap">
    <table>
      <thead>
        <tr>
          <th>ID</th>
          <th>Título</th>
          <th>Preço</th>
          <th>Loja / Categoria</th>
          <th>Status</th>
          <th>URL Afiliado</th>
          <th>Ações</th>
        </tr>
      </thead>
      <tbody>
        <?php foreach ($ofertas as $o): ?>
          <?php $isMeli = strtolower((string) $o['loja']) === 'mercado livre'; ?>
          <?php $isAffiliateOk = $isMeli ? admin_is_meli_affiliate_url($o['url_afiliado']) : false; ?>
          <tr>
            <td><?= (int) $o['id'] ?></td>
            <td class="title-cell">
              <strong><?= h($o['titulo']) ?></strong>
              <div class="meta-line">slug: <?= h($o['slug']) ?></div>
              <div class="meta-line">atualizado em: <?= h((string) $o['atualizado_em']) ?></div>
            </td>
            <td>R$ <?= number_format((float) $o['preco'], 2, ',', '.') ?></td>
            <td><?= h($o['loja']) ?><br><span class="meta-line"><?= h($o['categoria']) ?></span></td>
            <td>
              <span class="status <?= ((int) $o['ativo'] === 1) ? 'ok' : 'off' ?>"><?= ((int) $o['ativo'] === 1) ? 'Ativa' : 'Inativa' ?></span>
              <span class="status <?= ((int) $o['destaque'] === 1) ? 'ok' : 'off' ?>"><?= ((int) $o['destaque'] === 1) ? 'Destaque' : 'Normal' ?></span>
              <?php if ($isMeli): ?>
                <span class="status <?= $isAffiliateOk ? 'ok' : 'warn' ?>"><?= $isAffiliateOk ? 'Link afiliado OK' : 'Revisar link ML' ?></span>
              <?php endif; ?>
            </td>
            <td>
              <div class="url-box"><?= h($o['url_afiliado']) ?></div>
            </td>
            <td class="actions">
              <a class="btn-link" href="/admin/oferta_editar.php?id=<?= (int) $o['id'] ?>">Editar</a>
              <a class="btn-link primary" href="<?= h($o['url_afiliado']) ?>" target="_blank" rel="noopener sponsored nofollow">Testar link</a>
              <form method="post">
                <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
                <input type="hidden" name="id" value="<?= (int) $o['id'] ?>">
                <input type="hidden" name="acao" value="toggle_ativo">
                <button class="badge" type="submit"><?= ((int) $o['ativo'] === 1) ? 'Desativar' : 'Ativar' ?></button>
              </form>
              <form method="post">
                <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
                <input type="hidden" name="id" value="<?= (int) $o['id'] ?>">
                <input type="hidden" name="acao" value="toggle_destaque">
                <button class="badge" type="submit"><?= ((int) $o['destaque'] === 1) ? 'Remover destaque' : 'Destacar' ?></button>
              </form>
            </td>
          </tr>
        <?php endforeach; ?>
      </tbody>
    </table>
  </section>
</main>
</body>
</html>
