import re
import unicodedata
from typing import Any

from sqlalchemy import text


CATEGORY_PATTERNS: list[tuple[tuple[str, ...], str]] = [
    (("mouse", "mouse gamer"), "Mouses"),
    (("teclado", "keyboard"), "Teclados"),
    (("controle", "joystick", "gamepad"), "Controles"),
    (("monitor", "display"), "Monitores"),
    (("smartwatch", "watch", "relogio inteligente", "relogio smart"), "Smartwatches"),
    (("fone", "headphone", "earbuds", "bluetooth"), "Fones de Ouvido"),
    (("caixa de som", "speaker", "soundbar"), "Caixas Acusticas"),
    (("air fryer", "fritadeira"), "Fritadeiras Eletricas"),
    (("panela", "pressao eletrica", "panela eletrica"), "Panelas Eletricas"),
    (("cooktop", "forno eletrico", "microondas", "fogao"), "Eletrodomesticos"),
    (("umidificador", "humidificador"), "Umidificadores"),
    (("escova", "secador", "chapinha"), "Escovas Eletricas"),
    (("notebook", "laptop"), "Notebooks"),
    (("pc gamer", "computador", "desktop"), "Computadores"),
    (("tv", "smart tv", "televis"), "Smart TVs"),
    (("iphone", "samsung", "motorola", "xiaomi", "realme", "celular", "smartphone"), "Celulares e Smartphones"),
    (("cadeira", "escritorio"), "Cadeiras de Escritorio"),
    (("mesa",), "Mesas"),
    (("sofa", "rack", "guarda roupa", "armario"), "Moveis"),
    (("cama", "colchao", "travesseiro"), "Cama e Banho"),
    (("aspirador",), "Aspiradores"),
    (("liquidificador", "batedeira", "sanduicheira", "cafeteira", "chaleira"), "Eletroportateis"),
    (("garrafa termica", "garrafa", "copo termico"), "Utilidades Domesticas"),
    (("taca", "copo", "prato", "talher", "pote", "marmita"), "Utilidades Domesticas"),
    (("toalha", "lencol", "fronha", "edredom"), "Cama e Banho"),
    (("bolsa", "mochila", "carteira", "mala"), "Bolsas e Mochilas"),
    (("camiseta", "camisa", "blusa", "jaqueta", "calca", "bermuda", "short", "vestido", "saia"), "Moda"),
    (("tenis", "sapato", "chinelo", "sandalia"), "Calcados"),
    (("perfume", "hidratante", "maquiagem", "batom", "creme", "cosmetico"), "Beleza"),
    (("kit bebe", "bebe", "mamadeira", "fralda"), "Bebe"),
    (("whey", "suplemento", "creatina", "protein"), "Suplementos"),
    (("bicicleta", "esteira", "halter", "fitness"), "Esportes e Fitness"),
    (("pet", "cachorro", "gato", "racao"), "Pet Shop"),
    (("lampada", "led", "iluminacao"), "Iluminacao"),
    (("camera", "webcam"), "Cameras"),
]


def _normalize_token(value: Any) -> str:
    text_value = str(value or "").strip().lower()
    if not text_value:
        return ""
    text_value = unicodedata.normalize("NFKD", text_value)
    text_value = "".join(char for char in text_value if not unicodedata.combining(char))
    text_value = re.sub(r"[^a-z0-9]+", " ", text_value)
    return re.sub(r"\s+", " ", text_value).strip()


def infer_category_label(*values: Any, default: str = "ofertas") -> str:
    haystack = " ".join(_normalize_token(value) for value in values if value).strip()
    if not haystack:
        return default
    for patterns, label in CATEGORY_PATTERNS:
        if any(pattern in haystack for pattern in patterns):
            return label
    return default


def recategorize_store_offers(db, store: str, only_uncategorized: bool = True) -> dict[str, int]:
    conditions = ["ativo = 1", "LOWER(loja) = LOWER(:store)"]
    if only_uncategorized:
        conditions.append("LOWER(categoria) = 'ofertas'")

    rows = db.execute(
        text(
            f"""
            SELECT id, titulo, descricao, categoria, url_afiliado, tags
            FROM ofertas
            WHERE {' AND '.join(conditions)}
            ORDER BY atualizado_em DESC, id DESC
            """
        ),
        {"store": store},
    ).mappings().all()

    updated = 0
    skipped = 0
    for row in rows:
        new_category = infer_category_label(
            row["titulo"],
            row["descricao"],
            row["url_afiliado"],
            row["tags"],
            default=row["categoria"] or "ofertas",
        )
        if not new_category or new_category == (row["categoria"] or ""):
            skipped += 1
            continue
        db.execute(
            text("UPDATE ofertas SET categoria = :categoria WHERE id = :id"),
            {"categoria": new_category, "id": row["id"]},
        )
        updated += 1

    return {"processed": len(rows), "updated": updated, "skipped": skipped}
