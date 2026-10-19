#!/usr/bin/env python3
"""Read-only Xtream-compatible API facade for an existing M3U playlist.

This service indexes a playlist and exposes basic Xtream-style catalog endpoints.
It does not host, transcode, or proxy video. Stream requests redirect to the source URL.
Configure XTREAM_USERNAME and XTREAM_PASSWORD as environment variables.
"""
from __future__ import annotations

import hmac
import os
import re
import threading
import time
from typing import Any
from urllib.parse import quote

import requests
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, RedirectResponse, Response, StreamingResponse

APP_TITLE = "Personal Xtream-compatible API (read-only)"
PLAYLIST_URL = os.getenv(
    "PLAYLIST_URL",
    "https://raw.githubusercontent.com/jorgebcn2023/Iptv-argentina-espana/feature/titan-iptv-v2/playlist.m3u",
)
USERNAME = os.getenv("XTREAM_USERNAME", "")
PASSWORD = os.getenv("XTREAM_PASSWORD", "")
CACHE_SECONDS = max(60, int(os.getenv("PLAYLIST_CACHE_SECONDS", "300")))
HTTP_TIMEOUT = max(3, int(os.getenv("PLAYLIST_HTTP_TIMEOUT", "20")))
STREAM_PROXY_HEADERS = os.getenv("STREAM_PROXY_HEADERS", "auto").strip().lower()  # auto, always, never

app = FastAPI(title=APP_TITLE, version="0.1.0")
_lock = threading.Lock()
_cache: dict[str, Any] = {"loaded_at": 0.0, "channels": [], "last_error": None}


def _attr(line: str, key: str) -> str:
    match = re.search(r'(?:^|\s)' + re.escape(key) + r'="([^"]*)"', line)
    return match.group(1).strip() if match else ""


def _display_name(extinf: str) -> str:
    """Return the text after the last comma outside quoted attributes."""
    quoted = False
    separator = -1
    for index, char in enumerate(extinf):
        if char == '"':
            quoted = not quoted
        elif char == "," and not quoted:
            separator = index
    return extinf[separator + 1 :].strip() if separator >= 0 else _attr(extinf, "tvg-name")


def parse_m3u(text: str) -> list[dict[str, Any]]:
    """Parse entries conservatively while retaining the original EXTINF line and directives."""

    channels: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    pending_directives: list[str] = []

    for raw in text.lstrip("\ufeff").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTINF:"):
            if current is not None:
                # An incomplete entry is not advertised as playable.
                pass
            display_name = _display_name(line)
            group = _attr(line, "group-title") or "Sin categoría"
            current = {
                "extinf": line,
                "name": display_name or _attr(line, "tvg-name") or f"Canal {len(channels) + 1}",
                "tvg_id": _attr(line, "tvg-id"),
                "logo": _attr(line, "tvg-logo"),
                "group": group,
                "directives": [],
                "url": "",
            }
            pending_directives = []
            continue
        if line.startswith("#"):
            if current is not None and (
                line.startswith((
                    "#EXTVLCOPT:", "#KODIPROP:", "#EXTHTTP:", "#EXTGRP:",
                    "#EXTBG:", "#EXTIMG:", "#EXTALB:", "#EXTART:",
                    "#EXTGENRE:", "#EXTURL:",
                ))
            ):
                current["directives"].append(line)
            continue
        if line.startswith(("http://", "https://")) and current is not None:
            current["url"] = line
            current["id"] = str(len(channels) + 1)
            channels.append(current)
            current = None
            pending_directives = []
    return channels


def get_channels(force: bool = False) -> list[dict[str, Any]]:
    now = time.time()
    if not force and _cache["channels"] and now - _cache["loaded_at"] < CACHE_SECONDS:
        return _cache["channels"]
    with _lock:
        now = time.time()
        if not force and _cache["channels"] and now - _cache["loaded_at"] < CACHE_SECONDS:
            return _cache["channels"]
        try:
            response = requests.get(
                PLAYLIST_URL,
                timeout=HTTP_TIMEOUT,
                headers={"User-Agent": "PersonalXtreamAPI/0.1"},
            )
            response.raise_for_status()
            channels = parse_m3u(response.text)
            if not channels:
                raise ValueError("La playlist se descargó, pero no contiene entradas M3U reconocibles.")
            _cache.update(loaded_at=time.time(), channels=channels, last_error=None)
            return channels
        except Exception as exc:
            _cache["last_error"] = str(exc)
            if _cache["channels"]:
                return _cache["channels"]
            raise HTTPException(status_code=503, detail="No se pudo cargar la playlist configurada.") from exc


