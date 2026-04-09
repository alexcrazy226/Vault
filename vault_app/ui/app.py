import io
import logging
import random
import string
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from vault_app.auth import AuthService, UserSession
from vault_app.config import (
    APP_STATE_FILE,
    BACKGROUND_FILE,
    CLIPBOARD_CLEAR_DELAY_MS,
    DB_FILE,
    DEFAULT_THEME,
    DEFAULT_VOLUME,
    ICON_FILE,
    MUSIC_FILE,
    PASSWORD_LENGTH,
    SPECIALS,
    SUPPORTED_WALLPAPER_SUFFIXES,
    THEMES,
    WALLPAPER_DIR,
)
from vault_app.db import Database
from vault_app.notifier import TelegramNotifier
from vault_app.preferences import AppPreferences
from vault_app.vault import VaultService

try:
    from PIL import Image, ImageTk, UnidentifiedImageError
except ImportError:
    Image = None
    ImageTk = None
    UnidentifiedImageError = OSError

try:
    import pygame
except ImportError:
    pygame = None


logger = logging.getLogger(__name__)


def generate_password(length: int = PASSWORD_LENGTH) -> str:
    alphabet = string.ascii_letters + string.digits + SPECIALS
    while True:
        password = "".join(random.choice(alphabet) for _ in range(length))
        if (
            any(char.islower() for char in password)
            and any(char.isupper() for char in password)
            and any(char.isdigit() for char in password)
            and any(char in SPECIALS for char in password)
        ):
            return password


