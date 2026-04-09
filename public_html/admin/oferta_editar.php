<?php
require_once __DIR__ . '/_init.php';
admin_require_login();

$flash = admin_flash_get();
$pdo = db();
$currentAdmin = admin_current_user();
$id = (int) ($_GET['id'] ?? 0);
$erro = '';

function admin_request_public_base_url() {
  $https = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off')
    || ((string) ($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https');
  $scheme = $https ? 'https' : 'http';
  $host = trim((string) ($_SERVER['HTTP_HOST'] ?? 'zeropreco.com.br'));
  return $scheme . '://' . $host;
}

function admin_offer_video_upload_dir() {
  $dir = dirname(__DIR__) . '/uploads/ofertas_videos';
  if (!is_dir($dir)) {
    @mkdir($dir, 0775, true);
  }
  return $dir;
}

function admin_offer_image_upload_dir() {
  $dir = dirname(__DIR__) . '/uploads/ofertas_imagens';
  if (!is_dir($dir)) {
    @mkdir($dir, 0775, true);
  }
  return $dir;
}

function admin_offer_video_public_url($filename) {
  return admin_request_public_base_url() . '/uploads/ofertas_videos/' . rawurlencode((string) $filename);
}

function admin_offer_image_public_url($filename) {
  return admin_request_public_base_url() . '/uploads/ofertas_imagens/' . rawurlencode((string) $filename);
}

function admin_offer_video_save_upload($file) {
  if (!is_array($file) || empty($file['tmp_name']) || !is_uploaded_file((string) $file['tmp_name'])) {
    return '';
  }

  if (!empty($file['error']) && (int) $file['error'] !== UPLOAD_ERR_OK) {
    throw new RuntimeException('Falha no upload do video.');
  }

  $originalName = (string) ($file['name'] ?? 'video.mp4');
  $extension = strtolower((string) pathinfo($originalName, PATHINFO_EXTENSION));
  $allowedExtensions = ['mp4', 'webm', 'mov', 'm4v'];
  if (!in_array($extension, $allowedExtensions, true)) {
    throw new RuntimeException('Use um arquivo MP4, WEBM, MOV ou M4V.');
  }

  $size = (int) ($file['size'] ?? 0);
  if ($size <= 0 || $size > (80 * 1024 * 1024)) {
    throw new RuntimeException('O video precisa ter ate 80 MB.');
  }

  $filename = 'oferta-video-' . date('Ymd-His') . '-' . bin2hex(random_bytes(4)) . '.' . $extension;
  $targetPath = admin_offer_video_upload_dir() . '/' . $filename;
  if (!move_uploaded_file((string) $file['tmp_name'], $targetPath)) {
    throw new RuntimeException('Nao consegui salvar o video enviado.');
  }

  return admin_offer_video_public_url($filename);
}

function admin_offer_gallery_text_to_urls($value) {
  $lines = preg_split('~[\r\n,;]+~', (string) $value);
  $urls = [];
  foreach ($lines as $line) {
    $url = trim((string) $line);
    if ($url === '' || !preg_match('~^https?://~i', $url)) {
      continue;
    }
    if (in_array($url, $urls, true)) {
      continue;
    }
    $urls[] = $url;
  }
  return $urls;
}

function admin_offer_gallery_urls_to_text($urls) {
  return implode("\n", admin_shopee_video_decode_url_list($urls));
}

function admin_offer_image_save_uploads($files) {
  $saved = [];
  if (!is_array($files) || !isset($files['tmp_name'])) {
    return $saved;
  }

  $tmpNames = is_array($files['tmp_name']) ? $files['tmp_name'] : [$files['tmp_name']];
  $names = is_array($files['name'] ?? null) ? $files['name'] : [($files['name'] ?? 'imagem.jpg')];
  $errors = is_array($files['error'] ?? null) ? $files['error'] : [($files['error'] ?? UPLOAD_ERR_NO_FILE)];
  $sizes = is_array($files['size'] ?? null) ? $files['size'] : [($files['size'] ?? 0)];

  $allowedExtensions = ['jpg', 'jpeg', 'png', 'webp', 'gif'];
  $maxSize = 12 * 1024 * 1024;

  foreach ($tmpNames as $index => $tmpName) {
    $tmpName = (string) $tmpName;
    if ($tmpName === '' || !is_uploaded_file($tmpName)) {
      continue;
    }

    $errorCode = (int) ($errors[$index] ?? UPLOAD_ERR_OK);
    if ($errorCode !== UPLOAD_ERR_OK) {
      throw new RuntimeException('Falha no upload das imagens.');
    }

    $originalName = (string) ($names[$index] ?? 'imagem.jpg');
    $extension = strtolower((string) pathinfo($originalName, PATHINFO_EXTENSION));
    if (!in_array($extension, $allowedExtensions, true)) {
      throw new RuntimeException('Use imagens JPG, JPEG, PNG, WEBP ou GIF.');
    }

    $size = (int) ($sizes[$index] ?? 0);
    if ($size <= 0 || $size > $maxSize) {
      throw new RuntimeException('Cada imagem precisa ter ate 12 MB.');
    }

    $filename = 'oferta-img-' . date('Ymd-His') . '-' . bin2hex(random_bytes(4)) . '-' . $index . '.' . $extension;
    $targetPath = admin_offer_image_upload_dir() . '/' . $filename;
    if (!move_uploaded_file($tmpName, $targetPath)) {
      throw new RuntimeException('Nao consegui salvar uma das imagens enviadas.');
    }
    $saved[] = admin_offer_image_public_url($filename);
  }

  return $saved;
}

$oferta = [
  'id' => 0,
  'titulo' => '',
  'slug' => '',
  'descricao' => '',
  'preco' => '',
  'preco_antigo' => '',
  'desconto_percentual' => '',
  'preco_pix' => '',
  'preco_outros_meios' => '',
  'parcelas_texto' => '',
  'frete_texto' => '',
  'avaliacao_nota' => '',
  'avaliacao_total' => '',
  'promocao_texto' => '',
  'loja' => '',
  'url_afiliado' => '',
  'cupom' => '',
  'imagem_url' => '',
  'imagem_urls_json' => '',
  'video_url' => '',
  'categoria' => 'geral',
  'tags' => '',
  'destaque' => 0,
  'ativo' => 1,
  'expira_em' => '',
];

if ($id > 0) {
  $stmt = $pdo->prepare('SELECT * FROM ofertas WHERE id = ? LIMIT 1');
  $stmt->execute([$id]);
  $row = $stmt->fetch();
  if (!$row) {
    http_response_code(404);
    exit('Oferta nao encontrada');
  }
  $oferta = $row;
  $oferta['expira_em'] = $row['expira_em'] ? str_replace(' ', 'T', substr((string) $row['expira_em'], 0, 16)) : '';
  $oferta['video_url'] = admin_shopee_video_offer_video_url($row);
}

$galleryUrls = admin_shopee_video_offer_gallery_urls($oferta);

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
  admin_csrf_check_or_die();

  $idPost = (int) ($_POST['id'] ?? 0);
  $titulo = trim((string) ($_POST['titulo'] ?? ''));
  $slugInput = trim((string) ($_POST['slug'] ?? ''));
  $descricao = trim((string) ($_POST['descricao'] ?? ''));
  $precoRaw = trim((string) ($_POST['preco'] ?? ''));
  $precoAntigoRaw = trim((string) ($_POST['preco_antigo'] ?? ''));
  $descontoPercentualRaw = trim((string) ($_POST['desconto_percentual'] ?? ''));
  $precoPixRaw = trim((string) ($_POST['preco_pix'] ?? ''));
  $precoOutrosMeiosRaw = trim((string) ($_POST['preco_outros_meios'] ?? ''));
  $parcelasTexto = substr(trim((string) ($_POST['parcelas_texto'] ?? '')), 0, 120);
  $freteTexto = substr(trim((string) ($_POST['frete_texto'] ?? '')), 0, 160);
  $avaliacaoNotaRaw = trim((string) ($_POST['avaliacao_nota'] ?? ''));
  $avaliacaoTotalRaw = trim((string) ($_POST['avaliacao_total'] ?? ''));
  $promocaoTexto = substr(trim((string) ($_POST['promocao_texto'] ?? '')), 0, 255);
  $loja = strtolower(substr(trim((string) ($_POST['loja'] ?? '')), 0, 40));
  $urlAfiliado = trim((string) ($_POST['url_afiliado'] ?? ''));
  $cupom = substr(trim((string) ($_POST['cupom'] ?? '')), 0, 60);
  $imagemUrl = trim((string) ($_POST['imagem_url'] ?? ''));
  $imagemUrlsTexto = trim((string) ($_POST['imagem_urls_texto'] ?? ''));
  $galleryUrls = admin_offer_gallery_text_to_urls($imagemUrlsTexto);
  $videoUrl = trim((string) ($_POST['video_url'] ?? ''));
  $categoria = substr(trim((string) ($_POST['categoria'] ?? 'geral')), 0, 80);
  $tagsInput = substr(trim((string) ($_POST['tags'] ?? '')), 0, 255);
  $destaque = isset($_POST['destaque']) ? 1 : 0;
  $ativo = isset($_POST['ativo']) ? 1 : 0;
  $expiraRaw = trim((string) ($_POST['expira_em'] ?? ''));

  if ($titulo === '' || $urlAfiliado === '' || $precoRaw === '') {
    $erro = 'Titulo, preco e link afiliado sao obrigatorios.';
  }

  if ($erro === '' && $videoUrl !== '' && !preg_match('~^https?://~i', $videoUrl)) {
    $erro = 'A URL do video precisa comecar com http:// ou https://.';
  }

  if ($erro === '') {
    try {
      $uploadedImageUrls = admin_offer_image_save_uploads($_FILES['imagem_arquivos'] ?? null);
      foreach ($uploadedImageUrls as $uploadedImageUrl) {
        if (!in_array($uploadedImageUrl, $galleryUrls, true)) {
          $galleryUrls[] = $uploadedImageUrl;
        }
      }
      if ($imagemUrl !== '' && !in_array($imagemUrl, $galleryUrls, true)) {
        array_unshift($galleryUrls, $imagemUrl);
      }
      if ($imagemUrl === '' && !empty($galleryUrls)) {
        $imagemUrl = (string) $galleryUrls[0];
      }
      $uploadedVideoUrl = admin_offer_video_save_upload($_FILES['video_arquivo'] ?? null);
      if ($uploadedVideoUrl !== '') {
        $videoUrl = $uploadedVideoUrl;
      }
    } catch (Throwable $uploadError) {
      $erro = $uploadError->getMessage();
    }
  }

  if ($erro === '') {
    $slug = admin_unique_slug($pdo, admin_normalize_slug($slugInput, $titulo), $idPost);
    $preco = admin_parse_decimal($precoRaw);
    if (admin_offer_price_is_zero_or_less($preco)) {
      admin_flash_set('success', 'Oferta ignorada porque o preco esta zerado.');
      $redirect = '/admin/oferta_editar.php';
      if ($idPost > 0) {
        $redirect .= '?id=' . $idPost;
      }
      header('Location: ' . $redirect);
      exit;
    }

    $precoAntigo = ($precoAntigoRaw !== '') ? admin_parse_decimal($precoAntigoRaw) : null;
    $descontoPercentual = ($descontoPercentualRaw !== '') ? (int) round(admin_parse_decimal($descontoPercentualRaw)) : null;
    $precoPix = ($precoPixRaw !== '') ? admin_parse_decimal($precoPixRaw) : null;
    $precoOutrosMeios = ($precoOutrosMeiosRaw !== '') ? admin_parse_decimal($precoOutrosMeiosRaw) : null;
    $parcelasTexto = ($parcelasTexto !== '') ? $parcelasTexto : null;
    $freteTexto = ($freteTexto !== '') ? $freteTexto : null;
    $avaliacaoNota = ($avaliacaoNotaRaw !== '') ? admin_parse_decimal($avaliacaoNotaRaw) : null;
    $avaliacaoTotal = ($avaliacaoTotalRaw !== '') ? (int) round(admin_parse_decimal($avaliacaoTotalRaw)) : null;
    $promocaoTexto = ($promocaoTexto !== '') ? $promocaoTexto : null;
    $cupom = ($cupom !== '') ? $cupom : null;
    $imagemUrl = ($imagemUrl !== '') ? $imagemUrl : null;
    $imagemUrlsJson = !empty($galleryUrls) ? json_encode(array_values($galleryUrls), JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) : null;
    $tagsProcessed = tag_url_upsert($tagsInput, 'offer_video_url:', $videoUrl);
    if (strlen($tagsProcessed) > 255) {
      $erro = 'As tags ficaram grandes demais. Remova algumas tags antes de salvar o video.';
    }
    $tags = ($tagsProcessed !== '') ? $tagsProcessed : null;
    $categoria = ($categoria !== '') ? $categoria : 'geral';
    $expiraEm = ($expiraRaw !== '') ? str_replace('T', ' ', $expiraRaw) . ':00' : null;

    if ($erro === '') {
      if ($idPost > 0) {
        $sql = 'UPDATE ofertas
                SET slug=?, titulo=?, descricao=?, preco=?, preco_antigo=?, desconto_percentual=?, preco_pix=?, preco_outros_meios=?, parcelas_texto=?, frete_texto=?, avaliacao_nota=?, avaliacao_total=?, promocao_texto=?, loja=?, url_afiliado=?, cupom=?, imagem_url=?, imagem_urls_json=?, categoria=?, tags=?, destaque=?, ativo=?, expira_em=?
                WHERE id=?';
        $pdo->prepare($sql)->execute([
          $slug, $titulo, $descricao, $preco, $precoAntigo, $descontoPercentual, $precoPix, $precoOutrosMeios, $parcelasTexto, $freteTexto, $avaliacaoNota, $avaliacaoTotal, $promocaoTexto, $loja, $urlAfiliado, $cupom, $imagemUrl, $imagemUrlsJson, $categoria, $tags, $destaque, $ativo, $expiraEm, $idPost,
        ]);
      } else {
        $creatorId = $currentAdmin ? (int) ($currentAdmin['id'] ?? 0) : null;
        $creatorLogin = $currentAdmin ? admin_current_login_name() : null;
        $sql = 'INSERT INTO ofertas
                (slug, titulo, descricao, preco, preco_antigo, desconto_percentual, preco_pix, preco_outros_meios, parcelas_texto, frete_texto, avaliacao_nota, avaliacao_total, promocao_texto, loja, url_afiliado, cupom, imagem_url, imagem_urls_json, categoria, tags, destaque, ativo, criado_por_admin_id, criado_por_login, expira_em)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)';
        $pdo->prepare($sql)->execute([
          $slug, $titulo, $descricao, $preco, $precoAntigo, $descontoPercentual, $precoPix, $precoOutrosMeios, $parcelasTexto, $freteTexto, $avaliacaoNota, $avaliacaoTotal, $promocaoTexto, $loja, $urlAfiliado, $cupom, $imagemUrl, $imagemUrlsJson, $categoria, $tags, $destaque, $ativo, $creatorId, $creatorLogin, $expiraEm,
        ]);
        $idPost = (int) $pdo->lastInsertId();
      }

      if ($destaque === 1) {
        admin_enforce_featured_limit($pdo, $loja, $idPost);
      }

      header('Location: /admin/oferta_editar.php?id=' . $idPost . '&ok=1');
      exit;
    }
  }

  $oferta = [
    'id' => $idPost,
    'titulo' => $titulo,
    'slug' => $slugInput,
    'descricao' => $descricao,
    'preco' => $precoRaw,
    'preco_antigo' => $precoAntigoRaw,
    'desconto_percentual' => $descontoPercentualRaw,
    'preco_pix' => $precoPixRaw,
    'preco_outros_meios' => $precoOutrosMeiosRaw,
    'parcelas_texto' => $parcelasTexto ?? '',
    'frete_texto' => $freteTexto ?? '',
    'avaliacao_nota' => $avaliacaoNotaRaw,
    'avaliacao_total' => $avaliacaoTotalRaw,
    'promocao_texto' => $promocaoTexto ?? '',
    'loja' => $loja,
    'url_afiliado' => $urlAfiliado,
    'cupom' => $cupom ?? '',
    'imagem_url' => $imagemUrl ?? '',
    'imagem_urls_json' => !empty($galleryUrls) ? json_encode(array_values($galleryUrls), JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) : '',
    'video_url' => $videoUrl,
    'categoria' => $categoria,
    'tags' => $tagsInput ?? '',
    'destaque' => $destaque,
    'ativo' => $ativo,
    'expira_em' => $expiraRaw,
  ];
}

