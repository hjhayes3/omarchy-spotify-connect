"""Standard-library CLI for Spotify Connect device selection."""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import os
import secrets
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

from .core import apply_playback_device, merge_remembered_devices, parse_devices, resolve_device, token_expired

API = "https://api.spotify.com/v1"
ACCOUNTS = "https://accounts.spotify.com"
SCOPES = "user-read-playback-state user-modify-playback-state"
REDIRECT_URI = "http://127.0.0.1:43821/callback"
KEYRING_SERVICE = "omarchy-spotify-connect"


class AppError(RuntimeError):
    def __init__(self, message: str, kind: str = "error", retry_after: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.retry_after = retry_after


def config_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "omarchy-spotify-connect" / "config.json"


def remembered_path() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "omarchy-spotify-connect" / "devices.json"


def load_remembered() -> list[dict[str, str]]:
    path = remembered_path()
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AppError(f"Cannot read remembered devices from {path}: {exc}", "config") from exc
    return value if isinstance(value, list) else []


def save_remembered(devices: list[dict[str, str]]) -> None:
    path = remembered_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps(devices, indent=2) + "\n", encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def remember_device(device_id: str, name: str, device_type: str) -> None:
    if not device_id or not name:
        raise AppError("A device ID and name are required", "config")
    devices = [item for item in load_remembered() if item.get("id") != device_id]
    devices.append({"id": device_id, "name": name, "type": device_type or "speaker"})
    save_remembered(devices)


def forget_device(device_id: str) -> None:
    save_remembered([item for item in load_remembered() if item.get("id") != device_id])


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AppError(f"Cannot read {path}: {exc}", "config") from exc
    return value if isinstance(value, dict) else {}


def save_client_id(client_id: str) -> None:
    if not client_id or any(c.isspace() for c in client_id):
        raise AppError("Client ID must be a non-empty value without spaces", "config")
    path = config_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps({"client_id": client_id}, indent=2) + "\n", encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def client_id() -> str:
    value = os.environ.get("SPOTIFY_CLIENT_ID") or load_config().get("client_id")
    if not isinstance(value, str) or not value:
        raise AppError("Spotify Client ID is not configured; run: spotify-connect configure CLIENT_ID", "not_configured")
    return value


def require_keyring() -> str:
    executable = shutil.which("secret-tool")
    if not executable:
        raise AppError("secret-tool is required (provided by libsecret); tokens will not be stored in files", "keyring")
    return executable


def keyring_load() -> dict[str, Any] | None:
    proc = subprocess.run([require_keyring(), "lookup", "service", KEYRING_SERVICE, "account", "spotify"], capture_output=True, text=True, timeout=10, check=False)
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        token = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AppError("Stored Spotify credentials are invalid; run logout and authenticate again", "auth_expired") from exc
    return token if isinstance(token, dict) else None


def keyring_store(token: dict[str, Any]) -> None:
    payload = json.dumps(token, separators=(",", ":"))
    proc = subprocess.run([require_keyring(), "store", "--label", "Omarchy Spotify Connect", "service", KEYRING_SERVICE, "account", "spotify"], input=payload, text=True, capture_output=True, timeout=15, check=False)
    if proc.returncode != 0:
        raise AppError("Could not store Spotify credentials in Secret Service", "keyring")


def keyring_clear() -> None:
    subprocess.run([require_keyring(), "clear", "service", KEYRING_SERVICE, "account", "spotify"], capture_output=True, timeout=10, check=False)


def http_json(url: str, method: str = "GET", headers: dict[str, str] | None = None, body: dict[str, Any] | None = None) -> tuple[int, Any, dict[str, str]]:
    data = None if body is None else json.dumps(body).encode()
    request_headers = {"Accept": "application/json", **(headers or {})}
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None, dict(response.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = None
        message = ""
        if isinstance(payload, dict):
            error = payload.get("error")
            message = str(error.get("message", "")) if isinstance(error, dict) else str(error or "")
        if exc.code == 401:
            kind = "auth_expired"
        elif exc.code == 403:
            kind = "forbidden"
        elif exc.code == 429:
            kind = "rate_limited"
        else:
            kind = "api_error"
        retry = int(exc.headers.get("Retry-After", "0") or 0) or None
        raise AppError(message or f"Spotify API returned HTTP {exc.code}", kind, retry) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise AppError(f"Cannot reach Spotify: {getattr(exc, 'reason', exc)}", "network") from exc


def token_request(fields: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(f"{ACCOUNTS}/api/token", data=urllib.parse.urlencode(fields).encode(), headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            value = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise AppError("Spotify authentication failed; authenticate again", "auth_expired") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AppError(f"Cannot complete Spotify authentication: {exc}", "network") from exc
    value["expires_at"] = int(time.time()) + int(value.get("expires_in", 3600))
    return value


def access_token() -> str:
    token = keyring_load()
    if not token or not token.get("access_token"):
        raise AppError("Not authenticated; run: spotify-connect auth", "not_authenticated")
    if token_expired(token):
        refresh = token.get("refresh_token")
        if not refresh:
            raise AppError("Spotify authentication expired; authenticate again", "auth_expired")
        updated = token_request({"grant_type": "refresh_token", "refresh_token": str(refresh), "client_id": client_id()})
        if "refresh_token" not in updated:
            updated["refresh_token"] = refresh
        keyring_store(updated)
        token = updated
    return str(token["access_token"])


def spotify(path: str, method: str = "GET", body: dict[str, Any] | None = None) -> Any:
    _, payload, _ = http_json(f"{API}{path}", method, {"Authorization": f"Bearer {access_token()}"}, body)
    return payload


def fetch_devices(include_remembered: bool = True) -> list[Any]:
    devices = parse_devices(spotify("/me/player/devices"))
    playback = spotify("/me/player")
    devices = apply_playback_device(devices, playback)
    return merge_remembered_devices(devices, load_remembered()) if include_remembered else devices


def authenticate(no_browser: bool = False) -> dict[str, Any]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    params = {"client_id": client_id(), "response_type": "code", "redirect_uri": REDIRECT_URI, "scope": SCOPES, "state": state, "code_challenge_method": "S256", "code_challenge": challenge}
    url = f"{ACCOUNTS}/authorize?{urllib.parse.urlencode(params)}"
    result: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            result.update({key: values[0] for key, values in query.items() if values})
            body = b"<h1>Omarchy Spotify Connect</h1><p>Authentication received. You may close this tab.</p>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, _format: str, *_args: Any) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 43821), Handler)
    server.timeout = 180
    if no_browser:
        print(f"Open this URL to authorize Spotify:\n{url}", file=sys.stderr, flush=True)
    if not no_browser:
        webbrowser.open(url)
    server.handle_request()
    server.server_close()
    if result.get("state") != state:
        raise AppError("OAuth state did not match; authentication was cancelled", "auth_error")
    if result.get("error"):
        raise AppError(f"Spotify authorization denied: {result['error']}", "auth_error")
    code = result.get("code")
    if not code:
        raise AppError("No authorization response was received", "auth_error")
    token = token_request({"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI, "client_id": client_id(), "code_verifier": verifier})
    keyring_store(token)
    return {"authenticated": True}


def status_payload() -> dict[str, Any]:
    token = keyring_load()
    if not token:
        return {"authenticated": False, "configured": bool(load_config().get("client_id") or os.environ.get("SPOTIFY_CLIENT_ID")), "devices": [], "active_device": None}
    devices = fetch_devices()
    active = next((d.as_dict() for d in devices if d.is_active), None)
    return {"authenticated": True, "configured": True, "devices": [d.as_dict() for d in devices], "active_device": active}


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps({"ok": True, **payload}, separators=(",", ":")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spotify-connect", description="Select the current Spotify Connect playback device")
    sub = parser.add_subparsers(dest="command", required=True)
    configure = sub.add_parser("configure", help="save the Spotify application Client ID")
    configure.add_argument("client_id")
    auth = sub.add_parser("auth", help="authenticate with Spotify using PKCE")
    auth.add_argument("--no-browser", action="store_true")
    sub.add_parser("logout", help="remove tokens from Secret Service")
    sub.add_parser("status", help="show authentication, devices, and active device as JSON")
    sub.add_parser("devices", help="list available devices as JSON")
    transfer = sub.add_parser("transfer", help="transfer current playback")
    transfer.add_argument("selector")
    transfer.add_argument("--id", action="store_true", dest="by_id")
    remember = sub.add_parser("remember", help="cache a currently visible device ID")
    remember.add_argument("--id", required=True, dest="device_id")
    remember.add_argument("--name", required=True)
    remember.add_argument("--type", default="speaker", dest="device_type")
    forget = sub.add_parser("forget", help="remove a cached device ID")
    forget.add_argument("--id", required=True, dest="device_id")
    args = parser.parse_args(argv)
    try:
        if args.command == "configure":
            save_client_id(args.client_id); emit({"configured": True, "config_path": str(config_path())})
        elif args.command == "auth":
            emit(authenticate(args.no_browser))
        elif args.command == "logout":
            keyring_clear(); emit({"authenticated": False})
        elif args.command == "status":
            emit(status_payload())
        elif args.command == "devices":
            devices = fetch_devices(); emit({"devices": [d.as_dict() for d in devices]})
        elif args.command == "remember":
            remember_device(args.device_id, args.name, args.device_type)
            emit({"remembered": True, "device_id": args.device_id})
        elif args.command == "forget":
            forget_device(args.device_id)
            emit({"forgotten": True, "device_id": args.device_id})
        elif args.command == "transfer":
            device = resolve_device(fetch_devices(), args.selector, args.by_id)
            if not device.is_available:
                raise AppError(
                    f"{device.name} is remembered but currently unavailable; activate it in Spotify first, then refresh",
                    "device_unavailable",
                )
            if device.is_restricted:
                raise AppError(f"{device.name} is restricted and cannot accept Spotify Web API commands", "restricted")
            spotify("/me/player", "PUT", {"device_ids": [device.id]})
            emit({"transferred": True, "device": device.as_dict()})
        return 0
    except AppError as exc:
        print(json.dumps({"ok": False, "error": str(exc), "kind": exc.kind, "retry_after": exc.retry_after}, separators=(",", ":")))
        return 1
    except (ValueError, LookupError) as exc:
        print(json.dumps({"ok": False, "error": str(exc), "kind": "invalid_response"}, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
