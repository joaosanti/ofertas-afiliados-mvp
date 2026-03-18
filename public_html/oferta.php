<?php
require_once __DIR__ . '/inc/site.php';

$slug = $_GET['slug'] ?? '';
$pdo = db();

$stmt = $pdo->prepare("SELECT * FROM ofertas WHERE slug=? AND ativo=1 LIMIT 1");
$stmt->execute([$slug]);
$offer = $stmt->fetch();

if (!$offer) {
  http_response_code(404);
  exit('Oferta não encontrada');
}

if (isset($_GET['go']) && $_GET['go'] === '1') {
  $redirectUrl = site_offer_preferred_affiliate_url($offer);
  try {
    $pdo->prepare("INSERT INTO cliques (oferta_id, ip_hash, user_agent, referer) VALUES (?,?,?,?)")
        ->execute([
          $offer['id'],
          ip_hash(),
          substr((string) ($_SERVER['HTTP_USER_AGENT'] ?? ''), 0, 255),
          substr((string) ($_SERVER['HTTP_REFERER'] ?? ''), 0, 2000) ?: null,
        ]);
    header('X-ZeroPreco-Click-Logged: 1');
  } catch (Throwable $e) {
    error_log('Zero Preco click log failure: ' . $e->getMessage());
    header('X-ZeroPreco-Click-Logged: 0');
  }

  header("Location: " . $redirectUrl);
  exit;
}

$relatedOffers = site_fetch_related_offers($pdo, $offer, 4);
$discount = site_discount_percent($offer['preco'], $offer['preco_antigo']);
$soldCount = site_extract_sold_count($offer['tags'] ?? '');
$offerDescription = trim((string) ($offer['descricao'] ?? ''));
$offerDescription = preg_replace('/\s*\|\s*Comiss(?:a|ã)o:\s*[^|]+/iu', '', $offerDescription);
$offerDescription = preg_replace('/\s*\|\s*Retorno estimado:\s*[^|]+/iu', '', $offerDescription);
$displayDescription = preg_replace('/MLB\d+/', site_category_label($offer['categoria']), $offerDescription);
$commerceHighlights = [];
if (!empty($offer['desconto_percentual'])) { $commerceHighlights[] = $offer['desconto_percentual'] . '% OFF'; }
if (!empty($offer['preco_pix'])) { $commerceHighlights[] = 'No Pix: ' . site_money($offer['preco_pix']); }
if (!empty($offer['preco_outros_meios'])) { $commerceHighlights[] = 'Outros meios: ' . site_money($offer['preco_outros_meios']); }
if (!empty($offer['parcelas_texto'])) { $commerceHighlights[] = 'Parcelamento: ' . $offer['parcelas_texto']; }
if (!empty($offer['frete_texto'])) { $commerceHighlights[] = 'Frete: ' . $offer['frete_texto']; }
if (!empty($offer['avaliacao_nota'])) {
  $ratingText = 'Avaliacao: ' . number_format((float) $offer['avaliacao_nota'], 1, ',', '.');
  $ratingText .= !empty($offer['avaliacao_total']) ? '/5 (' . number_format((int) $offer['avaliacao_total'], 0, ',', '.') . ')' : '/5';
  $commerceHighlights[] = $ratingText;
}
if (!empty($offer['promocao_texto'])) { $commerceHighlights[] = 'Promocao: ' . $offer['promocao_texto']; }
$descriptionParts = preg_split('/[\r\n]+|[.;â€¢]+/', $offerDescription) ?: [];
$sellingPoints = [];
foreach ($descriptionParts as $part) {
  $clean = trim((string) $part);
  if ($clean !== '') {
    $clean = preg_replace('/\s*\|\s*Comiss(?:a|ã)o:\s*[^|]+/iu', '', $clean);
    $clean = preg_replace('/\s*\|\s*Retorno estimado:\s*[^|]+/iu', '', $clean);
    $clean = preg_replace('/MLB\d+/', site_category_label($offer['categoria']), $clean);
    $clean = trim($clean, " \t\n\r\0\x0B|");
    if ($clean !== '') {
      $sellingPoints[] = $clean;
    }
  }
  if (count($sellingPoints) >= 4) {
    break;
  }
}
if (!$sellingPoints) {
  $sellingPoints[] = 'Oferta monitorada com redirecionamento rápido para a loja oficial.';
  $sellingPoints[] = 'Preço visível na página para reduzir atrito antes do clique.';
  if ($discount !== null) {
    $sellingPoints[] = 'Desconto identificado em relação ao preço de referência.';
  }
  if (!empty($offer['cupom'])) {
    $sellingPoints[] = 'Cupom ativo destacado para aumentar a conversão.';
  }
}