$pageTitle = ((int) ($oferta['id'] ?? 0) > 0) ? 'Editar oferta' : 'Nova oferta';
$videoPreviewUrl = admin_shopee_video_offer_video_url($oferta);
$imageGalleryUrls = admin_shopee_video_offer_gallery_urls($oferta);
$imageGalleryText = admin_offer_gallery_urls_to_text($imageGalleryUrls);
?>
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Admin - <?= h($pageTitle) ?></title>
  <link rel="icon" type="image/png" href="/assets/img/logo-zp.png">
  <link rel="stylesheet" href="/assets/css/style.css">
  <link rel="stylesheet" href="/assets/css/admin.css">
</head>
<body class="admin-page">
<header>
  <div class="container admin-header">
    <div class="admin-brand">
      <a class="admin-brand-link" href="/admin/ofertas.php">
        <div class="admin-brand-mark">
          <img src="/assets/img/logo-zp.png" alt="Zero Preco">
        </div>
      </a>
      <div class="admin-brand-copy">
        <strong>Zero Preco Admin</strong>
        <span>Controle ofertas, links e publicacoes em um so lugar.</span>
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
        <h1><?= h($pageTitle) ?></h1>
      </div>
      <div class="admin-hero-actions">
        <?php if (!empty($oferta['url_afiliado'])): ?>
          <a class="btn-link primary" href="<?= h((string) $oferta['url_afiliado']) ?>" target="_blank" rel="noopener sponsored nofollow">Testar link afiliado</a>
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
        <?php if (!empty($oferta['criado_por_login'])): ?>
          <div class="admin-help" style="margin-top:10px;">Cadastrado por <?= h((string) $oferta['criado_por_login']) ?></div>
        <?php elseif ($currentAdmin): ?>
          <div class="admin-help" style="margin-top:10px;">Novo cadastro sera salvo como <?= h(admin_current_login_name()) ?></div>
        <?php endif; ?>
      </div>

      <form method="post" enctype="multipart/form-data">
        <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
        <input type="hidden" name="id" value="<?= (int) ($oferta['id'] ?? 0) ?>">
        <div class="admin-field-grid">
          <div class="admin-field is-full">
            <label for="titulo">Titulo*</label>
            <input id="titulo" name="titulo" value="<?= h((string) $oferta['titulo']) ?>" required>
          </div>
          <div class="admin-field is-full">
            <label for="slug">Slug (deixe vazio para gerar automaticamente)</label>
            <input id="slug" name="slug" value="<?= h((string) $oferta['slug']) ?>">
          </div>
          <div class="admin-field">
            <label for="preco">Preco*</label>
            <input id="preco" name="preco" value="<?= h((string) $oferta['preco']) ?>" required>
          </div>
          <div class="admin-field">
            <label for="preco_antigo">Preco antigo</label>
            <input id="preco_antigo" name="preco_antigo" value="<?= h((string) $oferta['preco_antigo']) ?>">
          </div>
          <div class="admin-field">
            <label for="desconto_percentual">Desconto (%)</label>
            <input id="desconto_percentual" name="desconto_percentual" value="<?= h((string) $oferta['desconto_percentual']) ?>">
          </div>
          <div class="admin-field">
            <label for="preco_pix">Preco no Pix</label>
            <input id="preco_pix" name="preco_pix" value="<?= h((string) $oferta['preco_pix']) ?>">
          </div>
          <div class="admin-field">
            <label for="preco_outros_meios">Preco em outros meios</label>
            <input id="preco_outros_meios" name="preco_outros_meios" value="<?= h((string) $oferta['preco_outros_meios']) ?>">
          </div>
          <div class="admin-field">
            <label for="loja">Loja</label>
            <input id="loja" name="loja" value="<?= h((string) $oferta['loja']) ?>">
          </div>
          <div class="admin-field">
            <label for="categoria">Categoria</label>
            <input id="categoria" name="categoria" value="<?= h((string) $oferta['categoria']) ?>">
          </div>
          <div class="admin-field is-full">
            <label for="url_afiliado">URL afiliado*</label>
            <input id="url_afiliado" type="url" name="url_afiliado" value="<?= h((string) $oferta['url_afiliado']) ?>" required>
          </div>
          <div class="admin-field">
            <label for="cupom">Cupom</label>
            <input id="cupom" name="cupom" value="<?= h((string) $oferta['cupom']) ?>">
          </div>
          <div class="admin-field">
            <label for="imagem_url">Imagem URL</label>
            <input id="imagem_url" type="url" name="imagem_url" value="<?= h((string) $oferta['imagem_url']) ?>">
          </div>
          <div class="admin-field is-full">
            <label for="imagem_urls_texto">Galeria de imagens</label>
            <textarea id="imagem_urls_texto" name="imagem_urls_texto" rows="4" placeholder="Uma URL por linha ou envie arquivos abaixo."><?= h($imageGalleryText) ?></textarea>
            <div class="admin-help" style="margin-top:8px;">A primeira imagem da galeria vira a capa principal quando o campo Imagem URL estiver vazio.</div>
          </div>
          <div class="admin-field is-full">
            <label for="imagem_arquivos">Upload de imagens</label>
            <input id="imagem_arquivos" type="file" name="imagem_arquivos[]" accept="image/jpeg,image/png,image/webp,image/gif,.jpg,.jpeg,.png,.webp,.gif" multiple>
            <div class="admin-help" style="margin-top:8px;">Envie varias imagens do produto. Elas entram na galeria e ajudam o gerador de video.</div>
          </div>
          <div class="admin-field is-full">
            <label for="video_url">Video URL</label>
            <input id="video_url" type="url" name="video_url" value="<?= h((string) ($oferta['video_url'] ?? '')) ?>" placeholder="https://...mp4 ou video publico da Shopee">
          </div>
          <div class="admin-field is-full">
            <label for="video_arquivo">Upload de video</label>
            <input id="video_arquivo" type="file" name="video_arquivo" accept="video/mp4,video/webm,video/quicktime,.mp4,.webm,.mov,.m4v">
            <div class="admin-help" style="margin-top:8px;">Se enviar um arquivo, ele substitui a URL acima para esta oferta.</div>
          </div>
          <div class="admin-field is-full">
            <label for="tags">Tags (separadas por virgula)</label>
            <input id="tags" name="tags" value="<?= h((string) $oferta['tags']) ?>">
          </div>
          <div class="admin-field is-full">
            <label for="parcelas_texto">Parcelamento</label>
            <input id="parcelas_texto" name="parcelas_texto" value="<?= h((string) $oferta['parcelas_texto']) ?>" placeholder="Ex.: 10x de R$ 12,90 sem juros">
          </div>
          <div class="admin-field is-full">
            <label for="frete_texto">Frete</label>
            <input id="frete_texto" name="frete_texto" value="<?= h((string) $oferta['frete_texto']) ?>" placeholder="Ex.: Frete gratis / Chega amanha">
          </div>
          <div class="admin-field">
            <label for="avaliacao_nota">Avaliacao</label>
            <input id="avaliacao_nota" name="avaliacao_nota" value="<?= h((string) $oferta['avaliacao_nota']) ?>">
          </div>
          <div class="admin-field">
            <label for="avaliacao_total">Total de avaliacoes</label>
            <input id="avaliacao_total" name="avaliacao_total" value="<?= h((string) $oferta['avaliacao_total']) ?>">
          </div>
          <div class="admin-field">
            <label for="expira_em">Expira em</label>
            <input id="expira_em" type="datetime-local" name="expira_em" value="<?= h((string) $oferta['expira_em']) ?>">
          </div>
          <div class="admin-field is-full">
            <label for="promocao_texto">Promocao / destaque comercial</label>
            <input id="promocao_texto" name="promocao_texto" value="<?= h((string) $oferta['promocao_texto']) ?>" placeholder="Ex.: 42% OFF no Pix ou saldo Mercado Pago">
          </div>
          <div class="admin-field is-full">
            <label for="descricao">Descricao</label>
            <textarea id="descricao" name="descricao" rows="4"><?= h((string) $oferta['descricao']) ?></textarea>
          </div>
        </div>

        <div class="admin-check-row">
          <label class="admin-check-chip"><input type="checkbox" name="ativo" value="1" <?= ((int) $oferta['ativo'] === 1) ? 'checked' : '' ?>> Ativa</label>
          <label class="admin-check-chip"><input type="checkbox" name="destaque" value="1" <?= ((int) $oferta['destaque'] === 1) ? 'checked' : '' ?>> Destaque</label>
        </div>

        <div class="admin-form-actions">
          <button class="btn" type="submit">Salvar</button>
          <?php if (!empty($oferta['url_afiliado'])): ?>
            <a class="badge" href="<?= h((string) $oferta['url_afiliado']) ?>" target="_blank" rel="noopener sponsored nofollow">Testar link afiliado</a>
          <?php endif; ?>
          <?php if (!empty($oferta['slug'])): ?>
            <a class="badge" href="/oferta.php?slug=<?= urlencode((string) $oferta['slug']) ?>&go=1" target="_blank" rel="noopener sponsored nofollow">Abrir pelo site</a>
          <?php endif; ?>
        </div>
      </form>
    </section>

    <aside class="admin-preview">
      <?php if (!empty($oferta['imagem_url'])): ?>
        <img class="admin-preview-thumb" src="<?= h((string) $oferta['imagem_url']) ?>" alt="<?= h((string) ($oferta['titulo'] ?: 'Preview da oferta')) ?>">
      <?php else: ?>
        <div class="admin-preview-thumb is-empty"><?= h(strtoupper(substr((string) ($oferta['loja'] ?: 'oferta'), 0, 2))) ?></div>
      <?php endif; ?>

      <?php if ($videoPreviewUrl !== ''): ?>
        <div class="admin-side-card">
          <strong>Preview do video</strong>
          <video controls preload="metadata" style="width:100%;margin-top:12px;border-radius:18px;background:#081b45;">
            <source src="<?= h($videoPreviewUrl) ?>">
          </video>
          <div class="admin-help" style="margin-top:8px;">O social vai tentar usar este video no formato de reel.</div>
        </div>
      <?php endif; ?>

      <?php if (!empty($imageGalleryUrls)): ?>
        <div class="admin-side-card">
          <strong>Galeria vinculada</strong>
          <div class="admin-meta-row" style="margin-top:10px;">
            <span class="admin-meta-chip"><?= count($imageGalleryUrls) ?> imagem(ns)</span>
          </div>
          <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:12px;">
            <?php foreach (array_slice($imageGalleryUrls, 0, 12) as $galleryImageUrl): ?>
              <a href="<?= h((string) $galleryImageUrl) ?>" target="_blank" rel="noopener">
                <img src="<?= h((string) $galleryImageUrl) ?>" alt="Imagem da galeria" style="width:100%;aspect-ratio:1/1;object-fit:cover;border-radius:14px;border:1px solid rgba(15,23,42,.1);">
              </a>
            <?php endforeach; ?>
          </div>
        </div>
      <?php endif; ?>

      <div>
        <span class="admin-kicker">Preview rapido</span>
        <h3 class="admin-card-title" style="margin-top:10px;"><?= h((string) ($oferta['titulo'] ?: 'Titulo da oferta')) ?></h3>
        <div class="admin-card-subtitle"><?= h((string) ($oferta['loja'] ?: 'loja')) ?> · <?= h((string) ($oferta['categoria'] ?: 'categoria')) ?></div>
      </div>

      <div class="admin-preview-price">
        <span class="admin-price"><?= $oferta['preco'] !== '' ? 'R$ ' . h((string) $oferta['preco']) : 'R$ --' ?></span>
        <?php if ($oferta['preco_antigo'] !== ''): ?>
          <span class="admin-price-old">R$ <?= h((string) $oferta['preco_antigo']) ?></span>
        <?php endif; ?>
      </div>

      <div class="admin-meta-row">
        <?php if (!empty($oferta['cupom'])): ?>
          <span class="admin-meta-chip">cupom <?= h((string) $oferta['cupom']) ?></span>
        <?php endif; ?>
        <?php if (!empty($oferta['preco_pix'])): ?>
          <span class="admin-meta-chip">Pix R$ <?= h((string) $oferta['preco_pix']) ?></span>
        <?php endif; ?>
        <?php if (!empty($oferta['parcelas_texto'])): ?>
          <span class="admin-meta-chip"><?= h((string) $oferta['parcelas_texto']) ?></span>
        <?php endif; ?>
        <?php if (!empty($oferta['frete_texto'])): ?>
          <span class="admin-meta-chip"><?= h((string) $oferta['frete_texto']) ?></span>
        <?php endif; ?>
        <span class="admin-status <?= ((int) $oferta['ativo'] === 1) ? 'ok' : 'off' ?>"><?= ((int) $oferta['ativo'] === 1) ? 'Ativa' : 'Inativa' ?></span>
        <span class="admin-status <?= ((int) $oferta['destaque'] === 1) ? 'ok' : 'off' ?>"><?= ((int) $oferta['destaque'] === 1) ? 'Destaque' : 'Normal' ?></span>
      </div>

      <div class="admin-side-card">
        <strong>Slug final</strong>
        <div class="admin-url-box"><?= h((string) ($oferta['slug'] ?: 'sera gerado automaticamente')) ?></div>
      </div>

      <div class="admin-side-card">
        <strong>Link afiliado</strong>
        <div class="admin-url-box"><?= h((string) ($oferta['url_afiliado'] ?: 'preencha a URL afiliada para validar o destino')) ?></div>
      </div>

      <?php if ($videoPreviewUrl !== ''): ?>
        <div class="admin-side-card">
          <strong>Video vinculado</strong>
          <div class="admin-url-box"><?= h($videoPreviewUrl) ?></div>
        </div>
      <?php endif; ?>

      <?php if (!empty($imageGalleryUrls)): ?>
        <div class="admin-side-card">
          <strong>URLs da galeria</strong>
          <div class="admin-url-box"><?= nl2br(h($imageGalleryText)) ?></div>
        </div>
      <?php endif; ?>

      <div class="admin-side-card">
        <strong>Descricao</strong>
        <div class="admin-description"><?= nl2br(h((string) ($oferta['descricao'] ?: 'Use este campo para destacar pontos fortes, prazo, voltagem, tamanho ou restricoes do produto.'))) ?></div>
      </div>

      <div class="admin-side-card">
        <strong>Informacoes comerciais</strong>
        <div class="admin-description"><?php
          $commerceLines = [];
          if ($oferta['desconto_percentual'] !== '') { $commerceLines[] = 'Desconto: ' . $oferta['desconto_percentual'] . '%'; }
          if ($oferta['preco_pix'] !== '') { $commerceLines[] = 'Preco no Pix: R$ ' . $oferta['preco_pix']; }
          if ($oferta['preco_outros_meios'] !== '') { $commerceLines[] = 'Outros meios: R$ ' . $oferta['preco_outros_meios']; }
          if ($oferta['parcelas_texto'] !== '') { $commerceLines[] = 'Parcelamento: ' . $oferta['parcelas_texto']; }
          if ($oferta['frete_texto'] !== '') { $commerceLines[] = 'Frete: ' . $oferta['frete_texto']; }
          if ($oferta['avaliacao_nota'] !== '') {
            $ratingLine = 'Avaliacao: ' . $oferta['avaliacao_nota'] . '/5';
            if ($oferta['avaliacao_total'] !== '') {
              $ratingLine .= ' (' . $oferta['avaliacao_total'] . ')';
            }
            $commerceLines[] = $ratingLine;
          }
          if ($oferta['promocao_texto'] !== '') { $commerceLines[] = 'Promocao: ' . $oferta['promocao_texto']; }
          echo nl2br(h($commerceLines ? implode("\n", $commerceLines) : 'Sem dados comerciais extras nesta oferta.'));
        ?></div>
      </div>

      <div class="admin-preview-actions">
        <?php if (!empty($oferta['slug'])): ?>
          <a class="btn-link" href="/oferta.php?slug=<?= urlencode((string) $oferta['slug']) ?>" target="_blank" rel="noopener">Ver pagina</a>
        <?php endif; ?>
        <?php if (!empty($oferta['url_afiliado'])): ?>
          <a class="btn-link primary" href="<?= h((string) $oferta['url_afiliado']) ?>" target="_blank" rel="noopener sponsored nofollow">Loja afiliada</a>
        <?php endif; ?>
      </div>
    </aside>
  </div>
</main>
</body>
</html>
