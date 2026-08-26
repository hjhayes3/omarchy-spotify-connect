"""Pure Spotify response and selection logic."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Device:
    id: str
    name: str
    type: str
    is_active: bool
    is_restricted: bool
    is_available: bool = True
    is_remembered: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "is_active": self.is_active,
            "is_restricted": self.is_restricted,
            "is_available": self.is_available,
            "is_remembered": self.is_remembered,
        }


def parse_devices(payload: Any) -> list[Device]:
    if not isinstance(payload, dict) or not isinstance(payload.get("devices"), list):
        raise ValueError("Spotify returned an invalid devices response")
    devices: list[Device] = []
    for raw in payload["devices"]:
        if not isinstance(raw, dict):
            continue
        device_id = raw.get("id")
        name = raw.get("name")
        if not isinstance(device_id, str) or not device_id or not isinstance(name, str) or not name:
            continue
        devices.append(Device(
            id=device_id,
            name=name,
            type=str(raw.get("type") or "unknown"),
            is_active=raw.get("is_active") is True,
            is_restricted=raw.get("is_restricted") is True,
        ))
    return devices


def apply_playback_device(devices: list[Device], playback: Any) -> list[Device]:
    raw = playback.get("device") if isinstance(playback, dict) else None
    active_id = str(raw.get("id") or "") if isinstance(raw, dict) else ""
    if not active_id:
        return devices
    updated = [Device(d.id, d.name, d.type, d.id == active_id, d.is_restricted, d.is_available, d.is_remembered) for d in devices]
    if any(d.id == active_id for d in updated):
        return updated
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        return updated
    updated.append(Device(
        active_id,
        name,
        str(raw.get("type") or "unknown"),
        True,
        raw.get("is_restricted") is True,
    ))
    return updated


def merge_remembered_devices(devices: list[Device], remembered: Any) -> list[Device]:
    """Add cached devices that Spotify did not return, preserving live data."""
    merged = list(devices)
    indexes = {device.id: index for index, device in enumerate(merged)}
    if not isinstance(remembered, list):
        return merged
    for raw in remembered:
        if not isinstance(raw, dict):
            continue
        device_id = raw.get("id")
        name = raw.get("name")
        if not isinstance(device_id, str) or not device_id or not isinstance(name, str) or not name:
            continue
        if device_id in indexes:
            index = indexes[device_id]
            live = merged[index]
            merged[index] = Device(live.id, live.name, live.type, live.is_active, live.is_restricted, True, True)
            continue
        indexes[device_id] = len(merged)
        merged.append(Device(device_id, name, str(raw.get("type") or "speaker"), False, False, False, True))
    return merged


def resolve_device(devices: list[Device], selector: str, by_id: bool = False) -> Device:
    matches = [d for d in devices if d.id == selector] if by_id else [d for d in devices if d.name.casefold() == selector.casefold()]
    if not matches:
        raise LookupError(f"Spotify Connect device not found: {selector}")
    if len(matches) > 1:
        details = ", ".join(f"{d.name} ({d.type}, id …{d.id[-6:]})" for d in matches)
        raise LookupError(f"Device name is ambiguous; use --id. Matches: {details}")
    return matches[0]


def token_expired(token: dict[str, Any], now: float | None = None, leeway: int = 60) -> bool:
    try:
        expires_at = float(token["expires_at"])
    except (KeyError, TypeError, ValueError):
        return True
    return expires_at <= (time.time() if now is None else now) + leeway
