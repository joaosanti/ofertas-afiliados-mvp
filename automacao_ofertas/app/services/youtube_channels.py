from __future__ import annotations

import os
import re
from typing import Any

from sqlalchemy import text


CREATE_YOUTUBE_CHANNEL_PROFILES_SQL = text(
    """
    CREATE TABLE IF NOT EXISTS youtube_channel_profiles (
      id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
      slug VARCHAR(80) NOT NULL,
      name VARCHAR(180) NOT NULL,
      handle VARCHAR(180) NULL,
      notes TEXT NULL,
      source_channels TEXT NULL,
      avoid_terms TEXT NULL,
      preferred_terms TEXT NULL,
      viral_tone TEXT NULL,
      client_id VARCHAR(255) NULL,
      client_secret TEXT NULL,
      redirect_uri VARCHAR(600) NULL,
      access_token LONGTEXT NULL,
      refresh_token LONGTEXT NULL,
      token_expires_at BIGINT NULL,
      oauth_state VARCHAR(120) NULL,
      channel_id VARCHAR(120) NULL,
      channel_title VARCHAR(255) NULL,
      channel_custom_url VARCHAR(255) NULL,
      channel_thumbnail_url VARCHAR(1000) NULL,
      is_default TINYINT(1) NOT NULL DEFAULT 0,
      is_active TINYINT(1) NOT NULL DEFAULT 1,
      created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
      UNIQUE KEY ux_youtube_channel_profiles_slug (slug),
      INDEX ix_youtube_channel_profiles_default (is_default),
      INDEX ix_youtube_channel_profiles_active (is_active),
      INDEX ix_youtube_channel_profiles_state (oauth_state)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """
)

YOUTUBE_CHANNEL_PROFILE_ALTER_SQL: dict[str, str] = {
    "source_channels": "ALTER TABLE youtube_channel_profiles ADD COLUMN source_channels TEXT NULL AFTER notes",
    "avoid_terms": "ALTER TABLE youtube_channel_profiles ADD COLUMN avoid_terms TEXT NULL AFTER notes",
    "preferred_terms": "ALTER TABLE youtube_channel_profiles ADD COLUMN preferred_terms TEXT NULL AFTER avoid_terms",
    "viral_tone": "ALTER TABLE youtube_channel_profiles ADD COLUMN viral_tone TEXT NULL AFTER preferred_terms",
}


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return normalized[:80] or "canal-youtube"


def _bool_flag(value: Any, default: bool = False) -> int:
    if value is None:
        return 1 if default else 0
    return 1 if bool(value) else 0


def _env_youtube_defaults() -> dict[str, Any]:
    return {
        "client_id": (os.getenv("YOUTUBE_CLIENT_ID") or "").strip() or None,
        "client_secret": (os.getenv("YOUTUBE_CLIENT_SECRET") or "").strip() or None,
        "redirect_uri": (os.getenv("YOUTUBE_REDIRECT_URI") or "").strip() or None,
        "access_token": (os.getenv("YOUTUBE_ACCESS_TOKEN") or "").strip() or None,
        "refresh_token": (os.getenv("YOUTUBE_REFRESH_TOKEN") or "").strip() or None,
        "token_expires_at": int((os.getenv("YOUTUBE_TOKEN_EXPIRES_AT") or "0").strip() or "0") or None,
    }


def ensure_youtube_channel_tables(db) -> None:
    db.execute(CREATE_YOUTUBE_CHANNEL_PROFILES_SQL)
    existing = {
        str(row["Field"])
        for row in db.execute(text("SHOW COLUMNS FROM youtube_channel_profiles")).mappings().all()
    }
    changed = False
    for field, sql in YOUTUBE_CHANNEL_PROFILE_ALTER_SQL.items():
        if field in existing:
            continue
        db.execute(text(sql))
        changed = True
    if changed:
        db.commit()
    db.commit()


def bootstrap_legacy_env_youtube_channel(db) -> None:
    ensure_youtube_channel_tables(db)
    current_total = db.execute(text("SELECT COUNT(*) AS total FROM youtube_channel_profiles")).mappings().first()
    if int((current_total or {}).get("total") or 0) > 0:
        return

    defaults = _env_youtube_defaults()
    if not defaults["client_id"] and not defaults["refresh_token"] and not defaults["access_token"]:
        return

    db.execute(
        text(
            """
            INSERT INTO youtube_channel_profiles
            (
              slug, name, handle, notes,
              client_id, client_secret, redirect_uri,
              access_token, refresh_token, token_expires_at,
              is_default, is_active
            )
            VALUES
            (
              :slug, :name, :handle, :notes,
              :client_id, :client_secret, :redirect_uri,
              :access_token, :refresh_token, :token_expires_at,
              1, 1
            )
            """
        ),
        {
            "slug": "canal-principal",
            "name": "Canal principal",
            "handle": None,
            "notes": "Perfil bootstrap criado a partir das variaveis antigas do .env.",
            **defaults,
        },
    )
    db.commit()


