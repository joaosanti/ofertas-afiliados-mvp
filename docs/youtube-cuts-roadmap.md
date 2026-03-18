# Roadmap de Cortes YouTube

## Objetivo

Criar no dashboard Python um fluxo para analisar um video do YouTube, sugerir cortes, gerar shorts verticais e publicar no canal com descricao enriquecida por ofertas recentes.

## Fase 1

Status: em andamento

Escopo:
- area nova `Cortes YouTube` no manager Python
- campo para colar link do video
- analise inicial do video
- preview do embed
- lista de sugestoes editoriais de cortes
- rascunho de legenda para cada corte

Observacao:
- esta fase ainda nao corta o video automaticamente
- esta fase ainda nao publica no YouTube
- esta fase prepara o intake e o briefing para a proxima etapa

## Fase 2

Escopo:
- baixar video/audio
- gerar cortes reais com ffmpeg
- transformar em vertical 9:16
- gerar legenda para o video curto
- exportar arquivos MP4 prontos

## Fase 3

Escopo:
- integrar com YouTube Data API
- autenticar via OAuth 2.0 do Google
- publicar Shorts com titulo, descricao e privacidade
- subir legenda e thumbnail quando fizer sentido

## Fase 4

Escopo:
- incluir os 5 ultimos produtos postados nas redes na descricao do video
- opcional: score por nicho e tema em alta
- opcional: fila de aprovacao manual antes da publicacao

## Dependencias previstas

- YouTube Data API
- OAuth 2.0 Google
- OpenAI para transcricao e apoio editorial
- yt-dlp para baixar video
- ffmpeg para gerar os cortes
