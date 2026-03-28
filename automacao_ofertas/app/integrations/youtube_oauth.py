from __future__ import annotations

import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import httpx
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3"
YOUTUBE_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
YOUTUBE_THUMBNAIL_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
SAO_PAULO_TZ = timezone(timedelta(hours=-3))

YOUTUBE_QUERY_STOPWORDS = {
    "sobre",
    "contra",
    "entre",
    "depois",
    "antes",
    "agora",
    "ainda",
    "porque",
    "quando",
    "como",
    "qual",
    "quais",
    "onde",
    "isso",
    "essa",
    "esse",
    "todo",
    "tudo",
    "mundo",
    "pode",
    "para",
    "com",
    "sem",
    "mais",
    "menos",
    "muito",
    "muita",
    "e",
    "do",
    "da",
    "dos",
    "das",
    "no",
    "na",
    "nos",
    "nas",
    "um",
    "uma",
    "uns",
    "umas",
    "que",
    "por",
    "ao",
    "aos",
    "as",
    "os",
    "o",
    "a",
}

CUT_BLOCKLIST_TERMS = {
    "short",
    "shorts",
    "corte",
    "cortes",
    "clip",
    "clips",
    "trecho",
    "trechos",
    "reels",
    "tiktok",
}

PODCAST_PRIORITY_TERMS = {
    "podcast",
    "podcasts",
    "entrevista",
    "entrevistas",
    "conversa",
    "conversa franca",
    "mesa redonda",
}

WAR_PRIORITY_TERMS = {
    "guerra",
    "guerras",
    "ataque",
    "ataques",
    "militar",
    "misseis",
    "missil",
    "otan",
    "ucrania",
    "russia",
    "israel",
    "iran",
    "china",
    "taiwan",
    "geopolitica",
    "geopolitico",
}

POLITICS_PRIORITY_TERMS = {
    "politica",
    "politico",
    "governo",
    "eleicao",
    "eleicoes",
    "congresso",
    "senado",
    "camara",
    "presidente",
    "ministro",
    "stf",
    "planalto",
    "lula",
    "bolsonaro",
    "trump",
}

SPORTS_PRIORITY_TERMS = {
    "futebol",
    "brasileirao",
    "brasileirão",
    "libertadores",
    "sul-americana",
    "sul americana",
    "copa do brasil",
    "g4",
    "z4",
    "rebaixamento",
    "arbitragem",
    "penalti",
    "pênalti",
    "var",
    "rodada",
    "mercado da bola",
    "janela",
    "tecnico",
    "técnico",
    "treinador",
    "flamengo",
    "corinthians",
    "palmeiras",
    "sao paulo",
    "são paulo",
    "santos",
    "gremio",
    "grêmio",
    "internacional",
    "inter",
    "vasco",
    "botafogo",
    "cruzeiro",
    "atletico",
    "atlético",
    "bahia",
    "fortaleza",
    "sport",
    "ceara",
    "ceará",
}

GENERAL_VIRAL_TERMS = {
    "polemica",
    "polêmica",
    "reacao",
    "reação",
    "bastidor",
    "bastidores",
    "provocacao",
    "provocação",
    "detona",
    "critic",
    "treta",
    "debate",
    "climao",
    "climão",
    "zoeira",
    "zoacao",
    "zoação",
    "brincadeira",
    "emocion",
    "revela",
    "bomba",
    "choc",
}

POLITICS_VIRAL_TERMS = {
    "ataque",
    "ameaca",
    "ameaça",
    "crise",
    "guerra",
    "conflito",
    "urgente",
    "alerta",
    "impacto no brasil",
    "mercado",
    "dolar",
    "dólar",
    "inflacao",
    "inflação",
    "stf",
    "trump",
    "lula",
    "bolsonaro",
}

SPORTS_VIRAL_TERMS = {
    "arbitragem",
    "var",
    "polêmica",
    "polemica",
    "bastidores",
    "provocacao",
    "provocação",
    "reacao",
    "reação",
    "zoeira",
    "zoacao",
    "zoação",
    "climão",
    "climao",
    "detona",
    "treta",
    "rival",
    "rivalidade",
}

DEFAULT_TREND_PROFILE = {
    "name": "economia_geopolitica",
    "query": "podcast guerra politica geopolitica governo",
    "query_label": "podcast + guerra/politica",
    "primary_terms": WAR_PRIORITY_TERMS | POLITICS_PRIORITY_TERMS,
    "subscriptions_only": True,
    "max_channels": 24,
    "recent_hours": 48,
    "uploads_per_channel": 4,
    "max_top_videos": 18,
    "per_channel_cap": 2,
    "minimum_primary_hits": 1,
    "minimum_cut_score": 58,
    "minimum_duration_seconds": 360,
    "not_found_error": "Nao encontrei videos de guerra/politica com cara de podcast entre os canais inscritos nas ultimas 48 horas.",
}

MAIN_CHANNEL_TREND_PROFILE = {
    "name": "politica_guerra_expansa",
    "query": "podcast guerra geopolitica politica governo congresso conflito analise debate",
    "query_label": "politica + guerra/geopolitica",
    "primary_terms": WAR_PRIORITY_TERMS | POLITICS_PRIORITY_TERMS,
    "subscriptions_only": True,
    "max_channels": 72,
    "recent_hours": 96,
    "uploads_per_channel": 6,
    "max_top_videos": 36,
    "per_channel_cap": 2,
    "minimum_primary_hits": 1,
    "minimum_cut_score": 72,
    "minimum_duration_seconds": 480,
    "not_found_error": "Nao encontrei videos fortes de politica/guerra entre os canais inscritos recentemente.",
}

