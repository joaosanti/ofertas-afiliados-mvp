# MVP — Site de Ofertas (Afiliados) + Importação via Python (DreamHost Shared)

Este projeto foi montado para você (João) importar no VS Code e continuar evoluindo com o Codex.
Objetivo: **ganhar dinheiro rápido** com afiliados (Shopee / TikTok / Mercado Livre) usando um **site de ofertas** no DreamHost Shared Unlimited (PHP + MySQL).

## Por que este formato (Ofertas) e não “comparador completo”?
- Comparador estilo Buscapé/Zoom é pesado para SEO e difícil competir no começo.
- **Página de ofertas** converte mais rápido quando você traz tráfego de TikTok/Instagram/Telegram.
- Depois que tiver tração, você pode adicionar “comparar preço” em produtos mais vistos e também alertas de queda de preço.

---

## Stack escolhida (compatível com seu DreamHost Shared)
- **Frontend/Servidor:** PHP
- **Banco:** MySQL (DreamHost)
- **Automação opcional:** Python (cron) para importar/atualizar ofertas via CSV

> DreamHost Shared é ótimo para PHP/MySQL, e Python funciona bem como script/cron. Rodar Flask/FastAPI como servidor contínuo geralmente não vale a dor no Shared.

---

## Estrutura do projeto
- `public_html/` → tudo que vai para o seu site no DreamHost
- `scripts/` → scripts Python (importação) e arquivos auxiliares

```
public_html/
  .htaccess
  index.php
  oferta.php
  categoria.php
  assets/
    css/style.css
    img/sem-img.png   (placeholder vazio — você pode substituir)
  inc/
    config.php        (configure DB e SITE_URL)
    db.php
    funcoes.php
  admin/
    README.md         (nota: admin ainda não implementado aqui; MVP usa CSV+Python)
scripts/
  importar_ofertas.py
  requirements.txt
  .env.example
  ofertas.csv         (exemplo)
```

---

## 1) Configurar o banco (MySQL)
No phpMyAdmin (DreamHost) rode o SQL abaixo:

```sql
CREATE TABLE ofertas (
  id INT AUTO_INCREMENT PRIMARY KEY,
  slug VARCHAR(180) NOT NULL UNIQUE,
  titulo VARCHAR(255) NOT NULL,
  descricao TEXT NULL,
  preco DECIMAL(10,2) NOT NULL DEFAULT 0,
  preco_antigo DECIMAL(10,2) NULL,
  loja VARCHAR(40) NOT NULL,
  url_afiliado TEXT NOT NULL,
  cupom VARCHAR(60) NULL,
  imagem_url TEXT NULL,
  categoria VARCHAR(80) NOT NULL,
  tags VARCHAR(255) NULL,
  destaque TINYINT(1) NOT NULL DEFAULT 0,
  ativo TINYINT(1) NOT NULL DEFAULT 1,
  expira_em DATETIME NULL,
  criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE cliques (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  oferta_id INT NOT NULL,
  ip_hash CHAR(64) NOT NULL,
  user_agent VARCHAR(255) NULL,
  referer TEXT NULL,
  criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX (oferta_id),
  CONSTRAINT fk_clique_oferta FOREIGN KEY (oferta_id) REFERENCES ofertas(id) ON DELETE CASCADE
);

CREATE TABLE admin_users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  email VARCHAR(180) NOT NULL UNIQUE,
  senha_hash VARCHAR(255) NOT NULL,
  criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

---

## 2) Configurar o PHP
Edite `public_html/inc/config.php`:

- `DB_NAME`, `DB_USER`, `DB_PASS` → conforme seu MySQL no DreamHost
- `SITE_URL` → seu domínio

---

## 3) URLs amigáveis
O `.htaccess` já está pronto para:

- `/` → home
- `/categoria/eletronicos` → lista por categoria
- `/oferta/air-fryer-5l` → página da oferta

---

## 4) Importação por CSV (mais rápido para começar)
Use `scripts/ofertas.csv` como base. Você pode preencher manualmente 20–50 ofertas boas.

Campos:
- `titulo, preco, preco_antigo, loja, url_afiliado, cupom, imagem_url, categoria, tags, destaque`

---

## 5) Rodar a importação local (VS Code) ou no DreamHost via SSH

### Local (recomendado para testar)
Crie um venv e instale dependências:

```bash
cd scripts
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
```

Crie um `.env` baseado em `.env.example` e rode:

```bash
python importar_ofertas.py
```

### No DreamHost (via SSH)
Mesma ideia, só ajustando caminhos e variáveis. Você pode exportar variáveis no `.bash_profile`
ou carregar usando ferramentas externas. Neste MVP, o script lê variáveis de ambiente.

---

## 6) Cron job (atualizar automaticamente)
Exemplo (a cada 30 min), ajustando paths:

```bash
*/30 * * * * /home/SEU_USER/seu_projeto/scripts/.venv/bin/python /home/SEU_USER/seu_projeto/scripts/importar_ofertas.py >> /home/SEU_USER/seu_projeto/scripts/log_import.txt 2>&1
```

---

## 7) Estratégia rápida de tráfego (TikTok)
- 2 a 4 vídeos/dia por 14 dias.
- Vídeos de 10–18s com:
  - “Oferta absurda de hoje”
  - preço “era X, agora Y”
  - cupom (se houver)
  - CTA: “link no site / ofertas do dia”
- Use sempre o mesmo destino: `/ofertas-do-dia.php`.

---

## Próximas evoluções (quando começar a vender)
1) Implementar painel admin (cadastro/edição) em `public_html/admin/`
2) Página “Top do dia” separada, com filtros por loja/categoria
3) “Comparar preço” opcional só para produtos mais clicados
4) Alertas de queda de preço (email/telegram) — vira renda recorrente

---

## Observações sobre afiliados
- Use sempre links oficiais de afiliado/creator de cada plataforma.
- Evite scraping pesado. Prefira feeds/parcerias quando existir.
- Este MVP foca em publicar ofertas rapidamente com rastreio de cliques (básico).

---

## Licença
Uso pessoal/comercial (seu).

Boa sorte e bora colocar no ar. 🔥
