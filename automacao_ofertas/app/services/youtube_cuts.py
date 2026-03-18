import os
import json
import html
import re
import shutil
import subprocess
import sys
from io import BytesIO
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import imageio_ffmpeg
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont, ImageOps
from sqlalchemy import bindparam, text

from app.database import SessionLocal


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_ROOT = PROJECT_ROOT / "automacao_ofertas" / "runtime" / "youtube_cuts"
ENV_PATH = PROJECT_ROOT / "automacao_ofertas" / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)


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


def _build_suggestion(title: str, author_name: str, video_url: str, angle: str, hook: str, duration_seconds: int, score: int) -> dict[str, Any]:
    safe_title = (title or "Podcast").strip()
    safe_author = (author_name or "canal").strip()
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
        "caption_draft": "\n".join(caption_lines).strip(),
        "reason": (
            f"Formato pensado para {angle.lower()}, com gancho curto e facil de adaptar "
            "para Shorts, Reels e cortes de podcast."
        ),
        "status": "editorial_brief",
    }


def _build_initial_cut_suggestions(title: str, author_name: str, video_url: str) -> list[dict[str, Any]]:
    templates = [
        ("Gancho forte", "Corte com frase de impacto logo no inicio", 35, 92),
        ("Opiniao forte", "Trecho com posicionamento claro ou discordancia", 45, 88),
        ("Passo pratico", "Trecho ensinando algo em poucos passos", 40, 84),
        ("Erro comum", "Trecho mostrando algo que as pessoas fazem errado", 32, 82),
        ("Momento surpreendente", "Trecho com dado, historia ou revelacao", 38, 80),
        ("Fechamento forte", "Trecho final com resumo ou chamada forte", 30, 78),
    ]
    return [
        _build_suggestion(title, author_name, video_url, angle, hook, duration_seconds, score)
        for angle, hook, duration_seconds, score in templates
    ]


