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
