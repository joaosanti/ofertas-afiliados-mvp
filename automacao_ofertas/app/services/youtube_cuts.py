import os
import json
import html
import re
import shutil
import subprocess
import sys
import configparser
from io import BytesIO
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import imageio_ffmpeg
from dotenv import load_dotenv
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps
from sqlalchemy import bindparam, text

from app.database import SessionLocal


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_ROOT = PROJECT_ROOT / "automacao_ofertas" / "runtime" / "youtube_cuts"
ENV_PATH = PROJECT_ROOT / "automacao_ofertas" / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)


DEFAULT_EDITORIAL_PROFILE = {
    "name": "Economia e geopolitica com impacto no Brasil",
    "positioning": (
        "Canal de cortes focado em economia, geopolitica, mercado, energia e politica economica "
        "com consequencias claras para Brasil, dolar, inflacao, combustivel e bolso."
    ),
    "title_formula": "assunto forte + consequencia clara + impacto no Brasil quando fizer sentido",
    "short_pill": "IMPACTO NO BRASIL",
    "long_kicker": "ECONOMIA E GEOPOLITICA",
    "short_series_summary": "Corte rapido sobre economia, geopolitica e impacto no Brasil.",
    "long_series_summary": "Analise editada pelo canal com foco em economia, geopolitica e impacto no Brasil.",
    "subscribe_line": "Inscreva-se para receber cortes diretos sobre dolar, inflacao, energia e crise global.",
    "notes_summary": "Os rascunhos de titulo e descricao agora seguem o perfil economia + geopolitica + impacto no Brasil.",
    "overlay_default_text_short": "Entenda o impacto real",
    "overlay_default_text_long": "Analise completa",
    "short_opening_checklist": [
        "frase forte no primeiro segundo",
        "rosto visivel no primeiro frame",
        "tema claro sem enrolacao",
        "legenda grande com destaque em azul",
    ],
    "long_opening_checklist": [
        "titulo especifico sem cliche generico",
        "thumb limpa sem texto corte longo",
        "gancho visual nos primeiros segundos",
        "tema conectado a economia, energia ou geopolita",
    ],
    "subtitle_style": {
        "font": "Arial Bold",
        "base_color": "branca",
        "active_color": "azul",
        "outline": "preta forte",
        "behavior": "palavra ativa muda de cor conforme a fala",
    },
}

SPORT_EDITORIAL_PROFILE = {
    "name": "Futebol quente e debate da rodada",
    "positioning": (
        "Canal de cortes focado em futebol, bastidores, arbitragem, Brasileirao, Libertadores, "
        "mercado da bola e leitura de jogo com linguagem direta e gancho forte."
    ),
    "title_formula": "clube ou tema quente + lance, polemica ou decisao + efeito na rodada",
    "short_pill": "FUTEBOL EM ALTA",
    "long_kicker": "DEBATE DE FUTEBOL",
    "short_series_summary": "Corte rapido sobre futebol, debate de rodada e bastidores do jogo.",
    "long_series_summary": "Analise editada pelo canal com foco em futebol, bastidores, arbitragem e leitura da rodada.",
    "subscribe_line": "Inscreva-se para receber cortes diretos de futebol, polemicas, arbitragem e bastidores da rodada.",
    "notes_summary": "Os rascunhos de titulo e descricao agora seguem o perfil futebol + debate da rodada + gancho forte.",
    "overlay_default_text_short": "O lance que muda tudo",
    "overlay_default_text_long": "Analise do jogo",
    "short_opening_checklist": [
        "frase forte no primeiro segundo",
        "tema da rodada claro de cara",
        "lance, polemica ou decisao bem identificados",
        "legenda grande com destaque em azul",
    ],
    "long_opening_checklist": [
        "titulo especifico sem cliche generico",
        "thumb limpa com tema claro do futebol",
        "gancho visual nos primeiros segundos",
        "tema conectado a jogo, rodada, arbitragem ou bastidor",
    ],
    "subtitle_style": {
        "font": "Arial Bold",
        "base_color": "branca",
        "active_color": "azul",
        "outline": "preta forte",
        "behavior": "palavra ativa muda de cor conforme a fala",
    },
}

EDITORIAL_PROFILE = DEFAULT_EDITORIAL_PROFILE


def _editorial_profile_for_channel(channel_profile_name: str | None = None) -> dict[str, Any]:
    lowered = str(channel_profile_name or "").strip().lower()
    if any(keyword in lowered for keyword in ["esporte", "futebol", "bola", "rodada", "g4", "libertadores", "brasileirao", "brasileirão"]):
        return SPORT_EDITORIAL_PROFILE
    return DEFAULT_EDITORIAL_PROFILE

def _split_channel_terms(value: Any) -> list[str]:
    tokens = re.split(r"[\n,;|]+", str(value or ""))
    return _dedupe_preserve_order([token.strip() for token in tokens if str(token or "").strip()], limit=18)


DEFAULT_VIRAL_SIGNAL_KEYWORDS = [
    "risada",
    "rindo",
    "engrac",
    "zoacao",
    "zoeira",
    "zoando",
    "brincadeira",
    "tirou sarro",
    "sarro",
    "provoc",
    "deboche",
    "debate",
    "reacao",
    "reagiu",
    "emocao",
    "emocion",
    "vibrou",
    "comemor",
    "surto",
    "climao",
    "climão",
]


def _viral_signal_keywords(viral_tone: str | None = None) -> list[str]:
    return _dedupe_preserve_order(DEFAULT_VIRAL_SIGNAL_KEYWORDS + _split_channel_terms(viral_tone), limit=24)


def _editorial_profile_with_preferences(
    editorial_profile: dict[str, Any],
    channel_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = dict(editorial_profile or EDITORIAL_PROFILE)
    preferences = channel_preferences or {}
    preferred_terms = _split_channel_terms(preferences.get("preferred_terms"))
    avoid_terms = _split_channel_terms(preferences.get("avoid_terms"))
    viral_tone = re.sub(r"\s+", " ", str(preferences.get("viral_tone") or "")).strip()
    profile["preferred_terms"] = preferred_terms
    profile["avoid_terms"] = avoid_terms
    profile["viral_tone"] = viral_tone
    profile["viral_signal_keywords"] = _viral_signal_keywords(viral_tone)
    if preferred_terms:
        profile["title_formula"] = f"{profile['title_formula']} + priorizar termos como {', '.join(preferred_terms[:6])}"
        profile["notes_summary"] = f"{profile['notes_summary']} Priorizar termos como {', '.join(preferred_terms[:6])}."
    if avoid_terms:
        profile["notes_summary"] = f"{profile['notes_summary']} Evitar termos como {', '.join(avoid_terms[:6])}."
    if viral_tone:
        profile["notes_summary"] = f"{profile['notes_summary']} Tom mais viral pedido: {viral_tone}."
    return profile


def _count_term_hits(text: str, terms: list[str]) -> int:
    lowered = (text or "").lower()
    hits = 0
    for term in terms:
        normalized = str(term or "").strip().lower()
        if normalized and normalized in lowered:
            hits += 1
    return hits


def _profile_preference_adjustment(text: str, editorial_profile: dict[str, Any] | None = None) -> tuple[int, list[str]]:
    profile = editorial_profile or EDITORIAL_PROFILE
    preferred_terms = list(profile.get("preferred_terms") or [])
    avoid_terms = list(profile.get("avoid_terms") or [])
    viral_keywords = list(profile.get("viral_signal_keywords") or DEFAULT_VIRAL_SIGNAL_KEYWORDS)
    preferred_hits = _count_term_hits(text, preferred_terms)
    avoid_hits = _count_term_hits(text, avoid_terms)
    viral_hits = _count_term_hits(text, viral_keywords)
    score_delta = min(preferred_hits * 8, 24) - min(avoid_hits * 18, 36) + min(viral_hits * 4, 12)
    notes: list[str] = []
    if preferred_hits:
        notes.append(f"Preferencias do canal encontradas: {preferred_hits} termo(s) forte(s).")
    if avoid_hits:
        notes.append(f"Trecho penalizado por {avoid_hits} termo(s) a evitar.")
    if viral_hits and str(profile.get('viral_tone') or '').strip():
        notes.append("Trecho com sinais de reacao, zoacao ou emocao alinhados ao canal.")
    return score_delta, notes


EDITORIAL_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "dolar": ["dolar", "cambio", "moeda", "fed", "juros", "bc", "banco central"],
    "inflacao": ["inflacao", "preco", "juros", "custo", "carestia", "recessao"],
    "combustivel": ["petroleo", "gasolina", "diesel", "combustivel", "petrobras", "energia", "gas"],
    "geopolitica": ["china", "taiwan", "iran", "israel", "russia", "ucrania", "otan", "guerra", "conflito", "nuclear"],
    "mercado": ["mercado", "bolsa", "acoes", "tarifa", "investidor", "economia", "crise"],
    "brasil": ["brasil", "brasileiro", "bolso", "importacao", "exportacao", "governo", "estado"],
}

HIGH_IMPACT_WORDS = [
    "alerta",
    "explode",
    "disparar",
    "crise",
    "guerra",
    "colapso",
    "mercado",
    "dolar",
    "inflacao",
    "petroleo",
    "combustivel",
    "china",
    "iran",
    "trump",
    "brasil",
    "risco",
    "ataque",
    "tarifa",
]

WEAK_OPENERS = [
    "entao",
    "cara",
    "assim",
    "tipo",
    "ta",
    "bom",
    "pois e",
    "veja bem",
    "olha",
    "olha so",
    "seguinte",
]

SHORT_SUBTITLE_MARGIN_H = 68
SHORT_SUBTITLE_MARGIN_V = 248
SHORT_VIDEO_WIDTH = 608
SHORT_VIDEO_HEIGHT = 1080
SHORT_SMART_CROP_ANALYSIS_HEIGHT = 360
SHORT_SMART_CROP_ANALYSIS_FPS = 2
SHORT_SMART_CROP_ANALYSIS_MAX_SECONDS = 6.0
SHORT_SMART_CROP_WINDOW_STEP = 6
SHORT_SMART_CROP_CENTER_STICKINESS = 1.18
SHORT_MIN_OPENING_SCORE = 54
SHORT_MIN_VISUAL_SCORE = 44
SHORT_STRONG_OPENING_SCORE = 62
SHORT_STRONG_VISUAL_SCORE = 54
YOUTUBE_CUTS_RETENTION = timedelta(hours=12)


def extract_youtube_video_id(raw_url: str) -> str:
    url = (raw_url or "").strip()
    if not url:
        raise ValueError("Cole um link do YouTube para analisar.")

    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()

    if host in {"youtu.be", "www.youtu.be"}:
        video_id = parsed.path.strip("/").split("/")[0]
        if video_id:
            return video_id

    if "youtube.com" in host:
        if parsed.path == "/watch":
            video_id = (parse_qs(parsed.query).get("v") or [""])[0].strip()
            if video_id:
                return video_id
        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) >= 2 and path_parts[0] in {"shorts", "embed", "live"}:
            return path_parts[1]

    raise ValueError("Nao consegui identificar o video nesse link do YouTube.")


def youtube_cuts_runtime_dir() -> Path:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    cleanup_expired_youtube_cuts()
    return RUNTIME_ROOT


def youtube_cuts_job_dir(job_id: str) -> Path:
    job_dir = youtube_cuts_runtime_dir() / job_id
    if not job_dir.exists():
        raise FileNotFoundError("Job de cortes nao encontrado.")
    return job_dir


def youtube_cuts_asset_path(job_id: str, filename: str) -> Path:
    safe_name = Path(filename).name
    asset_path = youtube_cuts_job_dir(job_id) / safe_name
    if not asset_path.is_file():
        raise FileNotFoundError("Arquivo do corte nao encontrado.")
    return asset_path


def youtube_cuts_manifest_path(job_id: str) -> Path:
    return youtube_cuts_job_dir(job_id) / "manifest.json"