def _build_initial_long_cut_suggestions(title: str, author_name: str, video_url: str) -> list[dict[str, Any]]:
    templates = [
        ("Corte longo principal", "Bloco maior com contexto, desenvolvimento e fechamento forte", 720, 94),
        ("Tema com retenção", "Bloco longo que sustenta busca, recomendação e tempo de exibição", 840, 90),
        ("Polêmica explicada", "Trecho completo com tese, argumento e conclusão em sequência", 660, 88),
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
        "notes": [
            "Fase 1: intake e briefing editorial.",
            "A transcricao com IA e os cortes reais entram na proxima fase.",
            "As sugestoes abaixo sao uma pauta inicial para validar o tema antes da automacao completa.",
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


def _browser_cookie_specs() -> list[str]:
    specs: list[str] = []
    explicit_specs = _parse_csv_env("YTDLP_COOKIES_FROM_BROWSER")
    if explicit_specs:
        return explicit_specs

    explicit_cookie_file = (os.getenv("YTDLP_COOKIES_FILE") or "").strip()
    if explicit_cookie_file:
        return specs

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
    if appdata:
        browser_profiles["firefox"] = (appdata / "Mozilla" / "Firefox" / "profiles.ini", ["default-release", "default"])

    ordered_specs: list[str] = []
    for browser, (state_path, fallback_profiles) in browser_profiles.items():
        ordered_specs.append(browser)
        if state_path.exists():
            last_profile = _read_browser_last_profile(state_path) if state_path.name.lower() == "local state" else ""
            if last_profile:
                ordered_specs.append(f"{browser}:{last_profile}")
        for profile in fallback_profiles:
            ordered_specs.append(f"{browser}:{profile}")

    seen: set[str] = set()
    for spec in ordered_specs:
        normalized = spec.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        specs.append(normalized)
    return specs


def _youtube_download_variants(video_url: str, output_template: str, *, with_subtitles: bool) -> list[list[str]]:
    base_command = _ytdlp_command()
    shared = [
        "--no-warnings",
        "--format",
        "mp4/best[ext=mp4]/best",
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


def _run_youtube_download_with_fallback(video_url: str, output_template: str, *, with_subtitles: bool) -> str:
    errors: list[str] = []
    for command in _youtube_download_variants(video_url, output_template, with_subtitles=with_subtitles):
        try:
            return _run_command(command)
        except Exception as exc:  # noqa: BLE001
            command_label = " ".join(command[:4])
            errors.append(f"{command_label}: {str(exc)}")
            continue
    hint = (
        "Falha ao baixar do YouTube. Se o video pedir confirmacao anti-bot, configure "
        "YTDLP_COOKIES_FILE com um cookies.txt exportado do navegador ou "
        "YTDLP_COOKIES_FROM_BROWSER com algo como chrome:Default,chrome:'Profile 1',edge:Default."
    )
    detail = errors[-1] if errors else "sem detalhes"
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
        text = _clean_vtt_text(" ".join(text_lines))
        if text:
            start = _parse_vtt_timestamp(start_raw.split(" ")[0])
            end = _parse_vtt_timestamp(end_raw.split(" ")[0])
            segments.append({"start": start, "end": end, "text": text})
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
    hot_words = [
        "como",
        "erro",
        "segredo",
        "verdade",
        "ninguem",
        "nunca",
        "sempre",
        "porque",
        "pol",
        "guerra",
        "dinheiro",
        "crise",
        "trump",
        "china",
        "iran",
        "russia",
        "brasil",
    ]
    for word in hot_words:
        if word in lowered:
            score += 6
    if "?" in text:
        score += 4
    score += min(len(text) // 80, 10)
    return min(score, 99)


def _hook_from_text(text: str) -> str:
    sentence = re.split(r"(?<=[\.\!\?])\s+", text.strip())[0]
    return sentence[:140].strip() or text[:140].strip()


def _title_from_text(text: str) -> str:
    hook = _hook_from_text(text)
    trimmed = hook.strip(" -:;,.")
    return trimmed[:90] or "Corte de podcast"


def _long_title_from_text(text: str, *, primary: bool = False) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    sentence = _hook_from_text(cleaned)
    lowered = cleaned.lower()

    if " porque " in f" {lowered} ":
        base = f"Por que {sentence[:72].strip(' -:;,.?')}"
    elif " como " in f" {lowered} ":
        base = f"Como {sentence[:76].strip(' -:;,.?')}"
    elif " erro" in lowered or " errado" in lowered:
        base = f"O erro que quase todo mundo comete: {sentence[:62].strip(' -:;,.?')}"
    elif any(word in lowered for word in ["guerra", "crise", "trump", "china", "iran", "russia", "brasil", "mercado"]):
        base = f"O que realmente esta por tras disso: {sentence[:58].strip(' -:;,.?')}"
    else:
        base = sentence[:90].strip(" -:;,.")

    base = base[:96].strip()
    if primary:
        return f"{base} | Analise completa"[:100]
    return f"{base} | Corte completo"[:100]


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

    ctr_words = ["segredo", "erro", "verdade", "crise", "guerra", "por que", "como", "ninguem", "nunca"]
    retention_words = ["porque", "entao", "agora", "ou seja", "por exemplo", "primeiro", "segundo"]
    topic_words = ["brasil", "china", "trump", "mercado", "dinheiro", "politica", "guerra", "crise", "negocio"]

    ctr += sum(6 for word in ctr_words if word in lowered)
    retention += sum(5 for word in retention_words if word in lowered)
    topic += sum(6 for word in topic_words if word in lowered)

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
        f"Entenda isso antes que seja tarde: {short_hook}".strip()[:100],
    ]
    deduped: list[str] = []
    for item in variants:
        normalized = item.strip()
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped[:3]


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
    sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", text or "") if item.strip()]
    preferred = [
        sentence for sentence in sentences
        if len(_clean_sentence_for_title(sentence)) >= 18
        and not _clean_sentence_for_title(sentence).lower() in {"ok", "exatamente", "obrigado", "valeu", "cara", "pois e"}
    ]
    if preferred:
        base = _clean_sentence_for_title(preferred[0])[:90]
        return base or "Corte de podcast"
    return _title_from_text(text)


def _short_candidate_editorial_score(text: str, start: float, duration: float, total_duration: float) -> tuple[int, dict[str, int]]:
    lowered = (text or "").lower()
    ctr = _score_text(text) + 8
    retention = 50
    context = 45

    strong_hooks = [
        "o problema",
        "a questao",
        "o ponto",
        "o erro",
        "o segredo",
        "isso explica",
        "o que acontece",
        "por que",
        "como",
        "na pratica",
        "quer dizer",
        "olha so",
        "primeiro",
        "entao",
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
        "comedia",
        "humor",
        "processo",
        "justica",
        "crime",
        "preconceito",
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

    sentence_count = max(1, len([part for part in re.split(r"[.!?]+", text or "") if part.strip()]))
    word_count = len(re.findall(r"\w+", text or ""))
    if 34 <= duration <= 55:
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
        "excerpt": str(item.get("transcript_excerpt") or "")[:900],
    }


def _rerank_short_candidates_with_openai(
    video: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    limit: int = 5,
    selection_strategy: str = "openai_heuristica",
) -> list[dict[str, Any]]:
    if not candidates:
        return []

    api_key = _openai_api_key()
    model = _openai_shorts_rerank_model()
    shortlist = candidates[: max(limit * 2, 8)]
    payload_candidates = [_short_candidate_summary(item) for item in shortlist]
    system_prompt = (
        "Voce e um editor senior de shorts para YouTube. "
        "Escolha os melhores cortes com foco em gancho forte, contexto suficiente, clareza, retencao e vontade de ver o episodio completo. "
        "Evite publi, encerramento, agradecimentos, trechos sem contexto, respostas genericas e frases muito internas. "
        "Prefira trechos de 35 a 55 segundos com tese clara, conflito, explicacao ou revelacao. "
        "Retorne JSON puro."
    )
    user_prompt = {
        "video_title": str(video.get("title") or ""),
        "channel": str(video.get("author_name") or ""),
        "target_count": int(limit),
        "instruction": (
            "Selecione os melhores candidatos em ordem de prioridade. "
            "Para cada item escolhido, devolva candidate_id, score_ia (0-100), title, hook e reason. "
            "O title deve ficar natural e clicavel, sem exagero vazio. "
            "O hook deve resumir o gancho do corte em uma frase curta."
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
        reason = _clean_sentence_for_title(str(raw.get("reason") or ""))[:220]
        hybrid_score = round((ai_score * 0.6) + (heuristic_score * 0.4))
        base["heuristic_score"] = heuristic_score
        base["ai_score"] = ai_score
        base["score"] = ai_score if selection_strategy == "openai" else hybrid_score
        base["title"] = title or str(base.get("title") or "")
        base["hook"] = hook or str(base.get("hook") or "")
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


def _build_short_cut_candidates(segments: list[dict[str, Any]], *, limit: int = 5) -> list[dict[str, Any]]:
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
        start = float(segments[cursor]["start"] or 0)
        end = float(segments[cursor]["end"] or start)
        text_parts = [segments[cursor]["text"]]
        runner = cursor + 1
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
            title = _best_short_title(text)
            hook = _hook_from_text(text)
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
                    "score": score,
                    "scorecard": scorecard,
                    "caption_draft": text,
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

    ranked: list[dict[str, Any]] = []
    for index, item in enumerate(selected):
        ranked.append(
            item
            | {
                "editorial_role": "principal" if index == 0 else f"secundario_{index}",
                "copy_title": item["title"],
            }
        )
    return ranked


def _build_long_cut_candidates(segments: list[dict[str, Any]], *, limit: int = 3) -> list[dict[str, Any]]:
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
        scorecard = _long_cut_scorecard(text, start, duration, total_duration)
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
                "title_variants": _title_variants_for_long_cut(text),
                "caption_draft": text[:5000].strip(),
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
                "title": _long_title_from_text(item["caption_draft"], primary=index == 0),
                "hook": item["hook"] if index > 0 else f"{item['hook']} | bloco principal",
                "title_variants": _title_variants_for_long_cut(item["caption_draft"]),
            }
        )

    return ranked


def _build_cut_candidates(segments: list[dict[str, Any]], *, limit: int = 5, mode: str = "short") -> list[dict[str, Any]]:
    normalized_mode = _normalize_cut_mode(mode)
    if normalized_mode == "long":
        return _build_long_cut_candidates(segments, limit=max(1, min(limit, 3)))
    return _build_short_cut_candidates(segments, limit=max(limit * 2, 8))


def _format_srt_timestamp(value: float) -> str:
    total_ms = int(round(value * 1000))
    hours = total_ms // 3_600_000
    minutes = (total_ms % 3_600_000) // 60_000
    seconds = (total_ms % 60_000) // 1000
    millis = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


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


def _write_cut_srt(job_dir: Path, cut_id: int, start_time: float, end_time: float, segments: list[dict[str, Any]]) -> Path:
    output = job_dir / f"cut-{cut_id:02d}.srt"
    rows = []
    counter = 1
    for segment in segments:
        if segment["end"] < start_time or segment["start"] > end_time:
            continue
        local_start = max(segment["start"], start_time) - start_time
        local_end = min(segment["end"], end_time) - start_time
        if local_end - local_start <= 0:
            continue
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
            rows.append(
                f"{counter}\n{_format_srt_timestamp(chunk_start)} --> {_format_srt_timestamp(chunk_end)}\n{chunk_text}\n"
            )
            counter += 1
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


def _generate_long_thumbnail(job_dir: Path, cut_id: int, video: dict[str, Any], item: dict[str, Any]) -> dict[str, Any] | None:
    source = _download_image(str(video.get("thumbnail_url") or ""))
    if source is None:
        return None

    filename = f"thumb-{cut_id:02d}.jpg"
    destination = job_dir / filename
    canvas = ImageOps.fit(source, (1280, 720), method=Image.Resampling.LANCZOS)
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle((48, 420, 1232, 672), radius=28, fill=(5, 16, 40, 190))
    draw.rounded_rectangle((48, 48, 310, 108), radius=24, fill=(24, 93, 255, 230))

    kicker_font = _load_font(28, bold=True)
    title_font = _load_font(54, bold=True)
    meta_font = _load_font(26, bold=False)
    draw.text((74, 63), "CORTE LONGO", font=kicker_font, fill=(255, 255, 255, 255))

    title_lines = _wrap_text(draw, item.get("title_variants", [item.get("title") or "Corte longo"])[0], title_font, 1110, 3)
    y = 448
    for line in title_lines:
        draw.text((74, y), line, font=title_font, fill=(255, 255, 255, 255))
        y += 64

    meta = f"{item.get('duration_label') or ''} | score {int((item.get('scorecard') or {}).get('overall') or item.get('score') or 0)}"
    draw.text((74, 620), meta.strip(" |"), font=meta_font, fill=(179, 214, 255, 255))

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


def _generate_vertical_cut(source_video: Path, subtitles_path: Path, output_video: Path, start_time: float, duration_seconds: float) -> None:
    ffmpeg = _ffmpeg_command()
    subtitle_filter = _escape_subtitles_filter_path(subtitles_path)
    vf = (
        "scale=-2:1080,"
        "crop=608:1080,"
        f"subtitles='{subtitle_filter}':force_style="
        "'FontName=Arial,FontSize=16,Bold=1,PrimaryColour=&H0000FFFF&,OutlineColour=&H00000000&,BorderStyle=1,Outline=3,Shadow=0,MarginV=28,Alignment=2'"
    )
    _run_command(
        ffmpeg
        + [
            "-y",
            "-ss",
            f"{start_time:.2f}",
            "-i",
            str(source_video),
            "-t",
            f"{duration_seconds:.2f}",
            "-vf",
            vf,
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(output_video),
        ]
    )


def _generate_horizontal_cut(source_video: Path, output_video: Path, start_time: float, duration_seconds: float) -> None:
    ffmpeg = _ffmpeg_command()
    vf = "scale=1920:-2,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black"
    _run_command(
        ffmpeg
        + [
            "-y",
            "-ss",
            f"{start_time:.2f}",
            "-i",
            str(source_video),
            "-t",
            f"{duration_seconds:.2f}",
            "-vf",
            vf,
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(output_video),
        ]
    )


def _extract_audio_chunks(source_video: Path, job_dir: Path) -> list[Path]:
    ffmpeg = _ffmpeg_command()
    pattern = job_dir / "audio-%03d.mp3"
    _run_command(
        ffmpeg
        + [
            "-y",
            "-i",
            str(source_video),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "32k",
            "-f",
            "segment",
            "-segment_time",
            "900",
            "-reset_timestamps",
            "1",
            str(pattern),
        ]
    )
    chunks = sorted(job_dir.glob("audio-*.mp3"))
    if not chunks:
        raise ValueError("Nao consegui extrair o audio do video para transcricao.")
    return chunks


def _transcribe_audio_chunk_via_openai(chunk_path: Path) -> dict[str, Any]:
    api_key = _openai_api_key()
    with chunk_path.open("rb") as audio_file:
        files = [
            ("file", (chunk_path.name, audio_file, "audio/mpeg")),
            ("model", (None, "whisper-1")),
            ("response_format", (None, "verbose_json")),
            ("timestamp_granularities[]", (None, "segment")),
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
            all_segments.append({"start": start, "end": end, "text": text})
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


def build_youtube_cut_publish_draft(job_id: str, cut_id: int, *, privacy_status: str = "private") -> dict[str, Any]:
    manifest = load_youtube_cuts_manifest(job_id)
    cuts = manifest.get("cuts") or []
    selected = next((item for item in cuts if int(item.get("cut_id") or 0) == int(cut_id)), None)
    if not isinstance(selected, dict):
        raise ValueError("Corte nao encontrado dentro do job selecionado.")

    video = manifest.get("video") or {}
    mode = _normalize_cut_mode(str(selected.get("mode") or manifest.get("mode") or "short"))
    recent_offers, recent_lines = _build_recent_offers_block(limit=5)
    normalized_privacy = (privacy_status or "private").strip().lower()
    if normalized_privacy not in {"private", "unlisted", "public"}:
        normalized_privacy = "private"

    chapters: list[str] = []
    if mode == "long":
        chapters = _build_long_chapters(
            str(selected.get("caption_draft") or ""),
            float(selected.get("start") or 0),
            float(selected.get("duration_seconds") or 0),
        )
        description_lines = [
            str(selected.get("hook") or selected.get("title") or "Corte longo pronto para publicar.").strip(),
            "",
            f"Tema base: {video.get('title') or 'Video base'}",
            f"Video completo: {video.get('url') or ''}".strip(),
            "",
            "Capitulos:",
            *chapters,
            "",
            "Ofertas recentes do projeto:",
            *recent_lines,
            "",
            "#podcast #cortes #analise",
        ]
        title = str(selected.get("copy_title") or selected.get("title") or "Corte longo YouTube").strip()[:100]
    else:
        description_lines = [
            str(selected.get("hook") or selected.get("title") or "Corte pronto para publicar.").strip(),
            "",
            f"Trecho original: {video.get('title') or 'Video base'}",
            f"Video completo: {video.get('url') or ''}".strip(),
            "",
            "Ofertas recentes do projeto:",
            *recent_lines,
            "",
            "#shorts #podcast #cortes",
        ]
        title = str(selected.get("copy_title") or selected.get("title") or "Corte YouTube").strip()[:100]
    return {
        "job_id": job_id,
        "cut_id": int(cut_id),
        "mode": mode,
        "title": title,
        "title_variants": list(selected.get("title_variants") or []),
        "scorecard": dict(selected.get("scorecard") or {}),
        "chapters": chapters,
        "editorial_role": str(selected.get("editorial_role") or ""),
        "thumbnail_asset_url": str(selected.get("thumbnail_asset_url") or ""),
        "thumbnail_filename": str(selected.get("thumbnail_filename") or ""),
        "description": "\n".join(line for line in description_lines if line is not None).strip(),
        "privacy_status": normalized_privacy,
        "recent_offers": recent_offers,
        "source_video": {
            "video_id": video.get("video_id"),
            "title": video.get("title"),
            "url": video.get("url"),
        },
        "publish_label": "Publicar video" if mode == "long" else "Publicar Short",
    }


def process_youtube_video_for_cuts(
    raw_url: str,
    *,
    limit: int = 5,
    mode: str = "short",
    selection_strategy: str = "openai_heuristica",
) -> dict[str, Any]:
    phase_one = analyze_youtube_video_for_cuts(raw_url)
    video = phase_one["video"]
    normalized_mode = _normalize_cut_mode(mode)
    normalized_strategy = _normalize_short_selection_strategy(selection_strategy)
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    job_id = f"{video['video_id']}-{timestamp}"
    job_dir = youtube_cuts_runtime_dir() / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    source_video, subtitle_file, subtitle_error = _download_video_and_subtitles(video["url"], job_dir)
    transcript_source = "youtube_subtitles"
    transcript_warning = ""
    if subtitle_file is not None:
        transcript_segments = _parse_vtt_segments(subtitle_file)
        transcript_text = _transcript_text(transcript_segments)
    else:
        transcript_source = "openai_audio"
        transcript_warning = subtitle_error
        transcript_segments, transcript_text = _transcribe_audio_via_openai(source_video, job_dir)
    cut_candidates = _build_cut_candidates(transcript_segments, limit=limit, mode=normalized_mode)
    if normalized_mode == "short" and normalized_strategy in {"openai", "openai_heuristica"}:
        try:
            cut_candidates = _rerank_short_candidates_with_openai(
                video,
                cut_candidates,
                limit=limit,
                selection_strategy=normalized_strategy,
            )
        except Exception as exc:  # noqa: BLE001
            transcript_warning = (
                f"{transcript_warning} | " if transcript_warning else ""
            ) + f"Reranqueamento IA indisponivel, usando heuristica local: {str(exc)}"
            cut_candidates = cut_candidates[:limit]
    elif normalized_mode == "short":
        cut_candidates = cut_candidates[:limit]

    generated_items = []
    for index, item in enumerate(cut_candidates, start=1):
        video_filename = f"cut-{index:02d}.mp4"
        video_output = job_dir / video_filename
        if normalized_mode == "long":
            subtitle_path = None
            _generate_horizontal_cut(source_video, video_output, item["start"], item["duration_seconds"])
        else:
            subtitle_path = _write_cut_srt(job_dir, index, item["start"], item["end"], transcript_segments)
            _generate_vertical_cut(source_video, subtitle_path, video_output, item["start"], item["duration_seconds"])
        thumbnail_asset = _generate_long_thumbnail(job_dir, index, video, item) if normalized_mode == "long" else None
        generated_items.append(
            item
            | {
                "cut_id": index,
                "job_id": job_id,
                "mode": normalized_mode,
                "video_asset_url": f"/dashboard/api/youtube/cuts/assets/{job_id}/{video_filename}",
                "video_filename": video_filename,
                "download_url": f"/dashboard/api/youtube/cuts/assets/{job_id}/{video_filename}",
                "thumbnail_asset_url": (thumbnail_asset or {}).get("asset_url"),
                "thumbnail_filename": (thumbnail_asset or {}).get("filename"),
                "copy_title": item["title"],
                "copy_description": item["caption_draft"],
                "status": "generated",
                "subtitle_asset_url": f"/dashboard/api/youtube/cuts/assets/{job_id}/{subtitle_path.name}" if subtitle_path else None,
                "subtitle_filename": subtitle_path.name if subtitle_path else None,
            }
        )

    payload = {
        "ok": True,
        "phase": 2,
        "job_id": job_id,
        "mode": normalized_mode,
        "selection_strategy": normalized_strategy if normalized_mode == "short" else "long_default",
        "video": video | {"source_filename": source_video.name, "subtitle_filename": subtitle_file.name if subtitle_file else None},
        "transcript": {
            "language_hint": subtitle_file.suffix.lstrip(".") if subtitle_file else "openai-whisper-1",
            "segments_count": len(transcript_segments),
            "text": transcript_text,
            "source": transcript_source,
            "warning": transcript_warning,
        },
        "cuts": generated_items,
        "notes": [
            "Fase 2: video baixado, transcricao base gerada e cortes montados.",
            "Shorts saem em vertical com legenda queimada usando as legendas do YouTube ou o fallback por audio.",
            "Corte longo sai em horizontal e sem legenda queimada para publicacao como video normal.",
        ],
    }
    _write_job_manifest(job_dir, payload)
    return payload
