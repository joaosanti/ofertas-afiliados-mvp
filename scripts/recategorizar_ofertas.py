from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "automacao_ofertas"))

from sqlalchemy import text  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.services.category_inference import infer_category_label  # noqa: E402


def safe_print(message: str) -> None:
    sys.stdout.buffer.write((message + "\n").encode("utf-8", errors="replace"))


def find_category_updates(db):
    rows = db.execute(
        text(
            """
            SELECT id, loja, titulo, descricao, categoria, url_afiliado, tags
            FROM ofertas
            WHERE ativo = 1
            ORDER BY atualizado_em DESC, id DESC
            """
        )
    ).mappings().all()

    updates = []
    for row in rows:
      current = (row["categoria"] or "ofertas").strip() or "ofertas"
      inferred = infer_category_label(
          row["titulo"],
          row["descricao"],
          row["url_afiliado"],
          row["tags"],
          default=current,
      )
      if inferred != current:
          updates.append(
              {
                  "id": int(row["id"]),
                  "store": row["loja"] or "",
                  "current_category": current,
                  "new_category": inferred,
                  "title": row["titulo"] or "",
              }
          )

    return updates


def write_backup_csv(rows):
    backup_dir = ROOT / "scripts" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = backup_dir / f"recategorizar_ofertas_{timestamp}.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["id", "store", "current_category", "new_category", "title"],
        )
        writer.writeheader()
        writer.writerows(rows)
    return path


def apply_updates(db, rows):
    for row in rows:
        db.execute(
            text("UPDATE ofertas SET categoria = :categoria WHERE id = :id"),
            {"categoria": row["new_category"], "id": row["id"]},
        )


def main():
    parser = argparse.ArgumentParser(description="Recategoriza ofertas ativas usando a inferencia existente.")
    parser.add_argument("--apply", action="store_true", help="Aplica as mudancas no banco.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        updates = find_category_updates(db)
        safe_print(f"Ofertas com categoria sugerida diferente: {len(updates)}")
        for row in updates[:30]:
            safe_print(f"{row['id']} | {row['store']} | {row['current_category']} -> {row['new_category']} | {row['title']}")

        if not updates:
            return

        backup_path = write_backup_csv(updates)
        safe_print(f"Backup CSV: {backup_path}")

        if not args.apply:
            safe_print("Dry-run concluido. Rode com --apply para gravar no banco.")
            return

        apply_updates(db, updates)
        db.commit()
        safe_print(f"Atualizadas: {len(updates)} ofertas.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