SPORT_TREND_PROFILE = {
    "name": "futebol_rodada",
    "query": "futebol brasileirao libertadores arbitragem mercado da bola rodada",
    "query_label": "futebol + rodada/arbitragem",
    "primary_terms": SPORTS_PRIORITY_TERMS,
    "subscriptions_only": True,
    "blocked_terms": {"ao vivo", "narração", "narracao", "live", "lives"},
    "max_channels": 120,
    "recent_hours": 96,
    "uploads_per_channel": 10,
    "max_top_videos": 72,
    "per_channel_cap": 4,
    "minimum_primary_hits": 1,
    "minimum_cut_score": 74,
    "minimum_duration_seconds": 300,
    "not_found_error": "Nao encontrei videos de futebol com potencial de corte entre os canais inscritos recentemente.",
}


def _trend_profile_for_channel(channel_profile_name: str | None = None) -> dict[str, Any]:
    lowered = _normalize_search_text(channel_profile_name or "")
    if any(keyword in lowered for keyword in ["esporte", "futebol", "bola", "rodada", "g4", "libertadores", "brasileirao", "brasileirão"]):
        return SPORT_TREND_PROFILE
    if "zero cortes" in lowered:
        return MAIN_CHANNEL_TREND_PROFILE
    return DEFAULT_TREND_PROFILE


def _split_channel_terms(value: Any) -> list[str]:
    tokens = re.split(r"[\n,;|]+", str(value or ""))
    return [str(token or "").strip() for token in tokens if str(token or "").strip()]


