"""
admin_store.py
--------------
Persistent storage for bot owners, authorized users, banned users,
and channel configurations in `bot_config.json`.
"""

import json
import os

CONFIG_FILE = "bot_config.json"


def _load() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "owners": [],
        "authorized_users": [],
        "banned_users": [],
        "quest_channel_id": None,
    }


def _save(data: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def is_owner(user_id: int | str, app_owner_id: int | None = None, guild_owner_id: int | None = None) -> bool:
    uid = int(user_id)
    if app_owner_id and uid == app_owner_id:
        return True
    if guild_owner_id and uid == guild_owner_id:
        return True
    data = _load()
    owners = [int(x) for x in data.get("owners", [])]
    return uid in owners


def add_owner(user_id: int | str) -> bool:
    data = _load()
    uid = int(user_id)
    owners = [int(x) for x in data.get("owners", [])]
    if uid not in owners:
        owners.append(uid)
        data["owners"] = owners
        _save(data)
        return True
    return False


def remove_owner(user_id: int | str) -> bool:
    data = _load()
    uid = int(user_id)
    owners = [int(x) for x in data.get("owners", [])]
    if uid in owners:
        owners.remove(uid)
        data["owners"] = owners
        _save(data)
        return True
    return False


def is_banned(user_id: int | str) -> bool:
    data = _load()
    banned = [int(x) for x in data.get("banned_users", [])]
    return int(user_id) in banned


def ban_user(user_id: int | str) -> bool:
    data = _load()
    uid = int(user_id)
    banned = [int(x) for x in data.get("banned_users", [])]
    if uid not in banned:
        banned.append(uid)
        data["banned_users"] = banned
        _save(data)
        return True
    return False


def unban_user(user_id: int | str) -> bool:
    data = _load()
    uid = int(user_id)
    banned = [int(x) for x in data.get("banned_users", [])]
    if uid in banned:
        banned.remove(uid)
        data["banned_users"] = banned
        _save(data)
        return True
    return False


def is_authorized(user_id: int | str) -> bool:
    data = _load()
    auths = [int(x) for x in data.get("authorized_users", [])]
    return int(user_id) in auths


def authorize_user(user_id: int | str) -> bool:
    data = _load()
    uid = int(user_id)
    auths = [int(x) for x in data.get("authorized_users", [])]
    if uid not in auths:
        auths.append(uid)
        data["authorized_users"] = auths
        _save(data)
        return True
    return False


def deauthorize_user(user_id: int | str) -> bool:
    data = _load()
    uid = int(user_id)
    auths = [int(x) for x in data.get("authorized_users", [])]
    if uid in auths:
        auths.remove(uid)
        data["authorized_users"] = auths
        _save(data)
        return True
    return False


def set_quest_channel(channel_id: int | str | None) -> None:
    data = _load()
    data["quest_channel_id"] = int(channel_id) if channel_id is not None else None
    _save(data)


def get_quest_channel() -> int | None:
    data = _load()
    return data.get("quest_channel_id")