def check_auth(username: str | None, password: str | None) -> None:
    if not USERNAME or not PASSWORD:
        raise HTTPException(status_code=503, detail="Configura XTREAM_USERNAME y XTREAM_PASSWORD en el entorno.")
    if not (
        isinstance(username, str)
        and isinstance(password, str)
        and hmac.compare_digest(username, USERNAME)
        and hmac.compare_digest(password, PASSWORD)
    ):
        raise HTTPException(status_code=401, detail="Credenciales incorrectas.")


def categories(channels: list[dict[str, Any]]) -> list[dict[str, str]]:
    groups: list[str] = []
    for channel in channels:
        group = channel["group"]
        if group not in groups:
            groups.append(group)
    return [{"category_id": str(i + 1), "category_name": name, "parent_id": 0} for i, name in enumerate(groups)]


def category_id_map(channels: list[dict[str, Any]]) -> dict[str, str]:
    return {item["category_name"]: item["category_id"] for item in categories(channels)}


def stream_record(channel: dict[str, Any], groups: dict[str, str], request: Request) -> dict[str, Any]:
    base = str(request.base_url).rstrip("/")
    stream_id = channel["id"]
    return {
        "num": int(stream_id),
        "name": channel["name"],
        "stream_type": "live",
        "stream_id": int(stream_id),
        "stream_icon": channel["logo"],
        "epg_channel_id": channel["tvg_id"],
        "added": "0",
        "is_adult": 0,
        "category_id": groups.get(channel["group"], "0"),
        "category_ids": [int(groups[channel["group"]])] if channel["group"] in groups else [],
        "custom_sid": "",
        "tv_archive": 0,
        "direct_source": channel["url"],
        "container_extension": "ts",
        "stream_url": f"{base}/live/{quote(USERNAME, safe='')}/{quote(PASSWORD, safe='')}/{stream_id}.ts",
    }


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "service": APP_TITLE,
        "status": "ok",
        "read_only": True,
        "catalog_endpoint": "/player_api.php",
        "playlist_endpoint": "/get.php",
        "note": "No video proxy/transcoding. Stream endpoint redirects to original source.",
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "catalog_loaded": bool(_cache["channels"]),
        "channel_count": len(_cache["channels"]),
        "cache_age_seconds": int(time.time() - _cache["loaded_at"]) if _cache["loaded_at"] else None,
        "last_refresh_error": _cache["last_error"],
    }


@app.get("/player_api.php")
def player_api(
    request: Request,
    username: str | None = Query(default=None),
    password: str | None = Query(default=None),
    action: str | None = Query(default=None),
    category_id: str | None = Query(default=None),
) -> Any:
    check_auth(username, password)
    channels = get_channels()
    groups = category_id_map(channels)

    if action is None:
        return {
            "user_info": {
                "username": USERNAME,
                "password": PASSWORD,
                "message": "Personal read-only M3U catalog",
                "auth": 1,
                "status": "Active",
                "exp_date": None,
                "is_trial": "0",
                "active_cons": "0",
                "created_at": "0",
                "max_connections": "1",
                "allowed_output_formats": ["m3u8", "ts"],
            },
            "server_info": {
                "url": request.url.hostname or "",
                "port": str(request.url.port or (443 if request.url.scheme == "https" else 80)),
                "https_port": str(request.url.port or 443),
                "server_protocol": request.url.scheme,
                "rtmp_port": "0",
                "timezone": "UTC",
                "timestamp_now": int(time.time()),
                "time_now": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
            },
        }
    if action == "get_live_categories":
        return categories(channels)
    if action == "get_live_streams":
        items = [c for c in channels if not category_id or groups.get(c["group"]) == category_id]
        return [stream_record(c, groups, request) for c in items]
    if action in {"get_vod_categories", "get_vod_streams", "get_series_categories", "get_series"}:
        # This source is live-only; advertise empty catalogs rather than fail on apps
        # that probe VOD/series actions during login.
        return []
    if action in {"get_short_epg", "get_simple_data_table", "get_vod_info", "get_series_info"}:
        return {"epg_listings": []} if action == "get_short_epg" else {}
    raise HTTPException(status_code=400, detail=f"Acción no implementada: {action}")


