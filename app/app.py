import queue
import tkinter as tk
from tkinter import messagebox
from typing import Dict, List, Optional

import chess
import chess.pgn
import pygame
from PIL import ImageTk

from config import (
    BOARD_IMG_WIDTH,
    DEFAULT_ENGINE_MOVETIME_MS,
    DEFAULT_ENGINE_MULTIPV,
    DEFAULT_ENGINE_SKILL,
    INFO_PANEL_MIN_WIDTH,
    MIN_BOARD_SIZE,
    SQUARE_SIZE,
)
from engine_handler import EngineHandler

from .analysis import AnalysisMixin
from .game import GameFlowMixin
from .interaction import InteractionMixin
from .reporting import GameReport, TrainingPuzzle
from .settings_utils import parse_bounded_int
from .ui import UIFlowMixin


class ChessAnalyzerApp(UIFlowMixin, GameFlowMixin, InteractionMixin, AnalysisMixin):
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("ChessAI")
        self.board_size = BOARD_IMG_WIDTH
        self.square_size = SQUARE_SIZE
        self.min_board_size = MIN_BOARD_SIZE
        self.min_info_panel_width = INFO_PANEL_MIN_WIDTH
        self.root.minsize(
            self.min_board_size + self.min_info_panel_width + 48,
            self.min_board_size + 180,
        )

        self.piece_images: Dict[str, ImageTk.PhotoImage] = {}
        self.current_game_node: Optional[chess.pgn.GameNode] = None
        self.board_state: chess.Board = chess.Board()
        self.board_orientation_white_pov: bool = True

        self.is_animating = False
        self.is_dragging = False
        self.drag_from_square: Optional[int] = None
        self.drag_image_id: Optional[int] = None
        self.selected_square_for_move: Optional[int] = None

        self.game_mode: str = "analysis"
        self.user_color: Optional[bool] = None
        self.evaluation_history: List[float] = []
        self.move_nodes_in_listbox: List[chess.pgn.GameNode] = []

        self.engine_skill_var = tk.IntVar(value=DEFAULT_ENGINE_SKILL)
        self.engine_multipv_var = tk.IntVar(value=DEFAULT_ENGINE_MULTIPV)
        self.engine_time_var = tk.IntVar(value=DEFAULT_ENGINE_MOVETIME_MS)

        self.board_only_mode = False
        self.hints_overlay_id = None

        self.analysis_queue: queue.Queue = queue.Queue()
        self.threat_move_obj: Optional[chess.Move] = None
        self.latest_analysis_lines: List[dict] = []
        self.latest_analysis_fen: Optional[str] = None
        self.current_coach_hint: str = ""
        self.latest_game_report: Optional[GameReport] = None

        self.training_puzzles: List[TrainingPuzzle] = []
        self.training_session_name: str = ""
        self.training_index: int = -1
        self.training_score: int = 0
        self.training_restore_state: Optional[dict] = None

        self.variation_tree_nodes: Dict[str, chess.pgn.GameNode] = {}
        self.coach_mode_var = tk.BooleanVar(value=True)

        self.analysis_in_flight = False
        self.pending_analysis_fen: Optional[str] = None
        self.full_analysis_in_progress = False

        self.init_sound()

        self.engine = EngineHandler(initial_skill_level=self.get_engine_skill_level())
        if not self.engine.process:
            messagebox.showwarning("Ошибка движка", "Stockfish не найден. Анализ будет недоступен.")

        self.load_assets()
        self.create_widgets()
        self.bind_shortcuts()

        if not self.engine.process:
            self.analyze_game_button.config(state=tk.DISABLED)
            self.threat_button.config(state=tk.DISABLED)
            self.skill_scale.state(["disabled"])
            self.multipv_spinbox.state(["disabled"])
            self.time_spinbox.state(["disabled"])

        self.board_canvas.bind("<ButtonPress-1>", self.on_mouse_down)
        self.board_canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.board_canvas.bind("<ButtonRelease-1>", self.on_mouse_up)
        self.board_canvas.bind("<Motion>", self.on_mouse_move)
        self.board_canvas.bind("<Leave>", lambda e: self.board_canvas.configure(cursor="arrow"))

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.update_board_display()
        self.update_info_panel()
        self.process_analysis_queue()
        self.prompt_color_and_start()

    def _read_bounded_int_setting(
        self,
        variable: tk.IntVar,
        *,
        default: int,
        minimum: int,
        maximum: int,
        widget: Optional[tk.Entry] = None,
    ) -> int:
        try:
            raw_value = widget.get() if widget is not None else variable.get()
        except tk.TclError:
            raw_value = default

        value = parse_bounded_int(raw_value, default=default, minimum=minimum, maximum=maximum)
        variable.set(value)

        if widget is not None:
            widget.delete(0, tk.END)
            widget.insert(0, str(value))

        return value

    def get_engine_skill_level(self) -> int:
        return self._read_bounded_int_setting(
            self.engine_skill_var,
            default=DEFAULT_ENGINE_SKILL,
            minimum=0,
            maximum=20,
        )

    def get_engine_multipv(self) -> int:
        return self._read_bounded_int_setting(
            self.engine_multipv_var,
            default=DEFAULT_ENGINE_MULTIPV,
            minimum=1,
            maximum=10,
            widget=getattr(self, "multipv_spinbox", None),
        )

    def get_engine_movetime_ms(self) -> int:
        return self._read_bounded_int_setting(
            self.engine_time_var,
            default=DEFAULT_ENGINE_MOVETIME_MS,
            minimum=200,
            maximum=10000,
            widget=getattr(self, "time_spinbox", None),
        )

    def on_closing(self) -> None:
        self.is_animating = False
        if self.engine and self.engine.process:
            self.engine.quit_engine()
        if getattr(self, "sound_enabled", False) and pygame.mixer.get_init():
            pygame.mixer.quit()
        self.root.destroy()
