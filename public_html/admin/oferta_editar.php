<?php
require_once __DIR__ . '/_init.php';
admin_require_login();

$flash = admin_flash_get();

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
    exit('Oferta nao encontrada');
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
    $erro = 'Titulo, preco e link afiliado sao obrigatorios.';
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

    if ($destaque === 1) {
      admin_enforce_featured_limit($pdo, $loja, $idPost);
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
  <link rel="stylesheet" href="/assets/css/admin.css">
</head>
<body class="admin-page">
<header>
  <div class="container admin-header">
    <div class="admin-brand">
      <div class="admin-brand-mark">
        <img src="/assets/img/logo-zp.png" alt="Zero Preco">
      </div>
      <div class="admin-brand-copy">
        <strong><?= $id > 0 ? 'Editar oferta' : 'Nova oferta' ?></strong>
        <span>Formulario amplo para revisar links, copy, imagem e expiracao.</span>
      </div>
    </div>
    <div class="admin-header-actions">
      <a class="badge" href="/admin/ofertas.php">Voltar</a>
      <a class="badge" href="/admin/logout.php">Sair</a>
    </div>
  </div>
</header>

<main class="container admin-shell">
  <section class="admin-hero">
    <div class="admin-hero-head">
      <div class="admin-hero-copy">
        <span class="admin-kicker">Editor visual</span>
        <h1><?= $id > 0 ? 'Ajuste a oferta com mais contexto antes de publicar.' : 'Cadastre um novo produto no mesmo estilo do dashboard.' ?></h1>
        <p>Titulo, imagem, cupom, preco e destino afiliado ficam organizados em campos mais compridos. A logica de salvamento continua a mesma, sem alterar o fluxo atual do site.</p>
      </div>
      <div class="admin-hero-actions">
        <?php if (!empty($oferta['url_afiliado'])): ?>
          <a class="btn-link primary" href="<?= h($oferta['url_afiliado']) ?>" target="_blank" rel="noopener sponsored nofollow">Testar link afiliado</a>
        <?php endif; ?>
        <?php if (!empty($oferta['slug'])): ?>
          <a class="badge" href="/oferta.php?slug=<?= urlencode((string) $oferta['slug']) ?>" target="_blank" rel="noopener">Ver pagina</a>
        <?php endif; ?>
      </div>
    </div>
  </section>

  <div class="admin-form-shell">
    <section class="admin-form">
    <?php if ($flash): ?>
      <div class="admin-alert <?= h((string) ($flash['type'] ?? '')) ?>"><?= h((string) ($flash['message'] ?? '')) ?></div>
    <?php endif; ?>
    <?php if (isset($_GET['ok']) && $_GET['ok'] === '1'): ?>
      <div class="admin-alert success">Oferta salva com sucesso.</div>
    <?php endif; ?>
    <?php if ($erro): ?>
      <div class="admin-alert error"><?= h($erro) ?></div>
    <?php endif; ?>

    <div>
      <h2 class="admin-form-title">Dados principais</h2>
      <p class="admin-form-copy">Preencha os campos essenciais do produto. O slug pode ficar vazio para geracao automatica.</p>
    </div>

    <form method="post">
      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
      <input type="hidden" name="id" value="<?= (int) ($oferta['id'] ?? 0) ?>">
      <div class="admin-field-grid">
        <div class="admin-field is-full">
          <label for="titulo">Titulo*</label>
          <input id="titulo" name="titulo" value="<?= h($oferta['titulo']) ?>" required>
        </div>
        <div class="admin-field is-full">
          <label for="slug">Slug (deixe vazio para gerar automaticamente)</label>
          <input id="slug" name="slug" value="<?= h($oferta['slug']) ?>">
        </div>
        <div class="admin-field">
          <label for="preco">Preco*</label>
          <input id="preco" name="preco" value="<?= h($oferta['preco']) ?>" required>
        </div>
        <div class="admin-field">
          <label for="preco_antigo">Preco antigo</label>
          <input id="preco_antigo" name="preco_antigo" value="<?= h($oferta['preco_antigo']) ?>">
        </div>
        <div class="admin-field">
          <label for="loja">Loja</label>
          <input id="loja" name="loja" value="<?= h($oferta['loja']) ?>">
        </div>
        <div class="admin-field">
          <label for="categoria">Categoria</label>
          <input id="categoria" name="categoria" value="<?= h($oferta['categoria']) ?>">
        </div>
        <div class="admin-field is-full">
          <label for="url_afiliado">URL afiliado*</label>
          <input id="url_afiliado" type="url" name="url_afiliado" value="<?= h($oferta['url_afiliado']) ?>" required>
        </div>
        <div class="admin-field">
          <label for="cupom">Cupom</label>
          <input id="cupom" name="cupom" value="<?= h($oferta['cupom']) ?>">
        </div>
        <div class="admin-field">
          <label for="imagem_url">Imagem URL</label>
          <input id="imagem_url" type="url" name="imagem_url" value="<?= h($oferta['imagem_url']) ?>">
        </div>
        <div class="admin-field is-full">
          <label for="tags">Tags (separadas por virgula)</label>
          <input id="tags" name="tags" value="<?= h($oferta['tags']) ?>">
        </div>
        <div class="admin-field">
          <label for="expira_em">Expira em</label>
          <input id="expira_em" type="datetime-local" name="expira_em" value="<?= h($oferta['expira_em']) ?>">
        </div>
        <div class="admin-field is-full">
          <label for="descricao">Descricao</label>
          <textarea id="descricao" name="descricao" rows="4"><?= h($oferta['descricao']) ?></textarea>
        </div>
      </div>
      <div class="admin-check-row">
        <label class="admin-check-chip"><input type="checkbox" name="ativo" value="1" <?= ((int) $oferta['ativo'] === 1) ? 'checked' : '' ?>> Ativa</label>
        <label class="admin-check-chip"><input type="checkbox" name="destaque" value="1" <?= ((int) $oferta['destaque'] === 1) ? 'checked' : '' ?>> Destaque</label>
      </div>
      <div class="admin-form-actions">
        <button class="btn" type="submit">Salvar</button>
        <?php if (!empty($oferta['url_afiliado'])): ?>
          <a class="badge" href="<?= h($oferta['url_afiliado']) ?>" target="_blank" rel="noopener sponsored nofollow">Testar link afiliado</a>
        <?php endif; ?>
        <?php if (!empty($oferta['slug'])): ?>
          <a class="badge" href="/oferta.php?slug=<?= urlencode((string) $oferta['slug']) ?>&go=1" target="_blank" rel="noopener sponsored nofollow">Abrir pelo site</a>
        <?php endif; ?>
      </div>
    </form>
    </section>

    <aside class="admin-preview">
      <?php if (!empty($oferta['imagem_url'])): ?>
        <img class="admin-preview-thumb" src="<?= h($oferta['imagem_url']) ?>" alt="<?= h($oferta['titulo'] ?: 'Preview da oferta') ?>">
      <?php else: ?>
        <div class="admin-preview-thumb is-empty"><?= h(strtoupper(substr((string) ($oferta['loja'] ?: 'oferta'), 0, 2))) ?></div>
      <?php endif; ?>

      <div>
        <span class="admin-kicker">Preview rapido</span>
        <h3 class="admin-card-title" style="margin-top: 10px;"><?= h($oferta['titulo'] ?: 'Titulo da oferta') ?></h3>
        <div class="admin-card-subtitle"><?= h($oferta['loja'] ?: 'loja') ?> · <?= h($oferta['categoria'] ?: 'categoria') ?></div>
      </div>

      <div class="admin-preview-price">
        <span class="admin-price"><?= $oferta['preco'] !== '' ? 'R$ ' . h((string) $oferta['preco']) : 'R$ --' ?></span>
        <?php if ($oferta['preco_antigo'] !== ''): ?>
          <span class="admin-price-old">R$ <?= h((string) $oferta['preco_antigo']) ?></span>
        <?php endif; ?>
      </div>

      <div class="admin-meta-row">
        <?php if (!empty($oferta['cupom'])): ?>
          <span class="admin-meta-chip">cupom <?= h($oferta['cupom']) ?></span>
        <?php endif; ?>
        <span class="admin-status <?= ((int) $oferta['ativo'] === 1) ? 'ok' : 'off' ?>"><?= ((int) $oferta['ativo'] === 1) ? 'Ativa' : 'Inativa' ?></span>
        <span class="admin-status <?= ((int) $oferta['destaque'] === 1) ? 'ok' : 'off' ?>"><?= ((int) $oferta['destaque'] === 1) ? 'Destaque' : 'Normal' ?></span>
      </div>

      <div class="admin-side-card">
        <strong>Slug final</strong>
        <div class="admin-url-box"><?= h($oferta['slug'] ?: 'sera gerado automaticamente') ?></div>
      </div>

      <div class="admin-side-card">
        <strong>Link afiliado</strong>
        <div class="admin-url-box"><?= h($oferta['url_afiliado'] ?: 'preencha a URL afiliada para validar o destino') ?></div>
      </div>

      <div class="admin-side-card">
        <strong>Descricao</strong>
        <div class="admin-description"><?= nl2br(h($oferta['descricao'] ?: 'Use este campo para destacar pontos fortes, prazo, voltagem, tamanho ou restricoes do produto.')) ?></div>
      </div>

      <div class="admin-preview-actions">
        <?php if (!empty($oferta['slug'])): ?>
          <a class="btn-link" href="/oferta.php?slug=<?= urlencode((string) $oferta['slug']) ?>" target="_blank" rel="noopener">Ver pagina</a>
        <?php endif; ?>
        <?php if (!empty($oferta['url_afiliado'])): ?>
          <a class="btn-link primary" href="<?= h($oferta['url_afiliado']) ?>" target="_blank" rel="noopener sponsored nofollow">Loja afiliada</a>
        <?php endif; ?>
      </div>
    </aside>
  </div>
</main>
</body>
</html>
