import io
import random
import re
import tkinter as tk
from tkinter import Toplevel, filedialog, messagebox, simpledialog, ttk
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import chess
import chess.pgn
import requests


class GameFlowMixin:
    LICHESS_GAME_ID_RE = re.compile(r"^[A-Za-z0-9]{8,}$")
    LICHESS_TIMEOUT_SEC = 10

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
            self.root.after(500, self.make_engine_move)

    def update_info_panel(self) -> None:
        self.clear_evaluation_display()
        self.game_status_label.config(text="")

        if self.current_game_node:
            game_root_node = self.current_game_node.game()
            headers = game_root_node.headers
            info_text = f"Белые: {headers.get('White', '?')} ({headers.get('WhiteElo', 'Н/Д')})\n"
            info_text += f"Черные: {headers.get('Black', '?')} ({headers.get('BlackElo', 'Н/Д')})\n"
            info_text += f"Результат: {headers.get('Result', '*')}, Событие: {headers.get('Event', '?')}"
            self.game_info_label.config(text=info_text)

            self.populate_moves_listbox()
            self.check_game_status()

            if not self.board_state.is_game_over() and self.game_mode == "analysis" and self.engine and self.engine.process:
                self.request_analysis_current_pos()
            else:
                self.update_eval_bar(None, None)
        else:
            self.game_info_label.config(text="Партия не загружена")
            self.moves_listbox.delete(0, tk.END)
            self.update_eval_bar(None, None)
            self.update_evaluation_graph()

    def populate_moves_listbox(self) -> None:
        self.moves_listbox.delete(0, tk.END)
        self.move_nodes_in_listbox = []

        game_root_node = self.current_game_node.game()
        board_for_san = game_root_node.board()

        self.moves_listbox.insert(tk.END, "--- Начало ---")
        self.move_nodes_in_listbox.append(game_root_node)

        for node in game_root_node.mainline():
            san_move = board_for_san.san(node.move)
            if board_for_san.turn == chess.WHITE:
                display_text = f"{board_for_san.fullmove_number}. {san_move}"
            else:
                display_text = f"{board_for_san.fullmove_number}... {san_move}"

            nags = "".join([{1: "!", 2: "?", 3: "!!", 4: "??", 5: "!?", 6: "?!"}.get(nag, "") for nag in node.nags])
            if nags:
                display_text += f" {nags}"

            if node.comment:
                display_text += f" ({node.comment[:40]})" if len(node.comment) > 40 else f" ({node.comment})"

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
        self.ax.set_xlabel("Номер хода")
        self.ax.set_ylabel("Оценка (сантипешки)")

        if self.evaluation_history:
            plies = range(len(self.evaluation_history))
            self.ax.plot(plies, self.evaluation_history, marker="o", linestyle="-")
            self.ax.axhline(0, color="black", linewidth=0.8, linestyle="--")

            max_abs_eval = max(abs(evaluation) for evaluation in self.evaluation_history)
            display_max = min(max_abs_eval + 100, 1000)
            self.ax.set_ylim(-display_max, display_max)
        else:
            self.ax.text(
                0.5,
                0.5,
                "Нет данных для графика.\nВыполните 'Анализировать партию'.",
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
            with open(filepath, "r", encoding="utf-8-sig") as pgn_file:
                pgn_text = pgn_file.read()

            pgn_io = io.StringIO(pgn_text)
            games: List[Tuple[dict, int]] = []
            while True:
                offset = pgn_io.tell()
                headers = chess.pgn.read_headers(pgn_io)
                if headers is None:
                    break
                games.append((headers, offset))

            if not games:
                messagebox.showerror("Ошибка PGN", "Не найдено ни одной партии в файле.")
                return

            if len(games) == 1:
                self.load_game_from_pgn(pgn_text, 0)
            else:
                self.show_pgn_selection_window(pgn_text, games)

        except Exception as exc:
            messagebox.showerror("Ошибка загрузки PGN", f"Произошла ошибка: {exc}")

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
            board = chess.Board(fen)
            game = chess.pgn.Game()
            game.setup(board)
            self.reset_to_new_game(game, preserve_orientation=True)
            self.game_mode = "puzzle"
            messagebox.showinfo("Режим Задачи", "Позиция загружена. Найдите лучший ход!")
        except ValueError:
            messagebox.showerror("Ошибка FEN", "Неверная строка FEN.")

    def _extract_lichess_game_id(self, raw_url: str) -> Optional[str]:
        try:
            parsed = urlparse(raw_url.strip())
        except Exception:
            return None

        host = parsed.netloc.lower()
        if host not in {"lichess.org", "www.lichess.org"}:
            return None

        parts = [part for part in parsed.path.split("/") if part]
        if not parts:
            return None

        game_id = parts[0]
        if not self.LICHESS_GAME_ID_RE.match(game_id):
            return None
        return game_id

    def load_from_url(self) -> None:
        raw_url = simpledialog.askstring("Загрузить по URL", "Введите URL партии с Lichess:", parent=self.root)
        if not raw_url:
            return

        game_id = self._extract_lichess_game_id(raw_url)
        if not game_id:
            messagebox.showerror("Ошибка URL", "Поддерживаются корректные URL вида https://lichess.org/<id>.")
            return

        api_url = f"https://lichess.org/game/export/{game_id}"
        try:
            response = requests.get(
                api_url,
                headers={"Accept": "application/x-chess-pgn"},
                timeout=self.LICHESS_TIMEOUT_SEC,
            )
            response.raise_for_status()
            self.load_game_from_pgn(response.text, 0)
        except requests.RequestException as exc:
            messagebox.showerror("Ошибка сети", f"Не удалось загрузить партию: {exc}")

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
        messagebox.showinfo("FEN Скопирован", "Текущий FEN скопирован в буфер обмена.")

    def reset_to_new_game(self, game_node: chess.pgn.GameNode, preserve_orientation: bool = True) -> None:
        self.current_game_node = game_node
        self.board_state = game_node.board()
        if not preserve_orientation:
            self.board_orientation_white_pov = True
        self.game_mode = "analysis"
        self.selected_square_for_move = None
        self.is_dragging = False
        self.drag_from_square = None
        self.drag_image_id = None
        self.evaluation_history = []
        self.pending_analysis_fen = None
        self.analysis_in_flight = False
        self.update_board_display()
        self.update_info_panel()
        self.update_navigation_buttons()
        self.update_evaluation_graph()

    def start_new_game_vs_engine(self) -> None:
        self.prompt_color_and_start()

    def check_game_status(self) -> None:
        status_text, color = "", "blue"
        if self.board_state.is_checkmate():
            winner = "Белые" if self.board_state.turn == chess.BLACK else "Черные"
            status_text, color = f"ШАХ И МАТ! {winner} победили.", "red"
        elif self.board_state.is_stalemate():
            status_text = "ПАТ! Ничья."
        elif self.board_state.is_insufficient_material():
            status_text = "Ничья (недостаточно материала)."
        elif self.board_state.is_seventyfive_moves():
            status_text = "Ничья (правило 75 ходов)."
        elif self.board_state.is_fivefold_repetition():
            status_text = "Ничья (5-кратное повторение)."
        self.game_status_label.config(text=status_text, foreground=color)
