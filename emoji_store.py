"""
emoji_store.py
--------------
Manages custom emoji storage and live code patching.
"""

import json
import os

CONFIG_FILE = "emoji_config.json"

DEFAULT_EMOJIS = {
    1: "🚀", 2: "🔗", 3: "🎗️", 4: "⭐", 5: "✅",
    6: "❌", 7: "⚠️", 8: "📊", 9: "🔄", 10: "🛡️",
    11: "💻", 12: "📱", 13: "⚡", 14: "🎁", 15: "🔴",
    16: "🟢", 17: "📌", 18: "👑", 19: "🏆", 20: "🎯",
    21: "⏳", 22: "🌸", 23: "🔄", 24: "❌", 25: "🔔"
}

LABELS = {
    1: "Rocket / Start", 2: "Link", 3: "Ribbon / Account", 4: "Star / Config",
    5: "Success / Tick", 6: "Error / Wrong", 7: "Alert / Warning", 8: "Stats / Overview",
    9: "Loading Dots", 10: "Shield / Profile", 11: "PC Guide", 12: "Mobile Guide",
    13: "Lightning / Speed", 14: "Gift / Reward", 15: "Red Status", 16: "Green Dot",
    17: "Report / Stop", 18: "Crown / Owner", 19: "Trophy / Leaderboard", 20: "Target / Autoquest",
    21: "Progress / Board", 22: "Flowers", 23: "ETA Time", 24: "Error Detail", 25: "Holiday / Extra"
}

def _load() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {int(k): v for k, v in data.items()}
        except Exception:
            pass
    return DEFAULT_EMOJIS.copy()

def _save(data: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in data.items()}, f, indent=2)

def get(slot: int) -> str:
    emojis = _load()
    return emojis.get(slot, DEFAULT_EMOJIS.get(slot, "📌"))

def get_all() -> dict:
    emojis = DEFAULT_EMOJIS.copy()
    emojis.update(_load())
    return emojis

def set_emoji(slot: int, emoji: str) -> bool:
    if slot < 1 or slot > 25:
        return False
    emojis = _load()
    emojis[slot] = emoji
    _save(emojis)
    return True

def reset_emoji(slot: int) -> bool:
    emojis = _load()
    if slot in emojis:
        del emojis[slot]
        _save(emojis)
    return True

def reset_all() -> None:
    if os.path.exists(CONFIG_FILE):
        try:
            os.remove(CONFIG_FILE)
        except Exception:
            pass

def apply_to_code() -> bool:
    return True