def _row_to_profile(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    defaults = _env_youtube_defaults()
    token_expires_at = row.get("token_expires_at")
    try:
        token_expires_at = int(token_expires_at) if token_expires_at is not None else None
    except Exception:
        token_expires_at = None
    return {
        "id": int(row.get("id") or 0),
        "slug": str(row.get("slug") or ""),
        "name": str(row.get("name") or ""),
        "handle": str(row.get("handle") or ""),
        "notes": str(row.get("notes") or ""),
        "source_channels": str(row.get("source_channels") or ""),
        "avoid_terms": str(row.get("avoid_terms") or ""),
        "preferred_terms": str(row.get("preferred_terms") or ""),
        "viral_tone": str(row.get("viral_tone") or ""),
        "client_id": str(row.get("client_id") or defaults["client_id"] or ""),
        "client_secret": str(row.get("client_secret") or defaults["client_secret"] or ""),
        "redirect_uri": str(row.get("redirect_uri") or defaults["redirect_uri"] or ""),
        "access_token": str(row.get("access_token") or ""),
        "refresh_token": str(row.get("refresh_token") or ""),
        "token_expires_at": token_expires_at,
        "oauth_state": str(row.get("oauth_state") or ""),
        "channel_id": str(row.get("channel_id") or ""),
        "channel_title": str(row.get("channel_title") or ""),
        "channel_custom_url": str(row.get("channel_custom_url") or ""),
        "channel_thumbnail_url": str(row.get("channel_thumbnail_url") or ""),
        "is_default": bool(row.get("is_default")),
        "is_active": bool(row.get("is_active")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "credentials_source": "profile" if row.get("client_id") or row.get("client_secret") or row.get("redirect_uri") else "env_default",
    }


def fetch_youtube_channel_profiles(db, *, include_inactive: bool = True) -> list[dict[str, Any]]:
    ensure_youtube_channel_tables(db)
    bootstrap_legacy_env_youtube_channel(db)
    sql = """
        SELECT *
        FROM youtube_channel_profiles
    """
    params: dict[str, Any] = {}
    if not include_inactive:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY is_default DESC, is_active DESC, updated_at DESC, id DESC"
    rows = db.execute(text(sql), params).mappings().all()
    return [profile for row in rows if (profile := _row_to_profile(dict(row)))]


def get_youtube_channel_profile(db, profile_id: int) -> dict[str, Any] | None:
    ensure_youtube_channel_tables(db)
    bootstrap_legacy_env_youtube_channel(db)
    row = db.execute(
        text("SELECT * FROM youtube_channel_profiles WHERE id = :id LIMIT 1"),
        {"id": int(profile_id)},
    ).mappings().first()
    return _row_to_profile(dict(row)) if row else None


def get_default_youtube_channel_profile(db) -> dict[str, Any] | None:
    ensure_youtube_channel_tables(db)
    bootstrap_legacy_env_youtube_channel(db)
    row = db.execute(
        text(
            """
            SELECT *
            FROM youtube_channel_profiles
            WHERE is_active = 1
            ORDER BY is_default DESC, updated_at DESC, id DESC
            LIMIT 1
            """
        )
    ).mappings().first()
    return _row_to_profile(dict(row)) if row else None


def get_youtube_channel_profile_by_state(db, state: str) -> dict[str, Any] | None:
    ensure_youtube_channel_tables(db)
    if not str(state or "").strip():
        return None
    row = db.execute(
        text("SELECT * FROM youtube_channel_profiles WHERE oauth_state = :state LIMIT 1"),
        {"state": str(state).strip()},
    ).mappings().first()
    return _row_to_profile(dict(row)) if row else None


def _unique_slug(db, base_value: str, *, exclude_id: int | None = None) -> str:
    base_slug = _slugify(base_value)
    slug = base_slug
    suffix = 2
    while True:
        if exclude_id:
            row = db.execute(
                text("SELECT id FROM youtube_channel_profiles WHERE slug = :slug AND id <> :id LIMIT 1"),
                {"slug": slug, "id": int(exclude_id)},
            ).mappings().first()
        else:
            row = db.execute(
                text("SELECT id FROM youtube_channel_profiles WHERE slug = :slug LIMIT 1"),
                {"slug": slug},
            ).mappings().first()
        if not row:
            return slug
        slug = f"{base_slug[:72]}-{suffix}"
        suffix += 1


def create_youtube_channel_profile(db, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_youtube_channel_tables(db)
    bootstrap_legacy_env_youtube_channel(db)
    slug = _unique_slug(db, payload.get("slug") or payload.get("name") or "canal-youtube")
    is_default = _bool_flag(payload.get("is_default"), default=False)
    if is_default:
        db.execute(text("UPDATE youtube_channel_profiles SET is_default = 0"))
    result = db.execute(
        text(
            """
            INSERT INTO youtube_channel_profiles
            (
              slug, name, handle, notes, source_channels, avoid_terms, preferred_terms, viral_tone,
              client_id, client_secret, redirect_uri,
              access_token, refresh_token, token_expires_at,
              oauth_state, channel_id, channel_title, channel_custom_url, channel_thumbnail_url,
              is_default, is_active
            )
            VALUES
            (
              :slug, :name, :handle, :notes, :source_channels, :avoid_terms, :preferred_terms, :viral_tone,
              :client_id, :client_secret, :redirect_uri,
              :access_token, :refresh_token, :token_expires_at,
              :oauth_state, :channel_id, :channel_title, :channel_custom_url, :channel_thumbnail_url,
              :is_default, :is_active
            )
            """
        ),
        {
            "slug": slug,
            "name": payload.get("name"),
            "handle": payload.get("handle") or None,
            "notes": payload.get("notes") or None,
            "source_channels": payload.get("source_channels") or None,
            "avoid_terms": payload.get("avoid_terms") or None,
            "preferred_terms": payload.get("preferred_terms") or None,
            "viral_tone": payload.get("viral_tone") or None,
            "client_id": payload.get("client_id") or None,
            "client_secret": payload.get("client_secret") or None,
            "redirect_uri": payload.get("redirect_uri") or None,
            "access_token": payload.get("access_token") or None,
            "refresh_token": payload.get("refresh_token") or None,
            "token_expires_at": payload.get("token_expires_at"),
            "oauth_state": payload.get("oauth_state") or None,
            "channel_id": payload.get("channel_id") or None,
            "channel_title": payload.get("channel_title") or None,
            "channel_custom_url": payload.get("channel_custom_url") or None,
            "channel_thumbnail_url": payload.get("channel_thumbnail_url") or None,
            "is_default": is_default,
            "is_active": _bool_flag(payload.get("is_active"), default=True),
        },
    )
    db.commit()
    return get_youtube_channel_profile(db, int(result.lastrowid)) or {}


def update_youtube_channel_profile(db, profile_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_youtube_channel_tables(db)
    current = get_youtube_channel_profile(db, profile_id)
    if not current:
        raise ValueError("Perfil de canal do YouTube nao encontrado.")

    next_slug = payload.get("slug")
    if next_slug is not None:
        next_slug = _unique_slug(db, next_slug or current["name"], exclude_id=profile_id)
    is_default = payload.get("is_default")
    if is_default:
        db.execute(text("UPDATE youtube_channel_profiles SET is_default = 0 WHERE id <> :id"), {"id": int(profile_id)})

    assignments: list[str] = []
    params: dict[str, Any] = {"id": int(profile_id)}
    allowed_fields = {
        "slug",
        "name",
        "handle",
        "notes",
        "source_channels",
        "avoid_terms",
        "preferred_terms",
        "viral_tone",
        "client_id",
        "client_secret",
        "redirect_uri",
        "access_token",
        "refresh_token",
        "token_expires_at",
        "oauth_state",
        "channel_id",
        "channel_title",
        "channel_custom_url",
        "channel_thumbnail_url",
        "is_default",
        "is_active",
    }
    normalized_payload = dict(payload)
    if next_slug is not None:
        normalized_payload["slug"] = next_slug
    if "is_default" in normalized_payload:
        normalized_payload["is_default"] = _bool_flag(normalized_payload.get("is_default"), default=current["is_default"])
    if "is_active" in normalized_payload:
        normalized_payload["is_active"] = _bool_flag(normalized_payload.get("is_active"), default=current["is_active"])

    for field in allowed_fields:
        if field not in normalized_payload:
            continue
        assignments.append(f"{field} = :{field}")
        params[field] = normalized_payload[field]

    if assignments:
        db.execute(
            text(f"UPDATE youtube_channel_profiles SET {', '.join(assignments)} WHERE id = :id"),
            params,
        )
        db.commit()

    updated = get_youtube_channel_profile(db, profile_id) or {}
    if updated and not updated.get("is_default"):
        default_exists = db.execute(
            text("SELECT id FROM youtube_channel_profiles WHERE is_default = 1 LIMIT 1")
        ).mappings().first()
        if not default_exists and updated.get("is_active"):
            db.execute(text("UPDATE youtube_channel_profiles SET is_default = 1 WHERE id = :id"), {"id": int(profile_id)})
            db.commit()
            updated = get_youtube_channel_profile(db, profile_id) or updated
    return updated


def delete_youtube_channel_profile(db, profile_id: int) -> dict[str, Any]:
    ensure_youtube_channel_tables(db)
    current = get_youtube_channel_profile(db, profile_id)
    if not current:
        raise ValueError("Perfil de canal do YouTube nao encontrado.")
    db.execute(text("DELETE FROM youtube_channel_profiles WHERE id = :id"), {"id": int(profile_id)})
    db.commit()

    remaining = fetch_youtube_channel_profiles(db)
    if remaining and not any(item.get("is_default") for item in remaining):
        db.execute(text("UPDATE youtube_channel_profiles SET is_default = 1 WHERE id = :id"), {"id": int(remaining[0]["id"])})
        db.commit()

    return current
