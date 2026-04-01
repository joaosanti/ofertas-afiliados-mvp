import argparse
import json
import sys
from pathlib import Path

from fastapi import HTTPException

from app.database import SessionLocal
from app.main import (
    execute_deploy_site,
    execute_import_run,
    execute_social_run,
    execute_youtube_auto_cut_publish,
    execute_youtube_cut_private_test,
    execute_youtube_cuts_analyze,
    execute_youtube_cuts_process,
    execute_youtube_cut_publish,
    execute_youtube_trends_themes,
)
from app.services.manual_file_import import preview_amazon_txt_file, preview_mercadolivre_txt_file, preview_shopee_csv_file
from app.services.manual_link_import import preview_manual_affiliate_links
from app.services.normalize import normalize_offer
from app.services.publish import publish_offer
from app.services.shopee_video import build_shopee_video_package
from app.services.store_maintenance import repair_mercadolivre_product_links
from app.services.youtube_cuts import rerender_youtube_cut


def _emit(payload: dict, exit_code: int = 0) -> int:
    print(json.dumps(payload, ensure_ascii=True, default=str))
    return exit_code


def _import_items(items: list[dict], actor_user_id: int | None = None, actor_login: str | None = None) -> dict:
    db = SessionLocal()
    summary = {"processed": 0, "created": 0, "updated": 0, "skipped": 0, "items": []}
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
    social_parser.add_argument("--mode", default="feed_story_reel")
    social_parser.add_argument("--limit", type=int, default=1)
    social_parser.add_argument("--offer-id", dest="offer_ids", action="append", type=int, default=[])

    shopee_video_parser = subparsers.add_parser("shopee-video-package", help="Gera pacote profissional para Shopee Video.")
    shopee_video_parser.add_argument("--draft-id", type=int, default=None)
    shopee_video_parser.add_argument("--offer-id", type=int, default=None)

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

    repair_meli_product_links_parser = subparsers.add_parser("repair-mercadolivre-product-links", help="Corrige links de produto do Mercado Livre salvos como perfil/lista.")
    repair_meli_product_links_parser.add_argument("--only-inactive", action="store_true")

    subparsers.add_parser("deploy-site", help="Envia public_html via SFTP.")

    yt_analyze_parser = subparsers.add_parser("youtube-cuts-analyze", help="Analisa um video do YouTube para cortes.")
    yt_analyze_parser.add_argument("--url", required=True)

    yt_process_parser = subparsers.add_parser("youtube-cuts-process", help="Gera cortes de um video do YouTube.")
    yt_process_parser.add_argument("--url", required=True)
    yt_process_parser.add_argument("--limit", type=int, default=5)
    yt_process_parser.add_argument("--mode", default="short")
    yt_process_parser.add_argument("--selection-strategy", default="openai_heuristica")
    yt_process_parser.add_argument("--risk-profile", default="default")
    yt_process_parser.add_argument("--channel-profile-id", type=int, default=None)
    yt_process_parser.add_argument("--no-burn-subtitles", action="store_true")

    yt_private_test_parser = subparsers.add_parser("youtube-cut-private-test", help="Gera um short com preset conservador e sobe como privado para revisao.")
    yt_private_test_parser.add_argument("--url", required=True)
    yt_private_test_parser.add_argument("--limit", type=int, default=3)
    yt_private_test_parser.add_argument("--selection-strategy", default="openai_heuristica")
    yt_private_test_parser.add_argument("--channel-profile-id", type=int, default=None)
    yt_private_test_parser.add_argument("--no-burn-subtitles", action="store_true")

    yt_publish_parser = subparsers.add_parser("youtube-cut-publish", help="Publica um corte gerado no YouTube.")
    yt_publish_parser.add_argument("--job-id", required=True)
    yt_publish_parser.add_argument("--cut-id", type=int, required=True)
    yt_publish_parser.add_argument("--title", default=None)
    yt_publish_parser.add_argument("--description", default=None)
    yt_publish_parser.add_argument("--privacy-status", default="public")
    yt_publish_parser.add_argument("--publish-at", default=None)
    yt_publish_parser.add_argument("--mode", default="short")
    yt_publish_parser.add_argument("--channel-profile-id", type=int, default=None)

    yt_rerender_parser = subparsers.add_parser("youtube-cut-rerender", help="Regera um corte curto com enquadramento manual.")
    yt_rerender_parser.add_argument("--job-id", required=True)
    yt_rerender_parser.add_argument("--cut-id", type=int, required=True)
    yt_rerender_parser.add_argument("--framing", default="auto")

    yt_trends_parser = subparsers.add_parser("youtube-trends-themes", help="Busca videos recentes em alta para virar corte.")
    yt_trends_parser.add_argument("--recent-limit", type=int, default=4)
    yt_trends_parser.add_argument("--videos-per-topic", type=int, default=4)
    yt_trends_parser.add_argument("--channel-profile-id", type=int, default=None)

    yt_auto_publish_parser = subparsers.add_parser("youtube-auto-cut-publish", help="Seleciona um video do radar, gera o melhor corte e publica no YouTube.")
    yt_auto_publish_parser.add_argument("--channel-profile-id", type=int, default=None)
    yt_auto_publish_parser.add_argument("--channel-profile-name", default=None)
    yt_auto_publish_parser.add_argument("--recent-limit", type=int, default=8)
    yt_auto_publish_parser.add_argument("--videos-per-topic", type=int, default=5)
    yt_auto_publish_parser.add_argument("--cut-limit", type=int, default=5)
    yt_auto_publish_parser.add_argument("--retry-candidates", type=int, default=4)
    yt_auto_publish_parser.add_argument("--lookback-days", type=int, default=14)
    yt_auto_publish_parser.add_argument("--selection-strategy", default="openai_heuristica")

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

        if args.command == "shopee-video-package":
            if args.draft_id is None and args.offer_id is None:
                return _emit({"ok": False, "error": "Informe --draft-id ou --offer-id."}, 1)
            result = build_shopee_video_package(
                draft_id=args.draft_id,
                offer_id=args.offer_id,
            )
            return _emit({"ok": True, "command": "shopee-video-package", "result": result})

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

        if args.command == "repair-mercadolivre-product-links":
            db = SessionLocal()
            try:
                result = repair_mercadolivre_product_links(db, only_inactive=bool(args.only_inactive))
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()
            return _emit({"ok": True, "command": "repair-mercadolivre-product-links", "result": result})

        if args.command == "deploy-site":
            result = execute_deploy_site()
            return _emit({"ok": True, "command": "deploy-site", "result": result})

        if args.command == "youtube-cuts-analyze":
            result = execute_youtube_cuts_analyze(args.url)
            return _emit({"ok": True, "command": "youtube-cuts-analyze", "result": result})

        if args.command == "youtube-cuts-process":
            result = execute_youtube_cuts_process(
                args.url,
                limit=max(1, int(args.limit)),
                mode=args.mode,
                selection_strategy=args.selection_strategy,
                risk_profile=args.risk_profile,
                channel_profile_id=args.channel_profile_id,
                burn_subtitles=not bool(args.no_burn_subtitles),
            )
            return _emit({"ok": True, "command": "youtube-cuts-process", "result": result})

        if args.command == "youtube-cut-private-test":
            result = execute_youtube_cut_private_test(
                args.url,
                limit=max(1, int(args.limit)),
                selection_strategy=args.selection_strategy,
                channel_profile_id=args.channel_profile_id,
                burn_subtitles=not bool(args.no_burn_subtitles),
            )
            return _emit({"ok": True, "command": "youtube-cut-private-test", "result": result})

        if args.command == "youtube-cut-publish":
            result = execute_youtube_cut_publish(
                job_id=args.job_id,
                cut_id=int(args.cut_id),
                title=args.title,
                description=args.description,
                privacy_status=args.privacy_status,
                publish_at=args.publish_at,
                mode=args.mode,
                channel_profile_id=args.channel_profile_id,
            )
            return _emit({"ok": True, "command": "youtube-cut-publish", "result": result})

        if args.command == "youtube-cut-rerender":
            result = rerender_youtube_cut(
                args.job_id,
                int(args.cut_id),
                framing=args.framing,
            )
            return _emit({"ok": True, "command": "youtube-cut-rerender", "result": result})

        if args.command == "youtube-trends-themes":
            result = execute_youtube_trends_themes(
                recent_limit=int(args.recent_limit),
                videos_per_topic=int(args.videos_per_topic),
                channel_profile_id=args.channel_profile_id,
            )
            return _emit({"ok": True, "command": "youtube-trends-themes", "result": result})

        if args.command == "youtube-auto-cut-publish":
            result = execute_youtube_auto_cut_publish(
                channel_profile_id=args.channel_profile_id,
                channel_profile_name=args.channel_profile_name,
                recent_limit=int(args.recent_limit),
                videos_per_topic=int(args.videos_per_topic),
                cut_limit=int(args.cut_limit),
                retry_candidates=int(args.retry_candidates),
                lookback_days=int(args.lookback_days),
                selection_strategy=args.selection_strategy,
            )
            return _emit({"ok": True, "command": "youtube-auto-cut-publish", "result": result})

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
