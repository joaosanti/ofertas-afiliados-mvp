# Shopee Video Admin

## Objetivo

Usar o catalogo salvo no MySQL para montar um fluxo operacional de `Shopee Video` sem depender de publicacao automatica que hoje nao tem endpoint publico confirmado.
O foco atual e deixar a postagem manual mais profissional e mais rapida.

## O que foi implementado

- tabela `shopee_video_drafts` criada pelo bootstrap do admin
- tela `/admin/shopee_video.php`
- selecao de ofertas `Shopee` do banco
- deteccao do video do produto pelas tags:
  - `shopee_video_url:`
  - `offer_video_url:`
- geracao de legenda base
- geracao de criativo por draft:
  - hook
  - texto de capa
  - CTA
  - hashtags
  - plano de cortes
  - checklist de publicacao
- geracao de `pacote profissional` por draft via runner Python
- aba `Pacotes pro ativos` para copiar hooks, CTA e baixar os arquivos depois
- limpeza automatica dos arquivos do pacote apos `24 horas`
- assets entregues pelo pacote:
  - `brief.txt`
  - `caption.txt`
  - `publish-checklist.txt`
  - `metadata.json`
  - `poster`
  - `card`
  - `video base` vertical a partir da imagem
  - `video original` quando existir fonte baixavel
- status da fila:
  - `manual_ready`
  - `needs_video`
  - `api_blocked`
  - `published`
  - `error`
  - `archived`
- status do pacote:
  - `not_started`
  - `ready`
  - `stale`
  - `error`
- exportacao CSV dos rascunhos selecionados

## Fluxo recomendado

1. Importar ou cadastrar ofertas Shopee normalmente.
2. Garantir que a oferta tenha link afiliado valido.
3. Se o coletor capturou video, abrir `/admin/shopee_video.php`.
4. Filtrar por `So com video`.
5. Selecionar as ofertas.
6. Gerar rascunhos no modo `Manual pronto`.
7. Abrir cada draft e clicar em `Gerar pacote pro`.
8. Baixar `brief`, `poster`, `video base` ou `video original`.
9. Editar ou postar manualmente no app da Shopee.
10. Voltar ao admin e marcar `Publicado`.
11. Se precisar copiar depois, usar a aba `Pacotes pro ativos` enquanto o material ainda estiver dentro da janela de 24h.

## Sobre API

- O painel detecta se `SHOPEE_API_KEY` e `SHOPEE_API_SECRET` existem no ambiente ou em `automacao_ofertas/.env`.
- Isso serve apenas para indicar que a API de catalogo/afiliados pode estar configurada.
- O MVP nao publica por API no `Shopee Video` porque a documentacao publica disponivel nao confirma um endpoint oficial para isso.

## Campos uteis no banco

Tabela `shopee_video_drafts`:

- `oferta_id`
- `status`
- `publish_mode`
- `caption`
- `affiliate_url`
- `video_source_url`
- `published_at`

## Melhorias futuras

- gerar pacote profissional em lote
- publicar o poster do pacote como preview dentro da tela
- suportar templates editoriais por nicho
- registrar historico de regeneracao por draft
- integrar fila mobile ou automacao de dispositivo quando existir um caminho seguro
