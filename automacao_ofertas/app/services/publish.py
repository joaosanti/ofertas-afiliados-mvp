import json

from sqlalchemy import text

from app.schemas import NormalizedOffer
from app.services.normalize import build_slug


UPSERT_SQL = text("""
INSERT INTO ofertas
(slug, titulo, descricao, preco, preco_antigo, desconto_percentual, preco_pix, preco_outros_meios, parcelas_texto, frete_texto, avaliacao_nota, avaliacao_total, promocao_texto, loja, url_afiliado, cupom, imagem_url, imagem_urls_json, video_urls_json, categoria, tags, destaque, ativo, criado_por_admin_id, criado_por_login)
VALUES
(:slug, :titulo, :descricao, :preco, :preco_antigo, :desconto_percentual, :preco_pix, :preco_outros_meios, :parcelas_texto, :frete_texto, :avaliacao_nota, :avaliacao_total, :promocao_texto, :loja, :url_afiliado, :cupom, :imagem_url, :imagem_urls_json, :video_urls_json, :categoria, :tags, :destaque, :ativo, :criado_por_admin_id, :criado_por_login)
ON DUPLICATE KEY UPDATE
  titulo = VALUES(titulo),
  descricao = VALUES(descricao),
  preco = VALUES(preco),
  preco_antigo = VALUES(preco_antigo),
  desconto_percentual = VALUES(desconto_percentual),
  preco_pix = VALUES(preco_pix),
  preco_outros_meios = VALUES(preco_outros_meios),
  parcelas_texto = VALUES(parcelas_texto),
  frete_texto = VALUES(frete_texto),
  avaliacao_nota = VALUES(avaliacao_nota),
  avaliacao_total = VALUES(avaliacao_total),
  promocao_texto = VALUES(promocao_texto),
  loja = VALUES(loja),
  url_afiliado = VALUES(url_afiliado),
  cupom = VALUES(cupom),
  imagem_url = VALUES(imagem_url),
  imagem_urls_json = VALUES(imagem_urls_json),
  video_urls_json = VALUES(video_urls_json),
  categoria = VALUES(categoria),
  tags = VALUES(tags),
  destaque = VALUES(destaque),
  ativo = VALUES(ativo)
""")

CHECK_SLUG_SQL = text("SELECT id FROM ofertas WHERE slug = :slug LIMIT 1")


def publish_offer(db, offer: NormalizedOffer, actor_user_id: int | None = None, actor_login: str | None = None) -> str:
    if float(offer.preco or 0) <= 0 and int(offer.ativo or 1) != 0:
        return "skipped"

    slug = build_slug(offer.titulo)
    existing = db.execute(CHECK_SLUG_SQL, {"slug": slug}).scalar()
    payload = offer.model_dump()
    payload["slug"] = slug
    payload["imagem_urls_json"] = json.dumps(offer.imagem_urls, ensure_ascii=True) if offer.imagem_urls else None
    payload["video_urls_json"] = json.dumps(offer.video_urls, ensure_ascii=True) if offer.video_urls else None
    payload["criado_por_admin_id"] = actor_user_id
    payload["criado_por_login"] = actor_login
    db.execute(UPSERT_SQL, payload)
    return "updated" if existing else "created"
