import os
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

import chess
import pygame
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from PIL import Image, ImageTk

from config import (
    BOARD_IMG_HEIGHT,
    BOARD_IMG_WIDTH,
    BOARD_ONLY_HINTS,
    EVAL_BAR_HEIGHT,
    IMAGE_DIR,
    INFO_PANEL_WIDTH,
    PIECE_DIR,
    PIECE_SYMBOL_TO_FILE,
    SOUND_DIR,
    SQUARE_SIZE,
)
from .analysis_utils import mate_to_white_perspective, score_to_white_perspective
from .helpers import make_placeholder_piece


class UIFlowMixin:
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
        try:
            board_img_path = os.path.join(IMAGE_DIR, "board.png")
            if os.path.exists(board_img_path):
                pil_board_image = Image.open(board_img_path).resize((BOARD_IMG_WIDTH, BOARD_IMG_HEIGHT), Image.LANCZOS)
                self.board_bg_image = ImageTk.PhotoImage(pil_board_image)
            else:
                self.board_bg_image = None
        except Exception:
            self.board_bg_image = None

        for symbol in list("PNBRQKpnbrqk"):
            self.piece_images[symbol] = None
        for symbol, filename in PIECE_SYMBOL_TO_FILE.items():
            color_folder = "white" if symbol.isupper() else "black"
            path = os.path.join(PIECE_DIR, color_folder, filename)
            if os.path.exists(path):
                try:
                    img = Image.open(path).resize((SQUARE_SIZE, SQUARE_SIZE), Image.LANCZOS)
                    self.piece_images[symbol] = ImageTk.PhotoImage(img)
                except Exception:
                    fallback_symbol = symbol.upper() if symbol.isupper() else symbol.lower()
                    self.piece_images[symbol] = make_placeholder_piece(fallback_symbol)
            else:
                fallback_symbol = symbol.upper() if symbol.isupper() else symbol.lower()
                self.piece_images[symbol] = make_placeholder_piece(fallback_symbol)

    def create_widgets(self) -> None:
        self.main_frame = ttk.Frame(self.root, padding=8)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        left_frame = ttk.Frame(self.main_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        self.board_canvas = tk.Canvas(
            left_frame,
            width=BOARD_IMG_WIDTH,
            height=BOARD_IMG_HEIGHT,
            bg="grey20",
            highlightthickness=0,
        )
        self.board_canvas.pack()
        if getattr(self, "board_bg_image", None):
            self.board_canvas.create_image(0, 0, anchor=tk.NW, image=self.board_bg_image)

        self.create_board_controls(left_frame)

        self.info_panel = ttk.Frame(self.main_frame, width=INFO_PANEL_WIDTH)
        self.info_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=False)
        self.info_panel.pack_propagate(False)
        self.create_info_panel_widgets()

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

        self.first_move_button = ttk.Button(pgn_controls_frame, text="|<", command=self.first_move_action, state=tk.DISABLED)
        self.first_move_button.pack(side=tk.LEFT, padx=2)
        self.prev_move_button = ttk.Button(pgn_controls_frame, text="<", command=self.prev_move_action, state=tk.DISABLED)
        self.prev_move_button.pack(side=tk.LEFT, padx=2)
        self.next_move_button = ttk.Button(pgn_controls_frame, text=">", command=self.next_move_action, state=tk.DISABLED)
        self.next_move_button.pack(side=tk.LEFT, padx=2)
        self.last_move_button = ttk.Button(pgn_controls_frame, text=">|", command=self.last_move_action, state=tk.DISABLED)
        self.last_move_button.pack(side=tk.LEFT, padx=2)
        self.flip_board_button = ttk.Button(pgn_controls_frame, text="Перевернуть (F)", command=self.flip_board)
        self.flip_board_button.pack(side=tk.LEFT, padx=6)
        self.copy_fen_button = ttk.Button(pgn_controls_frame, text="Копировать FEN", command=self.export_fen_to_clipboard)
        self.copy_fen_button.pack(side=tk.LEFT, padx=6)

        self.eval_bar_canvas = tk.Canvas(parent, height=EVAL_BAR_HEIGHT, bg="dim gray", highlightthickness=0)
        self.eval_bar_canvas.pack(fill=tk.X, pady=(6, 0))
        self.eval_line = self.eval_bar_canvas.create_rectangle(0, 0, BOARD_IMG_WIDTH / 2, EVAL_BAR_HEIGHT, fill="white", outline="")
        self.eval_text = self.eval_bar_canvas.create_text(
            BOARD_IMG_WIDTH / 2,
            EVAL_BAR_HEIGHT / 2,
            text="0.0",
            fill="black",
            font=("Arial", 10, "bold"),
        )

    def create_info_panel_widgets(self) -> None:
        self.notebook = ttk.Notebook(self.info_panel)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=6)

        analysis_tab = ttk.Frame(self.notebook)
        self.notebook.add(analysis_tab, text="Анализ")
        self.create_analysis_tab(analysis_tab)

        self.graph_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.graph_tab, text="График")
        self.create_graph_tab(self.graph_tab)

        self.report_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.report_tab, text="Отчет")
        self.create_report_tab(self.report_tab)

        self.variations_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.variations_tab, text="Варианты")
        self.create_variation_tab(self.variations_tab)

    def create_analysis_tab(self, parent: ttk.Frame) -> None:
        self.game_info_label = ttk.Label(parent, text="Партия не загружена", wraplength=INFO_PANEL_WIDTH - 20, justify=tk.LEFT)
        self.game_info_label.pack(anchor=tk.NW, pady=6, fill=tk.X, padx=6)

        moves_frame = ttk.Frame(parent)
        moves_frame.pack(fill=tk.BOTH, expand=True, pady=6, padx=6)
        self.moves_scrollbar = ttk.Scrollbar(moves_frame, orient=tk.VERTICAL)
        self.moves_listbox = tk.Listbox(moves_frame, yscrollcommand=self.moves_scrollbar.set, exportselection=False, font=("Courier", 10))
        self.moves_scrollbar.config(command=self.moves_listbox.yview)
        self.moves_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.moves_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.moves_listbox.bind("<<ListboxSelect>>", self.on_move_select_from_listbox)
        self.moves_listbox.bind("<Button-3>", self.show_annotation_menu)

        analysis_buttons_frame = ttk.Frame(parent)
        analysis_buttons_frame.pack(fill=tk.X, padx=6, pady=6)
        self.analyze_game_button = ttk.Button(analysis_buttons_frame, text="Анализировать партию", command=self.start_full_game_analysis)
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
        ttk.Label(
            coach_frame,
            textvariable=self.coach_hint_var,
            wraplength=INFO_PANEL_WIDTH - 40,
            justify=tk.LEFT,
        ).pack(fill=tk.X, pady=(6, 0))

        self.game_status_label = ttk.Label(parent, text="", font=("Arial", 10, "bold"), foreground="blue")
        self.game_status_label.pack(anchor=tk.NW, fill=tk.X, pady=6, padx=6)

    def create_graph_tab(self, parent: ttk.Frame) -> None:
        self.fig = Figure(figsize=(4, 3), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_title("Оценка партии")
        self.ax.set_xlabel("Номер хода")
        self.ax.set_ylabel("Оценка (сантипешки)")
        self.ax.grid(True)
        self.fig.tight_layout()

        self.graph_canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.graph_canvas.draw()
        self.graph_canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.update_evaluation_graph()

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

        self.report_text = tk.Text(parent, wrap=tk.WORD, height=20)
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

    def bind_shortcuts(self) -> None:
        self.root.bind("<space>", lambda e: self.toggle_board_only())
        self.root.bind("<Home>", lambda e: self.first_move_action())
        self.root.bind("<Left>", lambda e: self.prev_move_action())
        self.root.bind("<Right>", lambda e: self.next_move_action())
        self.root.bind("<End>", lambda e: self.last_move_action())
        self.root.bind("f", lambda e: self.flip_board())
        self.root.bind("F", lambda e: self.flip_board())
        self.root.bind("a", lambda e: self.request_analysis_current_pos())
        self.root.bind("A", lambda e: self.request_analysis_current_pos())
        self.root.bind("t", lambda e: self.show_threat())
        self.root.bind("T", lambda e: self.show_threat())
        self.root.bind("p", lambda e: self.start_best_move_challenge())
        self.root.bind("P", lambda e: self.start_best_move_challenge())
        self.root.bind("h", lambda e: self.show_help_dialog())
        self.root.bind("H", lambda e: self.show_help_dialog())

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
            self.is_animating = True
            self.animate_move(move_to_animate, captured, is_reverse_animation, animated_piece_symbol)
        else:
            self._draw_all_pieces()
            self._draw_move_arrows()
            if self.board_only_mode:
                self._draw_board_hints()

    def _draw_all_pieces(self) -> None:
        self.board_canvas.delete("piece")
        for square_index in chess.SQUARES:
            if self.is_dragging and self.drag_from_square == square_index:
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
                    x + SQUARE_SIZE / 2,
                    y + SQUARE_SIZE / 2,
                    text=symbol,
                    font=("Arial", 18),
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
        width = 220
        height = len(BOARD_ONLY_HINTS) * 16 + 12
        x = BOARD_IMG_WIDTH - width - 8
        y = BOARD_IMG_HEIGHT - height - 8
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
                y + 8 + idx * 16,
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
            x, y = file_index * SQUARE_SIZE, (7 - rank_index) * SQUARE_SIZE
        else:
            x, y = (7 - file_index) * SQUARE_SIZE, rank_index * SQUARE_SIZE
        return x, y

    def get_square_from_coords(self, x: int, y: int) -> Optional[int]:
        if x < 0 or y < 0 or x >= BOARD_IMG_WIDTH or y >= BOARD_IMG_HEIGHT:
            return None
        file_index = int(x // SQUARE_SIZE)
        rank_index = int(y // SQUARE_SIZE)
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
        center_offset = SQUARE_SIZE / 2
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

    def highlight_legal_moves(self, from_square: int) -> None:
        self.clear_highlighted_squares()
        x, y = self.get_square_coords(from_square)
        self.board_canvas.create_rectangle(
            x,
            y,
            x + SQUARE_SIZE,
            y + SQUARE_SIZE,
            outline="#FFD700",
            width=4,
            tags="highlight_selected",
        )

        for move in self.board_state.legal_moves:
            if move.from_square != from_square:
                continue
            to_x, to_y = self.get_square_coords(move.to_square)
            radius = SQUARE_SIZE / 6
            fill_color = "#FF6060" if self.board_state.is_capture(move) else "#A0A0A0"
            self.board_canvas.create_oval(
                to_x + SQUARE_SIZE / 2 - radius,
                to_y + SQUARE_SIZE / 2 - radius,
                to_x + SQUARE_SIZE / 2 + radius,
                to_y + SQUARE_SIZE / 2 + radius,
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
        bar_width = self.eval_bar_canvas.winfo_width()
        if bar_width <= 1:
            bar_width = BOARD_IMG_WIDTH

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

        white_width = bar_width * normalized_score
        self.eval_bar_canvas.coords(self.eval_line, 0, 0, white_width, EVAL_BAR_HEIGHT)
        self.eval_bar_canvas.delete("black_part")
        self.eval_bar_canvas.create_rectangle(
            white_width,
            0,
            bar_width,
            EVAL_BAR_HEIGHT,
            fill="black",
            outline="",
            tags="black_part",
        )
        self.eval_bar_canvas.coords(self.eval_text, bar_width / 2, EVAL_BAR_HEIGHT / 2)
        self.eval_bar_canvas.itemconfig(self.eval_text, text=text)
        self.eval_bar_canvas.tag_raise(self.eval_text)

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
            self.info_panel.forget()
            try:
                self.menu_bar.entryconfig("Файл", state="disabled")
            except Exception:
                pass
            self._draw_board_hints()
        else:
            self.info_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=False)
            try:
                self.menu_bar.entryconfig("Файл", state="normal")
            except Exception:
                pass
            self.board_canvas.delete("hint_overlay")
        self.update_board_display()

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
                "Double click по лучшему ходу - добавить как вариант",
            ]
        )
        messagebox.showinfo("Помощь", text)
