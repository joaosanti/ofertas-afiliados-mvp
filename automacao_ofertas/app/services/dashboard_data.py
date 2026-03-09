import json
import os
from typing import Any

from sqlalchemy import text


CATEGORY_LABELS = {
    "mlb1055": "Celulares e Smartphones",
    "mlb1714": "Mouses",
    "mlb135384": "Smartwatches",
    "mlb7457": "Fones e Kits Viva Voz",
    "mlb264715": "Escovas Elétricas",
    "mlb120425": "Umidificadores",
    "mlb456045": "Ar-Condicionado",
    "mlb48666": "Panelas Elétricas",
    "mlb120373": "Panela de Arroz",
    "mlb196208": "Fones de Ouvido",
    "mlb3843": "Caixas Bluetooth",
    "mlb268503": "Difusores de Aromas Elétricos",
    "mlb11507": "Caixas Acústicas",
    "mlb271858": "Smartbands",
    "mlb439402": "Panelas a Vapor",
    "mlb433422": "Escovas Alisadoras para Barba",
    "mlb264184": "Cadeiras de Banho",
    "mlb31682": "Panelas de Óleo",
    "mlb107501": "Caçarolas e Caldeirões",
    "mlb1664": "Fones",
}


CREATE_EXECUTIONS_SQL = text(
    """
    CREATE TABLE IF NOT EXISTS automacao_execucoes (
      id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
      tipo VARCHAR(40) NOT NULL,
      provider VARCHAR(50) NULL,
      canal VARCHAR(50) NULL,
      modo VARCHAR(50) NULL,
      status VARCHAR(20) NOT NULL DEFAULT 'running',
      requested_count INT NOT NULL DEFAULT 0,
      processed_count INT NOT NULL DEFAULT 0,
      payload_json LONGTEXT NULL,
      result_json LONGTEXT NULL,
      error_message TEXT NULL,
      criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      finalizado_em DATETIME NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """
)


OVERVIEW_SQL = text(
    """
    SELECT
      (SELECT COUNT(*) FROM ofertas WHERE ativo = 1 AND (expira_em IS NULL OR expira_em > NOW())) AS active_offers,
      (SELECT COUNT(*) FROM ofertas WHERE ativo = 1 AND destaque = 1 AND (expira_em IS NULL OR expira_em > NOW())) AS featured_offers,
      (SELECT COUNT(DISTINCT loja) FROM ofertas WHERE ativo = 1 AND (expira_em IS NULL OR expira_em > NOW())) AS tracked_stores,
      (SELECT COUNT(*) FROM cliques WHERE criado_em >= NOW() - INTERVAL 7 DAY) AS clicks_7d,
      (SELECT COUNT(*) FROM cliques WHERE criado_em >= NOW() - INTERVAL 30 DAY) AS clicks_30d,
      (SELECT ROUND(AVG(preco), 2) FROM ofertas WHERE ativo = 1 AND (expira_em IS NULL OR expira_em > NOW())) AS average_price,
      (SELECT COUNT(*) FROM automacao_execucoes WHERE tipo = 'import' AND status = 'success' AND criado_em >= NOW() - INTERVAL 7 DAY) AS import_runs_7d,
      (SELECT COALESCE(SUM(processed_count), 0) FROM automacao_execucoes WHERE tipo = 'social' AND status = 'success' AND criado_em >= NOW() - INTERVAL 7 DAY) AS social_posts_7d
    """
)


CLICKS_BY_DAY_SQL = text(
    """
    SELECT DATE(criado_em) AS day, COUNT(*) AS total
    FROM cliques
    WHERE criado_em >= CURRENT_DATE - INTERVAL :days DAY
    GROUP BY DATE(criado_em)
    ORDER BY day ASC
    """
)


OFFERS_BY_STORE_SQL = text(
    """
    SELECT loja AS label, COUNT(*) AS total
    FROM ofertas
    WHERE ativo = 1 AND (expira_em IS NULL OR expira_em > NOW())
    GROUP BY loja
    ORDER BY total DESC, loja ASC
    LIMIT 8
    """
)


CATEGORIES_SQL = text(
    """
    SELECT categoria AS label, COUNT(*) AS total
    FROM ofertas
    WHERE ativo = 1 AND (expira_em IS NULL OR expira_em > NOW())
    GROUP BY categoria
    ORDER BY total DESC, categoria ASC
    LIMIT 8
    """
)


TOP_CLICKED_SQL = text(
    """
    SELECT
      o.id,
      o.slug,
      o.titulo,
      o.loja,
      o.categoria,
      o.preco,
      o.imagem_url,
      COUNT(c.id) AS clicks
    FROM ofertas o
    LEFT JOIN cliques c
      ON c.oferta_id = o.id
      AND c.criado_em >= NOW() - INTERVAL :days DAY
    WHERE o.ativo = 1
      AND (o.expira_em IS NULL OR o.expira_em > NOW())
    GROUP BY o.id, o.slug, o.titulo, o.loja, o.categoria, o.preco, o.imagem_url
    ORDER BY clicks DESC, o.destaque DESC, o.atualizado_em DESC
    LIMIT :limit
    """
)


