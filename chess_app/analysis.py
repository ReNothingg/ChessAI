import queue
import threading
import tkinter as tk
from tkinter import Toplevel, messagebox, ttk
from typing import Any, Optional

import chess


class AnalysisMixin:
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
        try:
            game = self.current_game_node.game()
            nodes = list(game.mainline())
            total_moves = len(nodes)
            self.evaluation_history = []

            board = game.board()
            for idx, node in enumerate(nodes):
                fen_before = board.fen()
                if self.engine and self.engine.process:
                    analysis_before, _ = self.engine.analyze_position(fen_before, movetime_ms=self.engine_time_var.get())
                else:
                    analysis_before = []

                if analysis_before and analysis_before[0].get("move_uci"):
                    score_obj = analysis_before[0]
                    score_cp = score_obj.get("score_cp")

                    best_move_san = "N/A"
                    try:
                        engine_move = chess.Move.from_uci(score_obj.get("move_uci"))
                        if board.is_legal(engine_move):
                            best_move_san = board.san(engine_move)
                    except Exception:
                        pass

                    board.push(node.move)

                    if score_cp is not None:
                        current_player_score = score_cp if board.turn != chess.WHITE else -score_cp
                        self.evaluation_history.append(current_player_score)

                        fen_after = board.fen()
                        if self.engine and self.engine.process:
                            analysis_after, _ = self.engine.analyze_position(
                                fen_after,
                                movetime_ms=max(200, self.engine_time_var.get() // 4),
                            )
                        else:
                            analysis_after = []

                        if analysis_after and analysis_after[0].get("score_cp") is not None:
                            score_after_cp = analysis_after[0]["score_cp"]
                            next_player_score = score_after_cp if board.turn == chess.WHITE else -score_after_cp
                            eval_loss = current_player_score - (-next_player_score)

                            comment = f"[%eval {current_player_score / 100.0:.2f}] Лучший ход был {best_move_san}."
                            if eval_loss > 250:
                                comment += " (Зевок ??)"
                            elif eval_loss > 120:
                                comment += " (Ошибка ?)"
                            elif eval_loss > 60:
                                comment += " (Неточность ?!)"
                            node.comment = comment
                    else:
                        mate_score = 10000 if score_obj.get("score_mate", 0) > 0 else -10000
                        self.evaluation_history.append(mate_score if board.turn != chess.WHITE else -mate_score)
                else:
                    board.push(node.move)

                progress = (idx + 1) / total_moves * 100
                self.root.after(0, lambda progress_value=progress: self.progress_bar.config(value=progress_value))
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

            self.populate_moves_listbox()
            self.update_evaluation_graph()
            messagebox.showinfo("Анализ завершен", "Анализ партии окончен. Результаты добавлены в комментарии и на график.")

        self.root.after(0, finish_analysis)

    def show_threat(self) -> None:
        if self.is_animating or self.board_state.is_game_over():
            return

        def get_threat_in_thread() -> None:
            if not self.engine or not self.engine.process:
                return
            threat_uci = self.engine.get_threat(self.board_state.fen())
            if not threat_uci:
                return
            try:
                move = self.board_state.parse_uci(threat_uci)
                self.threat_move_obj = move
                self.root.after(0, self._draw_move_arrows)
            except Exception:
                self.threat_move_obj = None

        threading.Thread(target=get_threat_in_thread, daemon=True).start()

    def request_analysis_current_pos(self) -> None:
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
            analysis_lines, _ = self.engine.analyze_position(fen_string, movetime_ms=self.engine_time_var.get())
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
                            cp_val = line["score_cp"] if self.board_state.turn == chess.WHITE else -line["score_cp"]
                            eval_text = f"{cp_val / 100.0:+.2f}"

                        self.eval_tree.insert("", "end", values=(line["pv"], move_san, eval_text))
                    except Exception:
                        continue

                first_line = analysis_lines[0]
                self.update_eval_bar(first_line.get("score_cp"), first_line.get("score_mate"))
                self._draw_move_arrows()
        except queue.Empty:
            pass
        finally:
            self._schedule_pending_analysis_if_needed()
            self.root.after(100, self.process_analysis_queue)

    def update_engine_skill(self, event: Optional[Any] = None) -> None:
        if self.engine and self.engine.process:
            self.engine.set_skill_level(self.engine_skill_var.get())

    def update_engine_multipv(self, event: Optional[Any] = None) -> None:
        if self.engine and self.engine.process:
            self.engine.set_multi_pv(self.engine_multipv_var.get())
            self.request_analysis_current_pos()