class PasswordManagerApp:
    def __init__(self, root: tk.Tk) -> None:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
        self.root = root
        self.root.title("Vault")
        self.root.geometry("1120x720")
        self.root.minsize(760, 540)
        self.root.configure(bg="#050505")
        self._apply_window_icon()

        self.database = Database(DB_FILE)
        self.notifier = TelegramNotifier()
        self.auth_service = AuthService(self.database, self.notifier)
        self.vault_service = VaultService(self.database)
        self.preferences = AppPreferences(APP_STATE_FILE)
        self.app_state = self.preferences.load()

        self.current_session: UserSession | None = None
        self.current_theme_name = DEFAULT_THEME
        self.music_volume = DEFAULT_VOLUME
        self.current_background_choice = ""
        self.entries_cache = []
        self.filtered_entries = []
        self.background_source = None
        self.background_image = None
        self.background_item = None
        self.current_screen = "auth"
        self.canvas_chrome = []
        self.pending_avatar_bytes = None
        self.auth_avatar_preview = None
        self.profile_avatar_image = None
        self.settings_avatar_bytes = None
        self.settings_avatar_preview = None
        self.overlay_item = None
        self.auth_panel_item = None
        self.vault_header_item = None
        self.vault_left_item = None
        self.vault_right_item = None
        self.music_ready = False
        self.clipboard_clear_job = None
        self.last_copied_password = ""

        self.auth_status_var = tk.StringVar(value="Create an account or sign in.")
        self.vault_status_var = tk.StringVar(value="Sign in to open your vault.")
        self.search_var = tk.StringVar()
        self.show_password_var = tk.BooleanVar(value=False)
        self.remember_user_var = tk.BooleanVar(value=bool(self.app_state.get("remember_user")))

        self._ensure_wallpaper_dir()
        self._build_style()
        self._build_ui()
        self._start_background_music()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.show_auth_screen()

    def _build_style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        self._apply_theme(DEFAULT_THEME)

    def _apply_window_icon(self) -> None:
        if not ICON_FILE.exists():
            return

        try:
            self.root.iconbitmap(default=str(ICON_FILE))
        except tk.TclError as exc:
            logger.warning("Could not apply window icon: %s", exc)

    def _apply_theme(self, theme_name: str) -> None:
        self.current_theme_name = theme_name if theme_name in THEMES else DEFAULT_THEME
        theme = THEMES[self.current_theme_name]
        style = ttk.Style()

        style.configure("App.TFrame", background=theme["app_bg"])
        style.configure("Glass.TFrame", background=theme["panel_bg"], borderwidth=1, relief="solid")
        style.configure("GlassInner.TFrame", background=theme["panel_bg"])
        style.configure("Title.TLabel", background=theme["app_bg"], foreground=theme["title_fg"], font=("Consolas", 24, "bold"))
        style.configure("Sub.TLabel", background=theme["app_bg"], foreground=theme["muted_fg"], font=("Consolas", 10))
        style.configure("CardTitle.TLabel", background=theme["panel_bg"], foreground=theme["accent"], font=("Consolas", 12, "bold"))
        style.configure("Field.TLabel", background=theme["panel_bg"], foreground=theme["muted_fg"], font=("Consolas", 10, "bold"))
        style.configure("Status.TLabel", background=theme["app_bg"], foreground=theme["muted_fg"], font=("Consolas", 10))
        style.configure(
            "Primary.TButton",
            font=("Consolas", 10, "bold"),
            padding=(12, 8),
            background=theme["accent"],
            foreground="#f5f5f5",
            borderwidth=0,
        )
        style.map("Primary.TButton", background=[("active", theme["accent_active"])], foreground=[("active", "#ffffff")])
        style.configure(
            "Secondary.TButton",
            font=("Consolas", 10),
            padding=(12, 8),
            background=theme["panel_alt"],
            foreground=theme["title_fg"],
            borderwidth=0,
        )
        style.map("Secondary.TButton", background=[("active", theme["border"])], foreground=[("active", "#ffffff")])
        style.configure(
            "App.TEntry",
            padding=8,
            fieldbackground=theme["field_bg"],
            foreground=theme["field_fg"],
            insertcolor=theme["accent"],
            borderwidth=0,
        )
        style.configure("Robot.TCheckbutton", background=theme["panel_bg"], foreground=theme["title_fg"], font=("Consolas", 10))
        style.map("Robot.TCheckbutton", foreground=[("active", "#ffffff")], background=[("active", theme["panel_bg"])])

        self.root.configure(bg=theme["app_bg"])
        if hasattr(self, "canvas"):
            self.canvas.configure(bg=theme["app_bg"])
        if hasattr(self, "auth_avatar_label"):
            self.auth_avatar_label.configure(bg=theme["panel_bg"])
        if hasattr(self, "profile_avatar_label"):
            self.profile_avatar_label.configure(bg=theme["app_bg"])
        if hasattr(self, "entries_listbox"):
            self.entries_listbox.configure(
                bg=theme["list_bg"],
                fg=theme["list_fg"],
                selectbackground=theme["accent"],
                selectforeground="#ffffff",
            )
        if hasattr(self, "settings_window") and self.settings_window.winfo_exists():
            self.settings_window.configure(bg=theme["app_bg"])
        if hasattr(self, "canvas"):
            self._draw_canvas_chrome(self.canvas.winfo_width(), self.canvas.winfo_height())

    def _build_ui(self) -> None:
        self.canvas = tk.Canvas(self.root, highlightthickness=0, bd=0, bg="#050505")
        self.canvas.pack(fill="both", expand=True)

        self._load_background_image()

        self.auth_frame = ttk.Frame(self.canvas, style="App.TFrame", padding=22)
        self.vault_frame = ttk.Frame(self.canvas, style="App.TFrame", padding=22)

        self.auth_window = self.canvas.create_window(0, 0, anchor="nw", window=self.auth_frame)
        self.vault_window = self.canvas.create_window(0, 0, anchor="nw", window=self.vault_frame)
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        self._build_auth_frame()
        self._build_vault_frame()

    def _start_background_music(self) -> None:
        if pygame is None or not MUSIC_FILE.exists():
            return

        try:
            pygame.mixer.init()
            pygame.mixer.music.load(str(MUSIC_FILE))
            pygame.mixer.music.set_volume(self.music_volume)
            pygame.mixer.music.play(-1)
            self.music_ready = True
        except pygame.error as exc:
            logger.warning("Background music could not be started: %s", exc)
            self.music_ready = False

    def set_music_volume(self, value) -> None:
        self.music_volume = max(0.0, min(1.0, float(value)))
        if self.music_ready and pygame is not None:
            try:
                pygame.mixer.music.set_volume(self.music_volume)
            except pygame.error as exc:
                logger.warning("Could not change music volume: %s", exc)

    def _ensure_wallpaper_dir(self) -> None:
        try:
            WALLPAPER_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("Could not create wallpaper directory %s: %s", WALLPAPER_DIR, exc)

    def _get_wallpaper_options(self) -> list[str]:
        if not WALLPAPER_DIR.exists():
            return ["Default"]

        wallpaper_names = [
            path.name
            for path in sorted(WALLPAPER_DIR.iterdir())
            if path.is_file() and path.suffix.lower() in SUPPORTED_WALLPAPER_SUFFIXES
        ]
        return ["Default", *wallpaper_names]

    def _resolve_background_path(self, background_choice: str) -> Path:
        if background_choice:
            candidate = WALLPAPER_DIR / background_choice
            if candidate.exists():
                return candidate
        return BACKGROUND_FILE

    def _set_background_choice(self, background_choice: str) -> None:
        self.current_background_choice = background_choice
        self._load_background_image()
        if self.background_item is not None:
            self.canvas.coords(self.background_item, self.canvas.winfo_width() // 2, self.canvas.winfo_height() // 2)

    def _load_background_image(self) -> None:
        background_path = self._resolve_background_path(self.current_background_choice)
        if not background_path.exists():
            return

        try:
            if Image is not None:
                self.background_source = Image.open(background_path)
            else:
                self.background_source = tk.PhotoImage(file=str(background_path))
        except (tk.TclError, OSError, UnidentifiedImageError) as exc:
            logger.warning("Could not load background image: %s", exc)
            return

        self._resize_background(900, 560)

    def _resize_background(self, width: int, height: int) -> None:
        if self.background_source is None or width <= 0 or height <= 0:
            return

        if Image is not None and ImageTk is not None and not isinstance(self.background_source, tk.PhotoImage):
            resized = self.background_source.resize((width, height), Image.Resampling.LANCZOS)
            self.background_image = ImageTk.PhotoImage(resized)
        else:
            source = self.background_source
            image_width = max(1, source.width())
            image_height = max(1, source.height())
            scale_x = width / image_width
            scale_y = height / image_height
            scale = min(scale_x, scale_y)

            if scale >= 1:
                multiplier = max(1, int(scale))
                self.background_image = source.zoom(multiplier, multiplier)
            else:
                divisor = max(1, int(1 / scale))
                self.background_image = source.subsample(divisor, divisor)

        if self.background_item is None:
            self.background_item = self.canvas.create_image(0, 0, image=self.background_image, anchor="center")
        else:
            self.canvas.itemconfigure(self.background_item, image=self.background_image)

    def _create_rounded_rect(self, x1, y1, x2, y2, radius, **kwargs):
        points = [
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]
        return self.canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)

    def _draw_canvas_chrome(self, width: int, height: int) -> None:
        theme = THEMES[self.current_theme_name]
        for item in self.canvas_chrome:
            self.canvas.delete(item)
        self.canvas_chrome.clear()

        self.overlay_item = self.canvas.create_rectangle(0, 0, width, height, fill=theme["app_bg"], stipple="gray50", outline="")
        self.canvas_chrome.append(self.overlay_item)

        if self.current_screen == "auth":
            panel_width = min(max(360, width - 120), 460)
            panel_height = min(max(390, height - 140), 470)
            x1 = (width - panel_width) / 2
            y1 = max(40, (height - panel_height) / 2)
            x2 = x1 + panel_width
            y2 = y1 + panel_height

            self.auth_panel_item = self._create_rounded_rect(
                x1, y1, x2, y2, 22, fill=theme["panel_bg"], stipple="gray50", outline=theme["border"], width=2
            )
            accent = self.canvas.create_rectangle(x1, y1, x2, y1 + 6, fill=theme["border"], outline="")
            self.canvas_chrome.extend([self.auth_panel_item, accent])
            self.canvas.coords(self.auth_window, x1 + 24, y1 + 22)
            self.canvas.itemconfigure(self.auth_window, width=panel_width - 48)
        else:
            outer_left = 24
            outer_top = 18
            outer_right = width - 24
            outer_bottom = height - 22
            is_stacked = width < 980

            self.vault_header_item = self._create_rounded_rect(
                outer_left, outer_top, outer_right, outer_top + 76, 18, fill=theme["panel_bg"], stipple="gray50", outline=theme["accent"], width=2
            )
            self.canvas_chrome.append(self.vault_header_item)

            top = outer_top + 92
            gap = 18
            if is_stacked:
                left_bottom = top + max(250, int((outer_bottom - top - gap) * 0.44))
                self.vault_left_item = self._create_rounded_rect(
                    outer_left, top, outer_right, left_bottom, 18, fill=theme["panel_bg"], stipple="gray50", outline=theme["border"], width=2
                )
                self.vault_right_item = self._create_rounded_rect(
                    outer_left, left_bottom + gap, outer_right, outer_bottom, 18, fill=theme["panel_bg"], stipple="gray50", outline=theme["border"], width=2
                )
            else:
                split = outer_left + int((outer_right - outer_left) * 0.46)
                self.vault_left_item = self._create_rounded_rect(
                    outer_left, top, split, outer_bottom, 18, fill=theme["panel_bg"], stipple="gray50", outline=theme["border"], width=2
                )
                self.vault_right_item = self._create_rounded_rect(
                    split + gap, top, outer_right, outer_bottom, 18, fill=theme["panel_bg"], stipple="gray50", outline=theme["border"], width=2
                )
            self.canvas_chrome.extend([self.vault_left_item, self.vault_right_item])
            self.canvas.coords(self.vault_window, outer_left + 14, outer_top + 12)
            self.canvas.itemconfigure(self.vault_window, width=outer_right - outer_left - 28)

        self.canvas.tag_raise(self.auth_window)
        self.canvas.tag_raise(self.vault_window)

    def _on_canvas_resize(self, event) -> None:
        width = event.width
        height = event.height

        if self.background_item is not None:
            self._resize_background(width, height)
            self.canvas.coords(self.background_item, width // 2, height // 2)

        self._draw_canvas_chrome(width, height)
        self._update_responsive_layout(width)

    def _build_auth_frame(self) -> None:
        hero = ttk.Frame(self.auth_frame, style="App.TFrame")
        hero.pack(fill="x", pady=(0, 10))

        ttk.Label(hero, text="Personal Vault", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            hero,
            text="Local login, local database, and encrypted stored passwords.",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(6, 0))

        card = ttk.Frame(self.auth_frame, style="Glass.TFrame", padding=24)
        card.pack(fill="x", pady=4)

        self.auth_avatar_label = tk.Label(card, bg="#111111", bd=0, highlightthickness=0)
        self.auth_avatar_label.grid(row=0, column=0, columnspan=2, pady=(0, 10))
        self._set_auth_avatar_preview(None)

        ttk.Label(card, text="Sign in or register", style="CardTitle.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(0, 12)
        )

        ttk.Label(card, text="Username", style="Field.TLabel").grid(row=2, column=0, sticky="w", pady=6)
        self.auth_username_entry = ttk.Entry(card, width=34, style="App.TEntry")
        self.auth_username_entry.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        ttk.Label(card, text="Password", style="Field.TLabel").grid(row=4, column=0, sticky="w", pady=6)
        self.auth_password_entry = ttk.Entry(card, width=34, show="*", style="App.TEntry")
        self.auth_password_entry.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        ttk.Checkbutton(
            card,
            text="Remember username",
            variable=self.remember_user_var,
            style="Robot.TCheckbutton",
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(0, 10))

        ttk.Button(card, text="Choose avatar", style="Secondary.TButton", command=self.choose_avatar).grid(
            row=7, column=0, columnspan=2, sticky="ew", pady=(0, 14)
        )

        ttk.Button(card, text="Login", style="Primary.TButton", command=self.login_user).grid(row=8, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(card, text="Register", style="Secondary.TButton", command=self.register_user).grid(row=8, column=1, sticky="ew")

        remembered_username = self.app_state.get("last_username", "")
        if remembered_username:
            self.auth_username_entry.insert(0, remembered_username)

        ttk.Label(self.auth_frame, textvariable=self.auth_status_var, style="Status.TLabel").pack(anchor="w", pady=(12, 0))

        card.columnconfigure(0, weight=1)
        card.columnconfigure(1, weight=1)

    def _build_vault_frame(self) -> None:
        header = ttk.Frame(self.vault_frame, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 18))

        profile_wrap = ttk.Frame(header, style="App.TFrame")
        profile_wrap.pack(side="left")

        self.profile_avatar_label = tk.Label(profile_wrap, bg="#050505", bd=0, highlightthickness=0)
        self.profile_avatar_label.pack(side="left", padx=(0, 12))
        self._set_profile_avatar(None)

        title_wrap = ttk.Frame(profile_wrap, style="App.TFrame")
        title_wrap.pack(side="left")

        self.welcome_label = ttk.Label(title_wrap, text="Vault", style="Title.TLabel")
        self.welcome_label.pack(anchor="w")
        self.profile_subtitle = ttk.Label(title_wrap, text="Locked and loaded.", style="Sub.TLabel")
        self.profile_subtitle.pack(anchor="w")

        header_actions = ttk.Frame(header, style="App.TFrame")
        header_actions.pack(side="right")
        ttk.Button(header_actions, text="Settings", style="Secondary.TButton", command=self.open_settings).pack(side="left", padx=(0, 10))
        ttk.Button(header_actions, text="Logout", style="Secondary.TButton", command=self.logout_user).pack(side="left")

        body = ttk.Frame(self.vault_frame, style="App.TFrame")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=9)
        body.columnconfigure(1, weight=11)
        body.rowconfigure(0, weight=1)
        self.vault_body = body

        left_card = ttk.Frame(body, style="Glass.TFrame", padding=20)
        left_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.left_card = left_card

        ttk.Label(left_card, text="Save password", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 14))

        ttk.Label(left_card, text="Site", style="Field.TLabel").grid(row=1, column=0, sticky="w", pady=6)
        self.site_entry = ttk.Entry(left_card, style="App.TEntry")
        self.site_entry.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        ttk.Label(left_card, text="Login / Email", style="Field.TLabel").grid(row=3, column=0, sticky="w", pady=6)
        self.entry_login = ttk.Entry(left_card, style="App.TEntry")
        self.entry_login.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        ttk.Label(left_card, text="Password", style="Field.TLabel").grid(row=5, column=0, sticky="w", pady=6)
        self.entry_password = ttk.Entry(left_card, style="App.TEntry", show="*")
        self.entry_password.grid(row=6, column=0, sticky="ew", pady=(0, 12))

        ttk.Button(left_card, text="Generate", style="Secondary.TButton", command=self.handle_generate_password).grid(
            row=6, column=1, sticky="ew", padx=(10, 0)
        )

        ttk.Checkbutton(
            left_card,
            text="Show password",
            variable=self.show_password_var,
            command=self.toggle_password_visibility,
            style="Robot.TCheckbutton",
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(0, 8))

        actions = ttk.Frame(left_card, style="GlassInner.TFrame")
        actions.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(actions, text="Save entry", style="Primary.TButton", command=self.save_entry).pack(side="left", fill="x", expand=True)
        ttk.Button(actions, text="Clear", style="Secondary.TButton", command=self.clear_form).pack(side="left", fill="x", expand=True, padx=(10, 0))

        right_card = ttk.Frame(body, style="Glass.TFrame", padding=20)
        right_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self.right_card = right_card

        ttk.Label(right_card, text="Quick access", style="CardTitle.TLabel").pack(anchor="w", pady=(0, 10))

        self.search_entry = ttk.Entry(right_card, textvariable=self.search_var, style="App.TEntry")
        self.search_entry.pack(fill="x", pady=(0, 10))
        self.search_var.trace_add("write", self.filter_entries)

        self.entries_listbox = tk.Listbox(
            right_card,
            height=16,
            borderwidth=0,
            highlightthickness=0,
            bg="#0f0f0f",
            fg="#d7d7d7",
            selectbackground="#b31217",
            selectforeground="#ffffff",
            font=("Consolas", 10),
        )
        self.entries_listbox.pack(fill="both", expand=True)
        self.entries_listbox.bind("<<ListboxSelect>>", self.load_selected_entry)

        quick_actions = ttk.Frame(right_card, style="GlassInner.TFrame")
        quick_actions.pack(fill="x", pady=(12, 0))
        ttk.Button(quick_actions, text="Copy password", style="Secondary.TButton", command=self.copy_selected_password).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(quick_actions, text="Delete", style="Secondary.TButton", command=self.delete_selected_entry).pack(
            side="left", fill="x", expand=True, padx=(10, 0)
        )

        ttk.Label(self.vault_frame, textvariable=self.vault_status_var, style="Status.TLabel").grid(row=2, column=0, sticky="w", pady=(12, 0))

        self.vault_frame.columnconfigure(0, weight=1)
        self.vault_frame.rowconfigure(1, weight=1)
        left_card.columnconfigure(0, weight=1)
        left_card.columnconfigure(1, weight=1)
        right_card.columnconfigure(0, weight=1)

    def show_auth_screen(self) -> None:
        self.current_screen = "auth"
        self.canvas.itemconfigure(self.vault_window, state="hidden")
        self.canvas.itemconfigure(self.auth_window, state="normal")
        self._draw_canvas_chrome(self.canvas.winfo_width(), self.canvas.winfo_height())
        remembered_username = self.app_state.get("last_username", "") if self.remember_user_var.get() else ""
        if remembered_username and not self.auth_username_entry.get().strip():
            self.auth_username_entry.insert(0, remembered_username)
        self.auth_username_entry.focus()

    def _persist_auth_state(self, username: str) -> None:
        self.app_state["remember_user"] = bool(self.remember_user_var.get())
        self.app_state["last_username"] = username if self.remember_user_var.get() else ""
        self.preferences.save(self.app_state)

    def show_vault_screen(self) -> None:
        self.current_screen = "vault"
        self.canvas.itemconfigure(self.auth_window, state="hidden")
        self.canvas.itemconfigure(self.vault_window, state="normal")
        self._draw_canvas_chrome(self.canvas.winfo_width(), self.canvas.winfo_height())
        self._update_responsive_layout(self.canvas.winfo_width())
        self.site_entry.focus()

    def _update_responsive_layout(self, width: int) -> None:
        if not hasattr(self, "vault_body"):
            return

        if width < 980:
            self.left_card.grid_configure(row=0, column=0, padx=0, pady=(0, 12))
            self.right_card.grid_configure(row=1, column=0, padx=0, pady=0)
            self.vault_body.columnconfigure(0, weight=1)
            self.vault_body.columnconfigure(1, weight=0)
            self.vault_body.rowconfigure(0, weight=1)
            self.vault_body.rowconfigure(1, weight=1)
        else:
            self.left_card.grid_configure(row=0, column=0, padx=(0, 10), pady=0)
            self.right_card.grid_configure(row=0, column=1, padx=(10, 0), pady=0)
            self.vault_body.columnconfigure(0, weight=9)
            self.vault_body.columnconfigure(1, weight=11)
            self.vault_body.rowconfigure(0, weight=1)
            self.vault_body.rowconfigure(1, weight=0)

    def _make_avatar_image(self, image_bytes, size: int):
        if Image is None or ImageTk is None:
            fallback = tk.PhotoImage(width=size, height=size)
            fallback.put("#b31217", to=(0, 0, size, size))
            return fallback

        try:
            if image_bytes:
                image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
            else:
                image = Image.new("RGBA", (size, size), "#131313")
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            logger.warning("Avatar image is invalid, using fallback: %s", exc)
            image = Image.new("RGBA", (size, size), "#131313")

        # Любое изображение приводим к безопасному фиксированному размеру,
        # чтобы битые или слишком большие аватарки не ломали интерфейс.
        image = image.resize((size, size), Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(image)

    def _set_auth_avatar_preview(self, image_bytes) -> None:
        self.auth_avatar_preview = self._make_avatar_image(image_bytes, 64)
        self.auth_avatar_label.configure(image=self.auth_avatar_preview, width=64, height=64)

    def _set_profile_avatar(self, image_bytes) -> None:
        self.profile_avatar_image = self._make_avatar_image(image_bytes, 42)
        self.profile_avatar_label.configure(image=self.profile_avatar_image, width=42, height=42)

    def _pick_image_bytes(self):
        file_path = filedialog.askopenfilename(
            title="Choose avatar",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.gif *.bmp")],
        )
        if not file_path:
            return None

        try:
            image_bytes = Path(file_path).read_bytes()
            if Image is not None:
                with Image.open(io.BytesIO(image_bytes)) as image:
                    image.verify()
            return image_bytes
        except (OSError, UnidentifiedImageError, ValueError) as exc:
            logger.warning("Could not load avatar bytes: %s", exc)
            return None

    def choose_avatar(self) -> None:
        avatar_bytes = self._pick_image_bytes()
        if avatar_bytes is None:
            self.auth_status_var.set("Could not load avatar file.")
            return

        self._set_auth_avatar_preview(avatar_bytes)
        self.pending_avatar_bytes = avatar_bytes
        self.auth_status_var.set("Avatar selected for registration.")

    def choose_settings_avatar(self) -> None:
        avatar_bytes = self._pick_image_bytes()
        if avatar_bytes is None:
            self.vault_status_var.set("Could not load avatar file.")
            return

        self.settings_avatar_bytes = avatar_bytes
        self.settings_avatar_preview = self._make_avatar_image(avatar_bytes, 72)
        self.settings_avatar_label.configure(image=self.settings_avatar_preview, width=72, height=72)

    def open_settings(self) -> None:
        if self.current_session is None:
            return

        if hasattr(self, "settings_window") and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return

        row = self.database.get_user_by_id(self.current_session.user_id)
        if row is None:
            return

        self.settings_avatar_bytes = row["avatar"]
        self.settings_dns_check_var = tk.BooleanVar(value=bool(row["site_exists_check_enabled"]))
        self.settings_window = tk.Toplevel(self.root)
        self.settings_window.title("Account settings")
        self.settings_window.transient(self.root)
        self.settings_window.grab_set()
        self.settings_window.resizable(False, False)
        self.settings_window.configure(bg=THEMES[self.current_theme_name]["app_bg"])

        wrapper = ttk.Frame(self.settings_window, style="App.TFrame", padding=18)
        wrapper.pack(fill="both", expand=True)

        card = ttk.Frame(wrapper, style="Glass.TFrame", padding=18)
        card.pack(fill="both", expand=True)

        ttk.Label(card, text="Account settings", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

        self.settings_avatar_preview = self._make_avatar_image(row["avatar"], 72)
        self.settings_avatar_label = tk.Label(card, image=self.settings_avatar_preview, bg=THEMES[self.current_theme_name]["panel_bg"])
        self.settings_avatar_label.grid(row=1, column=0, columnspan=2, pady=(0, 10))

        ttk.Button(card, text="Change avatar", style="Secondary.TButton", command=self.choose_settings_avatar).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(0, 14)
        )

        ttk.Label(card, text="Username", style="Field.TLabel").grid(row=3, column=0, sticky="w", pady=4)
        self.settings_username_entry = ttk.Entry(card, style="App.TEntry")
        self.settings_username_entry.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        self.settings_username_entry.insert(0, row["username"])

        ttk.Label(card, text="New password", style="Field.TLabel").grid(row=5, column=0, sticky="w", pady=4)
        self.settings_password_entry = ttk.Entry(card, style="App.TEntry", show="*")
        self.settings_password_entry.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        ttk.Label(card, text="Theme", style="Field.TLabel").grid(row=7, column=0, sticky="w", pady=4)
        self.settings_theme_combo = ttk.Combobox(card, values=list(THEMES.keys()), state="readonly")
        self.settings_theme_combo.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        self.settings_theme_combo.set(row["theme_name"] if row["theme_name"] in THEMES else DEFAULT_THEME)

        ttk.Label(card, text="Music volume", style="Field.TLabel").grid(row=9, column=0, sticky="w", pady=4)
        self.settings_volume_scale = ttk.Scale(
            card,
            from_=0,
            to=100,
            orient="horizontal",
            command=lambda value: self.set_music_volume(float(value) / 100),
        )
        self.settings_volume_scale.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        self.settings_volume_scale.set(float(row["music_volume"]) * 100)

        ttk.Checkbutton(
            card,
            text="Check DNS before saving site",
            variable=self.settings_dns_check_var,
            style="Robot.TCheckbutton",
        ).grid(row=11, column=0, columnspan=2, sticky="w", pady=(0, 10))

        ttk.Label(card, text="Wallpaper", style="Field.TLabel").grid(row=12, column=0, sticky="w", pady=4)
        self.settings_wallpaper_combo = ttk.Combobox(card, values=self._get_wallpaper_options(), state="readonly")
        self.settings_wallpaper_combo.grid(row=13, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        current_wallpaper = row["background_choice"] if row["background_choice"] else "Default"
        if current_wallpaper not in self.settings_wallpaper_combo["values"]:
            self.settings_wallpaper_combo.configure(values=[*self.settings_wallpaper_combo["values"], current_wallpaper])
        self.settings_wallpaper_combo.set(current_wallpaper)

        ttk.Label(
            card,
            text=f"Wallpapers folder: {WALLPAPER_DIR}",
            style="Sub.TLabel",
        ).grid(row=14, column=0, columnspan=2, sticky="w", pady=(0, 6))

        ttk.Button(card, text="Refresh wallpapers", style="Secondary.TButton", command=self.refresh_wallpaper_choices).grid(
            row=15, column=0, columnspan=2, sticky="ew", pady=(0, 14)
        )

        ttk.Button(card, text="Save settings", style="Primary.TButton", command=self.save_settings).grid(row=16, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(card, text="Close", style="Secondary.TButton", command=self.settings_window.destroy).grid(row=16, column=1, sticky="ew")

        card.columnconfigure(0, weight=1)
        card.columnconfigure(1, weight=1)

    def save_settings(self) -> None:
        if self.current_session is None:
            return

        success, message, new_vault_secret = self.auth_service.update_settings(
            user_id=self.current_session.user_id,
            current_vault_secret=self.current_session.vault_secret,
            current_legacy_vault_secret=self.current_session.legacy_vault_secret,
            username=self.settings_username_entry.get(),
            new_password=self.settings_password_entry.get(),
            avatar=self.settings_avatar_bytes,
            theme_name=self.settings_theme_combo.get() if self.settings_theme_combo.get() in THEMES else DEFAULT_THEME,
            music_volume=self.settings_volume_scale.get() / 100,
            site_exists_check_enabled=self.settings_dns_check_var.get(),
            background_choice="" if self.settings_wallpaper_combo.get() == "Default" else self.settings_wallpaper_combo.get(),
            entries=self.vault_service.list_entries(self.current_session.user_id),
            decrypt_entry_password=self.vault_service.decrypt_entry_password,
        )
        if not success:
            if "username" in message.lower():
                messagebox.showwarning("Invalid username", message)
            elif "password" in message.lower():
                messagebox.showwarning("Invalid password", message)
            elif "already" in message.lower():
                messagebox.showerror("Username taken", message)
            else:
                messagebox.showerror("Settings error", message)
            return

        self.current_session = UserSession(
            user_id=self.current_session.user_id,
            username=self.settings_username_entry.get().strip(),
            avatar=self.settings_avatar_bytes,
            theme_name=self.settings_theme_combo.get() if self.settings_theme_combo.get() in THEMES else DEFAULT_THEME,
            music_volume=self.settings_volume_scale.get() / 100,
            site_exists_check_enabled=self.settings_dns_check_var.get(),
            background_choice="" if self.settings_wallpaper_combo.get() == "Default" else self.settings_wallpaper_combo.get(),
            vault_secret=new_vault_secret,
            legacy_vault_secret=b"",
        )
        self.welcome_label.configure(text=f"Vault: {self.current_session.username}")
        self._set_profile_avatar(self.current_session.avatar)
        self.set_music_volume(self.current_session.music_volume)
        self._apply_theme(self.current_session.theme_name)
        self._set_background_choice(self.current_session.background_choice)
        self.vault_status_var.set(message)
        self.settings_window.destroy()
        self.refresh_entries()

    def refresh_wallpaper_choices(self) -> None:
        self._ensure_wallpaper_dir()
        values = self._get_wallpaper_options()
        self.settings_wallpaper_combo.configure(values=values)
        if self.settings_wallpaper_combo.get() not in values:
            self.settings_wallpaper_combo.set("Default")

    def register_user(self) -> None:
        result = self.auth_service.register_user(
            username=self.auth_username_entry.get(),
            password=self.auth_password_entry.get(),
            avatar=self.pending_avatar_bytes,
            theme_name=self.current_theme_name,
            music_volume=self.music_volume,
            site_exists_check_enabled=True,
            background_choice="",
        )
        self.auth_status_var.set(result.message)
        if result.success:
            self._persist_auth_state(self.auth_username_entry.get().strip())
            self.auth_password_entry.delete(0, tk.END)
            self.pending_avatar_bytes = None
            self._set_auth_avatar_preview(None)

    def show_fake_breach_popup(self) -> None:
        popup = tk.Toplevel(self.root)
        popup.title("Security breach")
        popup.configure(bg="#2a120f")
        popup.resizable(False, False)
        popup.transient(self.root)
        popup.grab_set()

        frame = tk.Frame(popup, bg="#2a120f", padx=18, pady=18)
        frame.pack(fill="both", expand=True)

        tk.Label(
            frame,
            text="SQL injection successful! your entire password database has been sent to @smartdork GET PWNED DORK!",
            bg="#2a120f",
            fg="#ffd8d2",
            justify="left",
            wraplength=320,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")

        tk.Button(
            frame,
            text="OH FUCK",
            command=popup.destroy,
            bg="#d8573c",
            fg="white",
            activebackground="#b8442d",
            activeforeground="white",
            relief="flat",
            padx=14,
            pady=8,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="e", pady=(16, 0))

    def login_user(self) -> None:
        result = self.auth_service.login_user(self.auth_username_entry.get(), self.auth_password_entry.get())
        self.auth_status_var.set(result.message)
        if not result.success:
            if result.show_breach_popup:
                self.show_fake_breach_popup()
            return

        self.current_session = result.session
        self._persist_auth_state(self.current_session.username)
        self.set_music_volume(self.current_session.music_volume)
        self._apply_theme(self.current_session.theme_name)
        self._set_background_choice(self.current_session.background_choice)
        self.vault_service.migrate_entries_to_modern_crypto(
            self.current_session.user_id,
            self.current_session.vault_secret,
            self.current_session.legacy_vault_secret,
        )
        self.vault_status_var.set("Vault unlocked.")
        self.welcome_label.configure(text=f"Vault: {self.current_session.username}")
        self.profile_subtitle.configure(text="Only you can open this mess.")
        self._set_profile_avatar(self.current_session.avatar)
        self.show_vault_screen()
        self.clear_form()
        self.refresh_entries()

    def logout_user(self) -> None:
        remembered_name = self.current_session.username if self.current_session else self.auth_username_entry.get().strip()
        self._persist_auth_state(remembered_name)
        self.current_session = None
        self.entries_cache = []
        self.filtered_entries = []
        self.entries_listbox.delete(0, tk.END)
        self.clear_form()
        self.auth_password_entry.delete(0, tk.END)
        self.search_var.set("")
        self._set_profile_avatar(None)
        self._apply_theme(DEFAULT_THEME)
        self._set_background_choice("")
        self.set_music_volume(DEFAULT_VOLUME)
        self._cancel_clipboard_cleanup()
        self.vault_status_var.set("Signed out.")
        self.show_auth_screen()

    def handle_generate_password(self) -> None:
        self.entry_password.delete(0, tk.END)
        self.entry_password.insert(0, generate_password())
        self.vault_status_var.set("Generated a strong password.")

    def clear_form(self) -> None:
        self.site_entry.delete(0, tk.END)
        self.entry_login.delete(0, tk.END)
        self.entry_password.delete(0, tk.END)
        self.entries_listbox.selection_clear(0, tk.END)
        self.show_password_var.set(False)
        self.toggle_password_visibility()

    def toggle_password_visibility(self) -> None:
        self.entry_password.configure(show="" if self.show_password_var.get() else "*")

    def save_entry(self) -> None:
        if self.current_session is None:
            self.vault_status_var.set("You must be logged in.")
            return

        success, message = self.vault_service.save_entry(
            user_id=self.current_session.user_id,
            site=self.site_entry.get(),
            login_value=self.entry_login.get(),
            password_value=self.entry_password.get(),
            vault_secret=self.current_session.vault_secret,
            dns_check_enabled=self.current_session.site_exists_check_enabled,
        )
        if not success:
            if "Fill in" in message:
                messagebox.showwarning("Missing data", message)
            else:
                messagebox.showerror("Invalid site", message)
            self.vault_status_var.set(message)
            return

        self.vault_status_var.set(message)
        self.refresh_entries()
        self.clear_form()

    def refresh_entries(self) -> None:
        if self.current_session is None:
            return

        self.entries_cache = self.vault_service.list_entries(self.current_session.user_id)
        self.filter_entries()

    def filter_entries(self, *_args) -> None:
        query = self.search_var.get().strip().lower()
        if not query:
            self.filtered_entries = list(self.entries_cache)
        else:
            self.filtered_entries = [
                row
                for row in self.entries_cache
                if query in row["site_display"].lower() or query in row["login"].lower()
            ]

        self.entries_listbox.delete(0, tk.END)
        for row in self.filtered_entries:
            self.entries_listbox.insert(tk.END, f"{row['site_display']} [{row['login']}]")

    def load_selected_entry(self, _event=None) -> None:
        if self.current_session is None:
            return

        selection = self.entries_listbox.curselection()
        if not selection:
            return

        row = self.filtered_entries[selection[0]]
        try:
            password_value = self.vault_service.decrypt_entry_password(
                row,
                self.current_session.vault_secret,
                self.current_session.legacy_vault_secret,
            )
        except ValueError:
            self.vault_status_var.set("Could not decrypt this entry.")
            return

        site_value = row["site_display"] if row["site_normalized"].startswith("legacy://") else row["site_normalized"]
        self.site_entry.delete(0, tk.END)
        self.site_entry.insert(0, site_value)
        self.entry_login.delete(0, tk.END)
        self.entry_login.insert(0, row["login"])
        self.entry_password.delete(0, tk.END)
        self.entry_password.insert(0, password_value)
        self.vault_status_var.set(f"Loaded {row['site_display']}.")

    def copy_selected_password(self) -> None:
        if self.current_session is None:
            return

        selection = self.entries_listbox.curselection()
        if not selection:
            self.vault_status_var.set("Select an entry first.")
            return

        row = self.filtered_entries[selection[0]]
        try:
            password_value = self.vault_service.decrypt_entry_password(
                row,
                self.current_session.vault_secret,
                self.current_session.legacy_vault_secret,
            )
        except ValueError:
            self.vault_status_var.set("Could not decrypt this entry.")
            return

        self.root.clipboard_clear()
        self.root.clipboard_append(password_value)
        self.last_copied_password = password_value
        self._schedule_clipboard_cleanup()
        self.vault_status_var.set(f"Password copied for {row['site_display']}.")

    def _schedule_clipboard_cleanup(self) -> None:
        self._cancel_clipboard_cleanup()
        # Буфер очищаем только если в нём всё ещё наш пароль,
        # чтобы не стирать данные, которые пользователь скопировал позже.
        self.clipboard_clear_job = self.root.after(CLIPBOARD_CLEAR_DELAY_MS, self._clear_clipboard_if_unchanged)

    def _cancel_clipboard_cleanup(self) -> None:
        if self.clipboard_clear_job is not None:
            self.root.after_cancel(self.clipboard_clear_job)
            self.clipboard_clear_job = None

    def _clear_clipboard_if_unchanged(self) -> None:
        self.clipboard_clear_job = None
        try:
            current_value = self.root.clipboard_get()
        except tk.TclError:
            self.last_copied_password = ""
            return

        if current_value == self.last_copied_password:
            self.root.clipboard_clear()
            self.vault_status_var.set("Clipboard cleared automatically.")
        self.last_copied_password = ""

    def delete_selected_entry(self) -> None:
        selection = self.entries_listbox.curselection()
        if not selection:
            self.vault_status_var.set("Select an entry first.")
            return

        row = self.filtered_entries[selection[0]]
        confirmed = messagebox.askyesno("Delete entry", f"Delete saved password for {row['site_display']} [{row['login']}]?")
        if not confirmed:
            return

        self.vault_service.delete_entry(row["id"])
        self.refresh_entries()
        self.clear_form()
        self.vault_status_var.set(f"Deleted {row['site_display']} [{row['login']}].")

    def on_close(self) -> None:
        current_name = self.current_session.username if self.current_session else self.auth_username_entry.get().strip()
        self._persist_auth_state(current_name)
        self._cancel_clipboard_cleanup()
        if self.music_ready and pygame is not None:
            try:
                pygame.mixer.music.stop()
                pygame.mixer.quit()
            except pygame.error as exc:
                logger.warning("Could not stop music cleanly: %s", exc)
        self.database.close()
        self.root.destroy()