$siteBaseUrl = 'https://zeropreco.com.br';
$offerUrl = $siteBaseUrl . site_offer_href($offer['slug']);
$whatsappGroupLink = site_whatsapp_group_link();
$whatsappGroupLabel = site_whatsapp_group_label();
$whatsappGroupQrUrl = site_whatsapp_group_qr_url();
$siteHeaderCurrent = '';
$siteHeaderSearchPlaceholder = 'Buscar produto';
$shareTitle = trim((string) $offer['titulo']);
$shareSnippet = function_exists('mb_substr')
  ? mb_substr($displayDescription, 0, 220)
  : substr($displayDescription, 0, 220);
$shareDescription = $offerDescription !== ''
  ? preg_replace('/\s+/', ' ', $shareSnippet)
  : sprintf(
      '%s por %s no %s. Veja a oferta completa no Zero Preço.',
      $shareTitle,
      site_money($offer['preco']),
      site_store_label($offer['loja'])
    );
$shareImage = trim((string) ($offer['imagem_url'] ?? ''));
if ($shareImage === '') {
  $shareImage = $siteBaseUrl . '/assets/img/sem-img.png';
}
?>
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title><?= h($offer['titulo']) ?> | Zero Preço</title>
  <meta name="description" content="<?= h($shareDescription) ?>">
  <link rel="canonical" href="<?= h($offerUrl) ?>">
  <meta property="og:type" content="product">
  <meta property="og:site_name" content="Zero Preço">
  <meta property="og:locale" content="pt_BR">
  <meta property="og:title" content="<?= h($shareTitle) ?>">
  <meta property="og:description" content="<?= h($shareDescription) ?>">
  <meta property="og:url" content="<?= h($offerUrl) ?>">
  <meta property="og:image" content="<?= h($shareImage) ?>">
  <meta property="og:image:secure_url" content="<?= h($shareImage) ?>">
  <meta property="og:image:alt" content="<?= h($shareTitle) ?>">
  <meta property="product:price:amount" content="<?= h(number_format((float) $offer['preco'], 2, '.', '')) ?>">
  <meta property="product:price:currency" content="BRL">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="<?= h($shareTitle) ?>">
  <meta name="twitter:description" content="<?= h($shareDescription) ?>">
  <meta name="twitter:image" content="<?= h($shareImage) ?>">
  <link rel="icon" type="image/png" href="/assets/img/logo-zp.png">
  <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-8314124298799437" crossorigin="anonymous"></script>
  <?php require __DIR__ . '/inc/site_head_analytics.php'; ?>
  <link rel="stylesheet" href="/assets/css/style.css">
