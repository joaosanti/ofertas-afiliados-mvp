from pydantic import BaseModel


class NormalizedOffer(BaseModel):
    titulo: str
    descricao: str = ""
    preco: float
    preco_antigo: float | None = None
    desconto_percentual: int | None = None
    preco_pix: float | None = None
    preco_outros_meios: float | None = None
    parcelas_texto: str | None = None
    frete_texto: str | None = None
    avaliacao_nota: float | None = None
    avaliacao_total: int | None = None
    promocao_texto: str | None = None
    loja: str
    url_afiliado: str
    cupom: str | None = None
    imagem_url: str | None = None
    imagem_urls: list[str] | None = None
    video_urls: list[str] | None = None
    categoria: str = "ofertas"
    tags: str | None = None
    destaque: int = 0
    ativo: int = 1