def youtube_cut_video_path(job_id: str, cut_id: int) -> Path:
    return youtube_cuts_asset_path(job_id, f"cut-{int(cut_id):02d}.mp4")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _job_timestamp_from_name(job_name: str) -> datetime | None:
    match = re.search(r"-(\d{14})$", str(job_name or ""))
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _job_reference_time(job_dir: Path) -> datetime:
    manifest_path = job_dir / "manifest.json"
    try:
        if manifest_path.is_file():
            return datetime.fromtimestamp(manifest_path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        pass
    timestamp = _job_timestamp_from_name(job_dir.name)
    if timestamp is not None:
        return timestamp
    return datetime.fromtimestamp(job_dir.stat().st_mtime, tz=timezone.utc)


def cleanup_expired_youtube_cuts() -> list[str]:
    if not RUNTIME_ROOT.exists():
        return []
    cutoff = _utc_now() - YOUTUBE_CUTS_RETENTION
    removed: list[str] = []
    for child in RUNTIME_ROOT.iterdir():
        if not child.is_dir():
            continue
        try:
            if _job_reference_time(child) > cutoff:
                continue
            shutil.rmtree(child, ignore_errors=True)
            removed.append(child.name)
        except Exception:
            continue
    return removed


def _youtube_watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _youtube_embed_url(video_id: str) -> str:
    return f"https://www.youtube.com/embed/{video_id}"


def _youtube_thumbnail_url(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def _site_base_url() -> str:
    return (os.getenv("SITE_BASE_URL") or "https://zeropreco.com.br").rstrip("/")


def _openai_api_key() -> str:
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY nao configurada. Sem legenda do YouTube, o fallback de transcricao por audio precisa dessa chave."
        )
    return api_key


def _openai_shorts_rerank_model() -> str:
    return (os.getenv("OPENAI_SHORTS_RERANK_MODEL") or "gpt-4.1-mini").strip()


def _fetch_youtube_oembed(video_url: str) -> dict[str, Any]:
    endpoint = "https://www.youtube.com/oembed"
    params = {"url": video_url, "format": "json"}
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        response = client.get(endpoint, params=params)
        response.raise_for_status()
        return response.json()


def _ytdlp_command() -> list[str]:
    binary = shutil.which("yt-dlp")
    if binary:
        return [binary]
    venv_binary_name = "yt-dlp.exe" if os.name == "nt" else "yt-dlp"
    venv_binary = Path(sys.executable).with_name(venv_binary_name)
    if venv_binary.is_file():
        return [str(venv_binary)]
    try:
        import yt_dlp  # type: ignore  # noqa: F401

        return [sys.executable, "-m", "yt_dlp"]
    except Exception as exc:  # noqa: BLE001
        raise ValueError(
            "yt-dlp nao esta disponivel. Instale yt-dlp no ambiente do dashboard para baixar video e legendas do YouTube."
        ) from exc


def _ffmpeg_command() -> list[str]:
    try:
        return [imageio_ffmpeg.get_ffmpeg_exe()]
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Nao consegui localizar o ffmpeg para gerar os cortes.") from exc


def _ffprobe_command() -> list[str] | None:
    binary = shutil.which("ffprobe")
    if binary:
        return [binary]
    try:
        ffmpeg_binary = Path(_ffmpeg_command()[0])
    except Exception:  # noqa: BLE001
        return None
    probe_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    probe_binary = ffmpeg_binary.with_name(probe_name)
    return [str(probe_binary)] if probe_binary.is_file() else None


def _system_ffmpeg_command() -> list[str] | None:
    binary = shutil.which("ffmpeg")
    return [binary] if binary else None


def _probe_media_streams(media_path: Path) -> list[dict[str, Any]]:
    command = _ffprobe_command()
    if not command:
        return []
    try:
        payload = _run_command(
            command
            + [
                "-v",
                "error",
                "-show_streams",
                "-of",
                "json",
                str(media_path),
            ]
        )
        parsed = json.loads(payload or "{}")
    except Exception:  # noqa: BLE001
        return []
    streams = parsed.get("streams") or []
    return [item for item in streams if isinstance(item, dict)]


def _media_duration_seconds(media_path: Path) -> float:
    command = _ffprobe_command()
    if not command:
        return 0.0
    try:
        payload = _run_command(
            command
            + [
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(media_path),
            ]
        )
        parsed = json.loads(payload or "{}")
        duration = float((((parsed.get("format") or {}).get("duration")) or 0) or 0)
        return max(0.0, duration)
    except Exception:  # noqa: BLE001
        return 0.0


def _video_has_embedded_subtitle_stream(media_path: Path) -> bool:
    for stream in _probe_media_streams(media_path):
        if str(stream.get("codec_type") or "").strip().lower() == "subtitle":
            return True
    return False


def _video_dimensions(media_path: Path) -> tuple[int, int] | None:
    for stream in _probe_media_streams(media_path):
        if str(stream.get("codec_type") or "").strip().lower() != "video":
            continue
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
        if width > 0 and height > 0:
            return width, height
    return None


def _even_int(value: float) -> int:
    number = max(2, int(round(value)))
    return number if number % 2 == 0 else number - 1


def _scaled_width_for_height(width: int, height: int, target_height: int) -> int:
    if width <= 0 or height <= 0 or target_height <= 0:
        return 0
    return _even_int((width * target_height) / height)


def _resolve_burn_subtitles(
    *,
    mode: str,
    requested: bool,
    source_duration_seconds: float,
    youtube_subtitle_file: Path | None,
    source_video: Path,
) -> tuple[bool, dict[str, Any]]:
    if _normalize_cut_mode(mode) != "short" or not requested:
        return False, {
            "requested": bool(requested),
            "source_duration_seconds": round(float(source_duration_seconds or 0), 2),
            "has_downloaded_subtitles": bool(youtube_subtitle_file),
            "has_embedded_subtitles": False,
            "reason": "legenda desativada manualmente ou modo nao e short",
        }

    has_downloaded_subtitles = bool(youtube_subtitle_file)
    has_embedded_subtitles = _video_has_embedded_subtitle_stream(source_video)
    has_source_subtitles = has_downloaded_subtitles or has_embedded_subtitles
    is_short_source = float(source_duration_seconds or 0) < 600
    should_burn = not (is_short_source and has_source_subtitles)
    if is_short_source and has_source_subtitles:
        reason = "video curto ja tem legenda no arquivo ou no YouTube"
    elif is_short_source:
        reason = "video curto sem legenda detectada, adicionar legenda"
    else:
        reason = "video de 10 minutos ou mais segue com legenda no short"
    return should_burn, {
        "requested": True,
        "source_duration_seconds": round(float(source_duration_seconds or 0), 2),
        "has_downloaded_subtitles": has_downloaded_subtitles,
        "has_embedded_subtitles": has_embedded_subtitles,
        "reason": reason,
    }


def _load_font(size: int, bold: bool = False):
    candidates = []
    if bold:
        candidates.extend(
            [
                r"C:\Windows\Fonts\arialbd.ttf",
                r"C:\Windows\Fonts\segoeuib.ttf",
                r"C:\Windows\Fonts\calibrib.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            ]
        )
    candidates.extend(
        [
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\segoeui.ttf",
            r"C:\Windows\Fonts\calibri.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    )
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _run_command(command: list[str], *, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "sem detalhes").strip()
        raise ValueError(detail)
    return completed.stdout.strip()


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", (value or "").strip()).strip("-").lower()
    return cleaned[:80].rstrip("-") or "video"


def _normalize_cut_mode(mode: str | None) -> str:
    normalized = (mode or "short").strip().lower()
    return normalized if normalized in {"short", "long"} else "short"


def _normalize_short_selection_strategy(value: str | None) -> str:
    normalized = (value or "openai_heuristica").strip().lower()
    return normalized if normalized in {"openai", "heuristica", "openai_heuristica"} else "openai_heuristica"


def _format_duration_label(seconds: float) -> str:
    total_seconds = max(0, int(round(seconds)))
    minutes, remaining_seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes:02d}min"
    if minutes:
        return f"{minutes}min {remaining_seconds:02d}s"
    return f"{remaining_seconds}s"


def _dedupe_preserve_order(values: list[str], *, limit: int | None = None) -> list[str]:
    result: list[str] = []
    for item in values:
        normalized = re.sub(r"\s+", " ", str(item or "").strip())
        if normalized and normalized not in result:
            result.append(normalized)
        if limit and len(result) >= limit:
            break
    return result


def _clean_editorial_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _topic_hits(text: str) -> dict[str, int]:
    lowered = (text or "").lower()
    hits: dict[str, int] = {}
    for label, keywords in EDITORIAL_TOPIC_KEYWORDS.items():
        hits[label] = sum(1 for keyword in keywords if keyword in lowered)
    return hits


def _primary_topic_label(text: str) -> str:
    hits = _topic_hits(text)
    ordered = sorted(hits.items(), key=lambda item: item[1], reverse=True)
    if ordered and ordered[0][1] > 0:
        return ordered[0][0]
    return "mercado"


def _topic_tags_from_text(text: str) -> list[str]:
    hits = _topic_hits(text)
    ordered = [label for label, score in sorted(hits.items(), key=lambda item: item[1], reverse=True) if score > 0]
    if not ordered:
        ordered = ["mercado", "brasil"]
    return ordered[:3]


def _impact_frame_text(text: str, *, mode: str = "short") -> str:
    lowered = (text or "").lower()
    options: list[str] = []
    if "dolar" in lowered:
        options.extend(["O dolar pode disparar?", "Isso mexe no cambio"])
    if "inflacao" in lowered:
        options.extend(["A inflacao pode voltar?", "Isso pressiona os precos"])
    if any(word in lowered for word in ["petroleo", "gasolina", "diesel", "combustivel", "gas"]):
        options.extend(["Combustivel pode disparar?", "Isso pesa no bolso"])
    if any(word in lowered for word in ["china", "taiwan"]):
        options.extend(["China pode mudar tudo", "Vai sobrar para o Brasil?"])
    if any(word in lowered for word in ["iran", "israel", "russia", "ucrania", "guerra", "conflito", "nuclear"]):
        options.extend(["Crise global a caminho?", "O Brasil sentiria isso?"])
    if "brasil" in lowered or any(word in lowered for word in ["mercado", "juros", "tarifa", "governo"]):
        options.extend(["Qual o impacto no Brasil?", "Isso afeta o seu bolso"])
    if not options:
        options.extend(["Entenda o impacto real", "Isso pode escalar rapido"])
    chosen = options[0]
    return chosen[:40] if mode == "short" else chosen[:52]


def _looks_like_weak_opener(text: str) -> bool:
    sentence = _clean_editorial_text(_hook_from_text(text)).lower().strip(" -:;,.!?")
    return any(sentence.startswith(item) for item in WEAK_OPENERS)


def _opening_sentence_score(text: str) -> int:
    sentence = _clean_editorial_text(_hook_from_text(text))
    lowered = sentence.lower()
    score = 40
    if not sentence:
        return 0
    if _looks_like_weak_opener(sentence):
        score -= 24
    if "?" in sentence:
        score += 10
    if any(word in lowered for word in ["dolar", "inflacao", "brasil", "mercado", "guerra", "crise", "china", "combustivel"]):
        score += 14
    if any(word in lowered for word in ["impacto", "efeito", "risco", "alerta", "explica", "pode", "vai", "entenda"]):
        score += 10
    score += min(len(sentence) // 12, 8)
    return max(1, min(score, 99))


def _find_better_short_open(segments: list[dict[str, Any]], start_index: int, total_duration: float) -> int:
    best_index = start_index
    best_score = -1
    base_start = float(segments[start_index]["start"] or 0)
    for index in range(start_index, min(len(segments), start_index + 4)):
        segment = segments[index]
        start = float(segment["start"] or 0)
        if start - base_start > 7.5:
            break
        text = str(segment.get("text") or "")
        score = _opening_sentence_score(text)
        if (start / total_duration) < 0.02 if total_duration > 0 else False:
            score -= 4
        if score > best_score:
            best_score = score
            best_index = index
    return best_index


def _capitalize_headline(text: str) -> str:
    cleaned = _clean_editorial_text(text).strip(" -:;,.!?")
    if not cleaned:
        return ""
    return cleaned[0].upper() + cleaned[1:]


def _short_title_variants(text: str, chosen_title: str = "") -> list[str]:
    lowered = (text or "").lower()
    fallback = _clean_sentence_for_title(_hook_from_text(text))[:92] or "Corte de podcast"
    base = _capitalize_headline(chosen_title or fallback)[:92]
    hook = _clean_sentence_for_title(_hook_from_text(text))[:72]
    frame = _clean_sentence_for_title(_impact_frame_text(text, mode="short")).strip(" -:;,.!?")
    variants = [base]
    if hook:
        variants.append(f"{hook} | Entenda o impacto".strip()[:100])
    if frame:
        variants.append(f"{frame}: entenda o efeito".strip()[:100])
    if "dolar" in lowered:
        variants.extend(
            [
                "Dolar pode disparar com nova crise",
                "O que pode levar o dolar para cima",
            ]
        )
    if "inflacao" in lowered:
        variants.extend(
            [
                "Inflacao pode subir de novo?",
                "O sinal de que os precos podem voltar a subir",
            ]
        )
    if any(word in lowered for word in ["petroleo", "gasolina", "diesel", "combustivel", "gas"]):
        variants.extend(
            [
                "Petroleo em alta: o efeito no combustivel",
                "Gasolina pode subir com essa crise?",
            ]
        )
    if any(word in lowered for word in ["china", "taiwan"]):
        variants.extend(
            [
                "China x Taiwan: por que o mercado se preocupa",
                "O conflito entre China e Taiwan explicado rapido",
            ]
        )
    if any(word in lowered for word in ["iran", "israel", "russia", "ucrania", "guerra", "conflito", "nuclear"]):
        variants.extend(
            [
                "O risco de guerra e o efeito no Brasil",
                "Por que essa escalada preocupa o mercado",
            ]
        )
    if "brasil" in lowered:
        variants.extend(
            [
                "Como isso pode atingir o Brasil",
                "O que muda para o Brasil agora",
            ]
        )
    if "brasil" not in lowered and any(word in lowered for word in ["dolar", "inflacao", "gasolina", "diesel", "combustivel", "guerra", "mercado", "tarifa", "china"]):
        variants.append("O impacto disso no Brasil")
    return _dedupe_preserve_order(variants, limit=5)


def _hashtags_for_cut(topic_tags: list[str], *, mode: str) -> list[str]:
    normalized = [tag.lower() for tag in topic_tags if tag]
    hashtags = ["#economia", "#geopolitica", "#mercado", "#brasil", "#noticias", "#podcast", "#cortes"]
    if "dolar" in normalized:
        hashtags.append("#dolar")
    if "inflacao" in normalized:
        hashtags.append("#inflacao")
    if "combustivel" in normalized:
        hashtags.append("#combustivel")
    if "geopolitica" in normalized:
        hashtags.append("#guerra")
    if "brasil" in normalized:
        hashtags.append("#politica")
    if mode == "short":
        hashtags = ["#shorts", "#shortsyoutube"] + hashtags
    else:
        hashtags.extend(["#analise", "#youtubebrasil"])
    return _dedupe_preserve_order(hashtags, limit=10)


def _series_title_variants(base_title: str, *, part: int, total: int) -> list[str]:
    clean_title = _capitalize_headline(base_title)[:92] or "Corte de podcast"
    variants = [
        clean_title,
        f"Parte {part}: {clean_title}"[:100],
        f"{clean_title} | Parte {part}/{total}"[:100],
    ]
    return _dedupe_preserve_order(variants, limit=3)


def _short_series_notes(*, part: int, total: int) -> list[str]:
    if total <= 1:
        return []
    notes = [
        f"Serie curta detectada: parte {part} de {total}.",
        "Terminar o video com gancho para o proximo corte da serie.",
    ]
    if part < total:
        notes.append(f"No final, puxar para a parte {part + 1}.")
    else:
        notes.append("No final, puxar para o video completo ou para a primeira parte.")
    return notes


def _short_series_description(
    item: dict[str, Any],
    video: dict[str, Any],
    hashtags: list[str],
    *,
    editorial_profile: dict[str, Any] | None = None,
) -> str:
    profile = editorial_profile or EDITORIAL_PROFILE
    part = int(item.get("series_part") or 0)
    total = int(item.get("series_total") or 0)
    title_or_hook = str(item.get("hook") or item.get("title") or "").strip()
    lines = [title_or_hook, ""]
    if total > 1 and part > 0:
        lines.append(f"Parte {part} de {total} desta serie de cortes.")
        if part < total:
            lines.append(f"Veja tambem a parte {part + 1}.")
        else:
            lines.append("Veja as partes anteriores e o video completo.")
        lines.append("")
    lines.extend(
        [
            str(profile["short_series_summary"]),
            f"Video base: {video.get('title') or ''}".strip(),
            " ".join(hashtags),
        ]
    )
    return "\n".join(line for line in lines if line is not None).strip()


def _text_keywords_for_similarity(text: str) -> set[str]:
    stopwords = {
        "isso", "essa", "esse", "para", "porque", "sobre", "muito", "mais", "como", "quando", "onde",
        "tambem", "depois", "antes", "agora", "entao", "ainda", "pela", "pelos", "pelas", "entre",
        "com", "sem", "por", "uma", "uns", "umas", "que", "quem", "qual", "quais", "dos", "das",
        "nos", "nas", "ele", "ela", "eles", "elas", "isso", "isto", "aqui", "ali", "ser", "foi",
    }
    words = set()
    for raw in re.findall(r"[a-zA-ZÀ-ÿ0-9]+", (text or "").lower()):
        if len(raw) < 5 or raw in stopwords:
            continue
        words.add(raw)
    return words


def _short_items_should_chain(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_end = float(left.get("end") or 0)
    right_start = float(right.get("start") or 0)
    gap_seconds = max(0.0, right_start - left_end)
    left_tags = set(str(tag) for tag in (left.get("topic_tags") or []))
    right_tags = set(str(tag) for tag in (right.get("topic_tags") or []))
    topic_overlap = len(left_tags & right_tags)
    left_keywords = _text_keywords_for_similarity(str(left.get("transcript_excerpt") or ""))
    right_keywords = _text_keywords_for_similarity(str(right.get("transcript_excerpt") or ""))
    keyword_overlap = len(left_keywords & right_keywords)
    left_opening = int(left.get("opening_score") or 0)
    right_opening = int(right.get("opening_score") or 0)

    if gap_seconds <= 35 and topic_overlap >= 1:
        return True
    if gap_seconds <= 75 and topic_overlap >= 1 and keyword_overlap >= 2:
        return True
    if gap_seconds <= 120 and topic_overlap >= 2 and keyword_overlap >= 3 and min(left_opening, right_opening) >= 58:
        return True
    return False


def _apply_short_series_strategy(selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not selected:
        return []

    working = [dict(item) for item in selected]
    ordered_by_time = sorted(working, key=lambda item: (float(item.get("start") or 0), float(item.get("end") or 0)))
    groups: list[list[dict[str, Any]]] = []
    current_group: list[dict[str, Any]] = []

    for item in ordered_by_time:
        if not current_group:
            current_group = [item]
            continue
        if _short_items_should_chain(current_group[-1], item):
            current_group.append(item)
            continue
        groups.append(current_group)
        current_group = [item]
    if current_group:
        groups.append(current_group)

    indexed: dict[tuple[float, float], dict[str, Any]] = {}
    for group in groups:
        if len(group) <= 1:
            item = group[0]
            indexed[(float(item.get("start") or 0), float(item.get("end") or 0))] = (
                item
                | {
                    "copy_title": str(item.get("title") or ""),
                    "series_part": 0,
                    "series_total": 0,
                    "series_label": "",
                    "series_mode": "single",
                    "packaging_notes": list(item.get("packaging_notes") or []) + ["Short unico: entregar contexto completo sem depender de outra parte."],
                }
            )
            continue

        total = len(group)
        for part, item in enumerate(group, start=1):
            series_title_variants = _series_title_variants(str(item.get("title") or ""), part=part, total=total)
            indexed[(float(item.get("start") or 0), float(item.get("end") or 0))] = (
                item
                | {
                    "copy_title": series_title_variants[0],
                    "title": series_title_variants[0],
                    "title_variants": _dedupe_preserve_order(series_title_variants + list(item.get("title_variants") or []), limit=5),
                    "series_part": part,
                    "series_total": total,
                    "series_label": f"Parte {part}/{total}",
                    "series_mode": "series",
                    "packaging_notes": list(item.get("packaging_notes") or []) + _short_series_notes(part=part, total=total),
                }
            )

    ranked: list[dict[str, Any]] = []
    for index, item in enumerate(working):
        key = (float(item.get("start") or 0), float(item.get("end") or 0))
        enriched = indexed.get(key, item)
        ranked.append(
            enriched
            | {
                "editorial_role": "principal" if index == 0 else f"secundario_{index}",
            }
        )
    return ranked


def _build_suggestion(title: str, author_name: str, video_url: str, angle: str, hook: str, duration_seconds: int, score: int) -> dict[str, Any]:
    safe_title = (title or "Podcast").strip()
    safe_author = (author_name or "canal").strip()
    first_frame_text = _impact_frame_text(f"{safe_title} {hook}")
    topic_tags = _topic_tags_from_text(f"{safe_title} {hook}")
    caption_lines = [
        hook,
        safe_title,
        "",
        f"Corte sugerido do canal {safe_author}.",
        f"Video base: {video_url}",
    ]
    return {
        "angle": angle,
        "hook": hook,
        "duration_seconds": duration_seconds,
        "duration_label": _format_duration_label(duration_seconds),
        "score": score,
        "title": f"{angle}: {safe_title}",
        "title_variants": _short_title_variants(f"{hook} {safe_title}", f"{angle}: {safe_title}"),
        "first_frame_text": first_frame_text,
        "topic_tags": topic_tags,
        "caption_draft": "\n".join(caption_lines).strip(),
        "reason": (
            f"Formato pensado para {angle.lower()}, com gancho curto e facil de adaptar "
            "para Shorts, Reels e cortes de podcast."
        ),
        "packaging_notes": [
            f"Abertura sugerida: {first_frame_text}",
            "Legenda branca com borda preta e palavra ativa em azul.",
            "Titulo deve mostrar assunto e consequencia sem termos genericos.",
        ],
        "status": "editorial_brief",
    }


def _build_initial_cut_suggestions(title: str, author_name: str, video_url: str) -> list[dict[str, Any]]:
    templates = [
        ("Alerta de mercado", "Trecho com risco claro e efeito no bolso ou no mercado", 34, 94),
        ("Impacto no Brasil", "Trecho que conecta crise global com consequencia direta no Brasil", 38, 92),
        ("Explicacao rapida", "Trecho que explica um tema quente sem enrolacao", 42, 88),
        ("Opiniao forte", "Trecho com discordancia, previsao ou tese forte", 35, 86),
        ("Dado que assusta", "Trecho com numero, comparacao ou revelacao forte", 31, 84),
        ("Fechamento de impacto", "Trecho que termina com conclusao memoravel", 28, 80),
    ]
    return [
        _build_suggestion(title, author_name, video_url, angle, hook, duration_seconds, score)
        for angle, hook, duration_seconds, score in templates
    ]


def _build_initial_long_cut_suggestions(title: str, author_name: str, video_url: str) -> list[dict[str, Any]]:
    templates = [
        ("Corte longo principal", "Bloco com tese forte, contexto e fechamento claro para vídeo normal", 720, 95),
        ("Tema quente explicado", "Bloco longo com assunto atual, impacto no Brasil e boa retenção", 780, 92),
        ("Crise e consequências", "Trecho longo com risco, explicação e desdobramento econômico", 660, 89),
    ]
    return [
        _build_suggestion(title, author_name, video_url, angle, hook, duration_seconds, score)
        for angle, hook, duration_seconds, score in templates
    ]


def analyze_youtube_video_for_cuts(raw_url: str) -> dict[str, Any]:
    video_id = extract_youtube_video_id(raw_url)
    video_url = _youtube_watch_url(video_id)

    oembed_error = ""
    title = ""
    author_name = ""
    thumbnail_url = _youtube_thumbnail_url(video_id)

    try:
        oembed = _fetch_youtube_oembed(video_url)
        title = str(oembed.get("title") or "").strip()
        author_name = str(oembed.get("author_name") or "").strip()
        thumbnail_url = str(oembed.get("thumbnail_url") or thumbnail_url).strip() or thumbnail_url
    except Exception as exc:  # noqa: BLE001
        oembed_error = str(exc)

    if not title:
        title = f"Video YouTube {video_id}"

    suggestions = _build_initial_cut_suggestions(title, author_name, video_url)

    return {
        "ok": True,
        "phase": 1,
        "video": {
            "video_id": video_id,
            "url": video_url,
            "embed_url": _youtube_embed_url(video_id),
            "thumbnail_url": thumbnail_url,
            "title": title,
            "author_name": author_name,
        },
        "suggestions": suggestions,
        "long_suggestions": _build_initial_long_cut_suggestions(title, author_name, video_url),
        "strategy": {
            "profile": EDITORIAL_PROFILE["name"],
            "positioning": EDITORIAL_PROFILE["positioning"],
            "title_formula": EDITORIAL_PROFILE["title_formula"],
            "short_opening_checklist": EDITORIAL_PROFILE["short_opening_checklist"],
            "long_opening_checklist": EDITORIAL_PROFILE["long_opening_checklist"],
            "subtitle_style": EDITORIAL_PROFILE["subtitle_style"],
        },
        "notes": [
            "Fase 1: intake e briefing editorial.",
            "Perfil editorial aplicado: economia, geopolitica e impacto direto no Brasil.",
            "A transcricao com IA e os cortes reais entram na proxima fase.",
            "As sugestoes abaixo ja saem com foco em gancho, primeiro frame e titulo menos generico.",
        ],
        "roadmap_path": "docs/youtube-cuts-roadmap.md",
        "oembed_error": oembed_error,
    }


def _find_downloaded_video(job_dir: Path) -> Path:
    candidates = sorted(job_dir.glob("source.*"))
    for item in candidates:
        if item.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}:
            return item
    raise ValueError("Nao encontrei o video baixado para gerar os cortes.")


def _find_downloaded_vtt(job_dir: Path) -> Path:
    preferred = []
    preferred.extend(sorted(job_dir.glob("source*.pt-BR.vtt")))
    preferred.extend(sorted(job_dir.glob("source*.pt.vtt")))
    preferred.extend(sorted(job_dir.glob("source*.en.vtt")))
    preferred.extend(sorted(job_dir.glob("source*.vtt")))
    for item in preferred:
        if item.is_file():
            return item
    raise ValueError(
        "Nao encontrei legenda automatica do YouTube para esse video. "
        "Sem legenda disponivel nao consigo montar os cortes reais nesta fase."
    )


def _parse_csv_env(name: str) -> list[str]:
    raw_value = (os.getenv(name) or "").strip()
    if not raw_value:
        return []
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def _read_browser_last_profile(local_state_path: Path) -> str:
    try:
        payload = json.loads(local_state_path.read_text(encoding="utf-8"))
    except Exception:
        return ""

    profile = str(((payload.get("profile") or {}).get("last_used")) or "").strip()
    return profile


def _firefox_cookie_specs(appdata: Path, local_appdata: Path) -> list[str]:
    profiles_ini = appdata / "Mozilla" / "Firefox" / "profiles.ini"
    if not profiles_ini.exists():
        return []

    parser = configparser.ConfigParser()
    try:
        parser.read(profiles_ini, encoding="utf-8")
    except Exception:
        return []

    specs: list[str] = []
    base_profile_dir = appdata / "Mozilla" / "Firefox"
    sandbox_base_dir = local_appdata / "Packages" / "Mozilla.Firefox_n80bbvh6b1yt2" / "LocalCache" / "Roaming" / "Mozilla" / "Firefox"
    for section in parser.sections():
        if not section.lower().startswith("profile"):
            continue
        raw_path = str(parser.get(section, "Path", fallback="")).strip()
        if not raw_path:
            continue
        is_relative = parser.get(section, "IsRelative", fallback="1").strip() == "1"
        candidate_dirs: list[Path] = []
        if is_relative:
            candidate_dirs.append(base_profile_dir / raw_path)
            candidate_dirs.append(sandbox_base_dir / raw_path)
        else:
            candidate_dirs.append(Path(raw_path))
        if not any(path.exists() for path in candidate_dirs):
            continue
        profile_name = str(parser.get(section, "Name", fallback="")).strip()
        for option in [profile_name, Path(raw_path).name]:
            normalized = option.strip()
            if normalized:
                specs.append(f"firefox:{normalized}")
    return _dedupe_preserve_order(specs, limit=6)


def _linux_browser_cookie_roots(browser: str) -> list[Path]:
    home = Path.home()
    roots: dict[str, list[Path]] = {
        "chrome": [
            home / ".config" / "google-chrome",
            home / ".var" / "app" / "com.google.Chrome" / "config" / "google-chrome",
        ],
        "edge": [
            home / ".config" / "microsoft-edge",
            home / ".var" / "app" / "com.microsoft.Edge" / "config" / "microsoft-edge",
        ],
        "brave": [
            home / ".config" / "BraveSoftware" / "Brave-Browser",
            home / ".var" / "app" / "com.brave.Browser" / "config" / "BraveSoftware" / "Brave-Browser",
        ],
        "chromium": [
            home / ".config" / "chromium",
            home / "snap" / "chromium" / "current" / "chromium",
        ],
        "firefox": [
            home / ".config" / "mozilla" / "firefox",
            home / ".mozilla" / "firefox",
            home / ".var" / "app" / "org.mozilla.firefox" / "config" / "mozilla" / "firefox",
            home / ".var" / "app" / "org.mozilla.firefox" / ".mozilla" / "firefox",
            home / "snap" / "firefox" / "common" / ".mozilla" / "firefox",
        ],
    }
    return roots.get(browser, [])


def _linux_browser_cookie_spec_available(browser: str, profile: str) -> bool:
    roots = _linux_browser_cookie_roots(browser)
    if not roots:
        return False

    normalized_profile = profile.strip().strip("\"'") if profile else ""
    for root in roots:
        if not root.exists():
            continue
        if not normalized_profile:
            return True
        if browser == "firefox":
            for candidate in root.iterdir():
                if not candidate.is_dir():
                    continue
                name = candidate.name.strip()
                if name == normalized_profile or name.endswith(f".{normalized_profile}"):
                    return True
            continue
        candidate_paths = [
            root / normalized_profile,
            root / "User Data" / normalized_profile,
        ]
        if any(path.exists() for path in candidate_paths):
            return True
    return False


def _browser_cookie_spec_available(spec: str) -> bool:
    normalized = spec.strip()
    if not normalized:
        return False
    browser, _, profile = normalized.partition(":")
    browser = browser.strip().lower()
    profile = profile.strip()
    if os.name == "nt":
        known_specs = {item.lower() for item in _auto_browser_cookie_specs()}
        return normalized.lower() in known_specs or browser in known_specs
    if os.name == "posix":
        return _linux_browser_cookie_spec_available(browser, profile)
    return True


def _auto_browser_cookie_specs() -> list[str]:
    specs: list[str] = []
    browser_profiles: dict[str, tuple[Path, list[str]]] = {}
    local_appdata = Path(os.getenv("LOCALAPPDATA") or "")
    appdata = Path(os.getenv("APPDATA") or "")
    if local_appdata:
        browser_profiles.update(
            {
                "chrome": (local_appdata / "Google" / "Chrome" / "User Data" / "Local State", ["Default", "Profile 1", "Profile 2", "Profile 3"]),
                "edge": (local_appdata / "Microsoft" / "Edge" / "User Data" / "Local State", ["Default", "Profile 1", "Profile 2"]),
                "brave": (local_appdata / "BraveSoftware" / "Brave-Browser" / "User Data" / "Local State", ["Default", "Profile 1"]),
                "chromium": (local_appdata / "Chromium" / "User Data" / "Local State", ["Default"]),
            }
        )

    ordered_specs: list[str] = []
    for browser, (state_path, fallback_profiles) in browser_profiles.items():
        if not state_path.exists():
            continue
        ordered_specs.append(browser)
        last_profile = _read_browser_last_profile(state_path) if state_path.name.lower() == "local state" else ""
        if last_profile:
            ordered_specs.append(f"{browser}:{last_profile}")
        for profile in fallback_profiles:
            ordered_specs.append(f"{browser}:{profile}")
    if appdata and local_appdata:
        ordered_specs.extend(_firefox_cookie_specs(appdata, local_appdata))

    seen: set[str] = set()
    for spec in ordered_specs:
        normalized = spec.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        specs.append(normalized)
    return specs


def _browser_cookie_specs() -> list[str]:
    explicit_specs = _parse_csv_env("YTDLP_COOKIES_FROM_BROWSER")
    if explicit_specs:
        return [spec for spec in explicit_specs if _browser_cookie_spec_available(spec)]

    explicit_cookie_file = (os.getenv("YTDLP_COOKIES_FILE") or "").strip()
    if explicit_cookie_file:
        return []

    return _auto_browser_cookie_specs()


def _ytdlp_geo_bypass_args() -> list[str]:
    country = (os.getenv("YTDLP_GEO_BYPASS_COUNTRY") or "").strip().upper()
    if not country:
        return []
    return ["--geo-bypass", "--geo-bypass-country", country]


def _youtube_download_variants(video_url: str, output_template: str, *, with_subtitles: bool) -> list[list[str]]:
    base_command = _ytdlp_command()
    shared = [
        "--no-warnings",
        "--format",
        "bestvideo*[height<=1080]+bestaudio/best[height<=1080][ext=mp4]/best[height<=1080]",
        "--extractor-args",
        "youtube:player_client=android,web,tv",
        "--extractor-retries",
        "3",
        "--sleep-requests",
        "2",
        "--retry-sleep",
        "2",
        "--output",
        output_template,
    ]
    shared = _ytdlp_geo_bypass_args() + shared
    if with_subtitles:
        shared = [
            "--write-auto-sub",
            "--write-sub",
            "--sub-langs",
            "pt-BR,pt,en",
            "--sub-format",
            "vtt",
        ] + shared

    variants = [base_command + shared + [video_url]]

    cookie_file = (os.getenv("YTDLP_COOKIES_FILE") or "").strip()
    if cookie_file:
        variants.append(base_command + ["--cookies", cookie_file] + shared + [video_url])

    for browser_spec in _browser_cookie_specs():
        variants.append(base_command + ["--cookies-from-browser", browser_spec] + shared + [video_url])
    return variants


def _ffmpeg_h264_video_args(*, mode: str) -> list[str]:
    return [
        "-r",
        "30",
        "-c:v",
        "libx264",
        # DreamHost's static ffmpeg/libx264 build becomes unstable with overlay + multithreaded x264.
        "-threads",
        "1",
        "-preset",
        "slow",
        "-pix_fmt",
        "yuv420p",
    ]


def _ffmpeg_aac_audio_args() -> list[str]:
    return [
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
    ]


def _ffmpeg_filter_thread_args() -> list[str]:
    return [
        "-filter_threads",
        "1",
        "-filter_complex_threads",
        "1",
    ]


def _run_youtube_download_with_fallback(video_url: str, output_template: str, *, with_subtitles: bool) -> str:
    errors: list[str] = []
    for command in _youtube_download_variants(video_url, output_template, with_subtitles=with_subtitles):
        try:
            return _run_command(command)
        except Exception as exc:  # noqa: BLE001
            command_label = " ".join(command[:4])
            errors.append(f"{command_label}: {str(exc)}")
            continue
    detail = errors[-1] if errors else "sem detalhes"
    lowered_detail = detail.lower()
    if "not made this video available in your country" in lowered_detail or "not available in your country" in lowered_detail:
        geo_country = (os.getenv("YTDLP_GEO_BYPASS_COUNTRY") or "").strip().upper() or "BR"
        raise ValueError(
            "Falha ao baixar do YouTube por bloqueio de pais no servidor. "
            f"Tente novamente com YTDLP_GEO_BYPASS_COUNTRY={geo_country}. "
            "Se ainda falhar, esse video vai precisar de proxy/VPN em regiao permitida. "
            f"Ultima tentativa: {detail}"
        )
    hint = (
        "Falha ao baixar do YouTube. Se o video pedir confirmacao anti-bot, configure "
        "YTDLP_COOKIES_FILE com um cookies.txt exportado do navegador ou "
        "YTDLP_COOKIES_FROM_BROWSER com algo como chrome:Default,chrome:'Profile 1',edge:Default."
    )
    raise ValueError(f"{hint} Ultima tentativa: {detail}")


def _download_video_only(video_url: str, job_dir: Path) -> Path:
    output_template = str(job_dir / "source.%(ext)s")
    _run_youtube_download_with_fallback(video_url, output_template, with_subtitles=False)
    return _find_downloaded_video(job_dir)


def _download_video_and_subtitles(video_url: str, job_dir: Path) -> tuple[Path, Path | None, str]:
    output_template = str(job_dir / "source.%(ext)s")
    subtitle_error = ""

    try:
        _run_youtube_download_with_fallback(video_url, output_template, with_subtitles=True)
    except Exception as exc:  # noqa: BLE001
        subtitle_error = str(exc)
        source_video = _download_video_only(video_url, job_dir)
        return source_video, None, subtitle_error

    source_video = _find_downloaded_video(job_dir)
    try:
        subtitle_file = _find_downloaded_vtt(job_dir)
    except Exception as exc:  # noqa: BLE001
        subtitle_error = str(exc)
        subtitle_file = None

    return source_video, subtitle_file, subtitle_error


def _parse_vtt_timestamp(value: str) -> float:
    raw = value.strip().replace(",", ".")
    parts = raw.split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours = "0"
        minutes, seconds = parts
    else:
        raise ValueError("Timestamp VTT invalido.")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _clean_vtt_text(value: str) -> str:
    cleaned = html.unescape(re.sub(r"<[^>]+>", "", value or ""))
    cleaned = re.sub(r"&nbsp;", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _timed_word_entries_from_text(text: str, start: float, end: float) -> list[dict[str, Any]]:
    cleaned = _clean_vtt_text(text)
    words = [word for word in cleaned.split() if word.strip()]
    if not words or end <= start:
        return []
    weights = [max(1, len(re.sub(r"[^\w]", "", word)) or 1) for word in words]
    total_weight = sum(weights) or len(words)
    cursor = start
    entries: list[dict[str, Any]] = []
    for index, word in enumerate(words):
        word_duration = (end - start) * (weights[index] / total_weight)
        word_end = end if index == len(words) - 1 else min(end, cursor + word_duration)
        if word_end - cursor > 0:
            entries.append({"start": cursor, "end": word_end, "text": word})
        cursor = word_end
    return entries


def _parse_vtt_timed_words(raw_text: str, cue_start: float, cue_end: float) -> list[dict[str, Any]]:
    content = html.unescape((raw_text or "").replace("&nbsp;", " "))
    matches = list(re.finditer(r"<(\d{2}:\d{2}:\d{2}\.\d{3})>", content))
    if not matches:
        return []

    words: list[dict[str, Any]] = []
    lead_text = _clean_vtt_text(content[: matches[0].start()])
    first_timestamp = _parse_vtt_timestamp(matches[0].group(1))
    if lead_text and first_timestamp > cue_start:
        words.extend(_timed_word_entries_from_text(lead_text, cue_start, first_timestamp))

    for index, match in enumerate(matches):
        word_start = _parse_vtt_timestamp(match.group(1))
        next_match = matches[index + 1] if index + 1 < len(matches) else None
        word_end = _parse_vtt_timestamp(next_match.group(1)) if next_match else cue_end
        snippet_end = next_match.start() if next_match else len(content)
        snippet = _clean_vtt_text(content[match.end() : snippet_end])
        if not snippet or word_end <= word_start:
            continue
        words.extend(_timed_word_entries_from_text(snippet, word_start, word_end))
    return words


def _normalize_timed_words(raw_words: Any, *, offset: float = 0.0) -> list[dict[str, Any]]:
    if not isinstance(raw_words, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in raw_words:
        if not isinstance(item, dict):
            continue
        text = str(item.get("word") or item.get("text") or "").strip()
        try:
            start = float(item.get("start")) + offset
            end = float(item.get("end")) + offset
        except (TypeError, ValueError):
            continue
        normalized.extend(_timed_word_entries_from_text(text, start, end))
    return normalized


def _parse_vtt_segments(vtt_path: Path) -> list[dict[str, Any]]:
    lines = vtt_path.read_text(encoding="utf-8", errors="replace").splitlines()
    segments: list[dict[str, Any]] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if "-->" not in line:
            index += 1
            continue

        start_raw, end_raw = [part.strip() for part in line.split("-->", 1)]
        index += 1
        text_lines = []
        while index < len(lines) and lines[index].strip():
            text_lines.append(lines[index].rstrip())
            index += 1
        raw_text = " ".join(text_lines)
        text = _clean_vtt_text(raw_text)
        if text:
            start = _parse_vtt_timestamp(start_raw.split(" ")[0])
            end = _parse_vtt_timestamp(end_raw.split(" ")[0])
            segment = {"start": start, "end": end, "text": text}
            timed_words = _parse_vtt_timed_words(raw_text, start, end)
            if timed_words:
                segment["words"] = timed_words
            segments.append(segment)
        index += 1

    deduped: list[dict[str, Any]] = []
    last_text = ""
    for item in segments:
        if item["text"] == last_text:
            continue
        deduped.append(item)
        last_text = item["text"]
    return deduped


def _transcript_text(segments: list[dict[str, Any]]) -> str:
    return "\n".join(item["text"] for item in segments)


def _score_text(text: str) -> int:
    lowered = text.lower()
    score = 50
    for word in HIGH_IMPACT_WORDS:
        if word in lowered:
            score += 6
    if any(word in lowered for word in ["porque", "por que", "como", "impacto", "efeito", "risco", "alerta"]):
        score += 8
    if any(word in lowered for word in ["brasil", "bolso", "mercado", "dolar", "inflacao", "combustivel"]):
        score += 10
    if _looks_like_weak_opener(text):
        score -= 14
    if "?" in text:
        score += 4
    score += min(len(text) // 80, 10)
    return max(1, min(score, 99))


def _hook_from_text(text: str) -> str:
    sentence = re.split(r"(?<=[\.\!\?])\s+", text.strip())[0]
    cleaned = sentence[:140].strip() or text[:140].strip()
    return _clean_editorial_text(cleaned)


def _title_from_text(text: str) -> str:
    variants = _short_title_variants(text)
    return variants[0] if variants else "Corte de podcast"


def _long_title_from_text(text: str, *, primary: bool = False) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    lowered = cleaned.lower()
    base_variants = _short_title_variants(cleaned)
    base = base_variants[0] if base_variants else _hook_from_text(cleaned)
    if any(word in lowered for word in ["dolar", "inflacao", "mercado", "juros"]):
        prefix = "Entenda o impacto economico"
    elif any(word in lowered for word in ["china", "taiwan", "iran", "israel", "russia", "ucrania", "guerra", "conflito"]):
        prefix = "Entenda a crise e seus efeitos"
    else:
        prefix = "Analise completa"
    if primary:
        return f"{prefix}: {base}"[:100]
    return f"{base} | Explicacao completa"[:100]


def _long_candidate_editorial_score(text: str, start: float, duration: float, total_duration: float) -> int:
    lowered = text.lower()
    score = _score_text(text) + 12

    structure_markers = [
        "porque", "como", "entao", "mas", "so que", "ou seja", "na pratica",
        "por exemplo", "agora", "primeiro", "segundo", "terceiro", "no final",
    ]
    tension_markers = [
        "erro", "crise", "guerra", "problema", "segredo", "verdade", "risco",
        "perigo", "dinheiro", "mercado", "politica", "brasil", "china", "trump",
    ]
    retention_markers = ["?", "sabe", "olha", "veja", "repara", "presta atencao", "ninguem", "nunca", "sempre"]

    score += sum(4 for word in structure_markers if word in lowered)
    score += sum(5 for word in tension_markers if word in lowered)
    score += sum(2 for word in retention_markers if word in lowered)

    if 660 <= duration <= 840:
        score += 8
    elif 600 <= duration <= 900:
        score += 4

    start_ratio = (start / total_duration) if total_duration > 0 else 0
    if 0.08 <= start_ratio <= 0.72:
        score += 6
    elif start_ratio < 0.03:
        score -= 4

    paragraphs = max(1, len(re.split(r"[.!?]+", text)))
    score += min(paragraphs // 8, 8)
    return min(99, score)


def _long_cut_scorecard(text: str, start: float, duration: float, total_duration: float) -> dict[str, int]:
    lowered = text.lower()
    ctr = 48
    retention = 52
    topic = 44

    ctr_words = ["alerta", "risco", "crise", "guerra", "por que", "como", "impacto", "efeito", "mercado"]
    retention_words = ["porque", "entao", "agora", "ou seja", "por exemplo", "primeiro", "segundo", "na pratica"]
    topic_words = ["brasil", "china", "trump", "mercado", "dinheiro", "politica", "guerra", "crise", "dolar", "inflacao", "petroleo"]

    ctr += sum(6 for word in ctr_words if word in lowered)
    retention += sum(5 for word in retention_words if word in lowered)
    topic += sum(6 for word in topic_words if word in lowered)
    if _looks_like_weak_opener(text):
        ctr -= 14
        retention -= 8

    if 660 <= duration <= 840:
        retention += 8
    elif 600 <= duration <= 900:
        retention += 4

    start_ratio = (start / total_duration) if total_duration > 0 else 0
    if 0.08 <= start_ratio <= 0.72:
        topic += 8
        retention += 4

    ctr = min(99, ctr)
    retention = min(99, retention)
    topic = min(99, topic)
    overall = min(99, round((ctr * 0.38) + (retention * 0.42) + (topic * 0.20)))
    return {"ctr": ctr, "retention": retention, "topic": topic, "overall": overall}


def _title_variants_for_long_cut(text: str) -> list[str]:
    base = _long_title_from_text(text, primary=True)
    hook = _hook_from_text(text).strip(" -:;,.")
    short_hook = hook[:72].strip()
    variants = [
        base,
        f"{short_hook} | O ponto central".strip()[:100],
        f"Entenda o impacto real: {short_hook}".strip()[:100],
        f"{_impact_frame_text(text, mode='long')} | Analise".strip()[:100],
    ]
    deduped: list[str] = []
    for item in variants:
        normalized = item.strip()
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped[:3]


def _thumbnail_text_variants_for_long_cut(text: str) -> list[str]:
    lowered = (text or "").lower()
    variants = [_impact_frame_text(text, mode="long")]
    if "dolar" in lowered:
        variants.extend(["Dolar sob pressao", "Impacto no cambio"])
    if "inflacao" in lowered:
        variants.extend(["Inflacao em foco", "Preco pode subir"])
    if any(word in lowered for word in ["china", "taiwan", "iran", "israel", "russia", "ucrania", "guerra", "conflito"]):
        variants.extend(["Crise global", "Risco para o Brasil"])
    if any(word in lowered for word in ["petroleo", "gasolina", "diesel", "combustivel", "energia"]):
        variants.extend(["Energia em alerta", "Combustivel em risco"])
    variants.extend(["Entenda o impacto", "O ponto central"])
    return _dedupe_preserve_order([item[:34] for item in variants], limit=4)


def _build_long_chapters(text: str, start_seconds: float, duration_seconds: float) -> list[str]:
    sentences = [part.strip(" -:;,.") for part in re.split(r"(?<=[.!?])\s+", text or "") if part.strip()]
    if not sentences:
        return ["00:00 Abertura", "02:30 Ponto principal", "06:30 Analise", "10:30 Fechamento"]

    chapter_count = 4 if duration_seconds >= 720 else 3
    spacing = max(1, len(sentences) // chapter_count)
    timestamps = [0]
    if chapter_count >= 2:
        timestamps.append(int(min(duration_seconds * 0.28, duration_seconds - 1)))
    if chapter_count >= 3:
        timestamps.append(int(min(duration_seconds * 0.58, duration_seconds - 1)))
    if chapter_count >= 4:
        timestamps.append(int(min(duration_seconds * 0.82, duration_seconds - 1)))
    timestamps = timestamps[:chapter_count]

    chapters: list[str] = []
    for index, offset in enumerate(timestamps):
        label = sentences[min(index * spacing, len(sentences) - 1)][:62].strip()
        minutes, seconds = divmod(max(0, int(offset)), 60)
        chapters.append(f"{minutes:02d}:{seconds:02d} {label or 'Capitulo'}")
    return chapters


def _clean_sentence_for_title(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip(" -:;,.!?"))
    return cleaned


def _best_short_title(text: str) -> str:
    variants = _short_title_variants(text)
    if variants:
        return variants[0]
    sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", text or "") if item.strip()]
    preferred = [
        sentence for sentence in sentences
        if len(_clean_sentence_for_title(sentence)) >= 18
        and not _clean_sentence_for_title(sentence).lower() in {"ok", "exatamente", "obrigado", "valeu", "cara", "pois e"}
    ]
    if preferred:
        base = _clean_sentence_for_title(preferred[0])[:90]
        return base or "Corte de podcast"
    return "Corte de podcast"


def _short_candidate_editorial_score(text: str, start: float, duration: float, total_duration: float) -> tuple[int, dict[str, int]]:
    lowered = (text or "").lower()
    ctr = _score_text(text) + 8
    retention = 50
    context = 45

    strong_hooks = [
        "o problema",
        "o ponto",
        "o erro",
        "isso explica",
        "o que acontece",
        "por que",
        "como",
        "impacto",
        "efeito",
        "alerta",
        "risco",
        "agora",
    ]
    retention_markers = [
        "porque",
        "mas",
        "so que",
        "por exemplo",
        "na verdade",
        "quer dizer",
        "deixa eu te explicar",
        "vou te falar",
        "acontece que",
        "e ai",
    ]
    topic_markers = [
        "politica",
        "brasil",
        "china",
        "trump",
        "guerra",
        "mercado",
        "dinheiro",
        "dolar",
        "inflacao",
        "petroleo",
        "combustivel",
        "iran",
        "taiwan",
    ]
    weak_or_outro = [
        "obrigado",
        "valeu",
        "insider",
        "patrocinador",
        "patrocinadores",
        "livepix",
        "link na descricao",
        "comentario fixado",
        "discord",
        "vira membro",
        "segue o cara",
        "agenda",
        "porto alegre",
        "show amanha",
        "presenca",
        "vamos fazer o seguinte",
        "me receber",
        "cupom",
        "desconto",
        "mes do consumidor",
    ]

    ctr += sum(7 for word in strong_hooks if word in lowered)
    retention += sum(6 for word in retention_markers if word in lowered)
    context += sum(6 for word in topic_markers if word in lowered)
    if _looks_like_weak_opener(text):
        ctr -= 18
        retention -= 10

    sentence_count = max(1, len([part for part in re.split(r"[.!?]+", text or "") if part.strip()]))
    word_count = len(re.findall(r"\w+", text or ""))
    if 28 <= duration <= 42:
        retention += 14
    elif 34 <= duration <= 55:
        retention += 10
    elif 30 <= duration <= 59:
        retention += 6

    if 70 <= word_count <= 150:
        context += 8
    elif word_count < 40:
        context -= 14

    if sentence_count >= 3:
        retention += 5
        context += 4
    if any(word in lowered for word in ["brasil", "bolso", "mercado", "dolar", "inflacao", "combustivel"]):
        context += 10
        ctr += 4
    if "?" in text:
        ctr += 5

    start_ratio = (start / total_duration) if total_duration > 0 else 0
    if start_ratio < 0.02:
        context -= 8
    if start_ratio > 0.92:
        retention -= 10
        ctr -= 8

    weak_hits = sum(1 for word in weak_or_outro if word in lowered)
    if weak_hits:
        penalty = weak_hits * 16
        ctr -= penalty
        retention -= penalty
        context -= penalty

    title = _best_short_title(text).lower()
    if title in {"ok", "exatamente", "obrigado", "valeu"}:
        ctr -= 22
        retention -= 14
        context -= 14

    ctr = max(1, min(99, ctr))
    retention = max(1, min(99, retention))
    context = max(1, min(99, context))
    overall = max(1, min(99, round((ctr * 0.42) + (retention * 0.38) + (context * 0.20))))
    return overall, {"ctr": ctr, "retention": retention, "context": context, "overall": overall}


def _short_candidate_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": int(item.get("candidate_id") or 0),
        "start_label": item.get("start_label"),
        "duration_label": item.get("duration_label"),
        "heuristic_score": int(item.get("score") or 0),
        "title": str(item.get("title") or ""),
        "hook": str(item.get("hook") or ""),
        "first_frame_text": str(item.get("first_frame_text") or ""),
        "topic_tags": list(item.get("topic_tags") or []),
        "excerpt": str(item.get("transcript_excerpt") or "")[:900],
    }


def _rerank_short_candidates_with_openai(
    video: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    limit: int = 5,
    selection_strategy: str = "openai_heuristica",
    editorial_profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not candidates:
        return []

    api_key = _openai_api_key()
    model = _openai_shorts_rerank_model()
    shortlist = candidates[: max(limit * 2, 8)]
    payload_candidates = [_short_candidate_summary(item) for item in shortlist]
    profile = editorial_profile or EDITORIAL_PROFILE
    preferred_terms = list(profile.get("preferred_terms") or [])
    avoid_terms = list(profile.get("avoid_terms") or [])
    viral_tone = str(profile.get("viral_tone") or "").strip()
    preferred_terms_text = ", ".join(preferred_terms[:8])
    avoid_terms_text = ", ".join(avoid_terms[:8])
    system_prompt = (
        "Voce e um editor senior de shorts para YouTube. "
        f"O canal e focado em {profile['positioning']}. "
        "Escolha os melhores cortes com foco em gancho forte no primeiro segundo, contexto suficiente, clareza, retencao e vontade de ver o episodio completo. "
        "Evite publi, encerramento, agradecimentos, trechos sem contexto, respostas genericas e frases muito internas. "
        "Prefira trechos de 28 a 45 segundos com tese clara, conflito, explicacao, previsao, risco ou revelacao. "
        f"Use a formula editorial: {profile['title_formula']}. "
        f"{f'Priorize cortes com termos como: {preferred_terms_text}. ' if preferred_terms_text else ''}"
        f"{f'Evite selecionar ou destacar termos como: {avoid_terms_text}. ' if avoid_terms_text else ''}"
        f"{f'Tom viral pedido pelo canal: {viral_tone}. Puxe mais reacao, zoacao, brincadeira, provocacao ou sentimento quando isso aparecer de forma natural no trecho. ' if viral_tone else ''}"
        "Nao use titulos vagos ou genericos. "
        "Retorne JSON puro."
    )
    user_prompt = {
        "video_title": str(video.get("title") or ""),
        "channel": str(video.get("author_name") or ""),
        "target_count": int(limit),
        "channel_preferences": {
            "preferred_terms": preferred_terms,
            "avoid_terms": avoid_terms,
            "viral_tone": viral_tone,
        },
        "instruction": (
            "Selecione os melhores candidatos em ordem de prioridade. "
            "Para cada item escolhido, devolva candidate_id, score_ia (0-100), title, hook, first_frame_text e reason. "
            "O title deve ficar natural, clicavel, especifico e deixar clara a consequencia do tema. "
            "O hook deve resumir o gancho do corte em uma frase curta. "
            "O first_frame_text deve ter entre 3 e 6 palavras e funcionar como texto forte na abertura."
        ),
        "candidates": payload_candidates,
    }

    with httpx.Client(timeout=90) as client:
        response = client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
                ],
            },
        )
        response.raise_for_status()
        payload = response.json()

    content = (((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    if not content:
        return candidates[:limit]

    parsed = json.loads(content)
    picks = parsed.get("selected_candidates") or parsed.get("selected") or parsed.get("items") or []
    if not isinstance(picks, list):
        return candidates[:limit]

    indexed = {int(item.get("candidate_id") or 0): item for item in shortlist}
    selected: list[dict[str, Any]] = []
    used_ids: set[int] = set()
    for raw in picks:
        if not isinstance(raw, dict):
            continue
        candidate_id = int(raw.get("candidate_id") or 0)
        if candidate_id <= 0 or candidate_id in used_ids or candidate_id not in indexed:
            continue
        used_ids.add(candidate_id)
        base = dict(indexed[candidate_id])
        heuristic_score = max(1, min(99, int(base.get("score") or 0)))
        ai_score = max(1, min(99, int(raw.get("score_ia") or heuristic_score)))
        title = _clean_sentence_for_title(str(raw.get("title") or ""))[:100] or str(base.get("title") or "")
        hook = _clean_sentence_for_title(str(raw.get("hook") or ""))[:160] or str(base.get("hook") or "")
        first_frame_text = _clean_sentence_for_title(str(raw.get("first_frame_text") or ""))[:52] or str(base.get("first_frame_text") or "")
        reason = _clean_sentence_for_title(str(raw.get("reason") or ""))[:220]
        hybrid_score = round((ai_score * 0.6) + (heuristic_score * 0.4))
        base["heuristic_score"] = heuristic_score
        base["ai_score"] = ai_score
        base["score"] = ai_score if selection_strategy == "openai" else hybrid_score
        base["title"] = title or str(base.get("title") or "")
        base["hook"] = hook or str(base.get("hook") or "")
        base["first_frame_text"] = first_frame_text or str(base.get("first_frame_text") or "")
        base["title_variants"] = _short_title_variants(base["transcript_excerpt"], base["title"])
        if reason:
            base["ai_reason"] = reason
        base["selection_source"] = selection_strategy
        selected.append(base)
        if len(selected) >= limit:
            break

    if not selected:
        return candidates[:limit]

    if selection_strategy == "openai_heuristica":
        selected.sort(key=lambda item: int(item.get("score") or 0), reverse=True)

    return selected


def _build_short_cut_candidates(
    segments: list[dict[str, Any]],
    *,
    limit: int = 5,
    editorial_profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not segments:
        raise ValueError("Nao encontrei transcricao suficiente para detectar cortes.")

    candidates: list[dict[str, Any]] = []
    used_ranges: list[tuple[float, float]] = []
    total_duration = float(segments[-1]["end"] or 0)
    candidate_starts: list[int] = []
    next_threshold = 0.0

    for index, segment in enumerate(segments):
        if float(segment["start"] or 0) >= next_threshold:
            candidate_starts.append(index)
            next_threshold = float(segment["start"] or 0) + 12.0

    for cursor in candidate_starts:
        opening_index = _find_better_short_open(segments, cursor, total_duration)
        start = float(segments[opening_index]["start"] or 0)
        end = float(segments[cursor]["end"] or start)
        text_parts = [segments[opening_index]["text"]]
        runner = opening_index + 1
        while runner < len(segments) and end - start < 52:
            end = float(segments[runner]["end"] or end)
            text_parts.append(segments[runner]["text"])
            if end - start >= 38:
                break
            runner += 1
        duration = end - start
        if 28 <= duration <= 59:
            text = " ".join(text_parts).strip()
            score, scorecard = _short_candidate_editorial_score(text, start, duration, total_duration)
            preference_delta, preference_notes = _profile_preference_adjustment(text, editorial_profile)
            score = max(1, min(99, score + preference_delta))
            title = _best_short_title(text)
            hook = _hook_from_text(text)
            topic_tags = _topic_tags_from_text(text)
            first_frame_text = _impact_frame_text(text, mode="short")
            candidates.append(
                {
                    "candidate_id": len(candidates) + 1,
                    "start": max(0, start),
                    "end": end,
                    "start_label": _format_srt_timestamp(max(0, start)).replace(",", "."),
                    "end_label": _format_srt_timestamp(end).replace(",", "."),
                    "duration_seconds": round(duration, 2),
                    "duration_label": _format_duration_label(duration),
                    "transcript_excerpt": text,
                    "hook": hook,
                    "title": title,
                    "title_variants": _short_title_variants(text, title),
                    "first_frame_text": first_frame_text,
                    "topic_tags": topic_tags,
                    "score": score,
                    "scorecard": scorecard,
                    "preference_delta": preference_delta,
                    "caption_draft": hook,
                    "opening_score": _opening_sentence_score(text),
                    "packaging_notes": [
                        f"Primeiro frame: {first_frame_text}",
                        f"Abertura detectada com score { _opening_sentence_score(text) } para os primeiros segundos.",
                        "Legenda branca com contorno preto e palavra ativa em azul.",
                        "Evitar subir outro corte muito parecido no mesmo dia.",
                    ]
                    + preference_notes,
                }
            )

    if not candidates:
        raise ValueError("Nao encontrei trechos curtos com contexto suficiente para gerar shorts.")

    candidates.sort(key=lambda item: (item["score"], item["duration_seconds"]), reverse=True)

    selected: list[dict[str, Any]] = []
    for item in candidates:
        overlaps = any(not (item["end"] <= start or item["start"] >= end) for start, end in used_ranges)
        if overlaps:
            continue
        used_ranges.append((item["start"], item["end"]))
        selected.append(item)
        if len(selected) >= limit:
            break

    return _apply_short_series_strategy(selected)


def _build_long_cut_candidates(
    segments: list[dict[str, Any]],
    *,
    limit: int = 3,
    editorial_profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not segments:
        raise ValueError("Nao encontrei transcricao suficiente para detectar cortes longos.")

    total_duration = float(segments[-1]["end"] or 0)
    if total_duration < 480:
        raise ValueError("Esse video ainda esta curto demais para gerar cortes longos de 10 a 15 minutos.")

    min_duration = 600.0 if total_duration >= 600 else 480.0
    max_duration = 900.0 if total_duration >= 900 else min(max(total_duration, min_duration), 900.0)
    target_duration = min(720.0, max_duration)
    candidate_starts: list[int] = []
    step_seconds = 180.0
    next_threshold = 0.0

    for index, segment in enumerate(segments):
        if segment["start"] >= next_threshold:
            candidate_starts.append(index)
            next_threshold = segment["start"] + step_seconds

    candidates: list[dict[str, Any]] = []
    for cursor in candidate_starts:
        start = float(segments[cursor]["start"] or 0)
        end = float(segments[cursor]["end"] or start)
        text_parts = [segments[cursor]["text"]]
        runner = cursor + 1
        while runner < len(segments) and end - start < target_duration:
            end = float(segments[runner]["end"] or end)
            text_parts.append(segments[runner]["text"])
            runner += 1
        duration = end - start
        if duration < min_duration:
            continue
        if duration > max_duration:
            while runner > cursor + 1 and duration > max_duration:
                runner -= 1
                end = float(segments[runner - 1]["end"] or end)
                text_parts = [segments[item]["text"] for item in range(cursor, runner)]
                duration = end - start
        if duration < min_duration or duration > max_duration:
            continue

        text = " ".join(text_parts).strip()
        score = _long_candidate_editorial_score(text, start, duration, total_duration)
        preference_delta, preference_notes = _profile_preference_adjustment(text, editorial_profile)
        score = max(1, min(99, score + preference_delta))
        scorecard = _long_cut_scorecard(text, start, duration, total_duration)
        topic_tags = _topic_tags_from_text(text)
        candidates.append(
            {
                "start": max(0, start),
                "end": end,
                "start_label": _format_srt_timestamp(max(0, start)).replace(",", "."),
                "end_label": _format_srt_timestamp(end).replace(",", "."),
                "duration_seconds": round(duration, 2),
                "duration_label": _format_duration_label(duration),
                "transcript_excerpt": text[:1800].strip(),
                "hook": _hook_from_text(text),
                "title": _long_title_from_text(text),
                "score": score,
                "scorecard": scorecard,
                "first_frame_text": _impact_frame_text(text, mode="long"),
                "topic_tags": topic_tags,
                "preference_delta": preference_delta,
                "title_variants": _title_variants_for_long_cut(text),
                "thumbnail_text_variants": _thumbnail_text_variants_for_long_cut(text),
                "caption_draft": _hook_from_text(text),
                "packaging_notes": [
                    "Abrir o video com frase forte na tela nos primeiros segundos.",
                    "Thumbnail sem selo corte longo e com promessa objetiva.",
                    "Tema precisa conectar crise, mercado ou impacto no Brasil.",
                    "Adicionar end screen nos 5 a 20 segundos finais apontando para outro corte ou video completo.",
                    "Organizar o video em playlist do mesmo tema para aumentar sessao.",
                ]
                + preference_notes,
            }
        )

    if not candidates:
        raise ValueError("Nao encontrei blocos longos coerentes para gerar cortes de 10 a 15 minutos.")

    candidates.sort(key=lambda item: (item["score"], item["duration_seconds"]), reverse=True)

    selected: list[dict[str, Any]] = []
    used_ranges: list[tuple[float, float]] = []
    for item in candidates:
        overlaps = any(not (item["end"] <= start or item["start"] >= end) for start, end in used_ranges)
        if overlaps:
            continue
        used_ranges.append((item["start"], item["end"]))
        selected.append(item)
        if len(selected) >= limit:
            break

    ranked: list[dict[str, Any]] = []
    for index, item in enumerate(selected):
        editorial_role = "principal" if index == 0 else f"secundario_{index}"
        ranked.append(
            item
            | {
                "editorial_role": editorial_role,
                "title": _long_title_from_text(item["transcript_excerpt"], primary=index == 0),
                "hook": item["hook"] if index > 0 else item["hook"],
                "first_frame_text": item.get("first_frame_text") or _impact_frame_text(item["transcript_excerpt"], mode="long"),
                "title_variants": _title_variants_for_long_cut(item["transcript_excerpt"]),
                "thumbnail_text_variants": _thumbnail_text_variants_for_long_cut(item["transcript_excerpt"]),
            }
        )

    return ranked


def _build_cut_candidates(
    segments: list[dict[str, Any]],
    *,
    limit: int = 5,
    mode: str = "short",
    editorial_profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    normalized_mode = _normalize_cut_mode(mode)
    if normalized_mode == "long":
        return _build_long_cut_candidates(segments, limit=max(1, min(limit, 3)), editorial_profile=editorial_profile)
    return _build_short_cut_candidates(segments, limit=max(limit * 2, 8), editorial_profile=editorial_profile)


def _passes_short_opening_gate(item: dict[str, Any], *, relaxed: bool = False) -> bool:
    opening_score = int(item.get("opening_score") or 0)
    visual_score = int(item.get("opening_visual_score") or 0)
    subject_signal = str(item.get("opening_subject_signal") or "").strip().lower()
    if relaxed:
        if opening_score < max(1, SHORT_MIN_OPENING_SCORE - 8) and visual_score < max(1, SHORT_MIN_VISUAL_SCORE - 8):
            return False
        if opening_score < 42:
            return False
        return True
    if opening_score < SHORT_MIN_OPENING_SCORE:
        return False
    if visual_score < SHORT_MIN_VISUAL_SCORE:
        return False
    if opening_score < SHORT_STRONG_OPENING_SCORE and visual_score < SHORT_STRONG_VISUAL_SCORE:
        return False
    if visual_score < 50 and subject_signal == "fraco":
        return False
    return True


def _format_srt_timestamp(value: float) -> str:
    total_ms = int(round(value * 1000))
    hours = total_ms // 3_600_000
    minutes = (total_ms % 3_600_000) // 60_000
    seconds = (total_ms % 60_000) // 1000
    millis = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _format_ass_timestamp(value: float) -> str:
    total_cs = max(0, int(round(value * 100)))
    hours = total_cs // 360000
    minutes = (total_cs % 360000) // 6000
    seconds = (total_cs % 6000) // 100
    centiseconds = total_cs % 100
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"


def _split_subtitle_text(text: str, *, max_words: int = 5) -> list[str]:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return []

    chunks: list[str] = []
    phrases = [part.strip(" -") for part in re.split(r"(?<=[,.;:!?])\s+", cleaned) if part.strip()]
    for phrase in phrases:
        words = phrase.split()
        if len(words) <= max_words:
            chunks.append(phrase)
            continue
        for index in range(0, len(words), max_words):
            piece = " ".join(words[index:index + max_words]).strip()
            if piece:
                chunks.append(piece)
    return chunks or [cleaned]


def _ass_escape_text(text: str) -> str:
    escaped = str(text or "").replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")
    return escaped.replace("\n", r"\N")


def _word_highlight_markup(words: list[str], active_index: int) -> str:
    rendered: list[str] = []
    for index, word in enumerate(words):
        escaped_word = _ass_escape_text(str(word or "").upper())
        if index == active_index:
            rendered.append(r"{\c&H00FF8C3A&}" + escaped_word + r"{\c&H00FFFFFF&}")
        else:
            rendered.append(escaped_word)
    return " ".join(rendered)


def _group_timed_words_for_subtitles(
    word_entries: list[dict[str, Any]],
    *,
    max_words: int = 5,
    max_gap: float = 0.75,
) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for entry in word_entries:
        if current:
            previous_end = float(current[-1].get("end") or 0.0)
            current_start = float(entry.get("start") or 0.0)
            if len(current) >= max_words or current_start - previous_end > max_gap:
                groups.append(current)
                current = []
        current.append(entry)
    if current:
        groups.append(current)
    return groups


def _write_cut_ass(job_dir: Path, cut_id: int, start_time: float, end_time: float, segments: list[dict[str, Any]]) -> Path:
    output = job_dir / f"cut-{cut_id:02d}.ass"
    rows = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 608",
        "PlayResY: 1080",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Punch,Arial,50,&H00FFFFFF,&H00FF8C3A,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,4,0,2,{SHORT_SUBTITLE_MARGIN_H},{SHORT_SUBTITLE_MARGIN_H},{SHORT_SUBTITLE_MARGIN_V},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    timed_words_across_cut: list[dict[str, Any]] = []
    timed_word_signatures: set[tuple[int, int, str]] = set()
    fallback_segments: list[dict[str, Any]] = []
    for segment in segments:
        if segment["end"] < start_time or segment["start"] > end_time:
            continue
        local_start = max(segment["start"], start_time) - start_time
        local_end = min(segment["end"], end_time) - start_time
        if local_end - local_start <= 0:
            continue
        timed_words = []
        for word in _normalize_timed_words(segment.get("words") or []):
            word_start = max(float(word.get("start") or 0.0), start_time) - start_time
            word_end = min(float(word.get("end") or 0.0), end_time) - start_time
            word_text = str(word.get("text") or "").strip()
            if word_text and word_end - word_start > 0:
                signature = (
                    int(round(word_start * 100)),
                    int(round(word_end * 100)),
                    word_text,
                )
                if signature in timed_word_signatures:
                    continue
                timed_word_signatures.add(signature)
                timed_words.append({"start": word_start, "end": word_end, "text": word_text})
        if timed_words:
            timed_words_across_cut.extend(timed_words)
            continue
        fallback_segments.append(
            {
                "local_start": local_start,
                "local_end": local_end,
                "text": str(segment.get("text") or ""),
            }
        )

    timed_words_across_cut.sort(key=lambda item: (float(item.get("start") or 0.0), float(item.get("end") or 0.0), str(item.get("text") or "")))
    for group in _group_timed_words_for_subtitles(timed_words_across_cut):
        group_words = [str(word.get("text") or "").strip() for word in group if str(word.get("text") or "").strip()]
        if not group_words:
            continue
        for word_index, word in enumerate(group):
            word_start = float(word.get("start") or 0.0)
            word_end = float(word.get("end") or word_start)
            if word_end - word_start <= 0:
                continue
            rows.append(
                "Dialogue: 0,"
                f"{_format_ass_timestamp(word_start)},{_format_ass_timestamp(word_end)},"
                f"Punch,,0,0,0,,{_word_highlight_markup(group_words, word_index)}"
            )

    for segment in fallback_segments:
        local_start = float(segment["local_start"])
        local_end = float(segment["local_end"])
        subtitle_chunks = _split_subtitle_text(str(segment.get("text") or ""), max_words=5)
        if not subtitle_chunks:
            continue
        total_duration = local_end - local_start
        chunk_duration = total_duration / max(1, len(subtitle_chunks))
        cursor = local_start
        for index, chunk_text in enumerate(subtitle_chunks):
            chunk_start = cursor
            chunk_end = local_end if index == len(subtitle_chunks) - 1 else min(local_end, chunk_start + chunk_duration)
            if chunk_end - chunk_start <= 0:
                continue
            words = [word for word in chunk_text.split() if word.strip()]
            if not words:
                cursor = chunk_end
                continue
            weights = [max(1, len(re.sub(r"[^\w]", "", word)) or 1) for word in words]
            total_weight = sum(weights) or len(words)
            word_cursor = chunk_start
            for word_index, word in enumerate(words):
                word_duration = (chunk_end - chunk_start) * (weights[word_index] / total_weight)
                word_end = chunk_end if word_index == len(words) - 1 else min(chunk_end, word_cursor + word_duration)
                if word_end - word_cursor <= 0:
                    continue
                rows.append(
                    "Dialogue: 0,"
                    f"{_format_ass_timestamp(word_cursor)},{_format_ass_timestamp(word_end)},"
                    f"Punch,,0,0,0,,{_word_highlight_markup(words, word_index)}"
                )
                word_cursor = word_end
            cursor = chunk_end
    output.write_text("\n".join(rows).strip() + "\n", encoding="utf-8")
    return output


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: Any, max_width: int, max_lines: int) -> list[str]:
    words = str(text or "").split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        trial = " ".join(current + [word]).strip()
        if draw.textbbox((0, 0), trial, font=font)[2] <= max_width:
            current.append(word)
            continue
        if current:
            lines.append(" ".join(current))
        current = [word]
        if len(lines) >= max_lines - 1:
            break
    if current and len(lines) < max_lines:
        lines.append(" ".join(current))
    return lines[:max_lines]


def _fit_text_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, *, start_size: int, min_size: int = 14, bold: bool = False):
    size = start_size
    while size >= min_size:
        font = _load_font(size, bold=bold)
        bbox = draw.textbbox((0, 0), text, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            return font
        size -= 1
    return _load_font(min_size, bold=bold)


def _download_image(url: str) -> Image.Image | None:
    image_url = (url or "").strip()
    if not image_url:
        return None
    try:
        with httpx.Client(timeout=20, follow_redirects=True) as client:
            response = client.get(image_url)
            response.raise_for_status()
        return Image.open(BytesIO(response.content)).convert("RGB")
    except Exception:
        return None


def _generate_hook_overlay_asset(
    job_dir: Path,
    cut_id: int,
    text: str,
    *,
    mode: str,
    editorial_profile: dict[str, Any] | None = None,
) -> Path:
    normalized_mode = _normalize_cut_mode(mode)
    size = (608, 1080) if normalized_mode == "short" else (1920, 1080)
    filename = f"hook-{cut_id:02d}-{normalized_mode}.png"
    destination = job_dir / filename

    # Pedido atual: manter os cortes sem o bloco/titulo no topo.
    Image.new("RGBA", size, (0, 0, 0, 0)).save(destination, format="PNG")
    return destination


def _generate_long_thumbnail(
    job_dir: Path,
    cut_id: int,
    video: dict[str, Any],
    item: dict[str, Any],
    *,
    editorial_profile: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    source = _download_image(str(video.get("thumbnail_url") or ""))
    if source is None:
        return None
    profile = editorial_profile or EDITORIAL_PROFILE

    filename = f"thumb-{cut_id:02d}.jpg"
    destination = job_dir / filename
    canvas = ImageOps.fit(source, (1280, 720), method=Image.Resampling.LANCZOS)
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle((44, 398, 1236, 678), radius=34, fill=(5, 16, 40, 205))
    draw.rounded_rectangle((50, 50, 368, 114), radius=26, fill=(24, 93, 255, 236))

    kicker_font = _load_font(26, bold=True)
    title_font = _load_font(54, bold=True)
    meta_font = _load_font(26, bold=False)
    kicker_text = str(profile["long_kicker"])
    draw.text((74, 68), kicker_text, font=kicker_font, fill=(255, 255, 255, 255))

    headline = item.get("title_variants", [item.get("title") or profile["overlay_default_text_long"]])[0]
    title_lines = _wrap_text(draw, headline, title_font, 1110, 3)
    y = 430
    for line in title_lines:
        draw.text((74, y), line, font=title_font, fill=(255, 255, 255, 255))
        y += 64

    hook_text = str((item.get("thumbnail_text_variants") or [_impact_frame_text(str(item.get("hook") or item.get("title") or ""), mode="long")])[0]).strip()
    meta = f"{hook_text} | {item.get('duration_label') or ''} | score {int((item.get('scorecard') or {}).get('overall') or item.get('score') or 0)}"
    draw.text((74, 624), meta.strip(" |"), font=meta_font, fill=(179, 214, 255, 255))

    final_image = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
    final_image.save(destination, format="JPEG", quality=90, optimize=True)
    return {
        "filename": filename,
        "asset_url": f"/dashboard/api/youtube/cuts/assets/{job_dir.name}/{filename}",
    }


def _escape_subtitles_filter_path(path: Path) -> str:
    raw = str(path.resolve()).replace("\\", "/")
    if re.match(r"^[A-Za-z]:", raw):
        raw = raw[0] + "\\:" + raw[2:]
    return raw.replace("'", "\\'")


def _extract_motion_analysis_frames(
    source_video: Path,
    frames_dir: Path,
    *,
    start_time: float,
    duration_seconds: float,
) -> list[Path]:
    sample_duration = max(1.5, min(float(duration_seconds or 0.0), SHORT_SMART_CROP_ANALYSIS_MAX_SECONDS))
    sample_start = max(0.0, float(start_time or 0.0) + 0.25)
    frames_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = _ffmpeg_command()
    output_pattern = str(frames_dir / "frame-%03d.jpg")
    _run_command(
        ffmpeg
        + [
            "-y",
            *_ffmpeg_filter_thread_args(),
            "-ss",
            f"{sample_start:.2f}",
            "-i",
            str(source_video),
            "-t",
            f"{sample_duration:.2f}",
            "-vf",
            f"fps={SHORT_SMART_CROP_ANALYSIS_FPS},scale=-2:{SHORT_SMART_CROP_ANALYSIS_HEIGHT}:flags=fast_bilinear",
            "-q:v",
            "6",
            output_pattern,
        ]
    )
    return sorted(frames_dir.glob("frame-*.jpg"))


def _motion_column_scores(frame_paths: list[Path]) -> list[float]:
    previous: Image.Image | None = None
    column_scores: list[float] = []
    for frame_path in frame_paths:
        with Image.open(frame_path) as frame_image:
            grayscale = frame_image.convert("L")
            top = int(grayscale.height * 0.08)
            bottom = max(top + 1, int(grayscale.height * 0.78))
            window = grayscale.crop((0, top, grayscale.width, bottom))
            detail = window.filter(ImageFilter.FIND_EDGES).resize((window.width, 1))
            if previous is None:
                previous = window
                column_scores = [0.0] * window.width
                for index, value in enumerate(detail.getdata()):
                    column_scores[index] += float(value) * 0.35
                continue
            diff = ImageChops.difference(previous, window)
            compressed = diff.resize((window.width, 1))
            for index, value in enumerate(compressed.getdata()):
                column_scores[index] += float(value)
            for index, value in enumerate(detail.getdata()):
                column_scores[index] += float(value) * 0.35
            previous = window
    if not column_scores:
        return []
    smoothed: list[float] = []
    radius = 6
    for index in range(len(column_scores)):
        left = max(0, index - radius)
        right = min(len(column_scores), index + radius + 1)
        smoothed.append(sum(column_scores[left:right]))
    return smoothed


def _window_sum(prefix_sums: list[float], start: int, width: int) -> float:
    end = min(len(prefix_sums) - 1, start + width)
    start = max(0, min(start, end))
    return prefix_sums[end] - prefix_sums[start]


def _short_focus_zone(position_ratio: float) -> str:
    if position_ratio <= 0.34:
        return "esquerda"
    if position_ratio >= 0.66:
        return "direita"
    return "centro"


def _analyze_short_opening_visual_signal(
    source_video: Path,
    output_video: Path,
    *,
    start_time: float,
    duration_seconds: float,
) -> dict[str, Any]:
    dimensions = _video_dimensions(source_video)
    if dimensions is None:
        return {
            "crop_x": 0,
            "opening_visual_score": 50,
            "opening_focus_zone": "centro",
            "opening_focus_confidence": 0,
            "opening_subject_signal": "neutro",
        }

    source_width, source_height = dimensions
    scaled_width = _scaled_width_for_height(source_width, source_height, SHORT_VIDEO_HEIGHT)
    max_crop_x = max(0, scaled_width - SHORT_VIDEO_WIDTH)
    center_crop_x = max_crop_x // 2
    if max_crop_x <= 0:
        return {
            "crop_x": 0,
            "opening_visual_score": 52,
            "opening_focus_zone": "centro",
            "opening_focus_confidence": 0,
            "opening_subject_signal": "neutro",
        }

    analysis_width = _scaled_width_for_height(source_width, source_height, SHORT_SMART_CROP_ANALYSIS_HEIGHT)
    crop_width_analysis = max(2, min(analysis_width, _even_int(SHORT_VIDEO_WIDTH * SHORT_SMART_CROP_ANALYSIS_HEIGHT / SHORT_VIDEO_HEIGHT)))
    center_analysis_x = max(0, (analysis_width - crop_width_analysis) // 2)
    if analysis_width <= crop_width_analysis:
        return {
            "crop_x": center_crop_x,
            "opening_visual_score": 52,
            "opening_focus_zone": "centro",
            "opening_focus_confidence": 0,
            "opening_subject_signal": "neutro",
        }

    frames_dir = output_video.with_suffix("")
    frames_dir = frames_dir.with_name(f"{frames_dir.name}-smartcrop")
    try:
        frame_paths = _extract_motion_analysis_frames(
            source_video,
            frames_dir,
            start_time=start_time,
            duration_seconds=duration_seconds,
        )
        if len(frame_paths) < 2:
            return {
                "crop_x": center_crop_x,
                "opening_visual_score": 48,
                "opening_focus_zone": "centro",
                "opening_focus_confidence": 0,
                "opening_subject_signal": "fraco",
            }
        column_scores = _motion_column_scores(frame_paths)
        if not column_scores:
            return {
                "crop_x": center_crop_x,
                "opening_visual_score": 48,
                "opening_focus_zone": "centro",
                "opening_focus_confidence": 0,
                "opening_subject_signal": "fraco",
            }
        prefix_sums = [0.0]
        for value in column_scores:
            prefix_sums.append(prefix_sums[-1] + value)
        center_score = _window_sum(prefix_sums, center_analysis_x, crop_width_analysis)
        best_x = center_analysis_x
        best_score = center_score
        last_start = max(0, analysis_width - crop_width_analysis)
        step = max(2, SHORT_SMART_CROP_WINDOW_STEP)
        for start in range(0, last_start + 1, step):
            score = _window_sum(prefix_sums, start, crop_width_analysis)
            if score > best_score:
                best_score = score
                best_x = start
        average_energy = prefix_sums[-1] / max(1, len(column_scores))
        peak_energy = max(column_scores) if column_scores else 0.0
        focus_ratio = best_score / max(1.0, center_score or 1.0)
        peak_ratio = peak_energy / max(1.0, average_energy or 1.0)
        best_window_center = best_x + (crop_width_analysis / 2.0)
        focus_zone = _short_focus_zone(best_window_center / max(1.0, float(analysis_width)))
        confidence = max(
            0.0,
            min(
                1.0,
                ((focus_ratio - 1.0) * 0.58)
                + ((peak_ratio - 1.0) * 0.22),
            ),
        )
        visual_score = 46
        visual_score += min(16, max(0, round((focus_ratio - 1.0) * 22)))
        visual_score += min(14, max(0, round((peak_ratio - 1.0) * 10)))
        if average_energy < 14:
            visual_score -= 14
        elif average_energy < 22:
            visual_score -= 8
        elif average_energy > 40:
            visual_score += 6
        if focus_zone != "centro" and confidence >= 0.34:
            visual_score += 6
        elif focus_zone == "centro" and confidence < 0.12:
            visual_score -= 4
        visual_score = max(1, min(99, visual_score))
        if visual_score >= 72:
            subject_signal = "forte"
        elif visual_score >= 56:
            subject_signal = "medio"
        else:
            subject_signal = "fraco"
        if best_score <= center_score * SHORT_SMART_CROP_CENTER_STICKINESS:
            best_x = center_analysis_x
            focus_zone = "centro"
        ratio = scaled_width / max(1, analysis_width)
        detected_x = int(round(best_x * ratio))
        return {
            "crop_x": max(0, min(max_crop_x, detected_x)),
            "opening_visual_score": int(visual_score),
            "opening_focus_zone": focus_zone,
            "opening_focus_confidence": int(round(confidence * 100)),
            "opening_subject_signal": subject_signal,
        }
    except Exception:
        return {
            "crop_x": center_crop_x,
            "opening_visual_score": 50,
            "opening_focus_zone": "centro",
            "opening_focus_confidence": 0,
            "opening_subject_signal": "neutro",
        }
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)


def _detect_short_crop_x(
    source_video: Path,
    output_video: Path,
    *,
    start_time: float,
    duration_seconds: float,
) -> int:
    analysis = _analyze_short_opening_visual_signal(
        source_video,
        output_video,
        start_time=start_time,
        duration_seconds=duration_seconds,
    )
    return int(analysis.get("crop_x") or 0)


def _generate_vertical_cut(
    source_video: Path,
    subtitles_path: Path | None,
    overlay_path: Path,
    output_video: Path,
    start_time: float,
    duration_seconds: float,
    crop_x: int | None = None,
) -> None:
    ffmpeg = _ffmpeg_command()
    rendered_video = output_video.with_name(f"{output_video.stem}.video-only{output_video.suffix}")
    resolved_crop_x = int(crop_x) if crop_x is not None else _detect_short_crop_x(
        source_video,
        output_video,
        start_time=start_time,
        duration_seconds=duration_seconds,
    )
    filter_steps = [
        f"[0:v]scale=-2:{SHORT_VIDEO_HEIGHT}:flags=lanczos,crop={SHORT_VIDEO_WIDTH}:{SHORT_VIDEO_HEIGHT}:{resolved_crop_x}:0,setsar=1[base]",
        "[base][1:v]overlay=0:0:enable='lt(t,3.2)'[hooked]",
    ]
    if subtitles_path is not None:
        subtitle_filter = _escape_subtitles_filter_path(subtitles_path)
        filter_steps.append(f"[hooked]subtitles='{subtitle_filter}',format=yuv420p[vout]")
    else:
        filter_steps.append("[hooked]format=yuv420p[vout]")
    filter_complex = ";".join(filter_steps)
    try:
        _run_command(
            ffmpeg
            + [
                "-y",
                *_ffmpeg_filter_thread_args(),
                "-ss",
                f"{start_time:.2f}",
                "-i",
                str(source_video),
                "-loop",
                "1",
                "-i",
                str(overlay_path),
                "-t",
                f"{duration_seconds:.2f}",
                "-filter_complex",
                filter_complex,
                "-map",
                "[vout]",
                *_ffmpeg_h264_video_args(mode="short"),
                "-an",
                str(rendered_video),
            ]
        )
        _run_command(
            ffmpeg
            + [
                "-y",
                "-ss",
                f"{start_time:.2f}",
                "-i",
                str(source_video),
                "-i",
                str(rendered_video),
                "-t",
                f"{duration_seconds:.2f}",
                "-map",
                "1:v:0",
                "-map",
                "0:a:0?",
                "-c:v",
                "copy",
                *_ffmpeg_aac_audio_args(),
                "-shortest",
                str(output_video),
            ]
        )
    finally:
        rendered_video.unlink(missing_ok=True)


def _generate_horizontal_cut(
    source_video: Path,
    overlay_path: Path,
    output_video: Path,
    start_time: float,
    duration_seconds: float,
) -> None:
    ffmpeg = _ffmpeg_command()
    rendered_video = output_video.with_name(f"{output_video.stem}.video-only{output_video.suffix}")
    filter_complex = (
        "[0:v]scale=1920:-2:flags=lanczos,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[base];"
        "[base][1:v]overlay=0:0:enable='lt(t,4.0)',format=yuv420p[vout]"
    )
    try:
        _run_command(
            ffmpeg
            + [
                "-y",
                *_ffmpeg_filter_thread_args(),
                "-ss",
                f"{start_time:.2f}",
                "-i",
                str(source_video),
                "-loop",
                "1",
                "-i",
                str(overlay_path),
                "-t",
                f"{duration_seconds:.2f}",
                "-filter_complex",
                filter_complex,
                "-map",
                "[vout]",
                *_ffmpeg_h264_video_args(mode="long"),
                "-an",
                str(rendered_video),
            ]
        )
        _run_command(
            ffmpeg
            + [
                "-y",
                "-ss",
                f"{start_time:.2f}",
                "-i",
                str(source_video),
                "-i",
                str(rendered_video),
                "-t",
                f"{duration_seconds:.2f}",
                "-map",
                "1:v:0",
                "-map",
                "0:a:0?",
                "-c:v",
                "copy",
                *_ffmpeg_aac_audio_args(),
                "-shortest",
                str(output_video),
            ]
        )
    finally:
        rendered_video.unlink(missing_ok=True)


def _extract_audio_chunks(source_video: Path, job_dir: Path) -> list[Path]:
    def _cleanup_audio_chunks() -> None:
        for chunk_path in job_dir.glob("audio-*.*"):
            chunk_path.unlink(missing_ok=True)

    attempts: list[tuple[list[str], Path]] = []
    system_ffmpeg = _system_ffmpeg_command()
    if system_ffmpeg:
        attempts.append((system_ffmpeg, job_dir / "audio-%03d.mp3"))
        attempts.append((system_ffmpeg, job_dir / "audio-%03d.wav"))
    fallback_ffmpeg = _ffmpeg_command()
    attempts.append((fallback_ffmpeg, job_dir / "audio-%03d.wav"))

    errors: list[str] = []
    for ffmpeg, pattern in attempts:
        _cleanup_audio_chunks()
        command = ffmpeg + [
            "-y",
            "-i",
            str(source_video),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
        ]
        if pattern.suffix == ".mp3":
            command += [
                "-b:a",
                "32k",
            ]
        else:
            command += [
                "-c:a",
                "pcm_s16le",
            ]
        command += [
            "-f",
            "segment",
            "-segment_time",
            "900",
            "-reset_timestamps",
            "1",
            str(pattern),
        ]
        try:
            _run_command(command)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{' '.join(ffmpeg)} {pattern.suffix}: {str(exc)}")
            continue
        chunks = sorted(
            path for path in job_dir.glob("audio-*.*")
            if path.suffix.lower() in {".mp3", ".wav", ".m4a"}
        )
        if chunks:
            return chunks

    detail = errors[-1] if errors else "sem detalhes"
    raise ValueError(f"Nao consegui extrair o audio do video para transcricao. Ultima tentativa: {detail}")


def _transcribe_audio_chunk_via_openai(chunk_path: Path) -> dict[str, Any]:
    api_key = _openai_api_key()
    mime_type = "audio/mpeg" if chunk_path.suffix.lower() == ".mp3" else "audio/wav"
    with chunk_path.open("rb") as audio_file:
        files = [
            ("file", (chunk_path.name, audio_file, mime_type)),
            ("model", (None, "whisper-1")),
            ("response_format", (None, "verbose_json")),
            ("timestamp_granularities[]", (None, "segment")),
            ("timestamp_granularities[]", (None, "word")),
            ("language", (None, "pt")),
        ]
        with httpx.Client(timeout=180) as client:
            response = client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                files=files,
            )
            response.raise_for_status()
            return response.json()


def _transcribe_audio_via_openai(source_video: Path, job_dir: Path) -> tuple[list[dict[str, Any]], str]:
    chunks = _extract_audio_chunks(source_video, job_dir)
    all_segments: list[dict[str, Any]] = []
    transcript_blocks: list[str] = []
    chunk_offset = 0.0

    for chunk_path in chunks:
        payload = _transcribe_audio_chunk_via_openai(chunk_path)
        payload_segments = payload.get("segments") or []
        payload_words = _normalize_timed_words(payload.get("words") or [], offset=chunk_offset)
        payload_word_cursor = 0
        if isinstance(payload.get("text"), str) and payload["text"].strip():
            transcript_blocks.append(payload["text"].strip())
        for item in payload_segments:
            if not isinstance(item, dict):
                continue
            text = _clean_vtt_text(str(item.get("text") or ""))
            if not text:
                continue
            start = float(item.get("start") or 0) + chunk_offset
            end = float(item.get("end") or start) + chunk_offset
            segment_words = _normalize_timed_words(item.get("words") or [], offset=chunk_offset)
            if not segment_words and payload_words:
                lower_bound = start - 0.08
                upper_bound = end + 0.08
                while payload_word_cursor < len(payload_words) and float(payload_words[payload_word_cursor].get("end") or 0.0) < lower_bound:
                    payload_word_cursor += 1
                probe = payload_word_cursor
                while probe < len(payload_words):
                    word = payload_words[probe]
                    word_start = float(word.get("start") or 0.0)
                    if word_start > upper_bound:
                        break
                    word_end = float(word.get("end") or word_start)
                    if word_end >= lower_bound:
                        segment_words.append(word)
                    probe += 1
            segment_payload: dict[str, Any] = {"start": start, "end": end, "text": text}
            if segment_words:
                segment_payload["words"] = segment_words
            all_segments.append(segment_payload)
        chunk_offset += 900.0

    if not all_segments:
        raise ValueError("A transcricao por audio nao retornou segmentos suficientes para montar os cortes.")

    transcript_text = "\n".join(block for block in transcript_blocks if block).strip() or _transcript_text(all_segments)
    return all_segments, transcript_text


def _write_job_manifest(job_dir: Path, payload: dict[str, Any]) -> None:
    (job_dir / "manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_youtube_cuts_manifest(job_id: str) -> dict[str, Any]:
    manifest_path = youtube_cuts_manifest_path(job_id)
    if not manifest_path.is_file():
        raise FileNotFoundError("Manifesto do job de cortes nao encontrado.")
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Manifesto do job de cortes esta invalido.") from exc


def _manual_short_crop_x(source_video: Path, framing: str) -> int:
    dimensions = _video_dimensions(source_video)
    if dimensions is None:
        return 0
    source_width, source_height = dimensions
    scaled_width = _scaled_width_for_height(source_width, source_height, SHORT_VIDEO_HEIGHT)
    max_crop_x = max(0, scaled_width - SHORT_VIDEO_WIDTH)
    normalized = (framing or "auto").strip().lower()
    if normalized == "esquerda":
        return 0
    if normalized == "direita":
        return max_crop_x
    return max_crop_x // 2


def rerender_youtube_cut(job_id: str, cut_id: int, *, framing: str = "auto") -> dict[str, Any]:
    manifest = load_youtube_cuts_manifest(job_id)
    mode = _normalize_cut_mode(str(manifest.get("mode") or "short"))
    if mode != "short":
        raise ValueError("O override manual de enquadramento vale apenas para cortes em short.")

    cuts = list(manifest.get("cuts") or [])
    cut_index = next((index for index, item in enumerate(cuts) if int(item.get("cut_id") or 0) == int(cut_id)), -1)
    if cut_index < 0:
        raise ValueError("Corte nao encontrado dentro do job.")

    cut = dict(cuts[cut_index] or {})
    normalized_framing = (framing or "auto").strip().lower()
    if normalized_framing not in {"auto", "esquerda", "direita"}:
        normalized_framing = "auto"

    source_filename = str(((manifest.get("video") or {}).get("source_filename")) or "").strip()
    if not source_filename:
        raise ValueError("Arquivo fonte do video nao foi encontrado no manifesto.")

    job_dir = youtube_cuts_job_dir(job_id)
    source_video = youtube_cuts_asset_path(job_id, source_filename)
    video_filename = str(cut.get("video_filename") or f"cut-{int(cut_id):02d}.mp4").strip()
    output_video = job_dir / video_filename
    overlay_filename = str(cut.get("hook_overlay_filename") or "").strip()
    subtitle_filename = str(cut.get("subtitle_filename") or "").strip()

    if overlay_filename:
        overlay_path = youtube_cuts_asset_path(job_id, overlay_filename)
    else:
        overlay_path = _generate_hook_overlay_asset(
            job_dir,
            int(cut_id),
            str(cut.get("first_frame_text") or cut.get("hook") or cut.get("title") or ""),
            mode="short",
        )
        overlay_filename = overlay_path.name

    subtitle_path = youtube_cuts_asset_path(job_id, subtitle_filename) if subtitle_filename else None
    if normalized_framing == "auto":
        visual_signal = _analyze_short_opening_visual_signal(
            source_video,
            output_video,
            start_time=float(cut.get("start") or 0.0),
            duration_seconds=min(float(cut.get("duration_seconds") or 0.0), 4.0),
        )
        crop_x = int(visual_signal.get("crop_x") or 0)
        opening_focus_zone = str(visual_signal.get("opening_focus_zone") or "centro")
        opening_focus_confidence = int(visual_signal.get("opening_focus_confidence") or 0)
        opening_subject_signal = str(visual_signal.get("opening_subject_signal") or "neutro")
        opening_visual_score = int(visual_signal.get("opening_visual_score") or 50)
    else:
        crop_x = _manual_short_crop_x(source_video, normalized_framing)
        opening_focus_zone = normalized_framing
        opening_focus_confidence = 100
        opening_subject_signal = "manual"
        opening_visual_score = int(cut.get("opening_visual_score") or 50)

    _generate_vertical_cut(
        source_video,
        subtitle_path,
        overlay_path,
        output_video,
        float(cut.get("start") or 0.0),
        float(cut.get("duration_seconds") or 0.0),
        crop_x=crop_x,
    )

    cut["crop_override"] = normalized_framing
    cut["crop_x"] = crop_x
    cut["opening_focus_zone"] = opening_focus_zone
    cut["opening_focus_confidence"] = opening_focus_confidence
    cut["opening_subject_signal"] = opening_subject_signal
    cut["opening_visual_score"] = opening_visual_score
    cut["hook_overlay_filename"] = overlay_filename
    packaging_notes = list(cut.get("packaging_notes") or [])
    packaging_notes.append(f"Enquadramento manual: {normalized_framing}.")
    cut["packaging_notes"] = _dedupe_preserve_order(packaging_notes, limit=8)
    cuts[cut_index] = cut
    manifest["cuts"] = cuts
    _write_job_manifest(job_dir, manifest)

    return {
        "ok": True,
        "job_id": job_id,
        "cut_id": int(cut_id),
        "mode": "short",
        "framing": normalized_framing,
        "crop_x": crop_x,
        "opening_focus_zone": opening_focus_zone,
        "opening_focus_confidence": opening_focus_confidence,
        "opening_subject_signal": opening_subject_signal,
        "opening_visual_score": opening_visual_score,
        "video_filename": video_filename,
    }


def _fetch_recent_social_offers(limit: int = 5) -> list[dict[str, Any]]:
    db = SessionLocal()
    try:
        try:
            rows = db.execute(
                text(
                    """
                    SELECT result_json
                    FROM automacao_execucoes
                    WHERE tipo = 'social'
                      AND status = 'success'
                      AND result_json IS NOT NULL
                    ORDER BY criado_em DESC, id DESC
                    LIMIT 40
                    """
                )
            ).mappings().all()
        except Exception:
            rows = []

        offer_ids: list[int] = []
        seen: set[int] = set()
        for row in rows:
            payload = row.get("result_json")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except Exception:
                    payload = None
            if not isinstance(payload, dict):
                continue
            items = payload.get("items") or []
            if not isinstance(items, list):
                continue
            for item in items:
                offer_id = int((item or {}).get("offer_id") or 0)
                if offer_id <= 0 or offer_id in seen:
                    continue
                seen.add(offer_id)
                offer_ids.append(offer_id)
                if len(offer_ids) >= limit:
                    break
            if len(offer_ids) >= limit:
                break

        if not offer_ids:
            fallback = db.execute(
                text(
                    """
                    SELECT id, slug, titulo, loja, preco
                    FROM ofertas
                    WHERE ativo = 1
                    ORDER BY atualizado_em DESC, id DESC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            ).mappings().all()
            return [dict(row) for row in fallback]

        offer_rows = db.execute(
            text(
                """
                SELECT id, slug, titulo, loja, preco
                FROM ofertas
                WHERE id IN :offer_ids
                """
            ).bindparams(bindparam("offer_ids", expanding=True)),
            {"offer_ids": offer_ids},
        ).mappings().all()
        indexed = {int(row["id"]): dict(row) for row in offer_rows}
        return [indexed[offer_id] for offer_id in offer_ids if offer_id in indexed][:limit]
    finally:
        db.close()


def _format_price(value: Any) -> str:
    try:
        number = float(value or 0)
    except Exception:
        number = 0.0
    return f"R$ {number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _recent_offer_url(slug: str) -> str:
    return f"{_site_base_url()}/oferta.php?slug={slug}"


def _build_recent_offers_block(limit: int = 5) -> tuple[list[dict[str, Any]], list[str]]:
    offers = _fetch_recent_social_offers(limit=limit)
    lines: list[str] = []
    enriched: list[dict[str, Any]] = []
    for offer in offers:
        slug = str(offer.get("slug") or "").strip()
        title = str(offer.get("titulo") or "Oferta").strip()
        store = str(offer.get("loja") or "").strip()
        price_label = _format_price(offer.get("preco"))
        offer_url = _recent_offer_url(slug) if slug else _site_base_url()
        lines.append(f"- {title} | {store} | {price_label}")
        lines.append(offer_url)
        lines.append("")
        enriched.append(dict(offer) | {"offer_url": offer_url, "price_label": price_label})
    return enriched, lines


def build_youtube_cut_publish_draft(job_id: str, cut_id: int, *, privacy_status: str = "public") -> dict[str, Any]:
    manifest = load_youtube_cuts_manifest(job_id)
    editorial_profile = _editorial_profile_for_channel(str(manifest.get("target_channel_profile_name") or ""))
    cuts = manifest.get("cuts") or []
    selected = next((item for item in cuts if int(item.get("cut_id") or 0) == int(cut_id)), None)
    if not isinstance(selected, dict):
        raise ValueError("Corte nao encontrado dentro do job selecionado.")

    video = manifest.get("video") or {}
    mode = _normalize_cut_mode(str(selected.get("mode") or manifest.get("mode") or "short"))
    topic_tags = list(selected.get("topic_tags") or _topic_tags_from_text(str(selected.get("transcript_excerpt") or selected.get("hook") or "")))
    hashtags = _hashtags_for_cut(topic_tags, mode=mode)
    normalized_privacy = (privacy_status or "public").strip().lower()
    if normalized_privacy not in {"private", "unlisted", "public"}:
        normalized_privacy = "public"

    chapters: list[str] = []
    if mode == "long":
        chapter_source = str(selected.get("transcript_excerpt") or selected.get("hook") or selected.get("title") or "")
        chapters = _build_long_chapters(
            chapter_source,
            float(selected.get("start") or 0),
            float(selected.get("duration_seconds") or 0),
        )
        description_lines = [
            str(selected.get("hook") or selected.get("title") or "Corte longo pronto para publicar.").strip(),
            "",
            str(editorial_profile["long_series_summary"]),
            "",
            f"Tema base: {video.get('title') or 'Video base'}",
            f"Video completo: {video.get('url') or ''}".strip(),
            "",
            "Capitulos:",
            *chapters,
            "",
            str(editorial_profile["subscribe_line"]),
            "",
            " ".join(hashtags),
        ]
        title = str(selected.get("copy_title") or selected.get("title") or "Corte longo YouTube").strip()[:100]
    else:
        series_part = int(selected.get("series_part") or 0)
        series_total = int(selected.get("series_total") or 0)
        description_lines = [
            str(selected.get("hook") or selected.get("title") or "Corte pronto para publicar.").strip(),
            "",
            f"Parte {series_part} de {series_total} desta serie." if series_total > 1 and series_part > 0 else "",
            f"Continue na parte {series_part + 1}." if series_total > 1 and 0 < series_part < series_total else "",
            "Veja as partes anteriores e o video completo." if series_total > 1 and series_part == series_total else "",
            "",
            str(editorial_profile["short_series_summary"]),
            "",
            f"Trecho original: {video.get('title') or 'Video base'}",
            f"Video completo: {video.get('url') or ''}".strip(),
            "",
            str(editorial_profile["subscribe_line"]),
            "",
            " ".join(hashtags),
        ]
        title = str(selected.get("copy_title") or selected.get("title") or "Corte YouTube").strip()[:100]
    return {
        "job_id": job_id,
        "cut_id": int(cut_id),
        "channel_profile_id": manifest.get("target_channel_profile_id"),
        "channel_profile_name": manifest.get("target_channel_profile_name") or "",
        "mode": mode,
        "title": title,
        "title_variants": list(selected.get("title_variants") or []),
        "thumbnail_text_variants": list(selected.get("thumbnail_text_variants") or []),
        "scorecard": dict(selected.get("scorecard") or {}),
        "chapters": chapters,
        "topic_tags": topic_tags,
        "first_frame_text": str(selected.get("first_frame_text") or ""),
        "packaging_notes": list(selected.get("packaging_notes") or []),
        "series_mode": str(selected.get("series_mode") or "single"),
        "series_part": int(selected.get("series_part") or 0),
        "series_total": int(selected.get("series_total") or 0),
        "series_label": str(selected.get("series_label") or ""),
        "editorial_role": str(selected.get("editorial_role") or ""),
        "thumbnail_asset_url": str(selected.get("thumbnail_asset_url") or ""),
        "thumbnail_filename": str(selected.get("thumbnail_filename") or ""),
        "description": "\n".join(line for line in description_lines if line is not None).strip(),
        "privacy_status": normalized_privacy,
        "source_video": {
            "video_id": video.get("video_id"),
            "title": video.get("title"),
            "url": video.get("url"),
        },
        "publish_label": "Publicar video" if mode == "long" else "Publicar Short",
        "distribution_notes": [
            "Se for video longo, adicionar end screen nos 5 a 20 segundos finais.",
            "Colocar o video em playlist do mesmo tema para aumentar sessao.",
            "Usar cards apenas se houver um video claramente complementar.",
        ],
    }


def process_youtube_video_for_cuts(
    raw_url: str,
    *,
    limit: int = 5,
    mode: str = "short",
    selection_strategy: str = "openai_heuristica",
    channel_profile_id: int | None = None,
    channel_profile_name: str | None = None,
    channel_preferences: dict[str, Any] | None = None,
    burn_subtitles: bool = True,
) -> dict[str, Any]:
    phase_one = analyze_youtube_video_for_cuts(raw_url)
    editorial_profile = _editorial_profile_with_preferences(
        _editorial_profile_for_channel(channel_profile_name),
        channel_preferences,
    )
    video = phase_one["video"]
    normalized_mode = _normalize_cut_mode(mode)
    normalized_strategy = _normalize_short_selection_strategy(selection_strategy)
    created_at = _utc_now()
    timestamp = created_at.strftime("%Y%m%d%H%M%S")
    job_id = f"{video['video_id']}-{timestamp}"
    job_dir = youtube_cuts_runtime_dir() / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    source_video, subtitle_file, subtitle_error = _download_video_and_subtitles(video["url"], job_dir)
    source_duration_seconds = _media_duration_seconds(source_video)
    should_burn_subtitles, subtitle_decision = _resolve_burn_subtitles(
        mode=normalized_mode,
        requested=bool(burn_subtitles),
        source_duration_seconds=source_duration_seconds,
        youtube_subtitle_file=subtitle_file,
        source_video=source_video,
    )
    transcript_source = "youtube_subtitles"
    transcript_warning = ""
    if subtitle_file is not None:
        transcript_segments = _parse_vtt_segments(subtitle_file)
        transcript_text = _transcript_text(transcript_segments)
    else:
        transcript_source = "openai_audio"
        transcript_warning = subtitle_error
        transcript_segments, transcript_text = _transcribe_audio_via_openai(source_video, job_dir)
    cut_candidates = _build_cut_candidates(
        transcript_segments,
        limit=limit,
        mode=normalized_mode,
        editorial_profile=editorial_profile,
    )
    if normalized_mode == "short" and normalized_strategy in {"openai", "openai_heuristica"}:
        try:
            cut_candidates = _rerank_short_candidates_with_openai(
                video,
                cut_candidates,
                limit=limit,
                selection_strategy=normalized_strategy,
                editorial_profile=editorial_profile,
            )
        except Exception as exc:  # noqa: BLE001
            transcript_warning = (
                f"{transcript_warning} | " if transcript_warning else ""
            ) + f"Reranqueamento IA indisponivel, usando heuristica local: {str(exc)}"
            cut_candidates = cut_candidates[:limit]
    elif normalized_mode == "short":
        cut_candidates = cut_candidates[:limit]

    if normalized_mode == "short":
        visually_scored_candidates: list[dict[str, Any]] = []
        for index, item in enumerate(cut_candidates, start=1):
            visual_signal = _analyze_short_opening_visual_signal(
                source_video,
                job_dir / f"candidate-{index:02d}.mp4",
                start_time=float(item.get("start") or 0.0),
                duration_seconds=min(float(item.get("duration_seconds") or 0.0), 4.0),
            )
            visual_score = int(visual_signal.get("opening_visual_score") or 50)
            visual_delta = 0
            if visual_score >= 74:
                visual_delta = 8
            elif visual_score >= 62:
                visual_delta = 4
            elif visual_score <= 38:
                visual_delta = -14
            elif visual_score <= 48:
                visual_delta = -6
            scorecard = dict(item.get("scorecard") or {})
            scorecard["opening"] = int(item.get("opening_score") or 0)
            scorecard["visual"] = visual_score
            updated_item = item | visual_signal
            updated_item["scorecard"] = scorecard
            updated_item["visual_delta"] = visual_delta
            updated_item["score"] = max(1, min(99, int(item.get("score") or 0) + visual_delta))
            updated_item["packaging_notes"] = _dedupe_preserve_order(
                list(item.get("packaging_notes") or [])
                + [
                    f"Gancho inicial com score {int(item.get('opening_score') or 0)}.",
                    (
                        "Abertura visual "
                        f"{visual_signal.get('opening_subject_signal') or 'neutra'} "
                        f"com foco em {visual_signal.get('opening_focus_zone') or 'centro'} "
                        f"({int(visual_signal.get('opening_focus_confidence') or 0)}% de confianca)."
                    ),
                    "Evitar publicar esse corte se o rosto nao aparecer logo no primeiro segundo.",
                ]
            )
            visually_scored_candidates.append(updated_item)
        ranked_candidates = sorted(
            visually_scored_candidates,
            key=lambda item: (
                int(item.get("score") or 0),
                int(item.get("opening_score") or 0),
                int(item.get("opening_visual_score") or 0),
                float(item.get("duration_seconds") or 0.0),
            ),
            reverse=True,
        )
        gated_candidates = [item for item in ranked_candidates if _passes_short_opening_gate(item)]
        if len(gated_candidates) < limit:
            relaxed_candidates = [item for item in ranked_candidates if _passes_short_opening_gate(item, relaxed=True)]
            merged_candidates: list[dict[str, Any]] = []
            seen_candidate_ids: set[int] = set()
            for item in gated_candidates + relaxed_candidates + ranked_candidates:
                candidate_id = int(item.get("candidate_id") or 0)
                if candidate_id in seen_candidate_ids:
                    continue
                seen_candidate_ids.add(candidate_id)
                merged_candidates.append(item)
            cut_candidates = merged_candidates[:limit]
        else:
            cut_candidates = gated_candidates[:limit]

    generated_items = []
    for index, item in enumerate(cut_candidates, start=1):
        video_filename = f"cut-{index:02d}.mp4"
        video_output = job_dir / video_filename
        overlay_path = _generate_hook_overlay_asset(
            job_dir,
            index,
            str(item.get("first_frame_text") or item.get("hook") or item.get("title") or editorial_profile["overlay_default_text_short"]),
            mode=normalized_mode,
            editorial_profile=editorial_profile,
        )
        topic_tags = list(item.get("topic_tags") or _topic_tags_from_text(str(item.get("transcript_excerpt") or item.get("hook") or "")))
        hashtags = _hashtags_for_cut(topic_tags, mode=normalized_mode)
        if normalized_mode == "long":
            description_draft = "\n".join(
                [
                    str(item.get("hook") or item.get("title") or "").strip(),
                    "",
                    str(editorial_profile["long_series_summary"]),
                    f"Video base: {video.get('title') or ''}".strip(),
                    " ".join(hashtags),
                ]
            ).strip()
        else:
            description_draft = _short_series_description(item, video, hashtags, editorial_profile=editorial_profile)
        if normalized_mode == "long":
            subtitle_path = None
            _generate_horizontal_cut(source_video, overlay_path, video_output, item["start"], item["duration_seconds"])
        else:
            subtitle_path = _write_cut_ass(job_dir, index, item["start"], item["end"], transcript_segments) if should_burn_subtitles else None
            _generate_vertical_cut(
                source_video,
                subtitle_path,
                overlay_path,
                video_output,
                item["start"],
                item["duration_seconds"],
                crop_x=int(item.get("crop_x") or 0),
            )
        thumbnail_asset = _generate_long_thumbnail(job_dir, index, video, item, editorial_profile=editorial_profile) if normalized_mode == "long" else None
        generated_items.append(
            item
            | {
                "cut_id": index,
                "job_id": job_id,
                "mode": normalized_mode,
                "video_asset_url": f"/dashboard/api/youtube/cuts/assets/{job_id}/{video_filename}",
                "video_filename": video_filename,
                "download_url": f"/dashboard/api/youtube/cuts/assets/{job_id}/{video_filename}",
                "hook_overlay_asset_url": f"/dashboard/api/youtube/cuts/assets/{job_id}/{overlay_path.name}",
                "hook_overlay_filename": overlay_path.name,
                "thumbnail_asset_url": (thumbnail_asset or {}).get("asset_url"),
                "thumbnail_filename": (thumbnail_asset or {}).get("filename"),
                "copy_title": str(item.get("copy_title") or item["title"]),
                "copy_description": description_draft,
                "caption_draft": description_draft,
                "status": "generated",
                "series_mode": str(item.get("series_mode") or "single"),
                "series_part": int(item.get("series_part") or 0),
                "series_total": int(item.get("series_total") or 0),
                "series_label": str(item.get("series_label") or ""),
                "subtitle_asset_url": f"/dashboard/api/youtube/cuts/assets/{job_id}/{subtitle_path.name}" if subtitle_path else None,
                "subtitle_filename": subtitle_path.name if subtitle_path else None,
            }
        )

    payload = {
        "ok": True,
        "phase": 2,
        "job_id": job_id,
        "created_at_utc": created_at.isoformat(),
        "expires_at_utc": (created_at + YOUTUBE_CUTS_RETENTION).isoformat(),
        "target_channel_profile_id": int(channel_profile_id) if channel_profile_id else None,
        "target_channel_profile_name": str(channel_profile_name or "").strip(),
        "mode": normalized_mode,
        "burn_subtitles": should_burn_subtitles,
        "selection_strategy": normalized_strategy if normalized_mode == "short" else "long_default",
        "strategy": {
            "profile": editorial_profile["name"],
            "positioning": editorial_profile["positioning"],
            "title_formula": editorial_profile["title_formula"],
            "subtitle_style": editorial_profile["subtitle_style"],
            "preferred_terms": list(editorial_profile.get("preferred_terms") or []),
            "avoid_terms": list(editorial_profile.get("avoid_terms") or []),
            "viral_tone": str(editorial_profile.get("viral_tone") or ""),
        },
        "video": video | {"source_filename": source_video.name, "subtitle_filename": subtitle_file.name if subtitle_file else None},
        "transcript": {
            "language_hint": subtitle_file.suffix.lstrip(".") if subtitle_file else "openai-whisper-1",
            "segments_count": len(transcript_segments),
            "text": transcript_text,
            "source": transcript_source,
            "warning": transcript_warning,
        },
        "cuts": generated_items,
        "subtitle_decision": subtitle_decision,
        "notes": [
            note
            for note in [
                "Fase 2: video baixado, transcricao base gerada e cortes montados.",
                "Shorts saem em vertical com abertura forte e legenda dinamica com destaque em azul.",
                "Shorts agora filtram trechos com abertura visual fraca ou gancho inicial morno sempre que houver opcoes melhores.",
                "Corte longo sai em horizontal com gancho visual nos primeiros segundos e thumbnail mais limpa.",
                str(editorial_profile["notes_summary"]),
                (f"Priorizar: {', '.join(editorial_profile.get('preferred_terms') or [])}" if editorial_profile.get("preferred_terms") else ""),
                (f"Evitar: {', '.join(editorial_profile.get('avoid_terms') or [])}" if editorial_profile.get("avoid_terms") else ""),
                (f"Tom viral: {editorial_profile.get('viral_tone')}" if editorial_profile.get("viral_tone") else ""),
            ]
            if note
        ],
    }
    _write_job_manifest(job_dir, payload)
    return payload
