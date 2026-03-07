import os
import secrets
from hashlib import sha256
from pathlib import Path

import httpx
from fastapi import Cookie, Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app.collectors.amazon import fetch_amazon_offers
from app.collectors.mercadolivre import fetch_mercadolivre_offers, preview_mercadolivre_offers
from app.collectors.shopee import fetch_shopee_offers, preview_shopee_offers
from app.collectors.tiktok import fetch_tiktok_offers
from app.database import SessionLocal
from app.integrations.mercadolivre_oauth import build_auth_url, exchange_code, refresh_token
from app.services.dashboard_data import (
    fetch_dashboard_snapshot,
    record_execution_error,
    record_execution_start,
    record_execution_success,
)
from app.services.automation_scheduler import AutomationScheduler
from app.services.normalize import normalize_offer
from app.services.publish import publish_offer
from app.services.social_meta import (
    build_meta_post_previews,
    create_instagram_media_container,
    create_instagram_story_container,
    generate_story_asset,
    publish_facebook_offer_batch,
    publish_facebook_post,
    publish_instagram_container,
)

app = FastAPI(title="Automacao de Ofertas")
UI_DIR = Path(__file__).resolve().parents[1] / "dashboard_ui"
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
scheduler: AutomationScheduler | None = None


class MeliCodePayload(BaseModel):
    code: str


class MeliRefreshPayload(BaseModel):
    refresh_token: str


class MetaFacebookPostPayload(BaseModel):
    message: str
    link: str | None = None


class MetaFacebookBatchPayload(BaseModel):
    limit: int = 5


class MetaInstagramCreatePayload(BaseModel):
    image_url: str
    caption: str


class MetaInstagramPublishPayload(BaseModel):
    creation_id: str


class MetaStoryPayload(BaseModel):
    offer_id: int | None = None
    limit: int = 1


class MetaInstagramStoryCreatePayload(BaseModel):
    image_url: str


class DashboardImportRunPayload(BaseModel):
    providers: list[str] | None = None


class DashboardSocialRunPayload(BaseModel):
    platform: str
    mode: str = "feed"
    limit: int = 1


class DashboardSettingsPayload(BaseModel):
    manager_username: str | None = None
    manager_password: str | None = None
    auto_import_enabled: bool | None = None
    auto_import_times: str | None = None
    auto_import_providers: list[str] | None = None
    auto_social_enabled: bool | None = None
    auto_social_times: str | None = None
    auto_social_platform: str | None = None
    auto_social_mode: str | None = None
    auto_social_limit: int | None = None


class DashboardJobRunPayload(BaseModel):
    providers: list[str] | None = None
    platform: str | None = None
    mode: str | None = None
    limit: int | None = None


def _bool_env(name: str, default: bool = False) -> bool:
    value = (os.getenv(name) or "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on", "sim"}


def _manager_auth_enabled() -> bool:
    return _bool_env("MANAGER_AUTH_ENABLED", True)


def _manager_credentials() -> tuple[str, str]:
    return (
        (os.getenv("MANAGER_USERNAME") or "admin").strip() or "admin",
        (os.getenv("MANAGER_PASSWORD") or "zeropreco123").strip() or "zeropreco123",
    )


def _manager_cookie_name() -> str:
    return "zp_manager_session"


def _manager_session_value() -> str:
    username, password = _manager_credentials()
    seed = f"{username}:{password}:{os.getenv('META_APP_ID', 'zeropreco')}"
    return sha256(seed.encode("utf-8")).hexdigest()


