import io
import queue
import threading
import tkinter as tk
from tkinter import Toplevel, filedialog, messagebox, ttk
from typing import Any, Optional

import chess
import chess.pgn

from config import DEFAULT_TRAINING_PUZZLES

from .analysis_utils import (
    mate_to_white_perspective,
    merge_analysis_comment,
    score_to_white_perspective,
)
from .openings import apply_opening_headers
from .reporting import (
    TrainingPuzzle,
    analyze_game,
    build_coach_hint,
    build_report_text,
    build_training_puzzles,
)


class AnalysisMixin:
    def invalidate_cached_report(self) -> None:
        self.latest_game_report = None
        self.evaluation_history = []
        self.refresh_report_panel()

    def refresh_report_panel(self) -> None:
        if not hasattr(self, "report_text"):
            return

        headers = self.current_game_node.game().headers if self.current_game_node else {}
        report_text = build_report_text(self.latest_game_report, headers=headers)
        if self.training_puzzles and self.training_index >= 0:
            report_text += (
                f"\n\nТренировка: {self.training_session_name}\n"
                f"Позиция {self.training_index + 1} из {len(self.training_puzzles)}\n"
                f"Счет: {self.training_score}"
            )

        self.report_text.configure(state=tk.NORMAL)
        self.report_text.delete("1.0", tk.END)
        self.report_text.insert("1.0", report_text)
        self.report_text.configure(state=tk.DISABLED)

        if hasattr(self, "start_generated_puzzles_button"):
            state = tk.NORMAL if self.latest_game_report else tk.DISABLED
            self.start_generated_puzzles_button.config(state=state)

    def update_coach_hint_display(self, text: str) -> None:
        if not hasattr(self, "coach_hint_var"):
            return

        if not self.coach_mode_var.get():
            self.coach_hint_var.set("Режим тренера выключен.")
            return

        self.coach_hint_var.set(text or "Подсказка появится после анализа позиции или старта задачи.")

    def toggle_coach_mode(self) -> None:
        if self.game_mode == "puzzle":
            self.update_coach_hint_display(self.get_training_hint_text())
            return

        if self.latest_analysis_lines and self.latest_analysis_fen == self.board_state.fen():
            self._update_coach_hint_from_analysis(self.latest_analysis_lines)
        else:
            self.update_coach_hint_display("")

    def get_training_hint_text(self) -> str:
        if self.game_mode != "puzzle":
            return ""
        if 0 <= self.training_index < len(self.training_puzzles):
            return self.training_puzzles[self.training_index].coach_hint
        return ""

    def _update_coach_hint_from_analysis(self, analysis_lines: list[dict]) -> None:
        if not self.coach_mode_var.get():
            self.update_coach_hint_display("")
            return

        first_line = analysis_lines[0] if analysis_lines else None
        best_move = None
        if first_line and first_line.get("move_uci"):
            try:
                best_move = self.board_state.parse_uci(first_line["move_uci"])
            except Exception:
                best_move = None
        hint = build_coach_hint(self.board_state, best_move, first_line)
        self.current_coach_hint = hint
        self.update_coach_hint_display(hint)

    def start_full_game_analysis(self) -> None:
        if self.full_analysis_in_progress:
            return
        if not self.engine or not self.engine.process:
            messagebox.showwarning("Движок недоступен", "Полный анализ недоступен без Stockfish.")
            return
        if not self.current_game_node or not list(self.current_game_node.game().mainline()):
            messagebox.showwarning("Нет партии", "Загрузите партию с ходами для анализа.")
            return

        self.full_analysis_in_progress = True
        self.analyze_game_button.config(state=tk.DISABLED)

        self.analysis_progress_win = Toplevel(self.root)
        self.analysis_progress_win.title("Анализ")
        self.analysis_progress_win.transient(self.root)
        self.analysis_progress_win.grab_set()

        ttk.Label(self.analysis_progress_win, text="Идет анализ партии...").pack(padx=20, pady=10)
        self.progress_bar = ttk.Progressbar(self.analysis_progress_win, orient="horizontal", length=300, mode="determinate")
        self.progress_bar.pack(padx=20, pady=10)

        threading.Thread(target=self._run_full_game_analysis, daemon=True).start()

    def _run_full_game_analysis(self) -> None:
        failed_reason: Optional[str] = None
        report = None

        try:
            game = self.current_game_node.game()
            report = analyze_game(
                game,
                self.engine.analyze_position,
                self.get_engine_movetime_ms(),
                progress_callback=lambda progress: self.root.after(
                    0, lambda value=progress: self.progress_bar.config(value=value)
                ),
            )
            apply_opening_headers(game)

            for node, move_analysis in zip(game.mainline(), report.move_analyses):
                setattr(node, "analysis_data", move_analysis)
                if move_analysis.nag:
                    node.nags.add(move_analysis.nag)

                comment_chunks = []
                if move_analysis.white_eval_after is not None:
                    comment_chunks.append(f"[%eval {move_analysis.white_eval_after / 100.0:.2f}]")
                if move_analysis.best_move_san != "N/A":
                    comment_chunks.append(f"Best move was {move_analysis.best_move_san}.")
                if move_analysis.verdict:
                    comment_chunks.append(move_analysis.verdict)
                if move_analysis.coach_hint:
                    comment_chunks.append(f"Hint: {move_analysis.coach_hint}")
                if comment_chunks:
                    node.comment = merge_analysis_comment(node.comment, " ".join(comment_chunks))

        except Exception as exc:
            failed_reason = str(exc)

        def finish_analysis() -> None:
            if hasattr(self, "analysis_progress_win") and self.analysis_progress_win.winfo_exists():
                self.analysis_progress_win.destroy()
            self.full_analysis_in_progress = False
            self.analyze_game_button.config(state=tk.NORMAL)

            if failed_reason:
                messagebox.showerror("Ошибка анализа", f"Полный анализ завершился с ошибкой: {failed_reason}")
                return

            self.latest_game_report = report
            self.evaluation_history = list(report.evaluation_history) if report else []
            self.populate_moves_listbox()
            self.populate_variation_tree()
            self.update_evaluation_graph()
            self.refresh_report_panel()
            puzzle_count = len(build_training_puzzles(report, max_items=DEFAULT_TRAINING_PUZZLES)) if report else 0
            messagebox.showinfo(
                "Анализ завершен",
                f"Анализ партии окончен. Отчет обновлен, а для тренировки доступно {puzzle_count} позиций.",
            )

        self.root.after(0, finish_analysis)

    def show_threat(self) -> None:
        if self.is_animating or self.board_state.is_game_over():
            return

        expected_fen = self.board_state.fen()

        def get_threat_in_thread() -> None:
            if not self.engine or not self.engine.process:
                return
            threat_uci = self.engine.get_threat(expected_fen)
            if not threat_uci:
                return

            def apply_threat() -> None:
                if self.board_state.fen() != expected_fen or self.is_animating:
                    return
                try:
                    self.threat_move_obj = self.board_state.parse_uci(threat_uci)
                    self._draw_move_arrows()
                except Exception:
                    self.threat_move_obj = None

            self.root.after(0, apply_threat)

        threading.Thread(target=get_threat_in_thread, daemon=True).start()

    def request_analysis_current_pos(self) -> None:
        if self.game_mode == "puzzle":
            return
        if self.is_animating or not self.engine or not self.engine.process or self.board_state.is_game_over():
            return

        current_fen = self.board_state.fen()
        if self.analysis_in_flight:
            self.pending_analysis_fen = current_fen
            return

        self.clear_evaluation_display()
        self.analysis_in_flight = True
        self.pending_analysis_fen = None
        threading.Thread(target=self._run_engine_analysis, args=(current_fen,), daemon=True).start()

    def _run_engine_analysis(self, fen_string: str) -> None:
        analysis_lines = []
        try:
            analysis_lines, _ = self.engine.analyze_position(fen_string, movetime_ms=self.get_engine_movetime_ms())
        except Exception as exc:
            print("Engine analysis error:", exc)
        finally:
            self.analysis_queue.put((analysis_lines, fen_string))

    def _schedule_pending_analysis_if_needed(self) -> None:
        if self.analysis_in_flight:
            return
        pending_fen = self.pending_analysis_fen
        if not pending_fen:
            return
        if pending_fen != self.board_state.fen():
            self.pending_analysis_fen = None
            return
        if self.is_animating or self.board_state.is_game_over() or not self.engine or not self.engine.process:
            return

        self.pending_analysis_fen = None
        self.analysis_in_flight = True
        threading.Thread(target=self._run_engine_analysis, args=(pending_fen,), daemon=True).start()

    def process_analysis_queue(self) -> None:
        try:
            analysis_lines, analyzed_fen = self.analysis_queue.get_nowait()
            self.analysis_in_flight = False

            if self.board_state.fen() != analyzed_fen or self.is_animating:
                return

            self.latest_analysis_lines = analysis_lines
            self.latest_analysis_fen = analyzed_fen

            if analysis_lines:
                for item in self.eval_tree.get_children():
                    self.eval_tree.delete(item)

                for line in analysis_lines:
                    move_uci = line.get("move_uci")
                    if not move_uci or move_uci == "(none)":
                        continue
                    try:
                        move = self.board_state.parse_uci(move_uci)
                        move_san = self.board_state.san(move)

                        eval_text = ""
                        if line.get("score_mate") is not None:
                            eval_text = f"Мат в {abs(line['score_mate'])}"
                        elif line.get("score_cp") is not None:
                            cp_val = score_to_white_perspective(line["score_cp"], self.board_state.turn)
                            eval_text = f"{cp_val / 100.0:+.2f}"

                        self.eval_tree.insert("", "end", values=(line["pv"], move_san, eval_text))
                    except Exception:
                        continue

                first_line = analysis_lines[0]
                self.update_eval_bar(first_line.get("score_cp"), first_line.get("score_mate"))
                self._draw_move_arrows()
                self._update_coach_hint_from_analysis(analysis_lines)
            else:
                self.update_coach_hint_display("")
        except queue.Empty:
            pass
        finally:
            self._schedule_pending_analysis_if_needed()
            self.root.after(100, self.process_analysis_queue)

    def _snapshot_for_training(self) -> dict:
        return {
            "current_game_node": self.current_game_node,
            "board_orientation_white_pov": self.board_orientation_white_pov,
            "game_mode": self.game_mode,
            "user_color": self.user_color,
            "evaluation_history": list(self.evaluation_history),
            "latest_game_report": self.latest_game_report,
            "latest_analysis_lines": list(self.latest_analysis_lines),
            "latest_analysis_fen": self.latest_analysis_fen,
            "current_coach_hint": self.current_coach_hint,
        }

    def _restore_training_snapshot(self, snapshot: dict) -> None:
        self.current_game_node = snapshot["current_game_node"]
        self.board_state = self.current_game_node.board() if self.current_game_node else chess.Board()
        self.board_orientation_white_pov = snapshot["board_orientation_white_pov"]
        self.game_mode = snapshot["game_mode"]
        self.user_color = snapshot["user_color"]
        self.evaluation_history = list(snapshot["evaluation_history"])
        self.latest_game_report = snapshot["latest_game_report"]
        self.latest_analysis_lines = list(snapshot["latest_analysis_lines"])
        self.latest_analysis_fen = snapshot["latest_analysis_fen"]
        self.current_coach_hint = snapshot["current_coach_hint"]
        self.training_puzzles = []
        self.training_session_name = ""
        self.training_index = -1
        self.training_score = 0
        self.training_restore_state = None
        self.update_board_display()
        self.update_info_panel()
        self.update_navigation_buttons()
        self.update_evaluation_graph()
        if self.latest_analysis_lines and self.latest_analysis_fen == self.board_state.fen():
            self._update_coach_hint_from_analysis(self.latest_analysis_lines)
        else:
            self.update_coach_hint_display(self.current_coach_hint)

    def _show_training_puzzle(self, index: int) -> None:
        if not (0 <= index < len(self.training_puzzles)):
            self.finish_training_session()
            return

        puzzle = self.training_puzzles[index]
        board = chess.Board(puzzle.fen)
        game = chess.pgn.Game()
        game.setup(board)
        game.headers["Event"] = self.training_session_name or "Тренировка"
        game.headers["White"] = "Ход белых" if board.turn == chess.WHITE else "Белые"
        game.headers["Black"] = "Ход черных" if board.turn == chess.BLACK else "Черные"

        self.current_game_node = game
        self.board_state = board
        self.board_orientation_white_pov = board.turn == chess.WHITE
        self.game_mode = "puzzle"
        self.user_color = None
        self.training_index = index
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
        self.clear_evaluation_display()
        self.update_board_display()
        self.update_info_panel()
        self.update_navigation_buttons()
        self.update_evaluation_graph()
        self.update_coach_hint_display(self.get_training_hint_text())

    def _launch_training_session(self, puzzles: list[TrainingPuzzle], session_name: str) -> None:
        if not puzzles:
            messagebox.showinfo("Тренировка", "Подходящих позиций для тренировки не найдено.")
            return

        if self.training_restore_state is None:
            self.training_restore_state = self._snapshot_for_training()
        self.training_puzzles = puzzles
        self.training_session_name = session_name
        self.training_index = 0
        self.training_score = 0
        self._show_training_puzzle(0)

    def start_best_move_challenge(self) -> None:
        if not self.engine or not self.engine.process:
            messagebox.showwarning("Движок недоступен", "Режим «Найди лучший ход» требует Stockfish.")
            return
        if self.board_state.is_game_over():
            messagebox.showwarning("Позиция завершена", "Выберите позицию, в которой есть ход.")
            return

        fen = self.board_state.fen()
        progress_win = Toplevel(self.root)
        progress_win.title("Найди лучший ход")
        progress_win.transient(self.root)
        progress_win.grab_set()
        ttk.Label(progress_win, text="Готовлю тренировочную позицию...").pack(padx=20, pady=20)

        def worker() -> None:
            error_text: Optional[str] = None
            puzzle: Optional[TrainingPuzzle] = None
            try:
                analysis_lines, _ = self.engine.analyze_position(fen, movetime_ms=self.get_engine_movetime_ms())
                if not analysis_lines or not analysis_lines[0].get("move_uci"):
                    raise ValueError("Движок не вернул лучший ход.")
                best_line = analysis_lines[0]
                best_move = chess.Board(fen).parse_uci(best_line["move_uci"])
                puzzle = TrainingPuzzle(
                    fen=fen,
                    solution_uci=best_line["move_uci"],
                    best_move_san=chess.Board(fen).san(best_move),
                    source_label="Текущая позиция",
                    verdict="Найди лучший ход",
                    coach_hint=build_coach_hint(chess.Board(fen), best_move, best_line),
                )
            except Exception as exc:
                error_text = str(exc)

            def finish() -> None:
                if progress_win.winfo_exists():
                    progress_win.destroy()
                if error_text:
                    messagebox.showerror("Тренировка", error_text)
                    return
                self._launch_training_session([puzzle], "Найди лучший ход")

            self.root.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def start_generated_puzzle_session(self) -> None:
        if not self.latest_game_report:
            messagebox.showwarning("Нет анализа", "Сначала выполните полный анализ партии.")
            return

        puzzles = build_training_puzzles(self.latest_game_report, max_items=DEFAULT_TRAINING_PUZZLES)
        if not puzzles:
            messagebox.showinfo("Тренировка", "В партии не нашлось неточностей или ошибок для генерации задач.")
            return
        self._launch_training_session(puzzles, "Тренировка по ошибкам")

    def complete_training_attempt(self, success: bool) -> None:
        if success:
            self.training_score += 1

        next_index = self.training_index + 1
        if next_index < len(self.training_puzzles):
            self._show_training_puzzle(next_index)
            return
        self.finish_training_session()

    def finish_training_session(self) -> None:
        summary_text = f"Тренировка завершена. Результат: {self.training_score}/{len(self.training_puzzles)}."
        snapshot = self.training_restore_state
        if snapshot is not None:
            self._restore_training_snapshot(snapshot)
        else:
            self.training_puzzles = []
            self.training_session_name = ""
            self.training_index = -1
            self.training_score = 0
            self.training_restore_state = None
        messagebox.showinfo("Тренировка", summary_text)

    def start_batch_pgn_analysis(self) -> None:
        if not self.engine or not self.engine.process:
            messagebox.showwarning("Движок недоступен", "Пакетный анализ требует Stockfish.")
            return

        filepath = filedialog.askopenfilename(title="Выберите PGN для пакетного анализа", filetypes=(("PGN files", "*.pgn"), ("All files", "*.*")))
        if not filepath:
            return

        try:
            pgn_text = self._read_text_file_with_fallbacks(filepath)
            pgn_io = io.StringIO(pgn_text)
            games: list[tuple[dict, int]] = []
            while True:
                offset = pgn_io.tell()
                headers = chess.pgn.read_headers(pgn_io)
                if headers is None:
                    break
                games.append((headers, offset))
        except Exception as exc:
            messagebox.showerror("Пакетный анализ", f"Не удалось прочитать PGN: {exc}")
            return

        if not games:
            messagebox.showwarning("Пакетный анализ", "В файле не найдено партий.")
            return

        progress_win = Toplevel(self.root)
        progress_win.title("Пакетный анализ")
        progress_win.transient(self.root)
        progress_win.grab_set()

        status_var = tk.StringVar(value="Подготовка...")
        ttk.Label(progress_win, textvariable=status_var).pack(padx=20, pady=(16, 8))
        progress_bar = ttk.Progressbar(progress_win, orient="horizontal", length=360, mode="determinate")
        progress_bar.pack(padx=20, pady=(0, 16))

        def worker() -> None:
            error_text: Optional[str] = None
            rows: list[dict] = []

            try:
                for index, (headers, offset) in enumerate(games, start=1):
                    pgn_io_local = io.StringIO(pgn_text)
                    pgn_io_local.seek(offset)
                    game = chess.pgn.read_game(pgn_io_local)
                    if game is None:
                        continue

                    report = analyze_game(
                        game,
                        self.engine.analyze_position,
                        self.quick_batch_movetime_ms(),
                        progress_callback=lambda progress, i=index: self.root.after(
                            0,
                            lambda value=((i - 1) + (progress / 100.0)) / len(games) * 100.0: progress_bar.config(value=value),
                        ),
                    )
                    rows.append(
                        {
                            "index": index,
                            "offset": offset,
                            "headers": headers,
                            "report": report,
                        }
                    )
                    self.root.after(
                        0,
                        lambda i=index, total=len(games), h=headers: status_var.set(
                            f"Анализ {i}/{total}: {h.get('White', '?')} - {h.get('Black', '?')}"
                        ),
                    )
            except Exception as exc:
                error_text = str(exc)

            def finish() -> None:
                if progress_win.winfo_exists():
                    progress_win.destroy()
                if error_text:
                    messagebox.showerror("Пакетный анализ", error_text)
                    return
                self.show_batch_analysis_results(rows, pgn_text)

            self.root.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def show_batch_analysis_results(self, rows: list[dict], pgn_text: str) -> None:
        win = Toplevel(self.root)
        win.title("Пакетный анализ")
        win.geometry("980x520")

        columns = ("#", "white", "black", "result", "opening", "wacc", "bacc", "wbl", "bbl")
        tree = ttk.Treeview(win, columns=columns, show="headings")
        headings = {
            "#": "#",
            "white": "Белые",
            "black": "Черные",
            "result": "Результат",
            "opening": "Дебют",
            "wacc": "W Acc",
            "bacc": "B Acc",
            "wbl": "W ??",
            "bbl": "B ??",
        }
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(column, width=100 if column not in {"white", "black", "opening"} else 160, anchor="center")
        tree.column("white", anchor="w")
        tree.column("black", anchor="w")
        tree.column("opening", anchor="w")
        tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        details = tk.Text(win, height=8, wrap=tk.WORD)
        details.pack(fill=tk.X, expand=False, padx=10, pady=(0, 10))

        row_lookup = {}
        for row in rows:
            report = row["report"]
            headers = row["headers"]
            white_summary = report.summaries[chess.WHITE]
            black_summary = report.summaries[chess.BLACK]
            opening_text = report.opening.full_name if report.opening else headers.get("Opening", "-")
            item_id = tree.insert(
                "",
                "end",
                values=(
                    row["index"],
                    headers.get("White", "?"),
                    headers.get("Black", "?"),
                    headers.get("Result", "*"),
                    opening_text,
                    f"{white_summary.accuracy:.1f}",
                    f"{black_summary.accuracy:.1f}",
                    white_summary.blunders,
                    black_summary.blunders,
                ),
            )
            row_lookup[item_id] = row

        def on_select(event: Optional[tk.Event] = None) -> None:
            selection = tree.selection()
            if not selection:
                return
            row = row_lookup[selection[0]]
            details.configure(state=tk.NORMAL)
            details.delete("1.0", tk.END)
            details.insert("1.0", build_report_text(row["report"], headers=row["headers"]))
            details.configure(state=tk.DISABLED)

        def load_selected() -> None:
            selection = tree.selection()
            if not selection:
                return
            row = row_lookup[selection[0]]
            self.load_game_from_pgn(pgn_text, row["offset"])
            win.destroy()

        buttons = ttk.Frame(win)
        buttons.pack(fill=tk.X, padx=10, pady=(0, 10))
        ttk.Button(buttons, text="Загрузить выбранную партию", command=load_selected).pack(side=tk.RIGHT)

        tree.bind("<<TreeviewSelect>>", on_select)
        tree.bind("<Double-1>", lambda e: load_selected())
        if rows:
            first_item = tree.get_children()[0]
            tree.selection_set(first_item)
            tree.focus(first_item)
            on_select()

    def update_engine_skill(self, event: Optional[Any] = None) -> None:
        if self.engine and self.engine.process:
            self.engine.set_skill_level(self.get_engine_skill_level())

    def update_engine_multipv(self, event: Optional[Any] = None) -> None:
        if self.engine and self.engine.process:
            self.engine.set_multi_pv(self.get_engine_multipv())
            self.request_analysis_current_pos()
