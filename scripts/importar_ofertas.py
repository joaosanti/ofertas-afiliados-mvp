import csv
import os
from datetime import datetime

import pymysql
from slugify import slugify


def getenv(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return v if v is not None and str(v).strip() != "" else default


def repair_text(value):
    if value is None:
        return ""

    text = str(value).strip()
    if not text:
        return ""

    suspicious = ("Ã", "Â", "â€™", "â€œ", "â€", "�")
    if any(token in text for token in suspicious):
        try:
            repaired = text.encode("latin-1").decode("utf-8")
            if repaired:
                text = repaired
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass

    return text


def open_csv_text(path: str) -> str:
    with open(path, "rb") as f:
        raw = f.read()

    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue

    return raw.decode("utf-8", errors="replace")


DB_HOST = getenv("DB_HOST", "localhost")
DB_NAME = getenv("DB_NAME", "SEU_DB")
DB_USER = getenv("DB_USER", "SEU_USER")
DB_PASS = getenv("DB_PASS", "SUA_SENHA")
CSV_PATH = getenv("CSV_PATH", "ofertas.csv")


def conectar():
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


UPSERT_SQL = """
INSERT INTO ofertas
(slug, titulo, descricao, preco, preco_antigo, loja, url_afiliado, cupom, imagem_url, categoria, tags, destaque, ativo, expira_em)
VALUES
(%s, %s, NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, NULL)
ON DUPLICATE KEY UPDATE
titulo=VALUES(titulo),
preco=VALUES(preco),
preco_antigo=VALUES(preco_antigo),
loja=VALUES(loja),
url_afiliado=VALUES(url_afiliado),
cupom=VALUES(cupom),
imagem_url=VALUES(imagem_url),
categoria=VALUES(categoria),
tags=VALUES(tags),
destaque=VALUES(destaque),
ativo=1;
"""


def as_float(v):
    if v is None:
        return 0.0

    s = repair_text(v)
    if not s:
        return 0.0

    # aceita "279,90", "279.90" e tambem "1.299,90"
    s = s.replace(".", "").replace(",", ".")
    return float(s)


def main(csv_path: str):
    conn = conectar()
    total = 0
    csv_text = open_csv_text(csv_path)

    with conn.cursor() as cur:
        reader = csv.DictReader(csv_text.splitlines())
        for row in reader:
            titulo = repair_text(row.get("titulo"))
            if not titulo:
                continue

            slug = slugify(titulo)[:170]

            preco = as_float(row.get("preco"))
            preco_antigo_raw = repair_text(row.get("preco_antigo"))
            preco_antigo = as_float(preco_antigo_raw) if preco_antigo_raw else None

            loja = repair_text(row.get("loja")).lower()[:40]
            url_afiliado = repair_text(row.get("url_afiliado"))
            cupom = repair_text(row.get("cupom"))[:60] or None
            imagem_url = repair_text(row.get("imagem_url")) or None
            categoria = repair_text(row.get("categoria") or "geral")[:80]
            tags = repair_text(row.get("tags"))[:255] or None
            destaque = int((repair_text(row.get("destaque") or "0")) or 0)

            if not url_afiliado:
                continue

            cur.execute(
                UPSERT_SQL,
                (
                    slug,
                    titulo,
                    preco,
                    preco_antigo,
                    loja,
                    url_afiliado,
                    cupom,
                    imagem_url,
                    categoria,
                    tags,
                    destaque,
                ),
            )
            total += 1

    print(f"[{datetime.now().isoformat(timespec='seconds')}] importadas/atualizadas: {total}")


if __name__ == "__main__":
    main(CSV_PATH)
