<?php
require_once __DIR__ . '/_init.php';
admin_require_login();

$pdo = db();
$id = (int) ($_GET['id'] ?? 0);
$erro = '';

$oferta = [
  'id' => 0,
  'titulo' => '',
  'slug' => '',
  'descricao' => '',
  'preco' => '',
  'preco_antigo' => '',
  'loja' => '',
  'url_afiliado' => '',
  'cupom' => '',
  'imagem_url' => '',
  'categoria' => 'geral',
  'tags' => '',
  'destaque' => 0,
  'ativo' => 1,
  'expira_em' => '',
];

if ($id > 0) {
  $stmt = $pdo->prepare('SELECT * FROM ofertas WHERE id=? LIMIT 1');
  $stmt->execute([$id]);
  $row = $stmt->fetch();
  if (!$row) {
    http_response_code(404);
    exit('Oferta não encontrada');
  }
  $oferta = $row;
  $oferta['expira_em'] = $row['expira_em'] ? str_replace(' ', 'T', substr($row['expira_em'], 0, 16)) : '';
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
  admin_csrf_check_or_die();

  $idPost = (int) ($_POST['id'] ?? 0);
  $titulo = trim((string) ($_POST['titulo'] ?? ''));
  $slugInput = trim((string) ($_POST['slug'] ?? ''));
  $descricao = trim((string) ($_POST['descricao'] ?? ''));
  $precoRaw = trim((string) ($_POST['preco'] ?? ''));
  $precoAntigoRaw = trim((string) ($_POST['preco_antigo'] ?? ''));
  $loja = strtolower(substr(trim((string) ($_POST['loja'] ?? '')), 0, 40));
  $urlAfiliado = trim((string) ($_POST['url_afiliado'] ?? ''));
  $cupom = substr(trim((string) ($_POST['cupom'] ?? '')), 0, 60);
  $imagemUrl = trim((string) ($_POST['imagem_url'] ?? ''));
  $categoria = substr(trim((string) ($_POST['categoria'] ?? 'geral')), 0, 80);
  $tags = substr(trim((string) ($_POST['tags'] ?? '')), 0, 255);
  $destaque = isset($_POST['destaque']) ? 1 : 0;
  $ativo = isset($_POST['ativo']) ? 1 : 0;
  $expiraRaw = trim((string) ($_POST['expira_em'] ?? ''));

  if ($titulo === '' || $urlAfiliado === '' || $precoRaw === '') {
    $erro = 'Título, preço e link afiliado são obrigatórios.';
  } else {
    $slug = admin_unique_slug($pdo, admin_normalize_slug($slugInput, $titulo), $idPost);
    $preco = admin_parse_decimal($precoRaw);
    $precoAntigo = ($precoAntigoRaw !== '') ? admin_parse_decimal($precoAntigoRaw) : null;
    $cupom = ($cupom !== '') ? $cupom : null;
    $imagemUrl = ($imagemUrl !== '') ? $imagemUrl : null;
    $tags = ($tags !== '') ? $tags : null;
    $categoria = ($categoria !== '') ? $categoria : 'geral';
    $expiraEm = ($expiraRaw !== '') ? str_replace('T', ' ', $expiraRaw) . ':00' : null;

    if ($idPost > 0) {
      $sql = 'UPDATE ofertas
              SET slug=?, titulo=?, descricao=?, preco=?, preco_antigo=?, loja=?, url_afiliado=?, cupom=?, imagem_url=?, categoria=?, tags=?, destaque=?, ativo=?, expira_em=?
              WHERE id=?';
      $pdo->prepare($sql)->execute([
        $slug, $titulo, $descricao, $preco, $precoAntigo, $loja, $urlAfiliado, $cupom, $imagemUrl, $categoria, $tags, $destaque, $ativo, $expiraEm, $idPost,
      ]);
    } else {
      $sql = 'INSERT INTO ofertas
              (slug, titulo, descricao, preco, preco_antigo, loja, url_afiliado, cupom, imagem_url, categoria, tags, destaque, ativo, expira_em)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)';
      $pdo->prepare($sql)->execute([
        $slug, $titulo, $descricao, $preco, $precoAntigo, $loja, $urlAfiliado, $cupom, $imagemUrl, $categoria, $tags, $destaque, $ativo, $expiraEm,
      ]);
      $idPost = (int) $pdo->lastInsertId();
    }

    header('Location: /admin/oferta_editar.php?id=' . $idPost . '&ok=1');
    exit;
  }

  $oferta = [
    'id' => $idPost,
    'titulo' => $titulo,
    'slug' => $slugInput,
    'descricao' => $descricao,
    'preco' => $precoRaw,
    'preco_antigo' => $precoAntigoRaw,
    'loja' => $loja,
    'url_afiliado' => $urlAfiliado,
    'cupom' => $cupom ?? '',
    'imagem_url' => $imagemUrl ?? '',
    'categoria' => $categoria,
    'tags' => $tags ?? '',
    'destaque' => $destaque,
    'ativo' => $ativo,
    'expira_em' => $expiraRaw,
  ];
}
?>
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Admin - <?= $id > 0 ? 'Editar oferta' : 'Nova oferta' ?></title>
  <link rel="stylesheet" href="/assets/css/style.css">
  <style>
    .box { background: #fff; border: 1px solid #e5e7eb; border-radius: 14px; padding: 16px; }
    .fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
    .field label { display: block; font-size: 13px; color: #6b7280; margin-bottom: 6px; }
    .field input, .field textarea { width: 100%; border: 1px solid #d1d5db; border-radius: 10px; padding: 9px; font: inherit; }
    .field.full { grid-column: 1 / -1; }
    .ok { margin: 12px 0; padding: 10px; border: 1px solid #bbf7d0; background: #dcfce7; color: #166534; border-radius: 10px; }
    .err { margin: 12px 0; padding: 10px; border: 1px solid #fecaca; background: #fee2e2; color: #991b1b; border-radius: 10px; }
    @media (max-width: 840px) { .fields { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
<header>
  <div class="container" style="display:flex; align-items:center; justify-content:space-between; gap:10px;">
    <div style="font-weight:700;"><?= $id > 0 ? 'Editar oferta' : 'Nova oferta' ?></div>
    <div style="display:flex; gap:8px;">
      <a class="badge" href="/admin/ofertas.php">Voltar</a>
      <a class="badge" href="/admin/logout.php">Sair</a>
    </div>
  </div>
</header>

<main class="container">
  <section class="box">
    <?php if (isset($_GET['ok']) && $_GET['ok'] === '1'): ?>
      <div class="ok">Oferta salva com sucesso.</div>
    <?php endif; ?>
    <?php if ($erro): ?>
      <div class="err"><?= h($erro) ?></div>
    <?php endif; ?>

    <form method="post">
      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
      <input type="hidden" name="id" value="<?= (int) ($oferta['id'] ?? 0) ?>">
      <div class="fields">
        <div class="field full">
          <label for="titulo">Título*</label>
          <input id="titulo" name="titulo" value="<?= h($oferta['titulo']) ?>" required>
        </div>
        <div class="field full">
          <label for="slug">Slug (deixe vazio para gerar automaticamente)</label>
          <input id="slug" name="slug" value="<?= h($oferta['slug']) ?>">
        </div>
        <div class="field">
          <label for="preco">Preço*</label>
          <input id="preco" name="preco" value="<?= h($oferta['preco']) ?>" required>
        </div>
        <div class="field">
          <label for="preco_antigo">Preço antigo</label>
          <input id="preco_antigo" name="preco_antigo" value="<?= h($oferta['preco_antigo']) ?>">
        </div>
        <div class="field">
          <label for="loja">Loja</label>
          <input id="loja" name="loja" value="<?= h($oferta['loja']) ?>">
        </div>
        <div class="field">
          <label for="categoria">Categoria</label>
          <input id="categoria" name="categoria" value="<?= h($oferta['categoria']) ?>">
        </div>
        <div class="field full">
          <label for="url_afiliado">URL afiliado*</label>
          <input id="url_afiliado" type="url" name="url_afiliado" value="<?= h($oferta['url_afiliado']) ?>" required>
        </div>
        <div class="field">
          <label for="cupom">Cupom</label>
          <input id="cupom" name="cupom" value="<?= h($oferta['cupom']) ?>">
        </div>
        <div class="field">
          <label for="imagem_url">Imagem URL</label>
          <input id="imagem_url" type="url" name="imagem_url" value="<?= h($oferta['imagem_url']) ?>">
        </div>
        <div class="field full">
          <label for="tags">Tags (separadas por vírgula)</label>
          <input id="tags" name="tags" value="<?= h($oferta['tags']) ?>">
        </div>
        <div class="field">
          <label for="expira_em">Expira em</label>
          <input id="expira_em" type="datetime-local" name="expira_em" value="<?= h($oferta['expira_em']) ?>">
        </div>
        <div class="field full">
          <label for="descricao">Descrição</label>
          <textarea id="descricao" name="descricao" rows="4"><?= h($oferta['descricao']) ?></textarea>
        </div>
      </div>
      <div style="margin-top:12px; display:flex; gap:18px; flex-wrap:wrap;">
        <label><input type="checkbox" name="ativo" value="1" <?= ((int) $oferta['ativo'] === 1) ? 'checked' : '' ?>> Ativa</label>
        <label><input type="checkbox" name="destaque" value="1" <?= ((int) $oferta['destaque'] === 1) ? 'checked' : '' ?>> Destaque</label>
      </div>
      <div style="margin-top:14px;">
        <button class="btn" type="submit">Salvar</button>
        <?php if (!empty($oferta['url_afiliado'])): ?>
          <a class="badge" href="<?= h($oferta['url_afiliado']) ?>" target="_blank" rel="noopener sponsored nofollow" style="margin-left:8px;">Testar link afiliado</a>
        <?php endif; ?>
      </div>
    </form>
  </section>
</main>
</body>
</html>
