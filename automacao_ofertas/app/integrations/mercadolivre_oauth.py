from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import httpx
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

MELI_AUTH_URL = "https://auth.mercadolivre.com.br/authorization"
MELI_TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
MELI_API_URL = "https://api.mercadolibre.com"


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Variavel obrigatoria ausente: {name}")
    return value


def build_auth_url() -> dict[str, str]:
    app_id = _required_env("MELI_APP_ID")
    redirect_uri = _required_env("MELI_REDIRECT_URI")
    state = os.getenv("MELI_STATE", "").strip() or secrets.token_hex(16)

    redirect_encoded = quote_plus(redirect_uri)
    url = (
        f"{MELI_AUTH_URL}?response_type=code"
        f"&client_id={app_id}"
        f"&redirect_uri={redirect_encoded}"
        f"&state={state}"
    )
    return {"auth_url": url, "state": state}


def exchange_code(code: str) -> dict[str, Any]:
    app_id = _required_env("MELI_APP_ID")
    app_secret = _required_env("MELI_APP_SECRET")
    redirect_uri = _required_env("MELI_REDIRECT_URI")

    payload = {
        "grant_type": "authorization_code",
        "client_id": app_id,
        "client_secret": app_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    }

    with httpx.Client(timeout=20) as client:
        try:
            resp = client.post(MELI_TOKEN_URL, data=payload)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            detail = e.response.text if e.response is not None else str(e)
            raise ValueError(f"Erro OAuth Mercado Livre (exchange): {detail}") from e


def refresh_token(refresh_token_value: str) -> dict[str, Any]:
    app_id = _required_env("MELI_APP_ID")
    app_secret = _required_env("MELI_APP_SECRET")

    payload = {
        "grant_type": "refresh_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "refresh_token": refresh_token_value,
    }

    with httpx.Client(timeout=20) as client:
        try:
            resp = client.post(MELI_TOKEN_URL, data=payload)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            detail = e.response.text if e.response is not None else str(e)
            raise ValueError(f"Erro OAuth Mercado Livre (refresh): {detail}") from e


def get_user_id(access_token: str) -> str:
    with httpx.Client(timeout=20) as client:
        resp = client.get(
            f"{MELI_API_URL}/users/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        data = resp.json()
    return str(data.get("id"))
