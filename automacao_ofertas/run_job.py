import argparse
import json
import sys
from pathlib import Path

from fastapi import HTTPException

from app.database import SessionLocal
from app.main import execute_deploy_site, execute_import_run, execute_social_run
from app.services.manual_file_import import preview_amazon_txt_file, preview_mercadolivre_txt_file, preview_shopee_csv_file
from app.services.manual_link_import import preview_manual_affiliate_links
from app.services.normalize import normalize_offer
from app.services.publish import publish_offer


def _emit(payload: dict, exit_code: int = 0) -> int:
    print(json.dumps(payload, ensure_ascii=True, default=str))
    return exit_code


def _import_items(items: list[dict], actor_user_id: int | None = None, actor_login: str | None = None) -> dict:
    db = SessionLocal()
    summary = {"processed": 0, "created": 0, "updated": 0, "items": []}
    try:
        for item in items:
            store = (item.get("store") or "").strip() or "Oferta"
            normalized = normalize_offer(item, store, item.get("affiliate_code"))
            action = publish_offer(
                db,
                normalized,
                actor_user_id=actor_user_id,
                actor_login=actor_login,
            )
            summary["processed"] += 1
            summary[action] += 1
            summary["items"].append(
                {
                    "title": item.get("title"),
                    "store": store,
                    "price": item.get("price"),
                    "action": action,
                }
            )
        db.commit()
        return summary
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Executa jobs da automacao via CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    social_parser = subparsers.add_parser("social", help="Publica ofertas nas redes sociais.")
    social_parser.add_argument("--platform", required=True)
    social_parser.add_argument("--mode", default="feed")
    social_parser.add_argument("--limit", type=int, default=1)
    social_parser.add_argument("--offer-id", dest="offer_ids", action="append", type=int, default=[])

    import_parser = subparsers.add_parser("import", help="Roda importadores configurados.")
    import_parser.add_argument("--provider", dest="providers", action="append", default=[])

    import_file_parser = subparsers.add_parser("import-file", help="Importa um arquivo manual.")
    import_file_parser.add_argument("--kind", required=True, choices=["shopee_csv", "amazon_txt", "mercadolivre_txt"])
    import_file_parser.add_argument("--input-file", required=True)
    import_file_parser.add_argument("--actor-user-id", type=int, default=None)
    import_file_parser.add_argument("--actor-login", default=None)

    import_links_parser = subparsers.add_parser("import-links", help="Importa links colados manualmente.")
    import_links_parser.add_argument("--input-file", required=True)
    import_links_parser.add_argument("--actor-user-id", type=int, default=None)
    import_links_parser.add_argument("--actor-login", default=None)

    subparsers.add_parser("deploy-site", help="Envia public_html via SFTP.")

    args = parser.parse_args()

    try:
        if args.command == "social":
            result = execute_social_run(
                platform=args.platform,
                mode=args.mode,
                limit=max(1, int(args.limit)),
                offer_ids=args.offer_ids or None,
            )
            return _emit({"ok": True, "command": "social", "result": result})

        if args.command == "import":
            result = execute_import_run(args.providers or None)
            return _emit({"ok": True, "command": "import", "result": result})

        if args.command == "import-file":
            input_path = Path(args.input_file)
            if not input_path.is_file():
                return _emit({"ok": False, "error": "Arquivo informado nao encontrado."}, 1)
            content = input_path.read_bytes()
            if args.kind == "shopee_csv":
                items = preview_shopee_csv_file(content, input_path.name)
            elif args.kind == "amazon_txt":
                items = preview_amazon_txt_file(content, input_path.name)
            else:
                items = preview_mercadolivre_txt_file(content, input_path.name)
            items = [item for item in items if bool(item.get("selected", True))]
            result = _import_items(items, actor_user_id=args.actor_user_id, actor_login=args.actor_login)
            return _emit({"ok": True, "command": "import-file", "result": result})

        if args.command == "import-links":
            input_path = Path(args.input_file)
            if not input_path.is_file():
                return _emit({"ok": False, "error": "Arquivo informado nao encontrado."}, 1)
            raw_lines = input_path.read_text(encoding="utf-8", errors="replace").splitlines()
            links = [line.strip() for line in raw_lines if line.strip()]
            items = preview_manual_affiliate_links(links)
            items = [item for item in items if bool(item.get("import_allowed", item.get("affiliate_detected", True)))]
            result = _import_items(items, actor_user_id=args.actor_user_id, actor_login=args.actor_login)
            return _emit({"ok": True, "command": "import-links", "result": result})

        if args.command == "deploy-site":
            result = execute_deploy_site()
            return _emit({"ok": True, "command": "deploy-site", "result": result})

        return _emit({"ok": False, "error": "Comando nao suportado."}, 2)
    except HTTPException as exc:
        return _emit(
            {
                "ok": False,
                "error": str(exc.detail),
                "status_code": int(exc.status_code),
            },
            1,
        )
    except Exception as exc:  # noqa: BLE001
        return _emit({"ok": False, "error": str(exc)}, 1)


if __name__ == "__main__":
    sys.exit(main())