RECENT_OFFERS_SQL = text(
    """
    SELECT
      id,
      slug,
      titulo,
      loja,
      categoria,
      preco,
      preco_antigo,
      cupom,
      imagem_url,
      atualizado_em
    FROM ofertas
    WHERE ativo = 1
      AND (expira_em IS NULL OR expira_em > NOW())
    ORDER BY atualizado_em DESC, criado_em DESC
    LIMIT :limit
    """
)


RECENT_RUNS_SQL = text(
    """
    SELECT
      id,
      tipo,
      provider,
      canal,
      modo,
      status,
      requested_count,
      processed_count,
      error_message,
      criado_em,
      finalizado_em
    FROM automacao_execucoes
    ORDER BY criado_em DESC
    LIMIT :limit
    """
)


RUNS_BY_DAY_SQL = text(
    """
    SELECT
      DATE(criado_em) AS day,
      tipo,
      COUNT(*) AS total,
      COALESCE(SUM(processed_count), 0) AS processed
    FROM automacao_execucoes
    WHERE criado_em >= CURRENT_DATE - INTERVAL :days DAY
    GROUP BY DATE(criado_em), tipo
    ORDER BY day ASC, tipo ASC
    """
)


def ensure_dashboard_tables(db) -> None:
    db.execute(CREATE_EXECUTIONS_SQL)
    db.commit()


def _json_dump(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=True, default=str)


def record_execution_start(
    db,
    *,
    tipo: str,
    provider: str | None = None,
    canal: str | None = None,
    modo: str | None = None,
    requested_count: int = 0,
    payload: Any = None,
) -> int:
    ensure_dashboard_tables(db)
    result = db.execute(
        text(
            """
            INSERT INTO automacao_execucoes
            (tipo, provider, canal, modo, status, requested_count, payload_json)
            VALUES
            (:tipo, :provider, :canal, :modo, 'running', :requested_count, :payload_json)
            """
        ),
        {
            "tipo": tipo,
            "provider": provider,
            "canal": canal,
            "modo": modo,
            "requested_count": requested_count,
            "payload_json": _json_dump(payload),
        },
    )
    db.commit()
    return int(result.lastrowid)


def record_execution_success(db, execution_id: int, *, processed_count: int = 0, result: Any = None) -> None:
    db.execute(
        text(
            """
            UPDATE automacao_execucoes
            SET status = 'success',
                processed_count = :processed_count,
                result_json = :result_json,
                finalizado_em = NOW()
            WHERE id = :id
            """
        ),
        {
            "id": execution_id,
            "processed_count": processed_count,
            "result_json": _json_dump(result),
        },
    )
    db.commit()


def record_execution_error(db, execution_id: int, *, error_message: str, result: Any = None) -> None:
    db.execute(
        text(
            """
            UPDATE automacao_execucoes
            SET status = 'error',
                result_json = :result_json,
                error_message = :error_message,
                finalizado_em = NOW()
            WHERE id = :id
            """
        ),
        {
            "id": execution_id,
            "result_json": _json_dump(result),
            "error_message": (error_message or "")[:2000],
        },
    )
    db.commit()


def _rows_to_chart(rows, key_label: str = "label") -> list[dict[str, Any]]:
    return [{"label": row[key_label], "value": int(row["total"] or 0)} for row in rows]


