import os
import sys
from pathlib import Path


def _bundled_path(filename: str) -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path.cwd())) / filename
    return Path(__file__).resolve().parent.parent / filename


DB_FILE = Path("vault.db")
BACKGROUND_FILE = _bundled_path("OH FUCK.png")
MUSIC_FILE = _bundled_path("music.mp3")
ICON_FILE = _bundled_path("app.ico")
APP_STATE_FILE = Path("app_state.json")
WALLPAPER_DIR = Path(f"{os.getenv('SystemDrive', 'C:')}\\VaultWallpapers")

PASSWORD_LENGTH = 18
HASH_ITERATIONS = 200_000
ENC_ITERATIONS = 120_000
SPECIALS = "!@#$%^&*()-_=+?"
DEFAULT_THEME = "Mr. Robot"
DEFAULT_VOLUME = 0.35
CLIPBOARD_CLEAR_DELAY_MS = 25_000
LOGIN_LOCKOUT_THRESHOLD = 5
LOGIN_LOCKOUT_SECONDS = 20
SUPPORTED_WALLPAPER_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif"}


def _parse_chat_ids(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_IDS = _parse_chat_ids(os.getenv("TELEGRAM_CHAT_IDS", ""))


THEMES = {
    "Mr. Robot": {
        "app_bg": "#050505",
        "panel_bg": "#101010",
        "panel_alt": "#161616",
        "title_fg": "#f2f2f2",
        "muted_fg": "#9a9a9a",
        "accent": "#b31217",
        "accent_active": "#d51f26",
        "field_bg": "#0c0c0c",
        "field_fg": "#e7e7e7",
        "list_bg": "#0f0f0f",
        "list_fg": "#d7d7d7",
        "border": "#2c2c2c",
    },
    "Matrix": {
        "app_bg": "#020403",
        "panel_bg": "#07110a",
        "panel_alt": "#0c170f",
        "title_fg": "#d9ffd9",
        "muted_fg": "#73b173",
        "accent": "#18b44d",
        "accent_active": "#23d35d",
        "field_bg": "#061009",
        "field_fg": "#d8ffd8",
        "list_bg": "#07110a",
        "list_fg": "#d8ffd8",
        "border": "#1d4b2d",
    },
    "Ice": {
        "app_bg": "#09131a",
        "panel_bg": "#102028",
        "panel_alt": "#16303b",
        "title_fg": "#eef9ff",
        "muted_fg": "#9dbdc9",
        "accent": "#4aa3ff",
        "accent_active": "#70b7ff",
        "field_bg": "#0d1a22",
        "field_fg": "#eef9ff",
        "list_bg": "#0f1d25",
        "list_fg": "#eef9ff",
        "border": "#315565",
    },
}
