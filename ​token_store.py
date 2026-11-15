"""
token_store.py
--------------
Persistent storage for user Discord tokens in `user_tokens.json`.
"""

import json
import os

TOKEN_FILE = "user_tokens.json"


def _load() -> dict:
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save(data: dict) -> None:
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_token(user_id: int | str) -> str | None:
    data = _load()
    return data.get(str(user_id))


def set_token(user_id: int | str, token: str) -> None:
    data = _load()
    data[str(user_id)] = token.strip()
    _save(data)


def delete_token(user_id: int | str) -> bool:
    data = _load()
    uid = str(user_id)
    if uid in data:
        del data[uid]
        _save(data)
        return True
    return False


def has_token(user_id: int | str) -> bool:
    return get_token(user_id) is not None


def get_all_linked_user_ids() -> list[int]:
    data = _load()
    return [int(uid) for uid in data.keys()]
