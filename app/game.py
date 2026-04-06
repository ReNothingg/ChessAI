import io
import random
import tkinter as tk
from tkinter import Toplevel, filedialog, messagebox, simpledialog, ttk
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import chess
import chess.pgn
import requests

from config import DEFAULT_BATCH_MOVETIME_MS

from .import_utils import (
    chesscom_game_json_to_pgn,
    extract_chesscom_game_ref,
    extract_lichess_game_id,
    looks_like_fen,
    looks_like_pgn,
)
from .openings import apply_opening_headers
from .reporting import build_report_text


class GameFlowMixin:
    LICHESS_TIMEOUT_SEC = 10
    PGN_ENCODINGS = ("utf-8-sig", "utf-8", "cp1251", "latin-1")

    def prompt_color_and_start(self) -> None:
        win = Toplevel(self.root)
        win.title("Новая игра")
        win.transient(self.root)
        win.grab_set()
        ttk.Label(win, text="Выберите режим:").pack(padx=12, pady=(12, 6))

        choice = tk.StringVar(value="random")
        for text, value in (("Белыми", "white"), ("Черными", "black"), ("Случайно", "random"), ("Только анализ", "analysis")):
            ttk.Radiobutton(win, text=text, value=value, variable=choice).pack(anchor="w", padx=12)

        buttons = ttk.Frame(win)
        buttons.pack(fill=tk.X, pady=12, padx=12)
        ttk.Button(buttons, text="OK", command=lambda: self._apply_start_choice(choice.get(), win)).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Отмена", command=win.destroy).pack(side=tk.RIGHT, padx=(0, 6))

    def _apply_start_choice(self, value: str, dialog: Toplevel) -> None:
        dialog.destroy()
        if value == "analysis":
            self.reset_to_new_game(chess.pgn.Game())
            self.game_mode = "analysis"
            self.user_color = None
            return

        color = random.choice([chess.WHITE, chess.BLACK]) if value == "random" else (chess.WHITE if value == "white" else chess.BLACK)
        self.user_color = color
        game = chess.pgn.Game()
        game.headers["Event"] = "Игра против движка"
        game.headers["White"] = "Человек" if color == chess.WHITE else "Stockfish"
        game.headers["Black"] = "Stockfish" if color == chess.BLACK else "Человек"
        self.reset_to_new_game(game, preserve_orientation=True)
        self.board_orientation_white_pov = self.user_color == chess.WHITE
        self.update_board_display()
        self.game_mode = "play_engine"
        if self.board_state.turn != self.user_color:
            expected_fen = self.board_state.fen()
            self.root.after(500, lambda fen=expected_fen: self.make_engine_move(expected_fen=fen))

    def refresh_opening_metadata(self):
        if not self.current_game_node:
            return None
        return apply_opening_headers(self.current_game_node.game())

    def update_info_panel(self) -> None:
        self.clear_evaluation_display()
        self.game_status_label.config(text="")

        if self.current_game_node:
            game_root_node = self.current_game_node.game()
            headers = game_root_node.headers
            opening = self.refresh_opening_metadata()

            info_lines = [
                f"Белые: {headers.get('White', '?')} ({headers.get('WhiteElo', 'Н/Д')})",
                f"Черные: {headers.get('Black', '?')} ({headers.get('BlackElo', 'Н/Д')})",
                f"Результат: {headers.get('Result', '*')}, Событие: {headers.get('Event', '?')}",
            ]
            if opening:
                info_lines.append(f"Дебют: {opening.eco} {opening.full_name}")
            elif headers.get("Opening"):
                variation = headers.get("Variation")
                opening_name = headers.get("Opening", "")
                info_lines.append(
                    f"Дебют: {headers.get('ECO', '?')} {opening_name}{': ' + variation if variation else ''}"
                )

            if self.training_puzzles and self.training_index >= 0:
                info_lines.append(
                    f"Тренировка: {self.training_session_name} ({self.training_index + 1}/{len(self.training_puzzles)}), очки: {self.training_score}"
                )

            self.game_info_label.config(text="\n".join(info_lines))

            self.populate_moves_listbox()
            self.populate_variation_tree()
            self.check_game_status()
            self.refresh_report_panel()

            if (
                not self.board_state.is_game_over()
                and self.game_mode == "analysis"
                and self.engine
                and self.engine.process
                and not self.full_analysis_in_progress
            ):
                self.request_analysis_current_pos()
            else:
                self.update_eval_bar(None, None)
                self.update_coach_hint_display(self.get_training_hint_text())
        else:
            self.game_info_label.config(text="Партия не загружена")
            self.moves_listbox.delete(0, tk.END)
            self.update_eval_bar(None, None)
            self.update_evaluation_graph()
            self.refresh_report_panel()
            self.populate_variation_tree()
            self.update_coach_hint_display("")

    def _get_active_line_nodes(self) -> List[chess.pgn.GameNode]:
        if not self.current_game_node:
            return []

        path_nodes: List[chess.pgn.GameNode] = []
        cursor = self.current_game_node
        while cursor.parent is not None:
            path_nodes.append(cursor)
            cursor = cursor.parent
        path_nodes.reverse()

        line_nodes = list(path_nodes)
        tail = self.current_game_node
        while tail.variations:
            tail = tail.variation(0)
            line_nodes.append(tail)
        return line_nodes

    def populate_moves_listbox(self) -> None:
        self.moves_listbox.delete(0, tk.END)
        self.move_nodes_in_listbox = []

        if not self.current_game_node:
            return

        game_root_node = self.current_game_node.game()
        board_for_san = game_root_node.board()
        line_nodes = self._get_active_line_nodes()

        self.moves_listbox.insert(tk.END, "--- Начало ---")
        self.move_nodes_in_listbox.append(game_root_node)

        for node in line_nodes:
            san_move = board_for_san.san(node.move)
            move_prefix = f"{board_for_san.fullmove_number}. " if board_for_san.turn == chess.WHITE else f"{board_for_san.fullmove_number}... "
            display_text = move_prefix + san_move

            if node.parent and node.parent.variation(0) != node:
                display_text = "[V] " + display_text

            nags = "".join([{1: "!", 2: "?", 3: "!!", 4: "??", 5: "!?", 6: "?!"}.get(nag, "") for nag in node.nags])
            if nags:
                display_text += f" {nags}"

            if node.comment:
                comment_text = node.comment.replace("\n", " ")
                display_text += f" ({comment_text[:40]})" if len(comment_text) > 40 else f" ({comment_text})"

            self.moves_listbox.insert(tk.END, display_text)
            self.move_nodes_in_listbox.append(node)
            board_for_san.push(node.move)

        try:
            idx_to_select = self.move_nodes_in_listbox.index(self.current_game_node)
            self.moves_listbox.selection_clear(0, tk.END)
            self.moves_listbox.selection_set(idx_to_select)
            self.moves_listbox.see(idx_to_select)
        except (ValueError, tk.TclError):
            pass

    def update_evaluation_graph(self) -> None:
        self.ax.clear()
        self.ax.grid(True)
        self.ax.set_title("Оценка партии")
        self.ax.set_xlabel("Номер полухода")
        self.ax.set_ylabel("Оценка (сантипешки)")

        if self.evaluation_history:
            plies = range(1, len(self.evaluation_history) + 1)
            self.ax.plot(plies, self.evaluation_history, marker="o", linestyle="-")
            self.ax.axhline(0, color="black", linewidth=0.8, linestyle="--")

            max_abs_eval = max(abs(evaluation) for evaluation in self.evaluation_history)
            display_max = min(max_abs_eval + 100, 1000)
            self.ax.set_ylim(-display_max, display_max)
        else:
            self.ax.text(
                0.5,
                0.5,
                "Нет данных для графика.\nВыполните «Анализировать партию».",
                horizontalalignment="center",
                verticalalignment="center",
                transform=self.ax.transAxes,
            )

        self.fig.tight_layout()
        self.graph_canvas.draw()

    def load_pgn(self) -> None:
        filepath = filedialog.askopenfilename(title="Открыть PGN", filetypes=(("PGN files", "*.pgn"), ("All files", "*.*")))
        if not filepath:
            return

        try:
            pgn_text = self._read_text_file_with_fallbacks(filepath)
            self.load_pgn_text(pgn_text)
        except Exception as exc:
            messagebox.showerror("Ошибка загрузки PGN", f"Произошла ошибка: {exc}")

    def load_pgn_text(self, pgn_text: str) -> None:
        pgn_io = io.StringIO(pgn_text)
        games: List[Tuple[dict, int]] = []
        while True:
            offset = pgn_io.tell()
            headers = chess.pgn.read_headers(pgn_io)
            if headers is None:
                break
            games.append((headers, offset))

        if not games:
            raise ValueError("Не найдено ни одной партии в источнике.")

        if len(games) == 1:
            self.load_game_from_pgn(pgn_text, 0)
        else:
            self.show_pgn_selection_window(pgn_text, games)

    def _read_text_file_with_fallbacks(self, filepath: str) -> str:
        last_error: Optional[Exception] = None
        for encoding in self.PGN_ENCODINGS:
            try:
                with open(filepath, "r", encoding=encoding) as pgn_file:
                    return pgn_file.read()
            except UnicodeDecodeError as exc:
                last_error = exc

        if last_error:
            raise last_error

        with open(filepath, "r", encoding="utf-8") as pgn_file:
            return pgn_file.read()

    def show_pgn_selection_window(self, pgn_text: str, games: List[Tuple[dict, int]]) -> None:
        win = Toplevel(self.root)
        win.title("Выберите партию")

        tree = ttk.Treeview(win, columns=("white", "black", "result"), show="headings")
        tree.heading("white", text="Белые")
        tree.heading("black", text="Черные")
        tree.heading("result", text="Результат")

        for idx, (headers, _) in enumerate(games):
            tree.insert("", "end", values=(headers.get("White", "?"), headers.get("Black", "?"), headers.get("Result", "*")), iid=idx)

        tree.pack(padx=10, pady=10, fill="both", expand=True)

        def on_load() -> None:
            selected_item = tree.selection()
            if not selected_item:
                return
            game_index = int(selected_item[0])
            offset = games[game_index][1]
            self.load_game_from_pgn(pgn_text, offset)
            win.destroy()

        load_button = ttk.Button(win, text="Загрузить", command=on_load)
        load_button.pack(pady=10)
        tree.bind("<Double-1>", lambda e: on_load())

    def load_game_from_pgn(self, pgn_text: str, offset: int) -> None:
        pgn_io = io.StringIO(pgn_text)
        pgn_io.seek(offset)
        game = chess.pgn.read_game(pgn_io)
        if game:
            self.reset_to_new_game(game, preserve_orientation=True)
        else:
            messagebox.showerror("Ошибка PGN", "Не удалось прочитать выбранную партию.")

    def load_fen_dialog(self) -> None:
        fen = simpledialog.askstring("Загрузить FEN", "Введите строку FEN:", parent=self.root)
        if not fen:
            return

        try:
            self.load_fen_text(fen)
        except ValueError:
            messagebox.showerror("Ошибка FEN", "Неверная строка FEN.")

    def load_fen_text(self, fen: str) -> None:
        board = chess.Board(fen)
        game = chess.pgn.Game()
        game.setup(board)
        game.headers["Event"] = "Пользовательская позиция"
        self.reset_to_new_game(game, preserve_orientation=True)
        self.game_mode = "analysis"
        self.user_color = None

    def _extract_lichess_game_id(self, raw_url: str) -> Optional[str]:
        return extract_lichess_game_id(raw_url)

    def _extract_chesscom_game_ref(self, raw_url: str):
        return extract_chesscom_game_ref(raw_url)

    def _fetch_game_text_from_url(self, raw_url: str) -> str:
        lichess_game_id = self._extract_lichess_game_id(raw_url)
        if lichess_game_id:
            api_url = f"https://lichess.org/game/export/{lichess_game_id}"
            response = requests.get(
                api_url,
                headers={"Accept": "application/x-chess-pgn"},
                timeout=self.LICHESS_TIMEOUT_SEC,
            )
            response.raise_for_status()
            return response.text

        chesscom_ref = self._extract_chesscom_game_ref(raw_url)
        if chesscom_ref:
            api_url = f"https://www.chess.com/callback/{chesscom_ref.game_type}/game/{chesscom_ref.game_id}"
            response = requests.get(api_url, timeout=self.LICHESS_TIMEOUT_SEC)
            response.raise_for_status()
            return chesscom_game_json_to_pgn(response.json())

        parsed = urlparse(raw_url.strip())
        if parsed.scheme in {"http", "https"} and (parsed.path.endswith(".pgn") or "/pgn" in parsed.path):
            response = requests.get(raw_url.strip(), timeout=self.LICHESS_TIMEOUT_SEC)
            response.raise_for_status()
            return response.text

        raise ValueError("Поддерживаются URL Lichess, Chess.com и прямые ссылки на PGN.")

    def load_from_url(self) -> None:
        raw_url = simpledialog.askstring(
            "Загрузить по URL",
            "Введите URL партии с Lichess / Chess.com или прямую ссылку на PGN:",
            parent=self.root,
        )
        if not raw_url:
            return

        try:
            self.load_pgn_text(self._fetch_game_text_from_url(raw_url))
        except requests.RequestException as exc:
            messagebox.showerror("Ошибка сети", f"Не удалось загрузить партию: {exc}")
        except Exception as exc:
            messagebox.showerror("Ошибка URL", str(exc))

    def load_from_clipboard(self) -> None:
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            messagebox.showwarning("Буфер обмена", "Буфер обмена пуст или недоступен.")
            return

        payload = (text or "").strip()
        if not payload:
            messagebox.showwarning("Буфер обмена", "В буфере обмена нет текста.")
            return

        try:
            if payload.startswith(("http://", "https://", "lichess.org/", "www.lichess.org/", "chess.com/", "www.chess.com/")):
                self.load_pgn_text(self._fetch_game_text_from_url(payload))
            elif looks_like_fen(payload):
                self.load_fen_text(payload)
            elif looks_like_pgn(payload):
                self.load_pgn_text(payload)
            else:
                raise ValueError("Не удалось определить формат. Вставьте PGN, FEN или поддерживаемый URL.")
        except requests.RequestException as exc:
            messagebox.showerror("Ошибка сети", f"Не удалось загрузить данные: {exc}")
        except Exception as exc:
            messagebox.showerror("Ошибка импорта", str(exc))

    def save_pgn_with_annotations(self) -> None:
        if not self.current_game_node:
            messagebox.showwarning("Нет партии", "Сначала загрузите партию.")
            return

        filepath = filedialog.asksaveasfilename(
            defaultextension=".pgn",
            filetypes=[("PGN files", "*.pgn"), ("All files", "*.*")],
            title="Сохранить PGN как...",
        )
        if not filepath:
            return

        try:
            game = self.current_game_node.game()
            with open(filepath, "w", encoding="utf-8") as pgn_file:
                exporter = chess.pgn.FileExporter(pgn_file)
                game.accept(exporter)
            messagebox.showinfo("Сохранено", f"Партия успешно сохранена в {filepath}")
        except Exception as exc:
            messagebox.showerror("Ошибка сохранения", f"Не удалось сохранить файл: {exc}")

    def export_fen_to_clipboard(self) -> None:
        fen = self.board_state.fen()
        self.root.clipboard_clear()
        self.root.clipboard_append(fen)
        messagebox.showinfo("FEN скопирован", "Текущий FEN скопирован в буфер обмена.")

    def reset_to_new_game(self, game_node: chess.pgn.GameNode, preserve_orientation: bool = True) -> None:
        self.current_game_node = game_node
        self.board_state = game_node.board()
        apply_opening_headers(self.current_game_node.game())
        if not preserve_orientation:
            self.board_orientation_white_pov = True
        self.game_mode = "analysis"
        self.user_color = None
        self.selected_square_for_move = None
        self.is_dragging = False
        self.drag_from_square = None
        self.drag_image_id = None
        self.evaluation_history = []
        self.threat_move_obj = None
        self.pending_analysis_fen = None
        self.analysis_in_flight = False
        self.latest_analysis_lines = []
        self.latest_analysis_fen = None
        self.current_coach_hint = ""
        self.latest_game_report = None
        self.training_puzzles = []
        self.training_session_name = ""
        self.training_index = -1
        self.training_score = 0
        self.training_restore_state = None
        self.update_board_display()
        self.update_info_panel()
        self.update_navigation_buttons()
        self.update_evaluation_graph()

    def start_new_game_vs_engine(self) -> None:
        self.prompt_color_and_start()

    def quick_batch_movetime_ms(self) -> int:
        return max(200, min(self.get_engine_movetime_ms(), DEFAULT_BATCH_MOVETIME_MS))

    def check_game_status(self) -> None:
        status_text, color = "", "blue"
        if self.board_state.is_checkmate():
            winner = "Белые" if self.board_state.turn == chess.BLACK else "Черные"
            status_text, color = f"МАТ! {winner} победили.", "red"
        elif self.board_state.is_stalemate():
            status_text = "ПАТ! Ничья."
        elif self.board_state.is_insufficient_material():
            status_text = "Ничья (недостаточно материала)."
        elif self.board_state.is_seventyfive_moves():
            status_text = "Ничья (правило 75 ходов)."
        elif self.board_state.is_fivefold_repetition():
            status_text = "Ничья (5-кратное повторение)."
        self.game_status_label.config(text=status_text, foreground=color)

    def report_placeholder_text(self) -> str:
        headers = self.current_game_node.game().headers if self.current_game_node else {}
        return build_report_text(self.latest_game_report, headers=headers)
