# Automacao de Ofertas (Local)

Coleta ofertas e publica na tabela `ofertas` (mesmo banco do site PHP).

## 1) Setup

```powershell
cd automacao_ofertas
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

## 2) Rodar API local

```powershell
uvicorn app.main:app --reload --port 8010
```

Healthcheck:
- http://127.0.0.1:8010/health

## 3) Rodar coleta

```powershell
curl -X POST http://127.0.0.1:8010/collect/run
```

## 4) OAuth Mercado Livre (real)
1. Preencha no `.env`: `MELI_APP_ID`, `MELI_APP_SECRET`, `MELI_REDIRECT_URI`.
2. Gere URL de autorizacao:

```powershell
curl http://127.0.0.1:8010/integrations/meli/oauth/url
```

3. Abra `auth_url`, autorize, copie o `code` de retorno.
4. Troque `code` por token:

```powershell
curl -X POST http://127.0.0.1:8010/integrations/meli/oauth/exchange -H "Content-Type: application/json" -d '{"code":"SEU_CODE"}'
```

5. Salve `access_token` e `refresh_token` no `.env`.
6. Renovar token quando necessario:

```powershell
curl -X POST http://127.0.0.1:8010/integrations/meli/oauth/refresh -H "Content-Type: application/json" -d '{"refresh_token":"SEU_REFRESH"}'
```

Com `MELI_ACCESS_TOKEN` definido, o coletor tenta importar seus itens ativos via API autenticada.

## 5) Conectores
- Mercado Livre: API publica + OAuth real.
- Shopee: API de afiliados GraphQL assinada por `SHOPEE_API_KEY` + `SHOPEE_API_SECRET`, com fallback para `SHOPEE_FEED_URL`.
- Amazon/TikTok: leitura via `*_FEED_URL` (JSON) para plugar APIs oficiais.

## 6) Facebook + Instagram (Meta)

Cadastros necessarios:
1. Criar uma pagina no Facebook para o projeto.
2. Converter o Instagram em conta profissional.
3. Vincular o Instagram profissional a essa pagina.
4. Criar um app em `https://developers.facebook.com/`.
5. Adicionar os produtos `Facebook Login` e `Instagram Graph API`.

Variaveis esperadas no `.env`:

```env
SITE_BASE_URL=https://zeropreco.com.br
META_APP_ID=
META_APP_SECRET=
META_GRAPH_API_VERSION=v23.0
META_PAGE_ID=
META_INSTAGRAM_BUSINESS_ACCOUNT_ID=
META_ACCESS_TOKEN=
MANAGER_AUTH_ENABLED=true
MANAGER_USERNAME=admin
MANAGER_PASSWORD=troque-esta-senha
AUTO_IMPORT_ENABLED=true
AUTO_IMPORT_INTERVAL_MINUTES=180
AUTO_IMPORT_PROVIDERS=mercadolivre
AUTO_IMPORT_TIMES=06:30,12:30,18:30
AUTO_SOCIAL_ENABLED=true
AUTO_SOCIAL_INTERVAL_MINUTES=240
AUTO_SOCIAL_PLATFORM=facebook
AUTO_SOCIAL_MODE=feed
AUTO_SOCIAL_LIMIT=3
AUTO_SOCIAL_TIMES=07:00,13:00,19:00
```

Preview local dos posts gerados pelo sistema:

```powershell
curl "http://127.0.0.1:8010/social/meta/post-previews?limit=10"
```

Esse preview ja devolve:
- copy pronta
- link da oferta
- payload base para Facebook
- payload base para Instagram

Fluxo recomendado:
- importar ofertas
- gerar previews
- revisar os melhores itens
- depois conectar a publicacao automatica pela Graph API

## 7) Shopee Affiliate API (real)
1. Preencha no `.env`:

```env
SHOPEE_API_KEY=SEU_CREDENTIAL
SHOPEE_API_SECRET=SEU_SECRET
SHOPEE_AFFILIATE_TAG=SEU_TRACKING
SHOPEE_API_URL=https://open-api.affiliate.shopee.com.br/graphql
SHOPEE_QUERY_TERMS=fone bluetooth,air fryer,notebook
SHOPEE_LIMIT_PER_QUERY=20
SHOPEE_PAGES_PER_QUERY=2
SHOPEE_SORT_TYPE=1
SHOPEE_PRICE_DIVISOR=100000
```

2. Teste a consulta antes da importacao:

```powershell
curl "http://127.0.0.1:8010/integrations/shopee/product-offers-preview?keyword=fone%20bluetooth&limit=10&pages=1"
```

3. Se o preview vier com itens, rode a coleta normal:

```powershell
curl -X POST http://127.0.0.1:8010/collect/run
```

Observacoes:
- O coletor usa `offerLink` da Shopee quando existir; sem isso o produto nao entra.
- O campo `SHOPEE_PRICE_DIVISOR` fica configuravel porque a API pode devolver preco em unidade menor.
- Se sua conta ainda nao tiver acesso liberado na API de afiliados, deixe `SHOPEE_FEED_URL` preenchido como fallback.

## 8) Mercado Livre com foco em giro + preco baixo

Para puxar mais produtos com chance de clique e ticket menor, ajuste no `.env`:

```env
MELI_QUERY_TERMS=fone bluetooth,caixa de som,mouse gamer,smartwatch,air fryer,panela eletrica
MELI_MIN_PRICE=0
MELI_MAX_PRICE=350
MELI_MIN_SOLD=25
MELI_MAX_RESULTS=120
MELI_SORT_MODE=sales_low_price
```

Preview antes de importar:

```powershell
curl "http://127.0.0.1:8010/integrations/meli/product-offers-preview?keyword=fone%20bluetooth&limit=20&pages=2"
```

O ranking suporta:
- `sales_low_price`: mais vendidos primeiro, desempate por menor preco
- `low_price_sales`: menor preco primeiro, desempate por vendas
- `discount_sales`: maior desconto primeiro, desempate por vendas

## 9) Meli CSV (modo rapido)

Para importar ofertas sem depender da API publica, use CSV local.

1. Configure no `.env`:

```env
MELI_CSV_PATH=./data/meli_ofertas.csv
MERCADOLIVRE_AFFILIATE_TAG=a5bPc000008ol0jIAA
```

2. Edite `data/meli_ofertas.csv` com colunas:
`title,description,price,old_price,url,image,category,tags,featured,coupon`

3. Rode:

```powershell
curl -X POST http://127.0.0.1:8010/collect/run
```

Quando o CSV tiver linhas validas, ele tem prioridade sobre API e publica direto no banco.