def _manager_login_html(error: str | None = None) -> str:
    message = f"<p class='login-error'>{error}</p>" if error else ""
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Zero Preco Manager Login</title>
  <style>
    :root {{
      --bg:#071a45; --panel:#ffffff; --accent:#1d63ff; --text:#0e214f; --muted:#667494; --danger:#b63131;
    }}
    * {{ box-sizing:border-box; }}
    body {{
      margin:0; min-height:100vh; display:grid; place-items:center;
      background:
        radial-gradient(circle at 20% 20%, rgba(45,108,255,.28), transparent 32%),
        radial-gradient(circle at 80% 15%, rgba(32,173,116,.16), transparent 28%),
        linear-gradient(160deg,#061534,#0e2a68 55%,#123078);
      font-family: "Segoe UI", Arial, sans-serif; color:var(--text);
    }}
    .card {{
      width:min(460px, calc(100vw - 32px)); background:rgba(255,255,255,.96);
      border:1px solid rgba(10,31,75,.08); border-radius:28px; padding:32px;
      box-shadow:0 24px 70px rgba(4,17,46,.28);
    }}
    .brand {{ display:flex; gap:14px; align-items:center; margin-bottom:20px; }}
    .mark {{
      width:54px; height:54px; border-radius:16px; display:grid; place-items:center;
      background:linear-gradient(135deg,#1d63ff,#0b2d78); color:#fff; font-weight:800;
    }}
    h1 {{ margin:0; font-size:1.6rem; }}
    p {{ margin:6px 0 0; color:var(--muted); }}
    form {{ display:grid; gap:14px; margin-top:24px; }}
    label {{ display:grid; gap:8px; font-size:.95rem; color:var(--text); font-weight:600; }}
    input {{
      width:100%; border-radius:16px; border:1px solid rgba(13,35,79,.12); padding:14px 16px; font-size:1rem;
    }}
    button {{
      border:none; border-radius:16px; padding:14px 16px; font-size:1rem; font-weight:700;
      background:linear-gradient(135deg,#1d63ff,#0b2d78); color:#fff; cursor:pointer;
    }}
    .helper {{ margin-top:16px; font-size:.9rem; color:var(--muted); }}
    .login-error {{ margin-top:10px; color:var(--danger); font-weight:700; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="brand">
      <div class="mark">ZP</div>
      <div>
        <h1>Zero Preco Manager</h1>
        <p>Entrar no painel de importacao, social e analytics.</p>
      </div>
    </div>
    {message}
    <form method="post" action="/manager/login">
      <label>Usuario
        <input name="username" autocomplete="username" required />
      </label>
      <label>Senha
        <input name="password" type="password" autocomplete="current-password" required />
      </label>
      <button type="submit">Entrar</button>
    </form>
    <div class="helper">O painel agora usa sessao propria. Se preferir, troque as credenciais no .env.</div>
  </div>
</body>
</html>"""


def _env_settings_snapshot() -> dict:
    return {
        "manager_username": _manager_credentials()[0],
        "auto_import_enabled": _bool_env("AUTO_IMPORT_ENABLED", False),
        "auto_import_times": os.getenv("AUTO_IMPORT_TIMES") or "",
        "auto_import_providers": [item.strip() for item in (os.getenv("AUTO_IMPORT_PROVIDERS") or "mercadolivre").split(",") if item.strip()],
        "auto_social_enabled": _bool_env("AUTO_SOCIAL_ENABLED", False),
        "auto_social_times": os.getenv("AUTO_SOCIAL_TIMES") or "",
        "auto_social_platform": (os.getenv("AUTO_SOCIAL_PLATFORM") or "facebook").strip().lower(),
        "auto_social_mode": (os.getenv("AUTO_SOCIAL_MODE") or "feed").strip().lower(),
        "auto_social_limit": max(1, int((os.getenv("AUTO_SOCIAL_LIMIT") or "3").strip() or "3")),
    }


def _write_env_updates(updates: dict[str, str]) -> None:
    if not ENV_FILE.exists():
        raise HTTPException(status_code=500, detail=".env nao encontrado.")

    content = ENV_FILE.read_text(encoding="utf-8").splitlines()
    remaining = dict(updates)
    output: list[str] = []

    for line in content:
        replaced = False
        for key, value in list(remaining.items()):
            prefix = f"{key}="
            if line.startswith(prefix):
                output.append(f"{key}={value}")
                remaining.pop(key, None)
                replaced = True
                break
        if not replaced:
            output.append(line)

    for key, value in remaining.items():
        output.append(f"{key}={value}")

    ENV_FILE.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")

    for key, value in updates.items():
        os.environ[key] = value


def require_manager_auth(manager_session: str | None = Cookie(default=None, alias="zp_manager_session")) -> str:
    if not _manager_auth_enabled():
        return "disabled"
    if manager_session and secrets.compare_digest(manager_session, _manager_session_value()):
        return "ok"
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessao invalida.")


def _import_provider(db, store: str, offers: list[dict]) -> dict:
    processed = 0
    created = 0
    updated = 0
    for raw in offers:
        normalized = normalize_offer(raw, store, raw.get("affiliate_tag"))
        action = publish_offer(db, normalized)
        processed += 1
        if action == "created":
            created += 1
        else:
            updated += 1
    return {"processed": processed, "created": created, "updated": updated}


def _raise_meta_http_error(exc: httpx.HTTPStatusError) -> HTTPException:
    detail = exc.response.text if exc.response is not None else str(exc)
    status_code = exc.response.status_code if exc.response is not None else 502
    lowered = detail.lower()
    if "session has expired" in lowered or "\"code\":190" in lowered or "\"error_subcode\":463" in lowered:
        detail = (
            "Token da Meta expirou. Gere um novo META_ACCESS_TOKEN no Graph API Explorer "
            "e atualize o .env antes de rodar a publicacao social."
        )
    return HTTPException(status_code=status_code, detail=detail)


def _normalize_provider_key(value: str) -> str:
    raw = (value or "").strip().lower()
    mapping = {
        "mercado livre": "mercadolivre",
        "mercadolivre": "mercadolivre",
        "meli": "mercadolivre",
        "shopee": "shopee",
        "amazon": "amazon",
        "tiktok": "tiktok",
        "tiktok shop": "tiktok",
    }
    return mapping.get(raw, raw)


def _provider_label(key: str) -> str:
    mapping = {
        "mercadolivre": "Mercado Livre",
        "shopee": "Shopee",
        "amazon": "Amazon",
        "tiktok": "TikTok",
    }
    return mapping[key]


def _provider_fetcher(key: str):
    mapping = {
        "mercadolivre": fetch_mercadolivre_offers,
        "shopee": fetch_shopee_offers,
        "amazon": fetch_amazon_offers,
        "tiktok": fetch_tiktok_offers,
    }
    if key not in mapping:
        raise ValueError(f"Provedor nao suportado: {key}")
    return mapping[key]


def execute_import_run(providers: list[str] | None = None) -> dict:
    db = SessionLocal()
    items = providers or ["mercadolivre", "shopee", "amazon", "tiktok"]
    results = []

    try:
        for item in items:
            provider_key = _normalize_provider_key(item)
            run_id = record_execution_start(
                db,
                tipo="import",
                provider=provider_key,
                requested_count=0,
                payload={"provider": provider_key},
            )

            try:
                fetcher = _provider_fetcher(provider_key)
                offers = fetcher()
                import_summary = _import_provider(db, _provider_label(provider_key), offers)
                db.commit()
                result = {
                    "provider": provider_key,
                    "processed": import_summary["processed"],
                    "created": import_summary["created"],
                    "updated": import_summary["updated"],
                    "imported": import_summary["processed"],
                    "offers_found": len(offers),
                }
                record_execution_success(db, run_id, processed_count=import_summary["processed"], result=result)
                results.append({"run_id": run_id, "status": "success"} | result)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                error_message = str(exc)
                record_execution_error(db, run_id, error_message=error_message)
                results.append(
                    {
                        "run_id": run_id,
                        "provider": provider_key,
                        "status": "error",
                        "error": error_message,
                    }
                )

        return {
            "ok": True,
            "count": len(results),
            "success": len([item for item in results if item["status"] == "success"]),
            "error": len([item for item in results if item["status"] == "error"]),
            "items": results,
        }
    finally:
        db.close()


def execute_social_run(platform: str, mode: str = "feed", limit: int = 1) -> dict:
    platform = (platform or "").strip().lower()
    mode = (mode or "feed").strip().lower()
    limit = max(1, min(limit, 20))
    db = SessionLocal()

    run_id = record_execution_start(
        db,
        tipo="social",
        canal=platform,
        modo=mode,
        requested_count=limit,
        payload={"platform": platform, "mode": mode, "limit": limit},
    )

    try:
        if platform == "facebook" and mode == "feed":
            result = publish_facebook_offer_batch(db, limit=limit)
            record_execution_success(db, run_id, processed_count=int(result["count"]), result=result)
            return {"run_id": run_id} | result

        previews = build_meta_post_previews(db, limit=limit)
        if not previews:
            raise ValueError("Nao ha ofertas elegiveis para publicar.")

        items = []
        errors = []
        if platform == "instagram" and mode == "feed":
            for item in previews:
                try:
                    created = create_instagram_media_container(
                        image_url=item["instagram_payload"]["image_url"],
                        caption=item["instagram_payload"]["caption"],
                    )
                    published = publish_instagram_container(created["result"]["id"])
                    items.append(
                        {
                            "offer_id": item["offer_id"],
                            "slug": item["slug"],
                            "title": item["title"],
                            "creation_id": created["result"]["id"],
                            "publish_result": published["result"],
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    errors.append({"offer_id": item["offer_id"], "title": item["title"], "error": str(exc)})
        elif platform == "instagram" and mode == "story":
            for item in previews:
                try:
                    created = create_instagram_story_container(item["story_payload"]["image_url"])
                    published = publish_instagram_container(created["result"]["id"])
                    items.append(
                        {
                            "offer_id": item["offer_id"],
                            "slug": item["slug"],
                            "title": item["title"],
                            "creation_id": created["result"]["id"],
                            "publish_result": published["result"],
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    errors.append({"offer_id": item["offer_id"], "title": item["title"], "error": str(exc)})
        else:
            raise HTTPException(status_code=400, detail=f"Acao social nao suportada: {platform}/{mode}")

        result = {
            "ok": len(items) > 0,
            "platform": platform,
            "mode": mode,
            "count": len(items),
            "items": items,
            "errors": errors,
        }
        if items:
            record_execution_success(db, run_id, processed_count=len(items), result=result)
        else:
            record_execution_error(db, run_id, error_message="Nenhuma publicacao concluida.", result=result)
        return {"run_id": run_id} | result
    except HTTPException:
        raise
    except ValueError as e:
        record_execution_error(db, run_id, error_message=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPStatusError as e:
        record_execution_error(db, run_id, error_message=e.response.text if e.response is not None else str(e))
        raise _raise_meta_http_error(e)
    except httpx.HTTPError as e:
        record_execution_error(db, run_id, error_message=str(e))
        raise HTTPException(status_code=502, detail=str(e))
    finally:
        db.close()


@app.on_event("startup")
def startup_scheduler():
    global scheduler
    scheduler = AutomationScheduler(
        import_runner=execute_import_run,
        social_runner=execute_social_run,
    )
    scheduler.start()


@app.on_event("shutdown")
def shutdown_scheduler():
    if scheduler is not None:
        scheduler.stop()


@app.get("/")
def root():
    return {
        "name": "Automacao de Ofertas",
        "status": "ok",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/manager", response_class=HTMLResponse)
def manager_ui(request: Request, manager_session: str | None = Cookie(default=None, alias="zp_manager_session")):
    if _manager_auth_enabled() and (not manager_session or not secrets.compare_digest(manager_session, _manager_session_value())):
        return RedirectResponse(url="/manager/login", status_code=303)
    index_path = UI_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Dashboard React ainda nao foi gerado.")
    return index_path.read_text(encoding="utf-8")


@app.get("/manager/login", response_class=HTMLResponse)
def manager_login_page():
    if not _manager_auth_enabled():
        return RedirectResponse(url="/manager", status_code=303)
    return _manager_login_html()


@app.post("/manager/login")
def manager_login_submit(username: str = Form(...), password: str = Form(...)):
    expected_user, expected_password = _manager_credentials()
    valid_user = secrets.compare_digest(username or "", expected_user)
    valid_password = secrets.compare_digest(password or "", expected_password)
    if not (valid_user and valid_password):
        return HTMLResponse(_manager_login_html("Usuario ou senha invalidos."), status_code=401)

    response = RedirectResponse(url="/manager", status_code=303)
    response.set_cookie(
        key=_manager_cookie_name(),
        value=_manager_session_value(),
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=60 * 60 * 12,
    )
    return response


@app.post("/manager/logout")
def manager_logout():
    response = RedirectResponse(url="/manager/login", status_code=303)
    response.delete_cookie(_manager_cookie_name())
    return response


@app.get("/manager-assets/{asset_path:path}")
def manager_ui_assets(asset_path: str, _: str = Depends(require_manager_auth)):
    asset = (UI_DIR / asset_path).resolve()
    try:
        asset.relative_to(UI_DIR.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Asset invalido.") from exc

    if not asset.exists() or not asset.is_file():
        raise HTTPException(status_code=404, detail="Asset nao encontrado.")

    return FileResponse(asset)


@app.get("/dashboard/api/overview")
def dashboard_api_overview(_: str = Depends(require_manager_auth)):
    db = SessionLocal()
    try:
        snapshot = fetch_dashboard_snapshot(db)
        snapshot["automation"] = scheduler.snapshot() if scheduler is not None else None
        snapshot["manager"] = {
            "auth_enabled": _manager_auth_enabled(),
            "username": _manager_credentials()[0],
        }
        snapshot["settings"] = _env_settings_snapshot()
        return snapshot
    finally:
        db.close()


@app.get("/dashboard/api/import/preview")
def dashboard_api_import_preview(provider: str, keyword: str, limit: int = 10, pages: int = 1, _: str = Depends(require_manager_auth)):
    provider_key = _normalize_provider_key(provider)
    try:
        if provider_key == "mercadolivre":
            items = preview_mercadolivre_offers(keyword=keyword, limit=limit, pages=pages)
        elif provider_key == "shopee":
            items = preview_shopee_offers(keyword=keyword, limit=limit, pages=pages)
        else:
            raise HTTPException(status_code=501, detail=f"Preview ainda nao implementado para {provider}.")
        return {"provider": provider_key, "keyword": keyword, "count": len(items), "items": items}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/dashboard/api/import/run")
def dashboard_api_import_run(payload: DashboardImportRunPayload, _: str = Depends(require_manager_auth)):
    return execute_import_run(payload.providers)


@app.post("/dashboard/api/social/run")
def dashboard_api_social_run(payload: DashboardSocialRunPayload, _: str = Depends(require_manager_auth)):
    return execute_social_run(payload.platform, payload.mode, payload.limit)


@app.post("/dashboard/api/automation/import/run-now")
def dashboard_api_automation_import_run_now(payload: DashboardJobRunPayload, _: str = Depends(require_manager_auth)):
    providers = payload.providers or _env_settings_snapshot().get("auto_import_providers") or ["mercadolivre"]
    result = execute_import_run(providers)
    if scheduler is not None:
        scheduler._record_result("import", status="success" if not result.get("error") else "error", result=result)
    return result


@app.post("/dashboard/api/automation/social/run-now")
def dashboard_api_automation_social_run_now(payload: DashboardJobRunPayload, _: str = Depends(require_manager_auth)):
    settings = _env_settings_snapshot()
    platform = payload.platform or settings.get("auto_social_platform") or "facebook"
    mode = payload.mode or settings.get("auto_social_mode") or "feed"
    limit = int(payload.limit or settings.get("auto_social_limit") or 1)
    result = execute_social_run(platform, mode, limit)
    if scheduler is not None:
        scheduler._record_result("social", status="success" if not result.get("errors") else "error", result=result)
    return result


@app.post("/dashboard/api/settings")
def dashboard_api_settings_save(payload: DashboardSettingsPayload, _: str = Depends(require_manager_auth)):
    updates: dict[str, str] = {}

    if payload.manager_username is not None:
        username = payload.manager_username.strip() or "admin"
        updates["MANAGER_USERNAME"] = username

    password_changed = payload.manager_password is not None and payload.manager_password.strip() != ""
    if password_changed:
        updates["MANAGER_PASSWORD"] = payload.manager_password.strip()

    if payload.auto_import_enabled is not None:
        updates["AUTO_IMPORT_ENABLED"] = "true" if payload.auto_import_enabled else "false"
    if payload.auto_import_times is not None:
        updates["AUTO_IMPORT_TIMES"] = payload.auto_import_times.strip()
    if payload.auto_import_providers is not None:
        providers = [_normalize_provider_key(item) for item in payload.auto_import_providers if str(item).strip()]
        updates["AUTO_IMPORT_PROVIDERS"] = ",".join(dict.fromkeys(providers)) or "mercadolivre"

    if payload.auto_social_enabled is not None:
        updates["AUTO_SOCIAL_ENABLED"] = "true" if payload.auto_social_enabled else "false"
    if payload.auto_social_times is not None:
        updates["AUTO_SOCIAL_TIMES"] = payload.auto_social_times.strip()
    if payload.auto_social_platform is not None:
        updates["AUTO_SOCIAL_PLATFORM"] = payload.auto_social_platform.strip().lower() or "facebook"
    if payload.auto_social_mode is not None:
        updates["AUTO_SOCIAL_MODE"] = payload.auto_social_mode.strip().lower() or "feed"
    if payload.auto_social_limit is not None:
        updates["AUTO_SOCIAL_LIMIT"] = str(max(1, min(int(payload.auto_social_limit), 20)))

    if not updates:
        return {"ok": True, "message": "Nenhuma alteracao recebida.", "settings": _env_settings_snapshot(), "reauth_required": False}

    _write_env_updates(updates)

    if scheduler is not None:
        scheduler._refresh_next_run("import")
        scheduler._refresh_next_run("social")

    return {
        "ok": True,
        "message": "Configuracoes salvas no .env.",
        "settings": _env_settings_snapshot(),
        "reauth_required": password_changed,
    }


@app.get("/social/meta/post-previews")
def social_meta_post_previews(limit: int = 12):
    db = SessionLocal()
    try:
        items = build_meta_post_previews(db, limit=limit)
        return {"count": len(items), "items": items}
    finally:
        db.close()


@app.post("/social/meta/facebook/publish")
def social_meta_facebook_publish(payload: MetaFacebookPostPayload):
    try:
        return publish_facebook_post(message=payload.message, link=payload.link)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPStatusError as e:
        raise _raise_meta_http_error(e)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/social/meta/facebook/publish-batch")
def social_meta_facebook_publish_batch(payload: MetaFacebookBatchPayload):
    db = SessionLocal()
    try:
        return publish_facebook_offer_batch(db, limit=payload.limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPStatusError as e:
        raise _raise_meta_http_error(e)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=str(e))
    finally:
        db.close()


@app.post("/social/meta/instagram/create")
def social_meta_instagram_create(payload: MetaInstagramCreatePayload):
    try:
        return create_instagram_media_container(image_url=payload.image_url, caption=payload.caption)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPStatusError as e:
        raise _raise_meta_http_error(e)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/social/meta/story/generate")
def social_meta_story_generate(payload: MetaStoryPayload):
    db = SessionLocal()
    try:
        items = build_meta_post_previews(db, limit=max(1, min(payload.limit, 20)))
        if payload.offer_id is not None:
            items = [item for item in items if item["offer_id"] == payload.offer_id]
        if not items:
            raise HTTPException(status_code=404, detail="Nenhuma oferta encontrada para gerar story.")
        return {"count": len(items), "items": [item["story_payload"] | {"offer_id": item["offer_id"], "slug": item["slug"], "title": item["title"]} for item in items]}
    finally:
        db.close()


@app.post("/social/meta/instagram/story/create")
def social_meta_instagram_story_create(payload: MetaInstagramStoryCreatePayload):
    try:
        return create_instagram_story_container(payload.image_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPStatusError as e:
        raise _raise_meta_http_error(e)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/social/meta/instagram/publish")
def social_meta_instagram_publish(payload: MetaInstagramPublishPayload):
    try:
        return publish_instagram_container(payload.creation_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPStatusError as e:
        raise _raise_meta_http_error(e)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/integrations/shopee/product-offers-preview")
def shopee_product_offers_preview(keyword: str, limit: int = 10, pages: int = 1):
    try:
        offers = preview_shopee_offers(keyword=keyword, limit=limit, pages=pages)
        return {"keyword": keyword, "count": len(offers), "items": offers}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/integrations/meli/product-offers-preview")
def meli_product_offers_preview(keyword: str, limit: int = 10, pages: int = 1):
    try:
        offers = preview_mercadolivre_offers(keyword=keyword, limit=limit, pages=pages)
        return {"keyword": keyword, "count": len(offers), "items": offers}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/integrations/meli/oauth/url")
def meli_oauth_url():
    try:
        return build_auth_url()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/integrations/meli/callback")
def meli_oauth_callback(code: str | None = None, error: str | None = None, error_description: str | None = None):
    if error:
        return {
            "ok": False,
            "error": error,
            "error_description": error_description,
            "message": "Autorizacao negada ou bloqueada no retorno do Mercado Livre.",
        }

    if not code:
        return {"ok": False, "message": "Code nao recebido no callback."}

    try:
        tokens = exchange_code(code)
        return {
            "ok": True,
            "message": "Tokens gerados. Copie MELI_ACCESS_TOKEN e MELI_REFRESH_TOKEN para o .env.",
            "tokens": tokens,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/integrations/meli/oauth/exchange")
def meli_oauth_exchange(payload: MeliCodePayload):
    try:
        return exchange_code(payload.code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/integrations/meli/oauth/refresh")
def meli_oauth_refresh(payload: MeliRefreshPayload):
    try:
        return refresh_token(payload.refresh_token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/collect/run")
def run_collectors():
    db = SessionLocal()
    imported = {"Shopee": 0, "Mercado Livre": 0, "Amazon": 0, "TikTok": 0}

    try:
        imported["Shopee"] = _import_provider(db, "Shopee", fetch_shopee_offers())
        imported["Mercado Livre"] = _import_provider(db, "Mercado Livre", fetch_mercadolivre_offers())
        imported["Amazon"] = _import_provider(db, "Amazon", fetch_amazon_offers())
        imported["TikTok"] = _import_provider(db, "TikTok", fetch_tiktok_offers())

        db.commit()
        return {"imported": imported, "total": sum(imported.values())}
    finally:
        db.close()