def _category_label(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return "Geral"
    lowered = raw.lower()
    if lowered == "geral":
        return "Todas as categorias"
    if lowered in CATEGORY_LABELS:
        return CATEGORY_LABELS[lowered]
    if lowered.startswith("mlb"):
        return "Categoria Mercado Livre"
    return raw.replace("-", " ").replace("_", " ").strip() or "Geral"


def _provider_status(label: str, enabled: bool, mode: str, notes: str) -> dict[str, Any]:
    return {
        "provider": label,
        "enabled": enabled,
        "mode": mode,
        "notes": notes,
    }


def build_provider_status() -> dict[str, Any]:
    return {
        "imports": [
            _provider_status(
                "Mercado Livre",
                bool((os.getenv("MELI_ACCESS_TOKEN") or "").strip() or (os.getenv("MELI_CSV_PATH") or "").strip()),
                "API/OAuth + CSV",
                "Importador ativo com preview e importacao real.",
            ),
            _provider_status(
                "Shopee",
                bool((os.getenv("SHOPEE_API_KEY") or "").strip() or (os.getenv("SHOPEE_FEED_URL") or "").strip()),
                "GraphQL/API",
                "Estrutura pronta; depende das credenciais liberadas.",
            ),
            _provider_status(
                "Amazon",
                bool((os.getenv("AMAZON_FEED_URL") or "").strip() or (os.getenv("AMAZON_ACCESS_KEY") or "").strip()),
                "Feed/API",
                "Conector futuro; operacao depende das credenciais oficiais.",
            ),
            _provider_status(
                "TikTok",
                bool((os.getenv("TIKTOK_FEED_URL") or "").strip() or (os.getenv("TIKTOK_APP_ID") or "").strip()),
                "Feed/API",
                "Conector futuro; social e catalogo podem compartilhar a origem.",
            ),
        ],
        "social": [
            _provider_status(
                "Facebook Feed",
                bool((os.getenv("META_PAGE_ID") or "").strip() and (os.getenv("META_ACCESS_TOKEN") or "").strip()),
                "Meta Graph API",
                "Publicacao validada em producao.",
            ),
            _provider_status(
                "Facebook Reel",
                bool((os.getenv("META_PAGE_ID") or "").strip() and (os.getenv("META_ACCESS_TOKEN") or "").strip()),
                "Meta Graph API",
                "Fluxo por video MP4 vertical para a pagina do Facebook.",
            ),
            _provider_status(
                "Instagram Feed",
                bool((os.getenv("META_INSTAGRAM_BUSINESS_ACCOUNT_ID") or "").strip() and (os.getenv("META_ACCESS_TOKEN") or "").strip()),
                "Instagram Graph API",
                "Feed validado com create + publish.",
            ),
            _provider_status(
                "Instagram Story",
                bool((os.getenv("META_INSTAGRAM_BUSINESS_ACCOUNT_ID") or "").strip() and (os.getenv("META_ACCESS_TOKEN") or "").strip()),
                "Instagram Graph API",
                "Geracao pronta; publicacao ainda sensivel aos requisitos de media URI da Meta.",
            ),
        ],
    }


def fetch_dashboard_snapshot(db) -> dict[str, Any]:
    ensure_dashboard_tables(db)
    overview = dict(db.execute(OVERVIEW_SQL).mappings().one())
    click_rows = db.execute(CLICKS_BY_DAY_SQL, {"days": 14}).mappings().all()
    store_rows = db.execute(OFFERS_BY_STORE_SQL).mappings().all()
    category_rows = db.execute(CATEGORIES_SQL).mappings().all()
    top_clicked_rows = db.execute(TOP_CLICKED_SQL, {"days": 30, "limit": 10}).mappings().all()
    recent_offer_rows = db.execute(RECENT_OFFERS_SQL, {"limit": 10}).mappings().all()
    recent_run_rows = db.execute(RECENT_RUNS_SQL, {"limit": 5}).mappings().all()
    run_chart_rows = db.execute(RUNS_BY_DAY_SQL, {"days": 14}).mappings().all()

    clicks_by_day = [{"label": str(row["day"]), "value": int(row["total"] or 0)} for row in click_rows]
    runs_by_day: dict[str, dict[str, Any]] = {}
    for row in run_chart_rows:
        day = str(row["day"])
        bucket = runs_by_day.setdefault(day, {"label": day, "import": 0, "social": 0, "processed": 0})
        if row["tipo"] == "import":
            bucket["import"] = int(row["total"] or 0)
        elif row["tipo"] == "social":
            bucket["social"] = int(row["total"] or 0)
        bucket["processed"] += int(row["processed"] or 0)

    return {
        "overview": {
            "active_offers": int(overview["active_offers"] or 0),
            "featured_offers": int(overview["featured_offers"] or 0),
            "tracked_stores": int(overview["tracked_stores"] or 0),
            "clicks_7d": int(overview["clicks_7d"] or 0),
            "clicks_30d": int(overview["clicks_30d"] or 0),
            "average_price": float(overview["average_price"] or 0),
            "import_runs_7d": int(overview["import_runs_7d"] or 0),
            "social_posts_7d": int(overview["social_posts_7d"] or 0),
        },
        "charts": {
            "clicks_by_day": clicks_by_day,
            "offers_by_store": _rows_to_chart(store_rows),
            "offers_by_category": [{"label": _category_label(row["label"]), "value": int(row["total"] or 0)} for row in category_rows],
            "runs_by_day": list(runs_by_day.values()),
        },
        "top_clicked": [
            dict(row)
            | {
                "categoria": _category_label(row["categoria"]),
                "clicks": int(row["clicks"] or 0),
                "preco": float(row["preco"] or 0),
            }
            for row in top_clicked_rows
        ],
        "recent_offers": [
            dict(row)
            | {
                "categoria": _category_label(row["categoria"]),
                "preco": float(row["preco"] or 0),
                "preco_antigo": float(row["preco_antigo"]) if row["preco_antigo"] is not None else None,
            }
            for row in recent_offer_rows
        ],
        "recent_runs": [
            dict(row)
            | {
                "requested_count": int(row["requested_count"] or 0),
                "processed_count": int(row["processed_count"] or 0),
            }
            for row in recent_run_rows
        ],
        "status": build_provider_status(),
    }