def _trend_profile_with_preferences(
    trend_profile: dict[str, Any],
    channel_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = dict(trend_profile or DEFAULT_TREND_PROFILE)
    preferences = channel_preferences or {}
    preferred_terms = _split_channel_terms(preferences.get("preferred_terms"))
    avoid_terms = _split_channel_terms(preferences.get("avoid_terms"))
    viral_tone = re.sub(r"\s+", " ", str(preferences.get("viral_tone") or "")).strip()
    blocked_terms = set(profile.get("blocked_terms") or set())
    blocked_terms.update(term.lower() for term in avoid_terms if term)
    viral_terms = [term.lower() for term in _split_channel_terms(viral_tone) if term]
    profile["preferred_terms"] = preferred_terms
    profile["avoid_terms"] = avoid_terms
    profile["viral_tone"] = viral_tone
    profile["viral_terms"] = viral_terms
    profile["blocked_terms"] = blocked_terms
    return profile


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Variavel obrigatoria ausente: {name}")
    return value


def _required_config(name: str, explicit_value: str | None = None) -> str:
    value = str(explicit_value or "").strip()
    if value:
        return value
    return _required_env(name)


def youtube_redirect_uri(explicit_value: str | None = None) -> str:
    return _required_config("YOUTUBE_REDIRECT_URI", explicit_value)


def _youtube_api_get(access_token: str, path: str, *, params: dict[str, Any]) -> dict[str, Any]:
    with httpx.Client(timeout=30) as client:
        response = client.get(
            f"{YOUTUBE_API_URL}/{path.lstrip('/')}",
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        return response.json()


def _normalize_search_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_text.lower().strip()


def _search_tokens_from_title(title: str, *, limit: int = 5) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", _normalize_search_text(title))
    picked: list[str] = []
    for token in tokens:
        if len(token) < 4 or token in YOUTUBE_QUERY_STOPWORDS:
            continue
        if token not in picked:
            picked.append(token)
        if len(picked) >= limit:
            break
    return picked


def _build_title_queries(title: str) -> list[str]:
    normalized_title = re.sub(r"\s+", " ", str(title or "").strip())
    token_query = " ".join(_search_tokens_from_title(normalized_title, limit=5)).strip()
    compact_title = " ".join(normalized_title.split()[:8]).strip()
    queries: list[str] = []
    for candidate in [token_query, compact_title, "economia brasil"]:
        cleaned = re.sub(r"\s+", " ", candidate).strip()
        if cleaned and cleaned not in queries:
            queries.append(cleaned)
    return queries


def _parse_iso8601_duration_seconds(raw: str) -> int:
    text = str(raw or "").strip().upper()
    if not text:
        return 0
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", text)
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return (hours * 3600) + (minutes * 60) + seconds


def _format_duration_label(seconds: int) -> str:
    total = max(0, int(seconds or 0))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    if hours:
        return f"{hours}h {minutes:02d}min"
    if minutes:
        return f"{minutes}min {secs:02d}s"
    return f"{secs}s"


def _days_since_published(value: str) -> int:
    raw = str(value or "").strip()
    if not raw:
        return 9999
    try:
        published = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return 9999
    now = datetime.now(timezone.utc)
    return max(0, int((now - published).total_seconds() // 86400))


def _query_token_hits(title: str, query: str) -> int:
    title_tokens = set(_search_tokens_from_title(title, limit=8))
    query_tokens = set(_search_tokens_from_title(query, limit=8))
    if not title_tokens or not query_tokens:
        return 0
    return len(title_tokens & query_tokens)


def _term_hits(text: str, terms: set[str]) -> int:
    normalized = _normalize_search_text(text)
    return sum(1 for term in terms if term in normalized)


def _radar_blocked_terms_found(text: str, trend_profile: dict[str, Any] | None = None) -> list[str]:
    normalized = _normalize_search_text(text)
    blocked_terms = set((trend_profile or {}).get("blocked_terms") or set())
    return [term for term in blocked_terms if term and term in normalized]


def _radar_viral_hits(text: str, trend_profile: dict[str, Any] | None = None) -> int:
    profile = trend_profile or DEFAULT_TREND_PROFILE
    profile_name = str(profile.get("name") or "")
    terms = set(GENERAL_VIRAL_TERMS)
    if profile_name == "futebol_rodada":
        terms.update(SPORTS_VIRAL_TERMS)
    elif profile_name == "politica_guerra_expansa":
        terms.update(POLITICS_VIRAL_TERMS)
    terms.update(str(term).strip().lower() for term in (profile.get("viral_terms") or []) if str(term).strip())
    return _term_hits(text, terms)


def _looks_like_already_cut_video(title: str) -> bool:
    normalized = _normalize_search_text(title)
    tokens = set(re.findall(r"[a-z0-9]+", normalized))
    return any(token in tokens for token in CUT_BLOCKLIST_TERMS)


def _cut_potential_score(video: dict[str, Any], query: str, *, trend_profile: dict[str, Any] | None = None) -> tuple[int, list[str]]:
    profile = trend_profile or DEFAULT_TREND_PROFILE
    title = str(video.get("title") or "")
    description = str(video.get("description") or "")
    combined_text = f"{title} {description}".strip()
    duration_seconds = int(video.get("duration_seconds") or 0)
    view_count = int(video.get("view_count") or 0)
    age_days = int(video.get("age_days") or 9999)
    topic_hits = _query_token_hits(combined_text, query)
    looks_cut = _looks_like_already_cut_video(title)
    podcast_hits = _term_hits(combined_text, PODCAST_PRIORITY_TERMS)
    war_hits = _term_hits(combined_text, WAR_PRIORITY_TERMS)
    politics_hits = _term_hits(combined_text, POLITICS_PRIORITY_TERMS)
    sports_hits = _term_hits(combined_text, SPORTS_PRIORITY_TERMS)
    primary_hits = _term_hits(combined_text, set(profile.get("primary_terms") or set()))
    preferred_hits = _term_hits(combined_text, set(str(term).lower() for term in (profile.get("preferred_terms") or []) if str(term).strip()))
    blocked_hits = _radar_blocked_terms_found(combined_text, profile)
    viral_hits = _radar_viral_hits(combined_text, profile)

    score = 0
    reasons: list[str] = []

    if 900 <= duration_seconds <= 7200:
        score += 38
        reasons.append("duracao premium para tirar varios cortes")
    elif 1200 <= duration_seconds <= 10_800:
        score += 34
        reasons.append("duracao forte para tirar varios cortes")
    elif 720 <= duration_seconds < 1200:
        score += 24
        reasons.append("duracao boa para extrair cortes")
    elif 480 <= duration_seconds < 720:
        score += 14
        reasons.append("video medio com potencial de corte")
    else:
        score -= 16
        reasons.append("duracao menos ideal para corte")

    if view_count >= 500_000:
        score += 28
        reasons.append("muito forte em views")
    elif view_count >= 100_000:
        score += 22
        reasons.append("views altas")
    elif view_count >= 25_000:
        score += 16
        reasons.append("boa tracao")
    elif view_count >= 5_000:
        score += 9
        reasons.append("alguma tracao")

    if age_days <= 2:
        score += 26
        reasons.append("saiu nas ultimas 48 horas")
    elif age_days <= 7:
        score += 14
        reasons.append("bem recente")
    elif age_days <= 21:
        score += 6
        reasons.append("ainda recente")

    if age_days <= 2 and view_count >= 25_000:
        score += 10
        reasons.append("ganhou tracao muito rapido")

    if podcast_hits >= 1:
        score += 26
        reasons.append("tem cara de podcast ou conversa longa")

    if profile.get("name") == "futebol_rodada":
        if sports_hits >= 3:
            score += 28
            reasons.append("tema forte de futebol e rodada")
        elif sports_hits >= 1:
            score += 16
            reasons.append("tema alinhado com futebol")
    elif profile.get("name") == "politica_guerra_expansa":
        combined_geopolitics = war_hits + politics_hits
        if war_hits >= 3:
            score += 30
            reasons.append("tema muito forte de guerra e geopolitica")
        elif politics_hits >= 3:
            score += 28
            reasons.append("tema muito forte de politica")
        elif combined_geopolitics >= 3:
            score += 24
            reasons.append("tema quente de politica e conflito")
        elif war_hits >= 1 or politics_hits >= 1:
            score += 14
            reasons.append("tema alinhado com politica/guerra")
    else:
        if war_hits >= 2:
            score += 24
            reasons.append("tema forte de guerra ou geopolitica")
        elif politics_hits >= 2:
            score += 22
            reasons.append("tema forte de politica")
        elif war_hits >= 1 or politics_hits >= 1:
            score += 12
            reasons.append("tema alinhado com guerra/politica")

    if topic_hits >= 3:
        score += 20
        reasons.append("tema muito alinhado com o canal")
    elif topic_hits == 2:
        score += 14
        reasons.append("tema alinhado")
    elif topic_hits == 1:
        score += 8
        reasons.append("alguma conexao com o tema")

    if looks_cut:
        score -= 35
        reasons.append("parece ser corte/short ja pronto")
    else:
        score += 10
        reasons.append("tem cara de video completo")

    if primary_hits <= 0:
        score -= 26
    elif primary_hits >= 3:
        score += 14

    if viral_hits >= 4:
        score += 18
        reasons.append("gancho viral forte para corte")
    elif viral_hits >= 2:
        score += 10
        reasons.append("tem sinais fortes de repercussao")
    elif viral_hits >= 1:
        score += 5

    if preferred_hits >= 3:
        score += 18
        reasons.append("bate forte com as prioridades do canal")
    elif preferred_hits >= 1:
        score += 10
        reasons.append("alinhado com o que o canal quer puxar")

    if blocked_hits:
        score -= 60
        reasons.append(f"bloqueado por termos a evitar: {', '.join(blocked_hits[:2])}")

    if "?" in title:
        score += 4
    if any(token in _normalize_search_text(title) for token in ["vs", "x ", "x|", "detona", "reage", "crise", "ataque", "polemica", "polêmica"]):
        score += 6

    return max(1, min(score, 100)), reasons[:4]


def _videos_details(access_token: str, video_ids: list[str]) -> list[dict[str, Any]]:
    if not video_ids:
        return []
    payload = _youtube_api_get(
        access_token,
        "/videos",
        params={
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(video_ids[:20]),
            "maxResults": str(min(len(video_ids), 20)),
        },
    )
    indexed: dict[str, dict[str, Any]] = {}
    for item in payload.get("items") or []:
        snippet = item.get("snippet") or {}
        thumbnails = snippet.get("thumbnails") or {}
        content_details = item.get("contentDetails") or {}
        duration_seconds = _parse_iso8601_duration_seconds(str(content_details.get("duration") or ""))
        published_at = snippet.get("publishedAt") or ""
        indexed[str(item.get("id") or "")] = {
            "video_id": item.get("id"),
            "title": snippet.get("title") or "",
            "description": snippet.get("description") or "",
            "channel_title": snippet.get("channelTitle") or "",
            "channel_id": snippet.get("channelId") or "",
            "published_at": published_at,
            "thumbnail_url": (
                (thumbnails.get("high") or {}).get("url")
                or (thumbnails.get("medium") or {}).get("url")
                or (thumbnails.get("default") or {}).get("url")
                or ""
            ),
            "url": f"https://www.youtube.com/watch?v={item.get('id')}",
            "view_count": int(((item.get("statistics") or {}).get("viewCount")) or 0),
            "duration_seconds": duration_seconds,
            "duration_label": _format_duration_label(duration_seconds),
            "age_days": _days_since_published(published_at),
        }
    return [indexed[video_id] for video_id in video_ids if video_id in indexed]


def _fetch_subscribed_channels(access_token: str, *, max_results: int = 20) -> list[dict[str, Any]]:
    channels: list[dict[str, Any]] = []
    seen_channel_ids: set[str] = set()
    page_token = ""
    remaining = max(1, min(int(max_results or 20), 200))
    while remaining > 0:
        params: dict[str, Any] = {
            "part": "snippet",
            "mine": "true",
            "maxResults": str(min(remaining, 50)),
        }
        if page_token:
            params["pageToken"] = page_token
        payload = _youtube_api_get(access_token, "/subscriptions", params=params)
        for item in payload.get("items") or []:
            snippet = item.get("snippet") or {}
            resource = snippet.get("resourceId") or {}
            channel_id = str(resource.get("channelId") or "").strip()
            if not channel_id or channel_id in seen_channel_ids:
                continue
            seen_channel_ids.add(channel_id)
            channels.append(
                {
                    "channel_id": channel_id,
                    "title": snippet.get("title") or "",
                    "description": snippet.get("description") or "",
                }
            )
            remaining -= 1
            if remaining <= 0:
                break
        page_token = str(payload.get("nextPageToken") or "").strip()
        if not page_token:
            break
    return channels


def _fetch_uploads_playlists(access_token: str, channel_ids: list[str]) -> list[dict[str, Any]]:
    if not channel_ids:
        return []
    payload = _youtube_api_get(
        access_token,
        "/channels",
        params={
            "part": "snippet,contentDetails",
            "id": ",".join(channel_ids[:50]),
            "maxResults": str(min(len(channel_ids), 50)),
        },
    )
    results: list[dict[str, Any]] = []
    for item in payload.get("items") or []:
        snippet = item.get("snippet") or {}
        uploads_id = str((((item.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")) or "").strip()
        if not uploads_id:
            continue
        results.append(
            {
                "channel_id": str(item.get("id") or "").strip(),
                "channel_title": snippet.get("title") or "",
                "uploads_playlist_id": uploads_id,
            }
        )
    return results


def _fetch_recent_uploads_from_subscriptions(
    access_token: str,
    *,
    max_channels: int = 20,
    recent_hours: int = 48,
    uploads_per_channel: int = 4,
    exclude_channel_id: str = "",
) -> list[dict[str, Any]]:
    subscribed_channels = _fetch_subscribed_channels(access_token, max_results=max_channels)
    playlist_sources = _fetch_uploads_playlists(access_token, [str(item.get("channel_id") or "") for item in subscribed_channels])
    since = datetime.now(timezone.utc) - timedelta(hours=max(1, int(recent_hours or 48)))
    collected: list[dict[str, Any]] = []

    for source in playlist_sources:
        channel_id = str(source.get("channel_id") or "").strip()
        if exclude_channel_id and channel_id == exclude_channel_id:
            continue
        payload = _youtube_api_get(
            access_token,
            "/playlistItems",
            params={
                "part": "snippet,contentDetails",
                "playlistId": str(source.get("uploads_playlist_id") or ""),
                "maxResults": str(max(1, min(int(uploads_per_channel or 4), 12))),
            },
        )
        for item in payload.get("items") or []:
            snippet = item.get("snippet") or {}
            resource = snippet.get("resourceId") or {}
            video_id = str(resource.get("videoId") or (item.get("contentDetails") or {}).get("videoId") or "").strip()
            if not video_id:
                continue
            published_raw = str(snippet.get("publishedAt") or "").strip()
            try:
                published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            if published_at < since:
                continue
            collected.append(
                {
                    "video_id": video_id,
                    "channel_id": channel_id,
                    "channel_title": str(source.get("channel_title") or ""),
                    "published_at": published_raw,
                }
            )
    return collected


def _diversify_ranked_videos(ranked_videos: list[dict[str, Any]], *, limit: int, per_channel_cap: int = 2) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    per_channel_counts: dict[str, int] = {}

    for item in ranked_videos:
        channel_id = str(item.get("channel_id") or "").strip() or "__unknown__"
        if per_channel_counts.get(channel_id, 0) >= max(1, int(per_channel_cap or 2)):
            continue
        selected.append(item)
        per_channel_counts[channel_id] = per_channel_counts.get(channel_id, 0) + 1
        if len(selected) >= max(1, int(limit or 1)):
            break

    if len(selected) >= max(1, int(limit or 1)):
        return selected

    selected_ids = {str(item.get("video_id") or "").strip() for item in selected}
    for item in ranked_videos:
        video_id = str(item.get("video_id") or "").strip()
        if video_id in selected_ids:
            continue
        selected.append(item)
        selected_ids.add(video_id)
        if len(selected) >= max(1, int(limit or 1)):
            break

    return selected


def _radar_source_priority(item: dict[str, Any]) -> int:
    return 1 if str(item.get("source_type") or "").strip() == "subscription_channel" else 0


def _radar_sort_key(item: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        _radar_source_priority(item),
        int(item.get("view_count") or 0),
        int(item.get("cut_score") or 0),
        -int(item.get("age_days") or 9999),
    )


def _search_popular_full_videos_for_cuts(
    access_token: str,
    query: str,
    *,
    exclude_channel_id: str = "",
    exclude_video_ids: set[str] | None = None,
    limit: int = 4,
    trend_profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    blocked_ids = set(exclude_video_ids or set())
    min_duration_seconds = max(0, int((trend_profile or {}).get("minimum_duration_seconds") or 0))
    published_after = (datetime.now(timezone.utc) - timedelta(days=270)).strftime("%Y-%m-%dT%H:%M:%SZ")
    variants = [
        {
            "part": "snippet",
            "type": "video",
            "q": query,
            "maxResults": "12",
            "order": "viewCount",
            "regionCode": "BR",
            "relevanceLanguage": "pt",
            "videoDuration": "medium",
            "publishedAfter": published_after,
        },
        {
            "part": "snippet",
            "type": "video",
            "q": query,
            "maxResults": "12",
            "order": "relevance",
            "regionCode": "BR",
            "relevanceLanguage": "pt",
            "videoDuration": "medium",
            "publishedAfter": published_after,
        },
        {
            "part": "snippet",
            "type": "video",
            "q": query,
            "maxResults": "12",
            "order": "viewCount",
            "regionCode": "BR",
            "relevanceLanguage": "pt",
            "videoDuration": "long",
            "publishedAfter": published_after,
        },
        {
            "part": "snippet",
            "type": "video",
            "q": query,
            "maxResults": "12",
            "order": "relevance",
            "regionCode": "BR",
            "relevanceLanguage": "pt",
            "videoDuration": "long",
            "publishedAfter": published_after,
        },
        {
            "part": "snippet",
            "type": "video",
            "q": query,
            "maxResults": "12",
            "order": "viewCount",
            "regionCode": "BR",
            "relevanceLanguage": "pt",
            "publishedAfter": published_after,
        },
    ]

    ranked_items: list[dict[str, Any]] = []
    for params in variants:
        payload = _youtube_api_get(access_token, "/search", params=params)
        ordered_ids: list[str] = []
        for item in payload.get("items") or []:
            snippet = item.get("snippet") or {}
            video_id = str(((item.get("id") or {}).get("videoId")) or "").strip()
            if not video_id or video_id in blocked_ids:
                continue
            if exclude_channel_id and str(snippet.get("channelId") or "").strip() == exclude_channel_id:
                continue
            if video_id not in ordered_ids:
                ordered_ids.append(video_id)
            if len(ordered_ids) >= 10:
                break
        detailed = _videos_details(access_token, ordered_ids)
        for item in detailed:
            video_id = str(item.get("video_id") or "").strip()
            if video_id in blocked_ids:
                continue
            if int(item.get("duration_seconds") or 0) < min_duration_seconds:
                continue
            if _radar_blocked_terms_found(
                str(item.get("title") or "") + " " + str(item.get("description") or ""),
                trend_profile,
            ):
                continue
            score, reasons = _cut_potential_score(item, query, trend_profile=trend_profile)
            enriched = item | {"cut_score": score, "cut_reasons": reasons, "source_type": "search_fallback"}
            if video_id not in {str(existing.get("video_id") or "") for existing in ranked_items}:
                ranked_items.append(enriched)

    ranked_items.sort(key=_radar_sort_key, reverse=True)
    return ranked_items[:limit]


def fetch_recent_channel_uploads(access_token: str, *, max_results: int = 6) -> dict[str, Any]:
    payload = _youtube_api_get(
        access_token,
        "/channels",
        params={"part": "snippet,contentDetails", "mine": "true", "maxResults": "1"},
    )
    items = payload.get("items") or []
    if not items:
        raise ValueError("Nenhum canal do YouTube foi encontrado para essa conta.")

    channel = items[0]
    snippet = channel.get("snippet") or {}
    related = (channel.get("contentDetails") or {}).get("relatedPlaylists") or {}
    uploads_playlist_id = str(related.get("uploads") or "").strip()
    if not uploads_playlist_id:
        raise ValueError("Nao encontrei a playlist de uploads do canal autenticado no YouTube.")

    playlist_payload = _youtube_api_get(
        access_token,
        "/playlistItems",
        params={
            "part": "snippet,contentDetails",
            "playlistId": uploads_playlist_id,
            "maxResults": str(max(1, min(int(max_results or 6), 12))),
        },
    )

    videos: list[dict[str, Any]] = []
    for item in playlist_payload.get("items") or []:
        item_snippet = item.get("snippet") or {}
        resource = item_snippet.get("resourceId") or {}
        video_id = str(resource.get("videoId") or (item.get("contentDetails") or {}).get("videoId") or "").strip()
        if not video_id:
            continue
        thumbnails = item_snippet.get("thumbnails") or {}
        videos.append(
            {
                "video_id": video_id,
                "title": item_snippet.get("title") or "",
                "published_at": item_snippet.get("publishedAt") or "",
                "thumbnail_url": (
                    (thumbnails.get("high") or {}).get("url")
                    or (thumbnails.get("medium") or {}).get("url")
                    or (thumbnails.get("default") or {}).get("url")
                    or ""
                ),
                "url": f"https://www.youtube.com/watch?v={video_id}",
            }
        )

    return {
        "channel": {
            "id": channel.get("id"),
            "title": snippet.get("title") or "",
            "custom_url": snippet.get("customUrl") or "",
            "published_at": snippet.get("publishedAt") or "",
        },
        "videos": videos,
    }


def build_channel_trend_ideas(
    access_token: str,
    *,
    recent_limit: int = 4,
    videos_per_topic: int = 4,
    channel_profile_name: str | None = None,
    channel_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trend_profile = _trend_profile_with_preferences(
        _trend_profile_for_channel(channel_profile_name),
        channel_preferences,
    )
    subscriptions_only = bool(trend_profile.get("subscriptions_only", True))
    own_channel_payload = fetch_recent_channel_uploads(access_token, max_results=1)
    own_channel = own_channel_payload.get("channel") or {}
    recent_candidates = _fetch_recent_uploads_from_subscriptions(
        access_token,
        max_channels=int(trend_profile.get("max_channels") or 24),
        recent_hours=int(trend_profile.get("recent_hours") or 48),
        uploads_per_channel=int(trend_profile.get("uploads_per_channel") or 4),
        exclude_channel_id=str(own_channel.get("id") or ""),
    )
    if not recent_candidates:
        raise ValueError(
            f"Nao encontrei videos recentes dos canais inscritos nas ultimas {int(trend_profile.get('recent_hours') or 48)} horas."
        )

    candidate_details = _videos_details(access_token, [str(item.get("video_id") or "") for item in recent_candidates])
    recent_meta = {
        str(item.get("video_id") or ""): item
        for item in recent_candidates
        if str(item.get("video_id") or "").strip()
    }
    ranked_videos: list[dict[str, Any]] = []
    secondary_ranked_videos: list[dict[str, Any]] = []
    topic_query = str(trend_profile.get("query") or "")
    min_primary_hits = max(0, int(trend_profile.get("minimum_primary_hits") or 0))
    min_cut_score = max(1, int(trend_profile.get("minimum_cut_score") or 1))
    min_duration_seconds = max(0, int(trend_profile.get("minimum_duration_seconds") or 0))
    for video in candidate_details:
        video_id = str(video.get("video_id") or "").strip()
        merged = video | recent_meta.get(video_id, {})
        if int(merged.get("duration_seconds") or 0) < min_duration_seconds:
            continue
        score, reasons = _cut_potential_score(merged, topic_query, trend_profile=trend_profile)
        if _radar_blocked_terms_found(
            str(merged.get("title") or "") + " " + str(merged.get("description") or ""),
            trend_profile,
        ):
            continue
        primary_hits = _term_hits(
            str(merged.get("title") or "") + " " + str(merged.get("description") or ""),
            set(trend_profile.get("primary_terms") or set()),
        )
        if primary_hits < min_primary_hits:
            continue
        enriched = merged | {
            "cut_score": score,
            "cut_reasons": reasons,
            "source_type": "subscription_channel",
            "primary_hits": primary_hits,
        }
        if score >= min_cut_score:
            ranked_videos.append(enriched)
        else:
            secondary_ranked_videos.append(enriched)

    ranked_videos.sort(key=_radar_sort_key, reverse=True)
    diversified_limit = max(
        1,
        min(
            int(videos_per_topic or 4) * max(1, min(int(recent_limit or 4), 16)),
            int(trend_profile.get("max_top_videos") or 18),
        ),
    )
    if len(ranked_videos) < diversified_limit:
        secondary_ranked_videos.sort(key=_radar_sort_key, reverse=True)
        for item in secondary_ranked_videos:
            video_id = str(item.get("video_id") or "").strip()
            if video_id in {str(existing.get("video_id") or "") for existing in ranked_videos}:
                continue
            ranked_videos.append(item)
            if len(ranked_videos) >= diversified_limit:
                break
    if len(ranked_videos) < diversified_limit and not subscriptions_only:
        fallback_candidates = _search_popular_full_videos_for_cuts(
            access_token,
            topic_query,
            exclude_channel_id=str(own_channel.get("id") or ""),
            exclude_video_ids={str(item.get("video_id") or "") for item in ranked_videos + secondary_ranked_videos},
            limit=max(diversified_limit - len(ranked_videos), int(videos_per_topic or 4)),
            trend_profile=trend_profile,
        )
        ranked_videos.extend(
            item
            for item in fallback_candidates
            if int(item.get("cut_score") or 0) >= min_cut_score
        )
    ranked_videos.sort(key=_radar_sort_key, reverse=True)
    top_videos = _diversify_ranked_videos(
        ranked_videos,
        limit=diversified_limit,
        per_channel_cap=int(trend_profile.get("per_channel_cap") or 2),
    )
    if not top_videos:
        raise ValueError(str(trend_profile.get("not_found_error") or "Nao encontrei videos com potencial de corte entre os canais inscritos recentemente."))

    grouped: dict[str, dict[str, Any]] = {}
    for video in top_videos:
        channel_id = str(video.get("channel_id") or "").strip() or f"channel-{len(grouped) + 1}"
        bucket = grouped.setdefault(
            channel_id,
            {
                "seed_video_id": "",
                "seed_title": str(video.get("channel_title") or "Canal inscrito"),
                "seed_url": f"https://www.youtube.com/channel/{channel_id}" if channel_id.startswith("UC") else "",
                "seed_published_at": "",
                "query": str(trend_profile.get("query_label") or ""),
                "idea_type": "subscription_channels_recent_48h",
                "videos": [],
            },
        )
        bucket["videos"].append(video)

    ideas = list(grouped.values())[: max(1, min(int(recent_limit or 4), 16))]
    return {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "channel": own_channel | {"source_mode": "subscriptions_recent_48h"},
        "trend_profile": {
            "name": str(trend_profile.get("name") or ""),
            "query": str(trend_profile.get("query_label") or ""),
            "preferred_terms": list(trend_profile.get("preferred_terms") or []),
            "avoid_terms": list(trend_profile.get("avoid_terms") or []),
            "viral_tone": str(trend_profile.get("viral_tone") or ""),
            "subscriptions_only": subscriptions_only,
            "sort_priority": "views_then_cut_score",
        },
        "recent_uploads": top_videos[:24],
        "ideas": ideas,
    }


def build_youtube_auth_url(state: str, *, client_id: str | None = None, redirect_uri: str | None = None) -> dict[str, str]:
    client_id = _required_config("YOUTUBE_CLIENT_ID", client_id)
    redirect_uri = youtube_redirect_uri(redirect_uri)
    scope = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"

    url = (
        f"{GOOGLE_AUTH_URL}?response_type=code"
        f"&client_id={quote_plus(client_id)}"
        f"&redirect_uri={quote_plus(redirect_uri)}"
        f"&scope={quote_plus(scope)}"
        f"&access_type=offline"
        f"&prompt=consent"
        f"&include_granted_scopes=true"
        f"&state={quote_plus(state)}"
    )
    return {"auth_url": url, "state": state, "redirect_uri": redirect_uri}


def exchange_youtube_code(
    code: str,
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
    redirect_uri: str | None = None,
) -> dict[str, Any]:
    payload = {
        "code": code,
        "client_id": _required_config("YOUTUBE_CLIENT_ID", client_id),
        "client_secret": _required_config("YOUTUBE_CLIENT_SECRET", client_secret),
        "redirect_uri": youtube_redirect_uri(redirect_uri),
        "grant_type": "authorization_code",
    }
    with httpx.Client(timeout=30) as client:
        try:
            response = client.post(GOOGLE_TOKEN_URL, data=payload)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text if exc.response is not None else str(exc)
            raise ValueError(f"Erro OAuth YouTube (exchange): {detail}") from exc


def refresh_youtube_token(
    refresh_token_value: str,
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
) -> dict[str, Any]:
    payload = {
        "refresh_token": refresh_token_value,
        "client_id": _required_config("YOUTUBE_CLIENT_ID", client_id),
        "client_secret": _required_config("YOUTUBE_CLIENT_SECRET", client_secret),
        "grant_type": "refresh_token",
    }
    with httpx.Client(timeout=30) as client:
        try:
            response = client.post(GOOGLE_TOKEN_URL, data=payload)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text if exc.response is not None else str(exc)
            raise ValueError(f"Erro OAuth YouTube (refresh): {detail}") from exc


def fetch_youtube_channel(access_token: str) -> dict[str, Any]:
    with httpx.Client(timeout=30) as client:
        response = client.get(
            f"{YOUTUBE_API_URL}/channels",
            params={"part": "snippet", "mine": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        payload = response.json()
    items = payload.get("items") or []
    if not items:
        raise ValueError("Nenhum canal do YouTube foi encontrado para essa conta.")
    channel = items[0]
    snippet = channel.get("snippet") or {}
    return {
        "id": channel.get("id"),
        "title": snippet.get("title") or "",
        "custom_url": snippet.get("customUrl") or "",
        "published_at": snippet.get("publishedAt") or "",
        "thumbnails": snippet.get("thumbnails") or {},
    }


def upload_youtube_short(
    access_token: str,
    video_path: Path,
    *,
    title: str,
    description: str,
    privacy_status: str = "private",
    publish_at: str | None = None,
) -> dict[str, Any]:
    normalized_privacy = (privacy_status or "private").strip().lower()
    if normalized_privacy not in {"private", "unlisted", "public", "scheduled"}:
        normalized_privacy = "private"
    normalized_publish_at = ""
    if normalized_privacy == "scheduled":
        raw_publish_at = str(publish_at or "").strip()
        if not raw_publish_at:
            raise ValueError("Informe data e hora para programar a publicacao no YouTube.")
        try:
            parsed_publish_at = datetime.fromisoformat(raw_publish_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Data/hora de programacao invalida. Use um horario valido.") from exc
        if parsed_publish_at.tzinfo is None:
            parsed_publish_at = parsed_publish_at.replace(tzinfo=SAO_PAULO_TZ)
        scheduled_at_utc = parsed_publish_at.astimezone(timezone.utc)
        if scheduled_at_utc <= datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("A publicacao programada precisa estar pelo menos 5 minutos no futuro.")
        normalized_publish_at = scheduled_at_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        normalized_privacy = "private"

    metadata = {
        "snippet": {
            "title": (title or "").strip()[:100],
            "description": (description or "").strip()[:5000],
            "categoryId": "22",
            "defaultLanguage": "pt-BR",
        },
        "status": {
            "privacyStatus": normalized_privacy,
            "selfDeclaredMadeForKids": False,
        },
    }
    if normalized_publish_at:
        metadata["status"]["publishAt"] = normalized_publish_at

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Length": str(video_path.stat().st_size),
        "X-Upload-Content-Type": "video/mp4",
    }

    with httpx.Client(timeout=900) as client:
        start = client.post(
            YOUTUBE_UPLOAD_URL,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers=headers,
            json=metadata,
        )
        try:
            start.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = start.text.strip() if start is not None else ""
            try:
                payload = start.json()
                error = payload.get("error") or {}
                errors = error.get("errors") or []
                reason = str((errors[0] or {}).get("reason") or "").strip() if errors else ""
                message = str(error.get("message") or "").strip()
                if reason == "uploadLimitExceeded":
                    raise ValueError(
                        "O YouTube bloqueou novos uploads dessa conta por enquanto (uploadLimitExceeded). "
                        "Espere a liberacao da conta/canal e tente novamente mais tarde."
                    ) from exc
                if message:
                    raise ValueError(f"Falha ao iniciar upload no YouTube: {message}") from exc
            except ValueError:
                raise
            except Exception:
                pass
            raise ValueError(f"Falha ao iniciar upload no YouTube: {detail or str(exc)}") from exc
        upload_url = start.headers.get("Location", "").strip()
        if not upload_url:
            raise ValueError("Google nao retornou a URL de upload resumivel do video.")

        with video_path.open("rb") as video_file:
            finish = client.put(
                upload_url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "video/mp4",
                    "Content-Length": str(video_path.stat().st_size),
                },
                content=video_file.read(),
            )
        try:
            finish.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = finish.text.strip() if finish is not None else ""
            raise ValueError(f"Falha ao concluir upload no YouTube: {detail or str(exc)}") from exc
        payload = finish.json()
        if normalized_publish_at:
            payload["publishAt"] = normalized_publish_at
        return payload


def upload_youtube_thumbnail(access_token: str, video_id: str, image_path: Path) -> dict[str, Any]:
    video_id = (video_id or "").strip()
    if not video_id:
        raise ValueError("video_id do YouTube nao informado para upload da thumbnail.")
    if not image_path.is_file():
        raise ValueError("Arquivo de thumbnail nao encontrado para upload.")

    with httpx.Client(timeout=180) as client:
        with image_path.open("rb") as image_file:
            response = client.post(
                YOUTUBE_THUMBNAIL_UPLOAD_URL,
                params={"videoId": video_id},
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "image/jpeg"},
                content=image_file.read(),
            )
        response.raise_for_status()
        return response.json()