</head>
<body>
  <?php require __DIR__ . '/inc/site_header.php'; ?>

  <main class="page-shell" style="padding-top:28px;">
    <div class="container">
      <section class="detail-panel">
        <div class="breadcrumbs">
          <a href="/">Home</a>
          <span>/</span>
          <a href="<?= h(site_category_href($offer['categoria'])) ?>"><?= h(site_category_label($offer['categoria'])) ?></a>
          <span>/</span>
          <span><?= h(site_store_label($offer['loja'])) ?></span>
        </div>

        <div class="detail-grid">
          <div class="detail-media">
            <div class="detail-media-shell">
              <img src="<?= h($offer['imagem_url'] ?: '/assets/img/sem-img.png') ?>" alt="">
            </div>
            <div class="detail-trust">
              <span class="detail-trust-chip"><?= h(site_store_label($offer['loja'])) ?></span>
              <?php if ($discount !== null): ?>
                <span class="detail-trust-chip is-highlight">Desconto de <?= $discount ?>%</span>
              <?php endif; ?>
            </div>

            <div class="detail-whatsapp-card">
              <div class="detail-whatsapp-copy">
                <span class="detail-whatsapp-kicker"><?= h($whatsappGroupLabel) ?></span>
                <h3>Receba novas ofertas direto no WhatsApp</h3>
                <p>Entre no grupo para receber as melhores promocoes primeiro e voltar ao site so quando o produto fizer sentido para voce.</p>
                <a class="button button-primary" href="<?= h($whatsappGroupLink) ?>" target="_blank" rel="noopener noreferrer">Entrar no grupo</a>
              </div>
              <div class="detail-whatsapp-qr">
                <img src="<?= h($whatsappGroupQrUrl) ?>" alt="<?= h($whatsappGroupLabel) ?>">
              </div>
            </div>
          </div>

          <div class="detail-copy">
            <div class="kicker"><?= h(site_store_label($offer['loja'])) ?> &bull; Oferta com clique rastreado</div>
            <h1><?= h($offer['titulo']) ?></h1>
            <p><?= h($displayDescription ?: 'Produto pronto para divulgação com página de detalhe, preço visível e redirecionamento para a loja oficial.') ?></p>

            <div class="detail-price">
              <div class="price-row">
                <span class="price-now"><?= h(site_money($offer['preco'])) ?></span>
                <?php if (!empty($offer['preco_antigo'])): ?>
                  <span class="price-old"><?= h(site_money($offer['preco_antigo'])) ?></span>
                <?php endif; ?>
                <?php if ($discount !== null): ?>
                  <span class="flag flag-sale">-<?= $discount ?>%</span>
                <?php endif; ?>
              </div>
              <div class="detail-price-copy">
                <?php if ($discount !== null): ?>
                  Oferta com desconto aparente para acelerar a decisão de compra.
                <?php else: ?>
                  Preço atual destacado para comparação rápida antes de abrir a loja.
                <?php endif; ?>
              </div>
            </div>

            <?php if ($commerceHighlights): ?>
              <div class="detail-commerce-grid">
                <?php foreach ($commerceHighlights as $highlight): ?>
                  <span class="detail-commerce-chip"><?= h($highlight) ?></span>
                <?php endforeach; ?>
              </div>
            <?php endif; ?>


            <div class="cta-row" style="justify-content:flex-start;">
              <a class="button button-primary" href="?slug=<?= urlencode($offer['slug']) ?>&go=1" target="_blank" rel="noopener sponsored nofollow">Ir para a oferta</a>
            </div>
          </div>
        </div>
      </section>

      <?php if ($relatedOffers): ?>
        <section class="section-panel related-section">
          <div class="section-heading">
            <div>
              <h2>Produtos relacionados</h2>
              <div class="section-copy">Mais opções da mesma categoria ou da mesma loja para aumentar navegação e profundidade da sessão.</div>
            </div>
          </div>

          <div class="grid grid-tight">
            <?php foreach ($relatedOffers as $related): ?>
              <?php $relatedDiscount = site_discount_percent($related['preco'], $related['preco_antigo']); ?>
              <article class="card compact-card">
                <a class="card-media compact-media" href="<?= h(site_offer_redirect_href($related['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">
                  <img src="<?= h($related['imagem_url'] ?: '/assets/img/sem-img.png') ?>" alt="">
                  <div class="card-badges">
                    <?php if ($relatedDiscount !== null): ?>
                      <span class="flag flag-sale">-<?= $relatedDiscount ?>%</span>
                    <?php endif; ?>
                  </div>
                </a>
                <div class="card-body compact-body">
                  <div class="kicker"><?= h(site_store_label($related['loja'])) ?></div>
                  <div class="card-title compact-title"><?= h($related['titulo']) ?></div>
                  <div class="price-row compact-price-row">
                    <span class="price-now"><?= h(site_money($related['preco'])) ?></span>
                  </div>
                  <div class="card-footer compact-footer">
                    <a class="btn-link primary" href="<?= h(site_offer_redirect_href($related['slug'])) ?>" target="_blank" rel="noopener sponsored nofollow">Ver promoção</a>
                  </div>
                </div>
              </article>
            <?php endforeach; ?>
          </div>
        </section>
      <?php endif; ?>

    </div>
  </main>

  <?php require __DIR__ . '/inc/site_footer.php'; ?>
  <?php require __DIR__ . '/inc/site_footer_scripts.php'; ?>
</body>
</html>


