# Admin simples
Painel implementado com:
- login
- criar/editar oferta
- ativar/desativar oferta
- marcar/remover destaque

## URLs
- `/admin/index.php` -> login
- `/admin/ofertas.php` -> listagem e acoes rapidas
- `/admin/oferta_editar.php` -> nova oferta
- `/admin/oferta_editar.php?id=123` -> editar oferta
- `/admin/social.php` -> fluxo social para Meta e WhatsApp
- `/admin/shopee_video.php` -> fila manual de Shopee Video
- `/admin/youtube_cortes.php` -> cortes e publicacao no YouTube

## Como criar o primeiro usuario admin
1. Gere um hash de senha no PHP:

```bash
php -r "echo password_hash('SUA_SENHA_FORTE', PASSWORD_DEFAULT), PHP_EOL;"
```

2. No MySQL/phpMyAdmin, rode:

```sql
INSERT INTO admin_users (email, senha_hash)
VALUES ('seuemail@dominio.com', 'COLE_AQUI_O_HASH');
```

Depois disso, acesse `/admin/index.php` e entre com email/senha.

## Shopee Video
- A tela `/admin/shopee_video.php` usa as ofertas `Shopee` ja salvas no banco.
- Quando existe `shopee_video_url:` ou `offer_video_url:` nas tags da oferta, o admin marca o item como com video detectado.
- O fluxo atual prepara rascunho, legenda, exportacao CSV, controle de status e um `pacote profissional` por draft.
- O pacote profissional gera briefing, checklist, metadata, poster, card e video-base vertical para facilitar a postagem manual no app.
- Publicacao automatica no feed do Shopee Video ainda nao esta disponivel neste projeto porque nao ha endpoint publico confirmado para isso.