@app.get("/get.php", response_class=PlainTextResponse)
def get_playlist(
    username: str | None = Query(default=None),
    password: str | None = Query(default=None),
    type: str = Query(default="m3u_plus"),
    output: str = Query(default="ts"),
) -> str:
    check_auth(username, password)
    channels = get_channels()
    lines = ["#EXTM3U"]
    for channel in channels:
        # Preserve supported VLC/Kodi/HTTP directives in this M3U export.
        # Retain the source EXTINF line verbatim to preserve tvg-country, tvg-chno,
        # tvg-id, tvg-logo, custom attributes, and the original display name.
        lines.append(channel["extinf"])
        lines.extend(channel["directives"])
        lines.append(channel["url"])
    return "\n".join(lines) + "\n"


def _source_request_headers(channel: dict[str, Any], request: Request) -> dict[str, str]:
    """Translate common M3U VLC header directives for sources that require them."""
    headers: dict[str, str] = {"User-Agent": "VLC/3.0.20 LibVLC/3.0.20"}
    for directive in channel.get("directives", []):
        if directive.startswith("#EXTVLCOPT:http-user-agent="):
            headers["User-Agent"] = directive.split("=", 1)[1].strip()
        elif directive.startswith("#EXTVLCOPT:http-referrer="):
            headers["Referer"] = directive.split("=", 1)[1].strip()
        elif directive.startswith("#EXTVLCOPT:http-referer="):
            headers["Referer"] = directive.split("=", 1)[1].strip()
        elif directive.startswith("#EXTVLCOPT:http-origin="):
            headers["Origin"] = directive.split("=", 1)[1].strip()
        elif directive.startswith("#EXTHTTP:"):
            # Common M3U convention: JSON object containing request headers.
            import json
            try:
                parsed = json.loads(directive.split(":", 1)[1])
                if isinstance(parsed, dict):
                    headers.update({str(k): str(v) for k, v in parsed.items()})
            except (ValueError, TypeError):
                pass
    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header
    return headers


@app.get("/live/{username}/{password}/{stream_id}.ts")
def live_redirect(username: str, password: str, stream_id: str, request: Request) -> Response:
    check_auth(username, password)
    if not stream_id.isdigit():
        raise HTTPException(status_code=404, detail="Canal no encontrado.")
    channels = get_channels()
    index = int(stream_id) - 1
    if index < 0 or index >= len(channels) or channels[index]["id"] != stream_id:
        raise HTTPException(status_code=404, detail="Canal no encontrado.")
    channel = channels[index]
    has_headers = any(
        d.startswith(("#EXTVLCOPT:http-user-agent=", "#EXTVLCOPT:http-referrer=",
                      "#EXTVLCOPT:http-referer=", "#EXTVLCOPT:http-origin=", "#EXTHTTP:"))
        for d in channel.get("directives", [])
    )
    # Redirect is fastest and avoids routing video bandwidth through Render.
    # Only proxy when source-specific headers must be attached; opt-in override
    # STREAM_PROXY_HEADERS=always|never is available for diagnostics.
    should_proxy = STREAM_PROXY_HEADERS == "always" or (
        STREAM_PROXY_HEADERS == "auto" and has_headers
    )
    if STREAM_PROXY_HEADERS == "never" or not should_proxy:
        return RedirectResponse(url=channel["url"], status_code=307)

    try:
        upstream = requests.get(
            channel["url"], headers=_source_request_headers(channel, request),
            stream=True, allow_redirects=True, timeout=(8, 25),
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail="No se pudo conectar con la fuente del canal.") from exc

    if upstream.status_code >= 400:
        status = upstream.status_code
        upstream.close()
        raise HTTPException(status_code=502, detail=f"La fuente del canal respondió HTTP {status}.")
    response_headers: dict[str, str] = {}
    for key in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges", "Cache-Control"):
        value = upstream.headers.get(key)
        if value:
            response_headers[key] = value

    def body():
        try:
            for chunk in upstream.iter_content(chunk_size=64 * 1024):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    return StreamingResponse(
        body(), status_code=upstream.status_code,
        media_type=upstream.headers.get("Content-Type", "application/octet-stream"),
        headers=response_headers,
    )
