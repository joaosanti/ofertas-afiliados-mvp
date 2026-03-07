from pydantic import BaseModel


class NormalizedOffer(BaseModel):
    titulo: str
    descricao: str = ""
    preco: float
    preco_antigo: float | None = None
    loja: str
    url_afiliado: str
    cupom: str | None = None
    imagem_url: str | None = None
    categoria: str = "ofertas"
    tags: str | None = None
    destaque: int = 0
    ativo: int = 1
