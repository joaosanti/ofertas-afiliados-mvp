<?php
require_once __DIR__ . '/_init.php';
admin_require_login();

function admin_ensure_youtube_profiles_table(PDO $pdo) {
  $pdo->exec("
    CREATE TABLE IF NOT EXISTS youtube_channel_profiles (
      id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
      slug VARCHAR(80) NOT NULL,
      name VARCHAR(180) NOT NULL,
      handle VARCHAR(180) NULL,
      notes TEXT NULL,
      source_channels TEXT NULL,
      avoid_terms TEXT NULL,
      preferred_terms TEXT NULL,
      viral_tone TEXT NULL,
      client_id VARCHAR(255) NULL,
      client_secret TEXT NULL,
      redirect_uri VARCHAR(600) NULL,
      access_token LONGTEXT NULL,
      refresh_token LONGTEXT NULL,
      token_expires_at BIGINT NULL,
      oauth_state VARCHAR(120) NULL,
      channel_id VARCHAR(120) NULL,
      channel_title VARCHAR(255) NULL,
      channel_custom_url VARCHAR(255) NULL,
      channel_thumbnail_url VARCHAR(1000) NULL,
      is_default TINYINT(1) NOT NULL DEFAULT 0,
      is_active TINYINT(1) NOT NULL DEFAULT 1,
      created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
      UNIQUE KEY ux_youtube_channel_profiles_slug (slug),
      INDEX ix_youtube_channel_profiles_default (is_default),
      INDEX ix_youtube_channel_profiles_active (is_active),
      INDEX ix_youtube_channel_profiles_state (oauth_state)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  ");

  $columns = [];
  foreach ($pdo->query("SHOW COLUMNS FROM youtube_channel_profiles")->fetchAll() as $row) {
    $columns[] = (string) ($row['Field'] ?? '');
  }
  $alterSql = [
    'source_channels' => "ALTER TABLE youtube_channel_profiles ADD COLUMN source_channels TEXT NULL AFTER notes",
    'avoid_terms' => "ALTER TABLE youtube_channel_profiles ADD COLUMN avoid_terms TEXT NULL AFTER notes",
    'preferred_terms' => "ALTER TABLE youtube_channel_profiles ADD COLUMN preferred_terms TEXT NULL AFTER avoid_terms",
    'viral_tone' => "ALTER TABLE youtube_channel_profiles ADD COLUMN viral_tone TEXT NULL AFTER preferred_terms",
  ];
  foreach ($alterSql as $field => $sql) {
    if (!in_array($field, $columns, true)) {
      $pdo->exec($sql);
    }
  }
}

function admin_youtube_profile_slugify($value) {
  $slug = preg_replace('~[^a-z0-9]+~', '-', strtolower(trim((string) $value)));
  $slug = trim((string) $slug, '-');
  return $slug !== '' ? substr($slug, 0, 80) : 'canal-youtube';
}

function admin_youtube_unique_slug(PDO $pdo, $baseValue, $excludeId = 0) {
  $baseSlug = admin_youtube_profile_slugify($baseValue);
  $slug = $baseSlug;
  $suffix = 2;
  while (true) {
    if ((int) $excludeId > 0) {
      $stmt = $pdo->prepare("SELECT id FROM youtube_channel_profiles WHERE slug = ? AND id <> ? LIMIT 1");
      $stmt->execute([$slug, (int) $excludeId]);
    } else {
      $stmt = $pdo->prepare("SELECT id FROM youtube_channel_profiles WHERE slug = ? LIMIT 1");
      $stmt->execute([$slug]);
    }
    if (!$stmt->fetch()) {
      return $slug;
    }
    $slug = substr($baseSlug, 0, 72) . '-' . $suffix;
    $suffix++;
  }
}

function admin_fetch_youtube_profiles_admin(PDO $pdo) {
  $stmt = $pdo->query("
    SELECT *
    FROM youtube_channel_profiles
    ORDER BY is_default DESC, is_active DESC, updated_at DESC, id DESC
  ");
  return $stmt->fetchAll() ?: [];
}

function admin_fetch_youtube_profile_admin(PDO $pdo, $profileId) {
  if ((int) $profileId <= 0) {
    return null;
  }
  $stmt = $pdo->prepare("SELECT * FROM youtube_channel_profiles WHERE id = ? LIMIT 1");
  $stmt->execute([(int) $profileId]);
  return $stmt->fetch() ?: null;
}

function admin_youtube_profile_defaults() {
  return [
    'id' => 0,
    'name' => '',
    'handle' => '',
    'client_id' => '',
    'client_secret' => '',
    'redirect_uri' => '',
    'source_channels' => '',
    'avoid_terms' => '',
    'preferred_terms' => '',
    'viral_tone' => '',
    'notes' => '',
    'is_default' => 0,
    'is_active' => 1,
    'channel_title' => '',
    'channel_custom_url' => '',
    'updated_at' => null,
  ];
}

function admin_youtube_editorial_presets() {
  return [
    'comedia' => [
      'label' => 'Comedia',
      'avoid_terms' => "tragedia\nmorte\nacidente grave\ndebate tecnico demais\nexplicacao longa sem piada",
      'preferred_terms' => "zoacao, humor, meme, vergonha alheia, situacao do dia a dia, ironia, react, piada curta, pov, gafe, crise, comedia",
      'viral_tone' => "ritmo rapido, leve deboche, surpresa, exagero comico, frases curtas, linguagem popular, energia de short, final com punchline",
      'notes' => "Canal focado em humor curto, situacoes identificaveis, memes, POV, vergonha publica e piada de facil entendimento nos primeiros segundos.",
    ],
    'games' => [
      'label' => 'Games',
      'avoid_terms' => "politica fora de contexto\nassunto tecnico sem gameplay\nexplicacao lenta\ntrecho sem reacao\nsilencio prolongado",
      'preferred_terms' => "gameplay, rage, clutch, noob, boss, react, bug, fail, highlight, partida, desafio, zoacao entre amigos, momento engracado",
      'viral_tone' => "energia alta, reacao forte, cortes rapidos, provocacao leve, linguagem de gamer, foco em momentos de tensao, susto, clutch ou falha engracada",
      'notes' => "Canal focado em games com clips de reacao, jogadas fortes, rage, fails, momentos engraçados, desafios e cortes com contexto imediato.",
    ],
  ];
}

function admin_guess_youtube_profile_preset_key($profile) {
  $haystack = strtolower(trim((string) (($profile['name'] ?? '') . ' ' . ($profile['handle'] ?? '') . ' ' . ($profile['notes'] ?? ''))));
  if ($haystack === '') {
    return '';
  }
  if (strpos($haystack, 'comedia') !== false || strpos($haystack, 'humor') !== false || strpos($haystack, 'meme') !== false) {
    return 'comedia';
  }
  if (strpos($haystack, 'games') !== false || strpos($haystack, 'game') !== false || strpos($haystack, 'jogo') !== false || strpos($haystack, 'gameplay') !== false) {
    return 'games';
  }
  return '';
}

$pdo = db();
admin_ensure_youtube_profiles_table($pdo);
$flash = admin_flash_get();
$editorialPresets = admin_youtube_editorial_presets();
$selectedProfileId = max(0, (int) ($_GET['profile_id'] ?? 0));
$editingProfile = admin_fetch_youtube_profile_admin($pdo, $selectedProfileId);
$form = array_merge(admin_youtube_profile_defaults(), is_array($editingProfile) ? $editingProfile : []);
$suggestedPresetKey = admin_guess_youtube_profile_preset_key($form);
if ($suggestedPresetKey !== '' && isset($editorialPresets[$suggestedPresetKey])) {
  $suggestedPreset = $editorialPresets[$suggestedPresetKey];
  if (trim((string) ($form['avoid_terms'] ?? '')) === '') {
    $form['avoid_terms'] = $suggestedPreset['avoid_terms'];
  }
  if (trim((string) ($form['preferred_terms'] ?? '')) === '') {
    $form['preferred_terms'] = $suggestedPreset['preferred_terms'];
  }
  if (trim((string) ($form['viral_tone'] ?? '')) === '') {
    $form['viral_tone'] = $suggestedPreset['viral_tone'];
  }
  if (trim((string) ($form['notes'] ?? '')) === '') {
    $form['notes'] = $suggestedPreset['notes'];
  }
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
  admin_csrf_check_or_die();
  $action = (string) ($_POST['acao'] ?? '');
  $profileId = max(0, (int) ($_POST['profile_id'] ?? 0));

  if ($action === 'save_profile') {
    $name = trim((string) ($_POST['name'] ?? ''));
    $handle = trim((string) ($_POST['handle'] ?? ''));
    $clientId = trim((string) ($_POST['client_id'] ?? ''));
    $clientSecret = trim((string) ($_POST['client_secret'] ?? ''));
    $redirectUri = trim((string) ($_POST['redirect_uri'] ?? ''));
    $sourceChannels = trim((string) ($_POST['source_channels'] ?? ''));
    $avoidTerms = trim((string) ($_POST['avoid_terms'] ?? ''));
    $preferredTerms = trim((string) ($_POST['preferred_terms'] ?? ''));
    $viralTone = trim((string) ($_POST['viral_tone'] ?? ''));
    $notes = trim((string) ($_POST['notes'] ?? ''));
    $isDefault = isset($_POST['is_default']) ? 1 : 0;
    $isActive = isset($_POST['is_active']) ? 1 : 0;

    if ($name === '') {
      admin_flash_set('error', 'Informe o nome do perfil do canal.');
      header('Location: /admin/youtube_canais.php' . ($profileId > 0 ? '?profile_id=' . $profileId : ''));
      exit;
    }

    if ($isDefault) {
      $pdo->exec("UPDATE youtube_channel_profiles SET is_default = 0");
    }

    if ($profileId > 0) {
      $current = admin_fetch_youtube_profile_admin($pdo, $profileId);
      if (!$current) {
        admin_flash_set('error', 'Perfil do YouTube nao encontrado.');
        header('Location: /admin/youtube_canais.php');
        exit;
      }
      $slug = admin_youtube_unique_slug($pdo, $name, $profileId);
      $stmt = $pdo->prepare("
        UPDATE youtube_channel_profiles
        SET slug = ?, name = ?, handle = ?, client_id = ?, client_secret = ?, redirect_uri = ?,
            source_channels = ?, avoid_terms = ?, preferred_terms = ?, viral_tone = ?, notes = ?, is_default = ?, is_active = ?
        WHERE id = ?
        LIMIT 1
      ");
      $stmt->execute([
        $slug,
        $name,
        $handle !== '' ? $handle : null,
        $clientId !== '' ? $clientId : null,
        $clientSecret !== '' ? $clientSecret : null,
        $redirectUri !== '' ? $redirectUri : null,
        $sourceChannels !== '' ? $sourceChannels : null,
        $avoidTerms !== '' ? $avoidTerms : null,
        $preferredTerms !== '' ? $preferredTerms : null,
        $viralTone !== '' ? $viralTone : null,
        $notes !== '' ? $notes : null,
        $isDefault,
        $isActive,
        $profileId,
      ]);
      if (!$isDefault && $isActive) {
        $defaultExists = $pdo->query("SELECT id FROM youtube_channel_profiles WHERE is_default = 1 LIMIT 1")->fetch();
        if (!$defaultExists) {
          $pdo->prepare("UPDATE youtube_channel_profiles SET is_default = 1 WHERE id = ? LIMIT 1")->execute([$profileId]);
        }
      }
      admin_flash_set('success', 'Perfil do canal atualizado com sucesso.');
      header('Location: /admin/youtube_canais.php?profile_id=' . $profileId);
      exit;
    }

    $slug = admin_youtube_unique_slug($pdo, $name);
    $stmt = $pdo->prepare("
      INSERT INTO youtube_channel_profiles
      (
        slug, name, handle, client_id, client_secret, redirect_uri,
        source_channels, avoid_terms, preferred_terms, viral_tone, notes, is_default, is_active
      )
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ");
    $stmt->execute([
      $slug,
      $name,
      $handle !== '' ? $handle : null,
      $clientId !== '' ? $clientId : null,
      $clientSecret !== '' ? $clientSecret : null,
      $redirectUri !== '' ? $redirectUri : null,
      $sourceChannels !== '' ? $sourceChannels : null,
      $avoidTerms !== '' ? $avoidTerms : null,
      $preferredTerms !== '' ? $preferredTerms : null,
      $viralTone !== '' ? $viralTone : null,
      $notes !== '' ? $notes : null,
      $isDefault,
      $isActive,
    ]);
    $createdId = (int) $pdo->lastInsertId();
    if (!$isDefault && $isActive) {
      $defaultExists = $pdo->query("SELECT id FROM youtube_channel_profiles WHERE is_default = 1 LIMIT 1")->fetch();
      if (!$defaultExists) {
        $pdo->prepare("UPDATE youtube_channel_profiles SET is_default = 1 WHERE id = ? LIMIT 1")->execute([$createdId]);
      }
    }
    admin_flash_set('success', 'Novo perfil do YouTube criado com sucesso.');
    header('Location: /admin/youtube_canais.php?profile_id=' . $createdId);
    exit;
  }

  if ($action === 'apply_preset') {
    $presetKey = trim((string) ($_POST['preset_key'] ?? ''));
    $current = admin_fetch_youtube_profile_admin($pdo, $profileId);
    if (!$current) {
      admin_flash_set('error', 'Perfil do YouTube nao encontrado para aplicar preset.');
      header('Location: /admin/youtube_canais.php');
      exit;
    }
    if (!isset($editorialPresets[$presetKey])) {
      admin_flash_set('error', 'Preset editorial invalido.');
      header('Location: /admin/youtube_canais.php?profile_id=' . $profileId);
      exit;
    }
    $preset = $editorialPresets[$presetKey];
    $stmt = $pdo->prepare("
      UPDATE youtube_channel_profiles
      SET avoid_terms = ?, preferred_terms = ?, viral_tone = ?, notes = ?
      WHERE id = ?
      LIMIT 1
    ");
    $stmt->execute([
      $preset['avoid_terms'],
      $preset['preferred_terms'],
      $preset['viral_tone'],
      $preset['notes'],
      $profileId,
    ]);
    admin_flash_set('success', 'Preset editorial de ' . $preset['label'] . ' aplicado ao perfil.');
    header('Location: /admin/youtube_canais.php?profile_id=' . $profileId);
    exit;
  }

  if ($action === 'delete_profile') {
    $current = admin_fetch_youtube_profile_admin($pdo, $profileId);
    if (!$current) {
      admin_flash_set('error', 'Perfil do YouTube nao encontrado.');
      header('Location: /admin/youtube_canais.php');
      exit;
    }
    $stmt = $pdo->prepare("DELETE FROM youtube_channel_profiles WHERE id = ? LIMIT 1");
    $stmt->execute([$profileId]);
    $remaining = admin_fetch_youtube_profiles_admin($pdo);
    if ($remaining && !array_filter($remaining, static function ($item) { return !empty($item['is_default']); })) {
      $pdo->prepare("UPDATE youtube_channel_profiles SET is_default = 1 WHERE id = ? LIMIT 1")->execute([(int) $remaining[0]['id']]);
    }
    admin_flash_set('success', 'Perfil do canal removido.');
    header('Location: /admin/youtube_canais.php');
    exit;
  }
}

$profiles = admin_fetch_youtube_profiles_admin($pdo);
$adminCssVersion = (string) @filemtime(__DIR__ . '/../assets/css/admin.css');
?>
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Admin - Canais do YouTube</title>
  <link rel="icon" type="image/png" href="/assets/img/logo-zp.png">
  <link rel="stylesheet" href="/assets/css/style.css">
  <link rel="stylesheet" href="/assets/css/admin.css?v=<?= urlencode($adminCssVersion) ?>">
</head>
<body class="admin-page">
<?php admin_render_header('youtube_cortes'); ?>

<main class="container admin-shell">
  <?php if ($flash): ?>
    <div class="admin-alert <?= h((string) ($flash['type'] ?? '')) ?>"><?= h((string) ($flash['message'] ?? '')) ?></div>
  <?php endif; ?>

  <section class="admin-hero">
    <div class="admin-hero-head">
      <div class="admin-hero-copy">
        <span class="admin-kicker">Perfis de canal</span>
        <h1>Canais do YouTube</h1>
        <p>Cadastre varios canais no admin PHP e depois conecte cada um via OAuth.</p>
      </div>
      <div class="admin-hero-actions">
        <a class="btn-link" href="/admin/youtube_cortes.php">Voltar para cortes</a>
        <a class="btn-link primary" href="/admin/youtube_canais.php">Novo perfil</a>
      </div>
    </div>
  </section>

  <nav class="admin-subnav" aria-label="Submenu canais do YouTube">
    <a class="admin-subnav-link" href="/admin/youtube_cortes.php?tab=gerar">Gerar cortes</a>
    <a class="admin-subnav-link" href="/admin/youtube_cortes.php?tab=historico">Jobs e historico</a>
    <a class="admin-subnav-link is-active" href="/admin/youtube_canais.php">Cadastro de canais</a>
  </nav>

  <section class="admin-panel">
    <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title">Perfis cadastrados</h2>
        <p>Escolha um perfil para editar ou criar um novo canal de comedia, games ou qualquer outro nicho.</p>
      </div>
    </div>
    <?php if (!$profiles): ?>
      <div class="admin-empty">Nenhum perfil encontrado ainda.</div>
    <?php else: ?>
      <div class="admin-offers-grid">
        <?php foreach ($profiles as $profile): ?>
          <?php $profileId = (int) ($profile['id'] ?? 0); ?>
          <article class="admin-offer-card">
            <div class="admin-card-topline">
              <div>
                <h3 class="admin-card-title"><?= h((string) ($profile['name'] ?? 'Canal')) ?></h3>
                <div class="admin-card-subtitle">
                  <?= h((string) ($profile['handle'] ?? 'sem handle')) ?>
                  <?php if (!empty($profile['channel_title'])): ?>
                    · <?= h((string) $profile['channel_title']) ?>
                  <?php endif; ?>
                </div>
              </div>
            </div>
            <div class="admin-meta-row" style="margin-top:12px;">
              <span class="admin-status <?= !empty($profile['is_active']) ? 'ok' : 'off' ?>"><?= !empty($profile['is_active']) ? 'Ativo' : 'Inativo' ?></span>
              <span class="admin-status <?= !empty($profile['is_default']) ? 'ok' : 'off' ?>"><?= !empty($profile['is_default']) ? 'Padrao' : 'Secundario' ?></span>
              <span class="admin-meta-chip admin-meta-chip-soft"><?= !empty($profile['redirect_uri']) ? 'OAuth pronto' : 'Sem redirect' ?></span>
              <?php $sourceCount = count(array_filter(preg_split('~[\r\n,;|]+~', (string) ($profile['source_channels'] ?? '')))); ?>
              <span class="admin-meta-chip admin-meta-chip-soft"><?= $sourceCount > 0 ? ($sourceCount . ' canal(is)-fonte') : 'Usa inscricoes' ?></span>
            </div>
            <div class="admin-card-actions" style="margin-top:14px;">
              <a class="btn-link primary" href="/admin/youtube_canais.php?profile_id=<?= $profileId ?>">Editar</a>
              <a class="btn-link" href="/admin/youtube_cortes.php?channel_profile_id=<?= $profileId ?>">Usar nos cortes</a>
            </div>
          </article>
        <?php endforeach; ?>
      </div>
    <?php endif; ?>
  </section>

  <section class="admin-panel">
      <div class="admin-panel-head">
      <div>
        <h2 class="admin-section-title"><?= !empty($form['id']) ? 'Editar perfil' : 'Novo perfil do YouTube' ?></h2>
        <p>Depois de salvar, volte em YouTube cortes para reconectar esse canal com o Google.</p>
      </div>
    </div>

    <?php if ($suggestedPresetKey !== '' && isset($editorialPresets[$suggestedPresetKey])): ?>
      <div class="admin-help" style="margin-bottom:14px;">
        Sugestao automatica detectada para este canal: <strong><?= h((string) $editorialPresets[$suggestedPresetKey]['label']) ?></strong>.
        Os campos abaixo ja foram preenchidos para facilitar. Basta salvar para gravar no banco.
      </div>
    <?php endif; ?>

    <?php if (!empty($form['id'])): ?>
      <div class="admin-card-actions" style="margin-bottom:16px;">
        <form method="post">
          <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
          <input type="hidden" name="acao" value="apply_preset">
          <input type="hidden" name="profile_id" value="<?= (int) ($form['id'] ?? 0) ?>">
          <input type="hidden" name="preset_key" value="comedia">
          <button class="btn-link" type="submit">Aplicar preset Comedia</button>
        </form>
        <form method="post">
          <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
          <input type="hidden" name="acao" value="apply_preset">
          <input type="hidden" name="profile_id" value="<?= (int) ($form['id'] ?? 0) ?>">
          <input type="hidden" name="preset_key" value="games">
          <button class="btn-link" type="submit">Aplicar preset Games</button>
        </form>
      </div>
    <?php endif; ?>

    <form method="post" class="admin-filter-form">
      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
      <input type="hidden" name="acao" value="save_profile">
      <input type="hidden" name="profile_id" value="<?= (int) ($form['id'] ?? 0) ?>">

      <div class="admin-field-grid">
        <div class="admin-field">
          <label for="name">Nome do perfil</label>
          <input id="name" name="name" value="<?= h((string) ($form['name'] ?? '')) ?>" placeholder="Ex.: Zero Cortes Comedia" required>
        </div>
        <div class="admin-field">
          <label for="handle">Handle interno</label>
          <input id="handle" name="handle" value="<?= h((string) ($form['handle'] ?? '')) ?>" placeholder="@zerocortescomedia">
        </div>
        <div class="admin-field">
          <label for="redirect_uri">Redirect URI</label>
          <input id="redirect_uri" name="redirect_uri" value="<?= h((string) ($form['redirect_uri'] ?? '')) ?>" placeholder="https://zeropreco.com.br/admin/youtube_oauth_callback.php">
        </div>

        <div class="admin-field">
          <label for="client_id">Client ID</label>
          <input id="client_id" name="client_id" value="<?= h((string) ($form['client_id'] ?? '')) ?>" placeholder="Se vazio, usa o padrao do .env">
        </div>
        <div class="admin-field">
          <label for="client_secret">Client secret</label>
          <input id="client_secret" name="client_secret" value="<?= h((string) ($form['client_secret'] ?? '')) ?>" placeholder="Opcional se usar o padrao do .env">
        </div>
        <div class="admin-field">
          <label for="notes">Notas</label>
          <input id="notes" name="notes" value="<?= h((string) ($form['notes'] ?? '')) ?>" placeholder="Nicho, observacoes e diferencas do canal">
        </div>

        <div class="admin-field is-full">
          <label for="source_channels">Canais para buscar cortes</label>
          <textarea id="source_channels" name="source_channels" rows="5" placeholder="@flowgames&#10;https://www.youtube.com/@canal&#10;UCxxxxxxxxxxxxxxxxxxxxxx&#10;Nome do canal"><?= h((string) ($form['source_channels'] ?? '')) ?></textarea>
          <p class="admin-card-subtitle">Opcional. Um por linha. Aceita @handle, URL do canal, ID UC... ou nome. Se preencher, o radar usa essa lista antes das inscricoes da conta.</p>
        </div>
        <div class="admin-field is-full">
          <label for="avoid_terms">Palavras para evitar</label>
          <textarea id="avoid_terms" name="avoid_terms" rows="4" placeholder="Uma por linha ou separadas por virgula"><?= h((string) ($form['avoid_terms'] ?? '')) ?></textarea>
        </div>
        <div class="admin-field is-full">
          <label for="preferred_terms">Palavras para priorizar</label>
          <textarea id="preferred_terms" name="preferred_terms" rows="4" placeholder="Ex.: zoacao, gameplay, rage, reacts"><?= h((string) ($form['preferred_terms'] ?? '')) ?></textarea>
        </div>
        <div class="admin-field is-full">
          <label for="viral_tone">Tom viral do canal</label>
          <textarea id="viral_tone" name="viral_tone" rows="4" placeholder="Ex.: risadas, zoacao, brincadeira, provocacao leve"><?= h((string) ($form['viral_tone'] ?? '')) ?></textarea>
        </div>
      </div>

      <div class="admin-check-row" style="margin-top:16px;">
        <label class="admin-check-chip">
          <input type="checkbox" name="is_default" value="1" <?= !empty($form['is_default']) ? 'checked' : '' ?>>
          Definir como perfil padrao
        </label>
        <label class="admin-check-chip">
          <input type="checkbox" name="is_active" value="1" <?= !array_key_exists('is_active', $form) || !empty($form['is_active']) ? 'checked' : '' ?>>
          Perfil ativo
        </label>
      </div>

      <div class="admin-card-actions" style="margin-top:18px;">
        <button class="btn-link primary" type="submit">Salvar perfil</button>
        <?php if (!empty($form['id'])): ?>
          <a class="btn-link" href="/admin/youtube_cortes.php?channel_profile_id=<?= (int) $form['id'] ?>">Abrir em YouTube cortes</a>
        <?php endif; ?>
      </div>
    </form>

    <?php if (!empty($form['id'])): ?>
      <form method="post" onsubmit="return confirm('Apagar este perfil de canal agora?');" style="margin-top:18px;">
        <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
        <input type="hidden" name="acao" value="delete_profile">
        <input type="hidden" name="profile_id" value="<?= (int) ($form['id'] ?? 0) ?>">
        <button class="btn-link" type="submit">Apagar perfil</button>
      </form>
    <?php endif; ?>
  </section>
</main>
</body>
</html>
