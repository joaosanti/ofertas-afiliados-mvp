from sqlalchemy import text
from app.services.normalize import build_slug
from app.schemas import NormalizedOffer


UPSERT_SQL = text("""
INSERT INTO ofertas
(slug, titulo, descricao, preco, preco_antigo, loja, url_afiliado, cupom, imagem_url, categoria, tags, destaque, ativo)
VALUES
(:slug, :titulo, :descricao, :preco, :preco_antigo, :loja, :url_afiliado, :cupom, :imagem_url, :categoria, :tags, :destaque, :ativo)
ON DUPLICATE KEY UPDATE
  titulo = VALUES(titulo),
  descricao = VALUES(descricao),
  preco = VALUES(preco),
  preco_antigo = VALUES(preco_antigo),
  loja = VALUES(loja),
  url_afiliado = VALUES(url_afiliado),
  cupom = VALUES(cupom),
  imagem_url = VALUES(imagem_url),
  categoria = VALUES(categoria),
  tags = VALUES(tags),
  destaque = VALUES(destaque),
  ativo = VALUES(ativo)
""")

CHECK_SLUG_SQL = text("SELECT id FROM ofertas WHERE slug = :slug LIMIT 1")


def publish_offer(db, offer: NormalizedOffer) -> str:
    slug = build_slug(offer.titulo)
    existing = db.execute(CHECK_SLUG_SQL, {"slug": slug}).scalar()
    payload = offer.model_dump()
    payload["slug"] = slug
    db.execute(UPSERT_SQL, payload)
    return "updated" if existing else "created"
