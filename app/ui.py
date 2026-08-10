import os
import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from typing import Optional

import chess
import pygame
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from PIL import Image, ImageTk

from config import (
    BOARD_ONLY_HINTS,
    IMAGE_DIR,
    INFO_PANEL_WIDTH,
    PIECE_DIR,
    PIECE_SYMBOL_TO_FILE,
    SOUND_DIR,
)
from .analysis_utils import mate_to_white_perspective, score_to_white_perspective
from .helpers import make_placeholder_piece
from .navigation_utils import animation_excluded_squares


class UIFlowMixin:
    COLORS = {
        "bg": "#f5f5f7",
        "surface": "#ffffff",
        "surface_alt": "#ececf0",
        "border": "#d1d1d6",
        "text": "#1d1d1f",
        "muted": "#6e6e73",
        "accent": "#007aff",
        "selection": "#0a84ff",
        "danger": "#ff3b30",
    }

    def init_sound(self) -> None:
        try:
            pygame.mixer.init()
            move_sound_path = os.path.join(SOUND_DIR, "move.wav")
            capture_sound_path = os.path.join(SOUND_DIR, "capture.wav")
            self.move_sound = pygame.mixer.Sound(move_sound_path) if os.path.exists(move_sound_path) else None
            self.capture_sound = pygame.mixer.Sound(capture_sound_path) if os.path.exists(capture_sound_path) else None
            self.sound_enabled = True
        except Exception as exc:
            self.sound_enabled = False
            print(f"Sound init error: {exc}")

    def load_assets(self) -> None:
        self.board_bg_source: Optional[Image.Image] = None
        self.piece_source_images: dict[str, Optional[Image.Image]] = {}

        try:
            board_img_path = os.path.join(IMAGE_DIR, "board.png")
            if os.path.exists(board_img_path):
                with Image.open(board_img_path) as board_image:
                    self.board_bg_source = board_image.convert("RGBA")
        except Exception:
            self.board_bg_source = None

        for symbol in list("PNBRQKpnbrqk"):
            self.piece_images[symbol] = None
            self.piece_source_images[symbol] = None
        for symbol, filename in PIECE_SYMBOL_TO_FILE.items():
            color_folder = "white" if symbol.isupper() else "black"
            path = os.path.join(PIECE_DIR, color_folder, filename)
            if os.path.exists(path):
                try:
                    with Image.open(path) as piece_image:
                        self.piece_source_images[symbol] = piece_image.convert("RGBA")
                except Exception:
                    self.piece_source_images[symbol] = None

        self.refresh_scaled_assets()

    def refresh_scaled_assets(self) -> None:
        if self.board_bg_source is not None:
            resized_board = self.board_bg_source.resize((self.board_size, self.board_size), Image.LANCZOS)
            self.board_bg_image = ImageTk.PhotoImage(resized_board)
        else:
            self.board_bg_image = None

        for symbol in list("PNBRQKpnbrqk"):
            source_image = self.piece_source_images.get(symbol)
            if source_image is not None:
                resized_piece = source_image.resize((self.square_size, self.square_size), Image.LANCZOS)
                self.piece_images[symbol] = ImageTk.PhotoImage(resized_piece)
            else:
                fallback_symbol = symbol.upper() if symbol.isupper() else symbol.lower()
                self.piece_images[symbol] = make_placeholder_piece(fallback_symbol, size=self.square_size)

    def redraw_board_background(self) -> None:
        if not hasattr(self, "board_canvas"):
            return

        self.board_canvas.delete("board_bg")
        if self.board_bg_image:
            self.board_canvas.create_image(0, 0, anchor=tk.NW, image=self.board_bg_image, tags="board_bg")
            self.board_canvas.tag_lower("board_bg")
        self.draw_board_coordinates()

    def draw_board_coordinates(self) -> None:
        if not hasattr(self, "board_canvas"):
            return
        self.board_canvas.delete("coordinates")
        if not self.show_coordinates_var.get():
            return

        files = "abcdefgh" if self.board_orientation_white_pov else "hgfedcba"
        ranks = "87654321" if self.board_orientation_white_pov else "12345678"
        font = "TkSmallCaptionFont"
        for index, file_name in enumerate(files):
            label_color = "#8b5e3c" if (7 + index) % 2 == 0 else "#f4dfb9"
            self.board_canvas.create_text(
                index * self.square_size + self.square_size - 5,
                self.board_size - 4,
                text=file_name,
                anchor=tk.SE,
                fill=label_color,
                font=font,
                tags="coordinates",
            )
        for index, rank_name in enumerate(ranks):
            label_color = "#8b5e3c" if index % 2 == 0 else "#f4dfb9"
            self.board_canvas.create_text(
                5,
                index * self.square_size + 4,
                text=rank_name,
                anchor=tk.NW,
                fill=label_color,
                font=font,
                tags="coordinates",
            )
        self.board_canvas.tag_raise("coordinates")

    def create_widgets(self) -> None:
        self.configure_application_style()
        self.create_top_toolbar()
        self.create_status_bar()

        self.main_frame = ttk.Frame(self.root, padding=(12, 8), style="App.TFrame")
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        self.main_frame.rowconfigure(0, weight=1)
        self.main_frame.columnconfigure(0, weight=1, minsize=self.min_board_size)
        self.main_frame.columnconfigure(1, weight=0)
        self.main_frame.columnconfigure(2, weight=0, minsize=self.min_info_panel_width)

        self.left_frame = ttk.Frame(self.main_frame, padding=(0, 0, 8, 0))
        self.left_frame.grid(row=0, column=0, sticky="nsew")

        self.board_area = ttk.Frame(self.left_frame)
        self.board_area.pack(fill=tk.BOTH, expand=True)
        self.board_area.pack_propagate(False)
        self.board_area.bind("<Configure>", self.on_board_area_configure)

        self.board_canvas = tk.Canvas(
            self.board_area,
            width=self.board_size,
            height=self.board_size,
            bg=self.COLORS["bg"],
            highlightthickness=0,
        )
        self.board_canvas.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        self.redraw_board_background()

        self.create_board_controls(self.left_frame)

        # The divider is a continuous part of the panel edge. The entire visible
        # grey strip is draggable; there is no detached handle or hidden hit area.
        self.panel_resize_lane = tk.Frame(
            self.main_frame,
            width=4,
            background=self.COLORS["border"],
            cursor="sb_h_double_arrow",
            highlightthickness=0,
        )
        self.panel_resize_lane.grid(row=0, column=1, sticky="ns")
        self.panel_resize_lane.grid_propagate(False)
        self.panel_resize_lane.bind("<ButtonPress-1>", self.start_info_panel_resize)
        self.panel_resize_lane.bind("<B1-Motion>", self.resize_info_panel)
        self.panel_resize_lane.bind("<ButtonRelease-1>", self.finish_info_panel_resize)
        self.panel_resize_lane.bind(
            "<Enter>", lambda _event: self.panel_resize_lane.configure(background=self.COLORS["muted"])
        )
        self.panel_resize_lane.bind(
            "<Leave>", lambda _event: self.panel_resize_lane.configure(background=self.COLORS["border"])
        )
        self.bind_status_hint(self.panel_resize_lane, "Потяните серую границу, чтобы изменить ширину панели")

        self.info_panel = ttk.Frame(self.main_frame, width=INFO_PANEL_WIDTH, padding=(8, 0, 0, 0))
        self.info_panel.grid(row=0, column=2, sticky="nsew")
        # Children inside this frame use pack(), so pack propagation is what
        # must be disabled to keep the user-selected panel width authoritative.
        self.info_panel.pack_propagate(False)
        self._saved_info_panel_width = INFO_PANEL_WIDTH
        self.info_panel.bind("<Configure>", self.on_info_panel_configure)
        self.create_info_panel_widgets()
        self.root.bind("<<ThemeChanged>>", self._schedule_native_appearance_refresh, add="+")
        self.root.after_idle(self._restore_info_panel_width)
        self.root.after_idle(self.refresh_responsive_layout)

    def start_info_panel_resize(self, event: tk.Event) -> None:
        self._panel_resize_start_x = event.x_root
        self._panel_resize_start_width = self.info_panel.winfo_width()

    def resize_info_panel(self, event: tk.Event) -> None:
        if getattr(self, "_panel_resize_start_x", None) is None:
            return
        requested_width = self._panel_resize_start_width + self._panel_resize_start_x - event.x_root
        max_width = max(
            self.min_info_panel_width,
            self.main_frame.winfo_width() - self.min_board_size - self.panel_resize_lane.winfo_width(),
        )
        panel_width = max(self.min_info_panel_width, min(requested_width, max_width))
        self.info_panel.configure(width=panel_width)
        self._saved_info_panel_width = panel_width
        self.refresh_info_panel_layout()

    def finish_info_panel_resize(self, event: Optional[tk.Event] = None) -> None:
        panel_width = self.info_panel.winfo_width()
        self._saved_info_panel_width = panel_width
        self._panel_resize_start_x = None
        self.set_status_message(
            f"Ширина панели: {panel_width} px",
            clear_after_ms=1800,
        )
        self._schedule_responsive_refresh()

    def configure_application_style(self) -> None:
        self.is_macos = sys.platform == "darwin"
        style = ttk.Style(self.root)
        if self.is_macos and "aqua" in style.theme_names():
            style.theme_use("aqua")
            self._configure_native_macos_window()
        elif "clam" in style.theme_names():
            style.theme_use("clam")

        self.COLORS = self._resolve_system_palette()
        self.root.configure(bg=self.COLORS["bg"])
        self.root.option_add("*Font", "TkDefaultFont")

        self._brand_font = tkfont.nametofont("TkDefaultFont").copy()
        self._brand_font.configure(size=15, weight="bold")
        self._heading_font = tkfont.nametofont("TkDefaultFont").copy()
        self._heading_font.configure(size=11, weight="bold")
        self._small_font = tkfont.nametofont("TkDefaultFont").copy()
        self._small_font.configure(size=9)

        style.configure("Brand.TLabel", font=self._brand_font)
        style.configure("Muted.TLabel", foreground=self.COLORS["muted"], font=self._small_font)
        style.configure("Toolbar.TLabel", font=self._small_font)
        style.configure("CardTitle.TLabel", font=self._heading_font)
        style.configure("Treeview", rowheight=28)

        self.toolbar_button_style = "Toolbutton" if self.is_macos else "TButton"
        self.navigation_button_style = "Toolbutton" if self.is_macos else "TButton"
        self.primary_button_style = "TButton"
        self.toolbar_frame_style = "Glass.Toolbar.TFrame" if self.is_macos else "TFrame"
        self.toolbar_brand_style = "Glass.Brand.TLabel" if self.is_macos else "Brand.TLabel"
        self.toolbar_muted_style = "Glass.Muted.TLabel" if self.is_macos else "Muted.TLabel"
        if self.is_macos:
            style.configure("Glass.Toolbar.TFrame", background="systemTransparent")
            style.configure("Glass.Brand.TLabel", background="systemTransparent", font=self._brand_font)
            style.configure(
                "Glass.Muted.TLabel",
                background="systemTransparent",
                foreground=self.COLORS["muted"],
                font=self._small_font,
            )

    def _configure_native_macos_window(self) -> None:
        try:
            self.root.tk.call("wm", "attributes", self.root._w, "-appearance", "auto")
        except tk.TclError:
            pass
        try:
            self.root.tk.call(
                "wm",
                "attributes",
                self.root._w,
                "-stylemask",
                ("titled", "closable", "miniaturizable", "resizable", "fullsizecontentview"),
            )
        except tk.TclError:
            pass
        for command, value in (
            ("::tk::mac::useThemedToplevel", True),
            ("::tk::mac::useCompatibilityMetrics", False),
            ("::tk::mac::antialiasedtext", -1),
        ):
            try:
                self.root.tk.call(command, value)
            except tk.TclError:
                continue

    def _resolve_system_color(self, name: str, fallback: str) -> str:
        if not self.is_macos:
            return fallback
        try:
            red, green, blue = self.root.winfo_rgb(name)
            return f"#{red // 257:02x}{green // 257:02x}{blue // 257:02x}"
        except tk.TclError:
            return fallback

    def _resolve_system_palette(self) -> dict[str, str]:
        is_dark = False
        if self.is_macos:
            try:
                is_dark = bool(int(self.root.tk.call("wm", "attributes", self.root._w, "-isdark")))
            except (tk.TclError, TypeError, ValueError):
                pass

        fallback = {
            "bg": "#1e1e1e" if is_dark else "#f5f5f7",
            "surface": "#2c2c2e" if is_dark else "#ffffff",
            "surface_alt": "#3a3a3c" if is_dark else "#ececf0",
            "border": "#48484a" if is_dark else "#d1d1d6",
            "text": "#f5f5f7" if is_dark else "#1d1d1f",
            "muted": "#aeaeb2" if is_dark else "#6e6e73",
            "accent": "#0a84ff" if is_dark else "#007aff",
            "selection": "#0a84ff" if is_dark else "#007aff",
            "danger": "#ff453a" if is_dark else "#ff3b30",
        }
        system_names = {
            "bg": "systemWindowBackgroundColor",
            "surface": "systemControlBackgroundColor",
            "surface_alt": "systemTextBackgroundColor",
            "border": "systemSeparatorColor",
            "text": "systemLabelColor",
            "muted": "systemSecondaryLabelColor",
            "accent": "systemControlAccentColor",
            "selection": "systemSelectedContentBackgroundColor",
            "danger": "systemRedColor",
        }
        palette = {
            key: self._resolve_system_color(system_names[key], value)
            for key, value in fallback.items()
        }
        # macOS separatorColor is translucent. Tk drops its alpha channel and
        # renders it as solid black, so keep Apple's opaque fallback instead.
        palette["border"] = fallback["border"]
        return palette

    def _schedule_native_appearance_refresh(self, event: Optional[tk.Event] = None) -> None:
        pending = getattr(self, "_native_appearance_job", None)
        if pending is not None:
            self.root.after_cancel(pending)
        self._native_appearance_job = self.root.after_idle(self.refresh_native_appearance)

    def refresh_native_appearance(self) -> None:
        self._native_appearance_job = None
        self.COLORS = self._resolve_system_palette()
        self.root.configure(bg=self.COLORS["bg"])
        if hasattr(self, "board_canvas"):
            self.board_canvas.configure(bg=self.COLORS["bg"])
        if hasattr(self, "analysis_canvas"):
            self.analysis_canvas.configure(bg=self.COLORS["bg"])
        if hasattr(self, "panel_resize_lane"):
            self.panel_resize_lane.configure(background=self.COLORS["border"])
        if hasattr(self, "report_text"):
            self.report_text.configure(
                bg=self.COLORS["surface"],
                fg=self.COLORS["text"],
                insertbackground=self.COLORS["text"],
                selectbackground=self.COLORS["selection"],
            )
        if hasattr(self, "move_search_hint"):
            self.move_search_hint.configure(foreground=self.COLORS["muted"])
        if hasattr(self, "fig"):
            self.fig.set_facecolor(self.COLORS["bg"])
            self.update_evaluation_graph()

    def create_top_toolbar(self) -> None:
        toolbar_padding = (82, 12, 12, 9) if self.is_macos else (12, 7)
        toolbar = ttk.Frame(self.root, padding=toolbar_padding, style=self.toolbar_frame_style)
        toolbar.pack(fill=tk.X)

        ttk.Label(toolbar, text="ChessAI", style=self.toolbar_brand_style).pack(side=tk.LEFT, padx=(2, 16))
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))
        ttk.Button(toolbar, text="Открыть", command=self.load_pgn, style=self.toolbar_button_style).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Вставить", command=self.load_from_clipboard, style=self.toolbar_button_style).pack(side=tk.LEFT, padx=2)
        self.quick_analysis_button = ttk.Button(
            toolbar,
            text="Анализ позиции",
            command=self.request_analysis_current_pos,
            style=self.toolbar_button_style,
        )
        self.quick_analysis_button.pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Новая игра", command=self.start_new_game_vs_engine, style=self.toolbar_button_style).pack(side=tk.LEFT, padx=2)

        self.toolbar_mode_var = tk.StringVar(value="Режим анализа")
        ttk.Label(toolbar, textvariable=self.toolbar_mode_var, style=self.toolbar_muted_style).pack(side=tk.RIGHT, padx=(12, 4))
        ttk.Separator(self.root, orient=tk.HORIZONTAL).pack(fill=tk.X)

    def create_status_bar(self) -> None:
        self.status_message_var = tk.StringVar(value="Готово")
        self.status_position_var = tk.StringVar(value="Ход белых · начало партии")
        engine_text = "Stockfish подключен" if self.engine and self.engine.process else "Stockfish недоступен"
        self.status_engine_var = tk.StringVar(value=engine_text)

        status_container = ttk.Frame(self.root)
        status_container.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Separator(status_container, orient=tk.HORIZONTAL).pack(fill=tk.X)
        status_bar = ttk.Frame(status_container, padding=(12, 5))
        status_bar.pack(fill=tk.X)
        ttk.Label(status_bar, textvariable=self.status_message_var).pack(side=tk.LEFT)
        ttk.Label(status_bar, textvariable=self.status_engine_var, style="Muted.TLabel").pack(side=tk.RIGHT)
        ttk.Label(status_bar, text="  •  ", style="Muted.TLabel").pack(side=tk.RIGHT)
        ttk.Label(status_bar, textvariable=self.status_position_var, style="Muted.TLabel").pack(side=tk.RIGHT)

    def set_status_message(self, message: str, clear_after_ms: Optional[int] = None) -> None:
        if not hasattr(self, "status_message_var"):
            return
        self.status_message_var.set(message)
        pending = getattr(self, "_status_clear_job", None)
        if pending is not None:
            self.root.after_cancel(pending)
            self._status_clear_job = None
        if clear_after_ms:
            self._status_clear_job = self.root.after(clear_after_ms, lambda: self.status_message_var.set("Готово"))

    def bind_status_hint(self, widget: tk.Widget, message: str) -> None:
        widget.bind("<Enter>", lambda _event: self.set_status_message(message), add="+")
        widget.bind("<Leave>", lambda _event: self.set_status_message("Готово"), add="+")

    def refresh_status_bar(self) -> None:
        if not hasattr(self, "status_position_var"):
            return
        mode_labels = {
            "analysis": "Режим анализа",
            "play_engine": "Игра со Stockfish",
            "puzzle": "Тренировка",
        }
        self.toolbar_mode_var.set(mode_labels.get(self.game_mode, "ChessAI"))
        turn = "белых" if self.board_state.turn == chess.WHITE else "черных"
        ply = self.current_game_node.ply() if self.current_game_node else 0
        move_label = "начало партии" if ply == 0 else f"полуход {ply}"
        self.status_position_var.set(f"Ход {turn} · {move_label}")

    def create_board_controls(self, parent: ttk.Frame) -> None:
        pgn_controls_frame = ttk.Frame(parent)
        pgn_controls_frame.pack(fill=tk.X, pady=6)

        self.menu_bar = tk.Menu(self.root)
        self.root.config(menu=self.menu_bar)

        file_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="Файл", menu=file_menu)
        file_menu.add_command(label="Загрузить PGN...", command=self.load_pgn)
        file_menu.add_command(label="Загрузить FEN...", command=self.load_fen_dialog)
        file_menu.add_command(label="Загрузить по URL (Lichess / Chess.com)...", command=self.load_from_url)
        file_menu.add_command(label="Вставить PGN/FEN/URL из буфера", command=self.load_from_clipboard)
        file_menu.add_separator()
        file_menu.add_command(label="Сохранить PGN с аннотациями...", command=self.save_pgn_with_annotations)
        file_menu.add_command(label="Копировать PGN", command=self.export_pgn_to_clipboard)
        file_menu.add_command(label="Пакетный анализ PGN...", command=self.start_batch_pgn_analysis)
        file_menu.add_separator()
        file_menu.add_command(label="Выход", command=self.on_closing)

        game_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="Игра", menu=game_menu)
        game_menu.add_command(label="Новая игра с движком", command=self.start_new_game_vs_engine)
        game_menu.add_command(label="Режим: Только доска (Space)", command=self.toggle_board_only)

        training_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="Тренировка", menu=training_menu)
        training_menu.add_command(label="Найти лучший ход (P)", command=self.start_best_move_challenge)
        training_menu.add_command(label="Задачи из ошибок партии", command=self.start_generated_puzzle_session)

        view_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="Вид", menu=view_menu)
        view_menu.add_checkbutton(label="Координаты доски", variable=self.show_coordinates_var, command=self.toggle_board_coordinates)
        view_menu.add_checkbutton(label="Звуки ходов", variable=self.sound_enabled_var, command=self.toggle_sound)
        view_menu.add_checkbutton(label="Анимация ходов", variable=self.animations_enabled_var, command=self.toggle_animations)
        view_menu.add_separator()
        view_menu.add_checkbutton(
            label="Боковая панель (Cmd/Ctrl+B)",
            variable=self.info_panel_visible_var,
            command=self.apply_info_panel_visibility,
        )
        view_menu.add_command(label="Перевернуть доску (F)", command=self.flip_board)
        view_menu.add_command(label="Только доска (Space)", command=self.toggle_board_only)

        help_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="Справка", menu=help_menu)
        help_menu.add_command(label="Горячие клавиши (H)", command=self.show_help_dialog)

        self.first_move_button = ttk.Button(pgn_controls_frame, text="⏮", command=self.first_move_action, state=tk.DISABLED, style=self.navigation_button_style)
        self.first_move_button.pack(side=tk.LEFT, padx=2)
        self.prev_move_button = ttk.Button(pgn_controls_frame, text="◀", command=self.prev_move_action, state=tk.DISABLED, style=self.navigation_button_style)
        self.prev_move_button.pack(side=tk.LEFT, padx=2)
        self.next_move_button = ttk.Button(pgn_controls_frame, text="▶", command=self.next_move_action, state=tk.DISABLED, style=self.navigation_button_style)
        self.next_move_button.pack(side=tk.LEFT, padx=2)
        self.last_move_button = ttk.Button(pgn_controls_frame, text="⏭", command=self.last_move_action, state=tk.DISABLED, style=self.navigation_button_style)
        self.last_move_button.pack(side=tk.LEFT, padx=2)
        self.flip_board_button = ttk.Button(pgn_controls_frame, text="Перевернуть (F)", command=self.flip_board)
        self.flip_board_button.pack(side=tk.LEFT, padx=6)
        self.copy_fen_button = ttk.Button(pgn_controls_frame, text="Копировать FEN", command=self.export_fen_to_clipboard)
        self.copy_fen_button.pack(side=tk.LEFT, padx=6)

        for widget, hint in (
            (self.first_move_button, "Перейти к начальной позиции · Home"),
            (self.prev_move_button, "Предыдущий ход · ←"),
            (self.next_move_button, "Следующий ход · →"),
            (self.last_move_button, "Перейти в конец партии · End"),
            (self.flip_board_button, "Перевернуть доску · F"),
            (self.copy_fen_button, "Скопировать текущую позицию в формате FEN"),
        ):
            self.bind_status_hint(widget, hint)

        evaluation_frame = ttk.Frame(parent, padding=(4, 0))
        evaluation_frame.pack(fill=tk.X, pady=(2, 0))
        evaluation_frame.columnconfigure(1, weight=1)
        self.evaluation_progress_var = tk.DoubleVar(value=50.0)
        self.evaluation_text_var = tk.StringVar(value="0.00")
        ttk.Label(evaluation_frame, text="Белые", style="Muted.TLabel").grid(row=0, column=0, padx=(0, 8))
        self.evaluation_progress = ttk.Progressbar(
            evaluation_frame,
            orient=tk.HORIZONTAL,
            mode="determinate",
            maximum=100.0,
            variable=self.evaluation_progress_var,
        )
        self.evaluation_progress.grid(row=0, column=1, sticky="ew")
        self.bind_status_hint(
            self.evaluation_progress,
            "Оценка позиции: индикатор смещается в сторону белых или чёрных",
        )
        ttk.Label(
            evaluation_frame,
            textvariable=self.evaluation_text_var,
            width=7,
            anchor=tk.CENTER,
            font=self._heading_font,
        ).grid(row=0, column=2, padx=8)
        ttk.Label(evaluation_frame, text="Чёрные", style="Muted.TLabel").grid(row=0, column=3)

    def create_info_panel_widgets(self) -> None:
        self.notebook = ttk.Notebook(self.info_panel)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=6)

        self.analysis_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.analysis_tab, text="Анализ")

        self.analysis_canvas = tk.Canvas(
            self.analysis_tab,
            background=self.COLORS["bg"],
            highlightthickness=0,
            borderwidth=0,
        )
        analysis_scrollbar = ttk.Scrollbar(
            self.analysis_tab,
            orient=tk.VERTICAL,
            command=self.analysis_canvas.yview,
        )
        self.analysis_canvas.configure(yscrollcommand=analysis_scrollbar.set)
        analysis_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.analysis_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.analysis_content = ttk.Frame(self.analysis_canvas)
        self._analysis_content_window = self.analysis_canvas.create_window(
            0,
            0,
            anchor=tk.NW,
            window=self.analysis_content,
        )
        self.analysis_content.bind("<Configure>", self._sync_analysis_scrollregion)
        self.analysis_canvas.bind("<Configure>", self._resize_analysis_content)
        self.root.bind("<MouseWheel>", self._scroll_analysis_tab, add="+")
        self.root.bind("<Button-4>", self._scroll_analysis_tab, add="+")
        self.root.bind("<Button-5>", self._scroll_analysis_tab, add="+")
        self.create_analysis_tab(self.analysis_content)

        self.graph_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.graph_tab, text="График")
        self.create_graph_tab(self.graph_tab)

        self.report_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.report_tab, text="Отчет")
        self.create_report_tab(self.report_tab)

        self.variations_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.variations_tab, text="Варианты")
        self.create_variation_tab(self.variations_tab)
        self.notebook.bind("<<NotebookTabChanged>>", self.on_notebook_tab_changed)

    def _sync_analysis_scrollregion(self, event: Optional[tk.Event] = None) -> None:
        bounds = self.analysis_canvas.bbox("all")
        if bounds:
            self.analysis_canvas.configure(scrollregion=bounds)

    def _resize_analysis_content(self, event: tk.Event) -> None:
        self.analysis_canvas.itemconfigure(self._analysis_content_window, width=event.width)

    def _scroll_analysis_tab(self, event: tk.Event) -> Optional[str]:
        if self.notebook.select() != str(self.analysis_tab):
            return None

        hovered = self.root.winfo_containing(event.x_root, event.y_root)
        cursor = hovered
        while cursor is not None and cursor is not self.analysis_tab:
            cursor = getattr(cursor, "master", None)
        if cursor is not self.analysis_tab:
            return None

        if getattr(event, "num", None) == 4:
            direction = -1
        elif getattr(event, "num", None) == 5:
            direction = 1
        else:
            delta = getattr(event, "delta", 0)
            if delta == 0:
                return None
            direction = -1 if delta > 0 else 1
        self.analysis_canvas.yview_scroll(direction, "units")
        return "break"

    def create_analysis_tab(self, parent: ttk.Frame) -> None:
        game_card = ttk.LabelFrame(parent, text="Партия", padding=(10, 7))
        game_card.pack(fill=tk.X, padx=6, pady=(6, 4))
        self.game_info_label = ttk.Label(
            game_card,
            text="Партия не загружена",
            wraplength=INFO_PANEL_WIDTH - 36,
            justify=tk.LEFT,
        )
        self.game_info_label.pack(anchor=tk.NW, fill=tk.X)

        moves_card = ttk.LabelFrame(parent, text="Ходы", padding=(8, 6))
        moves_card.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
        search_frame = ttk.Frame(moves_card)
        search_frame.pack(fill=tk.X, pady=(0, 4))
        self.move_search_var = tk.StringVar()
        self.move_search_entry = ttk.Entry(search_frame, textvariable=self.move_search_var)
        self.move_search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.move_search_entry.insert(0, "")
        self.move_search_entry.bind("<Escape>", lambda event: self.clear_move_search())
        self.move_search_var.trace_add("write", lambda *_: self.populate_moves_listbox())
        ttk.Button(search_frame, text="×", width=3, command=self.clear_move_search).pack(side=tk.LEFT, padx=(6, 0))
        self.move_search_hint = ttk.Label(
            moves_card,
            text="Поиск по ходу, номеру или комментарию",
            foreground=self.COLORS["muted"],
            style="Muted.TLabel",
        )
        self.move_search_hint.pack(anchor=tk.W, pady=(0, 4))

        moves_frame = ttk.Frame(moves_card)
        moves_frame.pack(fill=tk.BOTH, expand=True)
        self.moves_scrollbar = ttk.Scrollbar(moves_frame, orient=tk.VERTICAL)
        self.moves_tree = ttk.Treeview(
            moves_frame,
            yscrollcommand=self.moves_scrollbar.set,
            show="tree",
            selectmode="browse",
            height=8,
        )
        self.moves_tree.column("#0", anchor=tk.W, stretch=True, width=260, minwidth=160)
        self.moves_scrollbar.config(command=self.moves_tree.yview)
        self.moves_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.moves_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.moves_tree.bind("<<TreeviewSelect>>", self.on_move_select_from_tree)
        self.moves_tree.bind("<Button-2>", self.show_annotation_menu)
        self.moves_tree.bind("<Button-3>", self.show_annotation_menu)
        self.moves_tree.bind("<Control-Button-1>", self.show_annotation_menu)

        analysis_buttons_frame = ttk.Frame(parent)
        analysis_buttons_frame.pack(fill=tk.X, padx=6, pady=6)
        self.analyze_game_button = ttk.Button(
            analysis_buttons_frame,
            text="Анализировать партию",
            command=self.start_full_game_analysis,
            style=self.primary_button_style,
        )
        if self.is_macos:
            self.analyze_game_button.state(["alternate"])
        self.analyze_game_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5))
        self.threat_button = ttk.Button(analysis_buttons_frame, text="Показать угрозу (T)", command=self.show_threat)
        self.threat_button.pack(side=tk.LEFT, expand=True, fill=tk.X)

        engine_settings_frame = ttk.LabelFrame(parent, text="Настройки движка", padding=6)
        engine_settings_frame.pack(fill=tk.X, padx=6, pady=6)

        skill_frame = ttk.Frame(engine_settings_frame)
        skill_frame.pack(fill=tk.X)
        ttk.Label(skill_frame, text="Сила (0-20):").pack(side=tk.LEFT)
        self.skill_scale = ttk.Scale(
            skill_frame,
            from_=0,
            to=20,
            orient=tk.HORIZONTAL,
            variable=self.engine_skill_var,
            command=self.update_engine_skill,
        )
        self.skill_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        ttk.Label(skill_frame, textvariable=self.engine_skill_var, width=2).pack(side=tk.LEFT)

        multipv_frame = ttk.Frame(engine_settings_frame)
        multipv_frame.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(multipv_frame, text="Количество строк (1-10):").pack(side=tk.LEFT)
        self.multipv_spinbox = ttk.Spinbox(
            multipv_frame,
            from_=1,
            to=10,
            textvariable=self.engine_multipv_var,
            width=3,
            command=self.update_engine_multipv,
        )
        self.multipv_spinbox.pack(side=tk.LEFT, padx=6)

        time_frame = ttk.Frame(engine_settings_frame)
        time_frame.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(time_frame, text="Время (мс):").pack(side=tk.LEFT)
        self.time_spinbox = ttk.Spinbox(
            time_frame,
            from_=200,
            to=10000,
            increment=100,
            textvariable=self.engine_time_var,
            width=8,
        )
        self.time_spinbox.pack(side=tk.LEFT, padx=6)

        eval_frame = ttk.LabelFrame(parent, text="Лучшие ходы", padding=6)
        eval_frame.pack(fill=tk.X, padx=6, pady=6)
        columns = ("#1", "#2", "#3")
        self.eval_tree = ttk.Treeview(eval_frame, columns=columns, show="headings", height=4)
        self.eval_tree.heading("#1", text="№")
        self.eval_tree.column("#1", width=30, anchor="center")
        self.eval_tree.heading("#2", text="Ход")
        self.eval_tree.column("#2", width=120, anchor="w")
        self.eval_tree.heading("#3", text="Оценка")
        self.eval_tree.column("#3", width=90, anchor="w")
        self.eval_tree.pack(fill=tk.X, expand=True)
        self.eval_tree.bind("<Double-1>", lambda e: self.add_selected_engine_variation())

        coach_frame = ttk.LabelFrame(parent, text="Тренер", padding=6)
        coach_frame.pack(fill=tk.X, padx=6, pady=6)
        ttk.Checkbutton(
            coach_frame,
            text="Показывать подсказки",
            variable=self.coach_mode_var,
            command=self.toggle_coach_mode,
        ).pack(anchor=tk.W)
        self.coach_hint_var = tk.StringVar(value="Подсказка появится после анализа позиции или старта задачи.")
        self.coach_hint_label = ttk.Label(
            coach_frame,
            textvariable=self.coach_hint_var,
            wraplength=INFO_PANEL_WIDTH - 40,
            justify=tk.LEFT,
        )
        self.coach_hint_label.pack(fill=tk.X, pady=(6, 0))

        self.game_status_label = ttk.Label(
            parent,
            text="",
            font=self._heading_font,
            foreground=self.COLORS["selection"],
        )
        self.game_status_label.pack(anchor=tk.NW, fill=tk.X, pady=6, padx=6)

    def create_graph_tab(self, parent: ttk.Frame) -> None:
        self.fig = Figure(figsize=(4, 3), dpi=100, facecolor=self.COLORS["bg"])
        self.ax = self.fig.add_subplot(111)
        self.ax.set_title("Оценка партии")
        self.ax.set_xlabel("Номер хода")
        self.ax.set_ylabel("Оценка (сантипешки)")
        self.ax.grid(True)
        self.fig.tight_layout()

        self.graph_canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.graph_canvas.draw()
        graph_widget = self.graph_canvas.get_tk_widget()
        graph_widget.configure(bg=self.COLORS["bg"], highlightthickness=0)
        graph_widget.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.graph_canvas.mpl_connect("button_press_event", self.on_graph_click)
        self.update_evaluation_graph(force=True)

    def create_report_tab(self, parent: ttk.Frame) -> None:
        buttons = ttk.Frame(parent)
        buttons.pack(fill=tk.X, padx=6, pady=(6, 0))
        ttk.Button(buttons, text="Анализировать", command=self.start_full_game_analysis).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(buttons, text="Найти ход", command=self.start_best_move_challenge).pack(side=tk.LEFT, padx=(0, 6))
        self.start_generated_puzzles_button = ttk.Button(
            buttons,
            text="Задачи из ошибок",
            command=self.start_generated_puzzle_session,
            state=tk.DISABLED,
        )
        self.start_generated_puzzles_button.pack(side=tk.LEFT)

        self.report_text = tk.Text(
            parent,
            wrap=tk.WORD,
            height=20,
            bg=self.COLORS["surface"],
            fg=self.COLORS["text"],
            insertbackground=self.COLORS["text"],
            selectbackground=self.COLORS["selection"],
            relief=tk.FLAT,
            padx=10,
            pady=10,
        )
        self.report_text.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.report_text.insert("1.0", "Отчет по партии появится здесь.")
        self.report_text.configure(state=tk.DISABLED)

    def create_variation_tab(self, parent: ttk.Frame) -> None:
        buttons = ttk.Frame(parent)
        buttons.pack(fill=tk.X, padx=6, pady=(6, 0))
        ttk.Button(buttons, text="Добавить из анализа", command=self.add_selected_engine_variation).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(buttons, text="В главную", command=self.promote_selected_variation_to_main).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(buttons, text="Удалить", command=self.delete_selected_variation).pack(side=tk.LEFT)

        self.variation_tree = ttk.Treeview(parent, show="tree")
        self.variation_tree.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.variation_tree.bind("<<TreeviewSelect>>", self.on_variation_tree_select)

    def on_board_area_configure(self, event: Optional[tk.Event] = None) -> None:
        self._schedule_responsive_refresh()

    def on_info_panel_configure(self, event: Optional[tk.Event] = None) -> None:
        self._schedule_responsive_refresh()

    def _schedule_responsive_refresh(self) -> None:
        pending_job = getattr(self, "_responsive_refresh_job", None)
        if pending_job is not None:
            self.root.after_cancel(pending_job)
        self._responsive_refresh_job = self.root.after(60, self.refresh_responsive_layout)

    def refresh_responsive_layout(self) -> None:
        self._responsive_refresh_job = None

        if not hasattr(self, "board_area") or not hasattr(self, "board_canvas"):
            return

        available_width = self.board_area.winfo_width()
        available_height = self.board_area.winfo_height()
        if available_width <= 1 or available_height <= 1:
            return

        new_board_size = min(available_width, available_height)
        new_board_size = max(self.min_board_size, new_board_size)
        new_board_size = max(8, (new_board_size // 8) * 8)

        if new_board_size != self.board_size:
            self.board_size = new_board_size
            self.square_size = max(1, self.board_size // 8)
            self.refresh_scaled_assets()
            self.board_canvas.config(width=self.board_size, height=self.board_size)
            self.redraw_board_background()
            self.update_board_display()

        self.refresh_info_panel_layout()

    def refresh_info_panel_layout(self) -> None:
        panel_width = self.info_panel.winfo_width() if hasattr(self, "info_panel") else INFO_PANEL_WIDTH
        if panel_width <= 1:
            panel_width = INFO_PANEL_WIDTH

        if hasattr(self, "game_info_label"):
            self.game_info_label.configure(wraplength=max(180, panel_width - 48))
        if hasattr(self, "coach_hint_label"):
            self.coach_hint_label.configure(wraplength=max(160, panel_width - 40))
        if hasattr(self, "moves_tree"):
            self.moves_tree.column("#0", width=max(160, panel_width - 56), minwidth=160)

        if hasattr(self, "eval_tree"):
            available_width = max(210, panel_width - 36)
            rank_width = 42
            score_width = max(76, min(110, available_width // 3))
            move_width = max(92, available_width - rank_width - score_width)
            self.eval_tree.column("#1", width=rank_width, minwidth=rank_width, anchor="center")
            self.eval_tree.column("#2", width=move_width, minwidth=92, anchor="w")
            self.eval_tree.column("#3", width=score_width, minwidth=76, anchor="w")

    def bind_shortcuts(self) -> None:
        self.root.bind("<space>", lambda e: self.run_shortcut(e, self.toggle_board_only))
        self.root.bind("<Home>", lambda e: self.run_shortcut(e, self.first_move_action))
        self.root.bind("<Left>", lambda e: self.run_shortcut(e, self.prev_move_action))
        self.root.bind("<Right>", lambda e: self.run_shortcut(e, self.next_move_action))
        self.root.bind("<End>", lambda e: self.run_shortcut(e, self.last_move_action))
        self.root.bind("f", lambda e: self.run_shortcut(e, self.flip_board))
        self.root.bind("F", lambda e: self.run_shortcut(e, self.flip_board))
        self.root.bind("a", lambda e: self.run_shortcut(e, self.request_analysis_current_pos))
        self.root.bind("A", lambda e: self.run_shortcut(e, self.request_analysis_current_pos))
        self.root.bind("t", lambda e: self.run_shortcut(e, self.show_threat))
        self.root.bind("T", lambda e: self.run_shortcut(e, self.show_threat))
        self.root.bind("p", lambda e: self.run_shortcut(e, self.start_best_move_challenge))
        self.root.bind("P", lambda e: self.run_shortcut(e, self.start_best_move_challenge))
        self.root.bind("h", lambda e: self.run_shortcut(e, self.show_help_dialog))
        self.root.bind("H", lambda e: self.run_shortcut(e, self.show_help_dialog))
        self.root.bind("<Control-f>", self.focus_move_search)
        self.root.bind("<Command-f>", self.focus_move_search)
        self.root.bind("<Control-o>", lambda e: self.load_pgn())
        self.root.bind("<Command-o>", lambda e: self.load_pgn())
        self.root.bind("<Control-b>", lambda e: self.run_shortcut(e, self.toggle_info_panel_visibility))
        self.root.bind("<Command-b>", lambda e: self.run_shortcut(e, self.toggle_info_panel_visibility))

    def run_shortcut(self, event: tk.Event, callback) -> Optional[str]:
        if event.widget.winfo_class() in {"Entry", "TEntry", "Text", "Spinbox", "TSpinbox"}:
            return None
        callback()
        return "break"

    def update_board_display(
        self,
        move_to_animate: Optional[chess.Move] = None,
        captured: bool = False,
        is_reverse_animation: bool = False,
        animated_piece_symbol: Optional[str] = None,
    ) -> None:
        if self.is_animating:
            return
        self.board_canvas.delete("piece", "arrow", "threat_arrow", "hint_overlay")
        self.clear_highlighted_squares()
        self.threat_move_obj = None

        if move_to_animate and animated_piece_symbol:
            excluded_squares = animation_excluded_squares(
                move_to_animate.from_square,
                move_to_animate.to_square,
                is_reverse=is_reverse_animation,
                captured=captured,
            )
            self._draw_all_pieces(excluded_squares=excluded_squares)
            self.draw_board_coordinates()
            self.is_animating = True
            self.animate_move(move_to_animate, captured, is_reverse_animation, animated_piece_symbol)
        else:
            self._draw_all_pieces()
            self._draw_move_arrows()
            self.draw_board_coordinates()
            if self.board_only_mode:
                self._draw_board_hints()

    def clear_move_search(self) -> None:
        if hasattr(self, "move_search_var"):
            self.move_search_var.set("")
            self.move_search_entry.focus_set()

    def focus_move_search(self, event: Optional[tk.Event] = None) -> str:
        if hasattr(self, "move_search_entry"):
            self.move_search_entry.focus_set()
            self.move_search_entry.selection_range(0, tk.END)
        return "break"

    def toggle_board_coordinates(self) -> None:
        self.draw_board_coordinates()
        state = "включены" if self.show_coordinates_var.get() else "скрыты"
        self.set_status_message(f"Координаты доски {state}", clear_after_ms=2500)

    def toggle_sound(self) -> None:
        requested = self.sound_enabled_var.get()
        if requested and not pygame.mixer.get_init():
            self.sound_enabled_var.set(False)
            self.sound_enabled = False
            messagebox.showwarning("Звук недоступен", "Аудиосистема не инициализирована.")
            return
        self.sound_enabled = requested
        state = "включены" if requested else "выключены"
        self.set_status_message(f"Звуки ходов {state}", clear_after_ms=2500)

    def toggle_animations(self) -> None:
        state = "включена" if self.animations_enabled_var.get() else "выключена"
        self.set_status_message(f"Анимация ходов {state}", clear_after_ms=2500)

    def _draw_all_pieces(self, excluded_squares: Optional[set[int]] = None) -> None:
        self.board_canvas.delete("piece")
        excluded_squares = excluded_squares or set()
        for square_index in chess.SQUARES:
            if square_index in excluded_squares or (self.is_dragging and self.drag_from_square == square_index):
                continue
            piece = self.board_state.piece_at(square_index)
            if not piece:
                continue
            symbol = piece.symbol()
            image = self.piece_images.get(symbol)
            x, y = self.get_square_coords(square_index)
            if image:
                self.board_canvas.create_image(x, y, anchor=tk.NW, image=image, tags=("piece", f"piece_at_{square_index}"))
            else:
                self.board_canvas.create_text(
                    x + self.square_size / 2,
                    y + self.square_size / 2,
                    text=symbol,
                    font=("Arial", max(12, self.square_size // 3)),
                    tags=("piece", f"piece_at_{square_index}"),
                )

    def _draw_move_arrows(self) -> None:
        self.board_canvas.delete("arrow")
        if self.current_game_node and self.current_game_node.move:
            move = self.current_game_node.move
            self.draw_arrow(move.from_square, move.to_square, color="#3366CC", width=3, tag="last_move_arrow")

        best_moves = self.get_best_moves_from_treeview()
        if best_moves:
            try:
                self.draw_arrow(best_moves[0].from_square, best_moves[0].to_square, color="#228B22", width=4, tag="engine_arrow")
            except Exception:
                pass
            for move in best_moves[1:]:
                try:
                    self.draw_arrow(move.from_square, move.to_square, color="#FFA500", width=2, tag="engine_arrow")
                except Exception:
                    pass

        if self.threat_move_obj:
            self.draw_arrow(
                self.threat_move_obj.from_square,
                self.threat_move_obj.to_square,
                color="#FF0000",
                width=4,
                tag="threat_arrow",
            )

    def _draw_board_hints(self) -> None:
        width = min(220, max(150, self.board_size - 16))
        line_height = 16
        height = len(BOARD_ONLY_HINTS) * line_height + 12
        x = self.board_size - width - 8
        y = self.board_size - height - 8
        self.board_canvas.create_rectangle(
            x,
            y,
            x + width,
            y + height,
            fill="#111111",
            outline="#444444",
            width=1,
            stipple="gray25",
            tags="hint_overlay",
        )
        for idx, line in enumerate(BOARD_ONLY_HINTS):
            self.board_canvas.create_text(
                x + 8,
                y + 8 + idx * line_height,
                anchor="nw",
                text=line,
                font=("Arial", 9),
                fill="white",
                tags="hint_overlay",
            )

    def get_square_coords(self, square_index: int) -> tuple[int, int]:
        file_index = chess.square_file(square_index)
        rank_index = chess.square_rank(square_index)
        if self.board_orientation_white_pov:
            x, y = file_index * self.square_size, (7 - rank_index) * self.square_size
        else:
            x, y = (7 - file_index) * self.square_size, rank_index * self.square_size
        return x, y

    def get_square_from_coords(self, x: int, y: int) -> Optional[int]:
        if x < 0 or y < 0 or x >= self.board_size or y >= self.board_size:
            return None
        file_index = int(x // self.square_size)
        rank_index = int(y // self.square_size)
        if self.board_orientation_white_pov:
            file_index, rank_index = file_index, 7 - rank_index
        else:
            file_index, rank_index = 7 - file_index, rank_index
        if 0 <= file_index <= 7 and 0 <= rank_index <= 7:
            return chess.square(file_index, rank_index)
        return None

    def draw_arrow(self, from_sq: int, to_sq: int, color: str, width: int, tag: str) -> None:
        x1, y1 = self.get_square_coords(from_sq)
        x2, y2 = self.get_square_coords(to_sq)
        center_offset = self.square_size / 2
        self.board_canvas.create_line(
            x1 + center_offset,
            y1 + center_offset,
            x2 + center_offset,
            y2 + center_offset,
            arrow=tk.LAST,
            fill=color,
            width=width,
            tags=(tag, "arrow"),
        )

    def update_navigation_buttons(self) -> None:
        if self.current_game_node:
            can_go_back = tk.NORMAL if self.current_game_node.parent else tk.DISABLED
            can_go_forward = tk.NORMAL if self.current_game_node.variations else tk.DISABLED
            self.first_move_button.config(state=can_go_back)
            self.prev_move_button.config(state=can_go_back)
            self.next_move_button.config(state=can_go_forward)
            self.last_move_button.config(state=can_go_forward)
        else:
            self.first_move_button.config(state=tk.DISABLED)
            self.prev_move_button.config(state=tk.DISABLED)
            self.next_move_button.config(state=tk.DISABLED)
            self.last_move_button.config(state=tk.DISABLED)

    def flip_board(self) -> None:
        if self.is_animating:
            return
        self.board_orientation_white_pov = not self.board_orientation_white_pov
        self.clear_highlighted_squares()
        self.selected_square_for_move = None
        self.update_board_display()
        self.set_status_message("Доска перевернута", clear_after_ms=2000)

    def highlight_legal_moves(self, from_square: int) -> None:
        self.clear_highlighted_squares()
        x, y = self.get_square_coords(from_square)
        self.board_canvas.create_rectangle(
            x,
            y,
            x + self.square_size,
            y + self.square_size,
            outline="#FFD700",
            width=4,
            tags="highlight_selected",
        )

        for move in self.board_state.legal_moves:
            if move.from_square != from_square:
                continue
            to_x, to_y = self.get_square_coords(move.to_square)
            radius = self.square_size / 6
            fill_color = "#FF6060" if self.board_state.is_capture(move) else "#A0A0A0"
            self.board_canvas.create_oval(
                to_x + self.square_size / 2 - radius,
                to_y + self.square_size / 2 - radius,
                to_x + self.square_size / 2 + radius,
                to_y + self.square_size / 2 + radius,
                fill=fill_color,
                outline="",
                tags="highlight",
            )

    def clear_highlighted_squares(self) -> None:
        self.board_canvas.delete("highlight_selected", "highlight")

    def clear_evaluation_display(self) -> None:
        for item in self.eval_tree.get_children():
            self.eval_tree.delete(item)
        self.board_canvas.delete("engine_arrow")

    def update_eval_bar(self, score_cp: Optional[int], score_mate: Optional[int], max_eval_cp: int = 1000) -> None:
        normalized_score, text = 0.5, "0.0"
        if self.board_state.is_checkmate():
            normalized_score = 0.0 if self.board_state.turn == chess.WHITE else 1.0
            text = "МАТ"
        elif score_mate is not None:
            white_mate_score = mate_to_white_perspective(score_mate, self.board_state.turn)
            normalized_score = 1.0 if white_mate_score > 0 else 0.0
            text = f"M{abs(score_mate)}"
        elif score_cp is not None:
            white_score = score_to_white_perspective(score_cp, self.board_state.turn)
            clamped_score = max(-max_eval_cp, min(max_eval_cp, white_score))
            normalized_score = (clamped_score / max_eval_cp) * 0.5 + 0.5
            text = f"{white_score / 100.0:+.2f}"

        self.evaluation_progress_var.set(normalized_score * 100.0)
        self.evaluation_text_var.set(text)

    def play_sound(self, captured: bool) -> None:
        if not getattr(self, "sound_enabled", False):
            return
        try:
            sound = self.capture_sound if captured else self.move_sound
            if sound:
                sound.play()
        except Exception as exc:
            print(f"Ошибка воспроизведения звука: {exc}")

    def toggle_board_only(self) -> None:
        self.board_only_mode = not self.board_only_mode
        if self.board_only_mode:
            self._panel_visible_before_board_only = self.info_panel_visible_var.get()
            self.info_panel_visible_var.set(False)
            self.apply_info_panel_visibility()
            try:
                self.menu_bar.entryconfig("Файл", state="disabled")
            except Exception:
                pass
            self._draw_board_hints()
        else:
            self.info_panel_visible_var.set(getattr(self, "_panel_visible_before_board_only", True))
            self.apply_info_panel_visibility()
            try:
                self.menu_bar.entryconfig("Файл", state="normal")
            except Exception:
                pass
            self.board_canvas.delete("hint_overlay")
        self._schedule_responsive_refresh()
        self.update_board_display()

    def toggle_info_panel_visibility(self) -> None:
        if self.board_only_mode:
            self.toggle_board_only()
            if not self.info_panel_visible_var.get():
                self.info_panel_visible_var.set(True)
                self.apply_info_panel_visibility()
            return
        self.info_panel_visible_var.set(not self.info_panel_visible_var.get())
        self.apply_info_panel_visibility()

    def apply_info_panel_visibility(self) -> None:
        should_show = self.info_panel_visible_var.get()
        is_visible = bool(self.info_panel.grid_info())
        if should_show and not is_visible:
            self.main_frame.columnconfigure(2, minsize=self.min_info_panel_width)
            self.panel_resize_lane.grid()
            self.info_panel.grid()
            self.root.after_idle(self._restore_info_panel_width)
            self.set_status_message("Боковая панель показана", clear_after_ms=1800)
        elif not should_show and is_visible:
            self._saved_info_panel_width = self.info_panel.winfo_width()
            self.info_panel.grid_remove()
            self.panel_resize_lane.grid_remove()
            self.main_frame.columnconfigure(2, minsize=0)
            self.set_status_message("Боковая панель скрыта", clear_after_ms=1800)
        self._schedule_responsive_refresh()

    def _restore_info_panel_width(self) -> None:
        if not self.info_panel.grid_info():
            return
        total_width = self.main_frame.winfo_width()
        if total_width <= 1:
            self.root.after(50, self._restore_info_panel_width)
            return
        panel_width = max(
            self.min_info_panel_width,
            min(
                getattr(self, "_saved_info_panel_width", INFO_PANEL_WIDTH),
                total_width - self.min_board_size - self.panel_resize_lane.winfo_reqwidth(),
            ),
        )
        self.info_panel.configure(width=panel_width)

    def show_help_dialog(self) -> None:
        text = "\n".join(
            [
                "Горячие клавиши:",
                "Space - режим только доски",
                "Home / End - в начало / в конец партии",
                "Left / Right - перемотка ходов",
                "F - перевернуть доску",
                "A - анализ текущей позиции",
                "T - показать угрозу",
                "P - найти лучший ход",
                "Ctrl/Cmd + F - поиск по ходам",
                "Ctrl/Cmd + O - открыть PGN",
                "Ctrl/Cmd + B - показать/скрыть боковую панель",
                "Клик по графику - перейти к ходу",
                "Double click по лучшему ходу - добавить как вариант",
            ]
        )
        messagebox.showinfo("Помощь", text)
