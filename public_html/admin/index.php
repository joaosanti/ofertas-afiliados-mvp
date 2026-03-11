<?php
require_once __DIR__ . '/_init.php';

$flash = admin_flash_get();

if (admin_is_logged_in()) {
  header('Location: /admin/ofertas.php');
  exit;
}

$erro = '';
$email = trim((string) ($_POST['email'] ?? ''));

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
  admin_csrf_check_or_die();
  $senha = (string) ($_POST['senha'] ?? '');

  if ($email === '' || $senha === '') {
    $erro = 'Preencha email e senha.';
  } else {
    $stmt = db()->prepare('SELECT id, senha_hash FROM admin_users WHERE email = ? LIMIT 1');
    $stmt->execute([$email]);
    $user = $stmt->fetch();

    if ($user && password_verify($senha, $user['senha_hash'])) {
      $_SESSION['admin_user_id'] = (int) $user['id'];
      session_regenerate_id(true);
      header('Location: /admin/ofertas.php');
      exit;
    }
    $erro = 'Login invalido.';
  }
}
?>
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Admin - Login</title>
  <link rel="icon" type="image/png" href="/assets/img/logo-zp.png">
  <link rel="stylesheet" href="/assets/css/style.css">
  <link rel="stylesheet" href="/assets/css/admin.css">
  <style>
    .panel { max-width: 420px; margin: 40px auto; background: #fff; border: 1px solid #e5e7eb; border-radius: 14px; padding: 18px; }
    .field { margin-top: 10px; }
    .field label { display: block; font-size: 13px; color: #6b7280; margin-bottom: 6px; }
    .field input { width: 100%; border: 1px solid #d1d5db; border-radius: 10px; padding: 10px; }
    .err { margin-top: 10px; color: #991b1b; background: #fee2e2; border: 1px solid #fecaca; border-radius: 10px; padding: 10px; }
  </style>
</head>
<body class="admin-page">
<header>
  <div class="container" style="display:flex; align-items:center; justify-content:space-between;">
    <div style="font-weight:700;">Admin de Ofertas</div>
    <a class="badge" href="/">Ver site</a>
  </div>
</header>

<main class="container">
  <section class="panel">
    <h1 style="margin:0 0 10px;">Entrar</h1>
    <?php if ($flash): ?>
      <div class="admin-alert <?= h((string) ($flash['type'] ?? '')) ?>"><?= h((string) ($flash['message'] ?? '')) ?></div>
    <?php endif; ?>
    <form method="post">
      <input type="hidden" name="csrf" value="<?= h(admin_csrf_token()) ?>">
      <div class="field">
        <label for="email">Email</label>
        <input id="email" type="email" name="email" value="<?= h($email) ?>" required>
      </div>
      <div class="field">
        <label for="senha">Senha</label>
        <input id="senha" type="password" name="senha" required>
      </div>
      <div style="margin-top:14px;">
        <button class="btn" type="submit">Entrar</button>
      </div>
      <?php if ($erro): ?>
        <div class="err"><?= h($erro) ?></div>
      <?php endif; ?>
    </form>
  </section>
</main>
</body>
</html>


