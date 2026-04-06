import tkinter as tk
from tkinter import messagebox, simpledialog
from typing import List, Optional

import chess
import chess.pgn

from config import ANIMATION_DELAY, ANIMATION_STEPS, SQUARE_SIZE


class InteractionMixin:
    def make_user_move(self, move: chess.Move) -> None:
        if not self.board_state.is_legal(move):
            return

        if self.game_mode == "puzzle":
            self.check_puzzle_move(move)
            return

        self._apply_move(move)

    def _apply_move(self, move: chess.Move) -> None:
        captured = self._is_capture_move(move)
        animated_piece_symbol = self.get_animated_piece_symbol(move)

        if self.current_game_node is None:
            game = chess.pgn.Game()
            game.setup(self.board_state)
            self.current_game_node = game

        self.invalidate_cached_report()
        new_node = None
        for variation in self.current_game_node.variations:
            if variation.move == move:
                new_node = variation
                break
        if new_node is None:
            new_node = self.current_game_node.add_variation(move)

        self._set_active_node(
            new_node,
            is_forward_move=True,
            move_to_animate=move,
            captured=captured,
            animated_piece_symbol=animated_piece_symbol,
        )

        if self._is_engine_turn():
            expected_fen = self.board_state.fen()
            self.root.after(500, lambda fen=expected_fen: self.make_engine_move(expected_fen=fen))

    def _is_capture_move(self, move: chess.Move) -> bool:
        return self.board_state.is_capture(move) or self.board_state.is_en_passant(move)

    def _is_engine_turn(self, expected_fen: Optional[str] = None) -> bool:
        if self.game_mode != "play_engine" or self.user_color is None:
            return False
        if self.board_state.is_game_over() or self.board_state.turn == self.user_color:
            return False
        if expected_fen is not None and self.board_state.fen() != expected_fen:
            return False
        return True

    def make_engine_move(self, expected_fen: Optional[str] = None) -> None:
        if self.is_animating or not self.engine or not self.engine.process:
            return
        if not self._is_engine_turn(expected_fen):
            return

        fen_to_analyze = self.board_state.fen()

        def find_and_make_move() -> None:
            _, best_move_uci = self.engine.analyze_position(fen_to_analyze, movetime_ms=self.get_engine_movetime_ms())
            if not best_move_uci:
                return
            try:
                move = chess.Move.from_uci(best_move_uci)
            except Exception:
                return

            def apply_engine_move() -> None:
                if not self._is_engine_turn(fen_to_analyze):
                    return
                if self.board_state.is_legal(move):
                    self._apply_move(move)

            self.root.after(0, apply_engine_move)

        import threading

        threading.Thread(target=find_and_make_move, daemon=True).start()

    def check_puzzle_move(self, user_move: chess.Move) -> None:
        if not self.engine or not self.engine.process:
            messagebox.showwarning("Движок недоступен", "Проверка задач недоступна без Stockfish.")
            return

        expected_fen = self.board_state.fen()

        def check_in_thread() -> None:
            _, best_move_uci = self.engine.analyze_position(expected_fen, movetime_ms=self.get_engine_movetime_ms())
            try:
                best_move = chess.Move.from_uci(best_move_uci)
            except Exception:
                best_move = None

            def show_result() -> None:
                if self.game_mode != "puzzle" or self.board_state.fen() != expected_fen:
                    return

                best_move_san = self.board_state.san(best_move) if best_move and self.board_state.is_legal(best_move) else "N/A"
                if best_move and user_move == best_move and self.board_state.is_legal(user_move):
                    messagebox.showinfo("Правильно!", f"Отличный ход! {self.board_state.san(user_move)}")
                    self.complete_training_attempt(True)
                else:
                    hint_text = self.get_training_hint_text()
                    message = f"Неправильный ход. Лучшим ходом был {best_move_san}."
                    if hint_text:
                        message += f"\n\nПодсказка тренера: {hint_text}"
                    messagebox.showwarning("Неверно", message)
                    self.complete_training_attempt(False)

            self.root.after(0, show_result)

        import threading

        threading.Thread(target=check_in_thread, daemon=True).start()

    def on_mouse_move(self, event: tk.Event) -> None:
        if self.is_animating:
            return
        square_index = self.get_square_from_coords(event.x, event.y)
        if square_index is None:
            self.board_canvas.configure(cursor="arrow")
            return

        piece = self.board_state.piece_at(square_index)
        can_move_now = piece is not None and piece.color == self.board_state.turn
        if self.game_mode == "play_engine":
            can_move_now = can_move_now and self.user_color == self.board_state.turn

        self.board_canvas.configure(cursor="hand2" if can_move_now else "arrow")

        if self.is_dragging and self.drag_image_id is not None:
            x = event.x - SQUARE_SIZE // 2
            y = event.y - SQUARE_SIZE // 2
            self.board_canvas.coords(self.drag_image_id, x, y)

    def on_mouse_down(self, event: tk.Event) -> None:
        if self.is_animating or self.board_state.is_game_over():
            return
        if self.game_mode == "play_engine" and self.board_state.turn != self.user_color:
            return

        square_index = self.get_square_from_coords(event.x, event.y)
        if square_index is None:
            return

        piece = self.board_state.piece_at(square_index)
        if not piece or piece.color != self.board_state.turn:
            self._click_select_logic(square_index)
            return

        self.is_dragging = True
        self.drag_from_square = square_index
        self.highlight_legal_moves(square_index)
        symbol = piece.symbol()
        image = self.piece_images.get(symbol)
        if image:
            x = event.x - SQUARE_SIZE // 2
            y = event.y - SQUARE_SIZE // 2
            self.drag_image_id = self.board_canvas.create_image(x, y, image=image, anchor=tk.NW, tags="dragging")
            self.board_canvas.delete(f"piece_at_{square_index}")
        self.board_canvas.configure(cursor="hand2")

    def on_mouse_drag(self, event: tk.Event) -> None:
        if not self.is_dragging or self.drag_image_id is None:
            return
        x = event.x - SQUARE_SIZE // 2
        y = event.y - SQUARE_SIZE // 2
        self.board_canvas.coords(self.drag_image_id, x, y)

    def on_mouse_up(self, event: tk.Event) -> None:
        if self.is_dragging:
            to_square = self.get_square_from_coords(event.x, event.y)
            from_square = self.drag_from_square
            self._end_drag_visuals()
            if to_square is not None and from_square is not None:
                move = self.create_move_obj(from_square, to_square)
                if move and self.board_state.is_legal(move):
                    self.make_user_move(move)
                    return
            self.update_board_display()
            return

        square_index = self.get_square_from_coords(event.x, event.y)
        if square_index is not None:
            self._click_select_logic(square_index)

    def _end_drag_visuals(self) -> None:
        self.is_dragging = False
        self.drag_from_square = None
        if self.drag_image_id is not None:
            self.board_canvas.delete(self.drag_image_id)
        self.drag_image_id = None
        self.clear_highlighted_squares()
        self.board_canvas.configure(cursor="arrow")

    def _click_select_logic(self, clicked_square: int) -> None:
        if self.selected_square_for_move is not None:
            move = self.create_move_obj(self.selected_square_for_move, clicked_square)
            self.selected_square_for_move = None
            self.clear_highlighted_squares()

            if move and self.board_state.is_legal(move):
                if self.game_mode == "play_engine" and self.board_state.turn != self.user_color:
                    return
                self.make_user_move(move)
            elif self.board_state.piece_at(clicked_square) and self.board_state.piece_at(clicked_square).color == self.board_state.turn:
                self.selected_square_for_move = clicked_square
                self.highlight_legal_moves(clicked_square)
        else:
            piece = self.board_state.piece_at(clicked_square)
            if piece and piece.color == self.board_state.turn:
                if self.game_mode == "play_engine" and self.board_state.turn != self.user_color:
                    return
                self.selected_square_for_move = clicked_square
                self.highlight_legal_moves(clicked_square)

    def next_move_action(self) -> None:
        if self.current_game_node and self.current_game_node.variations:
            target_node = self.current_game_node.variation(0)
            move = target_node.move
            captured = self._is_capture_move(move)
            animated_piece_symbol = self.get_animated_piece_symbol(move)
            self._set_active_node(
                target_node,
                is_forward_move=True,
                move_to_animate=move,
                captured=captured,
                animated_piece_symbol=animated_piece_symbol,
            )

    def prev_move_action(self) -> None:
        if self.current_game_node and self.current_game_node.parent is not None:
            move_to_undo = self.current_game_node.move
            target_node = self.current_game_node.parent
            animated_piece_symbol = self.get_animated_piece_symbol(move_to_undo, is_undo=True)
            self._set_active_node(
                target_node,
                is_forward_move=False,
                move_to_animate=move_to_undo,
                animated_piece_symbol=animated_piece_symbol,
            )

    def first_move_action(self) -> None:
        if self.current_game_node:
            root_node = self.current_game_node.game()
            if root_node != self.current_game_node:
                self._set_active_node(root_node)

    def last_move_action(self) -> None:
        if not self.current_game_node:
            return

        target_node = self.current_game_node
        while target_node.variations:
            target_node = target_node.variation(0)

        if target_node != self.current_game_node:
            self._set_active_node(target_node)

    def on_move_select_from_listbox(self, event: tk.Event) -> None:
        if self.is_animating or not event.widget.curselection():
            return

        selected_idx = event.widget.curselection()[0]
        if 0 <= selected_idx < len(self.move_nodes_in_listbox):
            target_node = self.move_nodes_in_listbox[selected_idx]
            if target_node != self.current_game_node:
                self._set_active_node(target_node)

    def populate_variation_tree(self) -> None:
        if not hasattr(self, "variation_tree"):
            return

        for item in self.variation_tree.get_children():
            self.variation_tree.delete(item)
        self.variation_tree_nodes = {}

        if not self.current_game_node:
            return

        root_node = self.current_game_node.game()
        root_id = self.variation_tree.insert("", "end", text="Начало", open=True)
        self.variation_tree_nodes[root_id] = root_node

        def add_children(parent_item: str, node: chess.pgn.GameNode, board: chess.Board) -> None:
            for idx, child in enumerate(node.variations):
                san = board.san(child.move)
                move_prefix = f"{board.fullmove_number}. " if board.turn == chess.WHITE else f"{board.fullmove_number}... "
                label = move_prefix + san
                if idx > 0:
                    label = f"[V{idx}] {label}"
                item_id = self.variation_tree.insert(parent_item, "end", text=label, open=(idx == 0))
                self.variation_tree_nodes[item_id] = child
                board.push(child.move)
                add_children(item_id, child, board)
                board.pop()

        add_children(root_id, root_node, root_node.board())
        self._sync_variation_tree_selection()

    def _sync_variation_tree_selection(self) -> None:
        if not hasattr(self, "variation_tree"):
            return
        for item_id, node in self.variation_tree_nodes.items():
            if node == self.current_game_node:
                self.variation_tree.selection_set(item_id)
                self.variation_tree.focus(item_id)
                parent = item_id
                while parent:
                    parent = self.variation_tree.parent(parent)
                    if parent:
                        self.variation_tree.item(parent, open=True)
                self.variation_tree.see(item_id)
                break

    def on_variation_tree_select(self, event: Optional[tk.Event] = None) -> None:
        if not hasattr(self, "variation_tree"):
            return
        selection = self.variation_tree.selection()
        if not selection:
            return
        node = self.variation_tree_nodes.get(selection[0])
        if node and node != self.current_game_node:
            self._set_active_node(node)

    def _get_selected_variation_node(self) -> Optional[chess.pgn.GameNode]:
        if not hasattr(self, "variation_tree"):
            return None
        selection = self.variation_tree.selection()
        if not selection:
            return None
        return self.variation_tree_nodes.get(selection[0])

    def promote_selected_variation_to_main(self) -> None:
        node = self._get_selected_variation_node()
        if not node or node.parent is None:
            return
        node.parent.promote_to_main(node)
        self.invalidate_cached_report()
        self.populate_variation_tree()
        self.populate_moves_listbox()
        self._set_active_node(node)

    def delete_selected_variation(self) -> None:
        node = self._get_selected_variation_node()
        if not node or node.parent is None:
            return
        parent = node.parent
        if messagebox.askyesno("Удалить вариант", "Удалить выбранный вариант со всеми продолжениями?"):
            parent.remove_variation(node)
            self.invalidate_cached_report()
            self._set_active_node(parent)

    def add_selected_engine_variation(self) -> None:
        if not self.latest_analysis_lines or not self.current_game_node:
            messagebox.showwarning("Нет анализа", "Сначала проанализируйте текущую позицию.")
            return
        if self.latest_analysis_fen != self.board_state.fen():
            messagebox.showwarning("Нет анализа", "Актуальные линии анализа для этой позиции отсутствуют.")
            return

        selected_line = self.latest_analysis_lines[0]
        selection = self.eval_tree.selection()
        if selection:
            selected_pv = self.eval_tree.item(selection[0], "values")[0]
            for line in self.latest_analysis_lines:
                if str(line.get("pv")) == str(selected_pv):
                    selected_line = line
                    break

        move_uci = selected_line.get("move_uci")
        if not move_uci:
            return
        try:
            move = self.board_state.parse_uci(move_uci)
        except Exception:
            messagebox.showerror("Вариант", "Не удалось добавить вариант из анализа.")
            return

        self.invalidate_cached_report()
        target_node = None
        for variation in self.current_game_node.variations:
            if variation.move == move:
                target_node = variation
                break
        if target_node is None:
            target_node = self.current_game_node.add_variation(move)
        self._set_active_node(target_node)

    def show_annotation_menu(self, event: tk.Event) -> None:
        selection = self.moves_listbox.curselection()
        if not selection:
            return

        selected_idx = selection[0]
        if selected_idx == 0:
            return

        node_to_annotate = self.move_nodes_in_listbox[selected_idx]
        menu = tk.Menu(self.root, tearoff=0)
        nags = {
            "Хороший ход (!)": 1,
            "Ошибка (?)": 2,
            "Блестящий ход (!!)": 3,
            "Грубый зевок (??)": 4,
            "Интересный ход (!?)": 5,
            "Сомнительный ход (?!)": 6,
        }
        for label, code in nags.items():
            menu.add_command(label=label, command=lambda c=code: self.add_nag_annotation(node_to_annotate, c))

        menu.add_separator()
        menu.add_command(label="Добавить/изменить комментарий...", command=lambda: self.add_text_comment(node_to_annotate))
        menu.add_command(label="Очистить аннотации", command=lambda: self.clear_annotations(node_to_annotate))
        menu.tk_popup(event.x_root, event.y_root)

    def add_nag_annotation(self, node: chess.pgn.GameNode, nag_code: int) -> None:
        node.nags.add(nag_code)
        self.populate_moves_listbox()

    def add_text_comment(self, node: chess.pgn.GameNode) -> None:
        comment = simpledialog.askstring("Комментарий", "Введите ваш комментарий:", initialvalue=node.comment, parent=self.root)
        if comment is not None:
            node.comment = comment
            self.populate_moves_listbox()

    def clear_annotations(self, node: chess.pgn.GameNode) -> None:
        node.nags.clear()
        node.comment = ""
        self.populate_moves_listbox()

    def _set_active_node(
        self,
        target_node: Optional[chess.pgn.GameNode],
        is_forward_move: Optional[bool] = None,
        move_to_animate: Optional[chess.Move] = None,
        captured: bool = False,
        animated_piece_symbol: Optional[str] = None,
    ) -> None:
        if self.is_animating or target_node is None:
            return

        self.current_game_node = target_node
        self.board_state = self.current_game_node.board()

        if move_to_animate:
            self.update_board_display(
                move_to_animate=move_to_animate,
                captured=captured,
                is_reverse_animation=not is_forward_move,
                animated_piece_symbol=animated_piece_symbol,
            )
        else:
            self.update_board_display()
            self.update_info_panel()
            self.update_navigation_buttons()
        self._sync_variation_tree_selection()

    def animate_move(self, move: chess.Move, captured: bool, is_reverse_animation: bool, piece_symbol: str) -> None:
        from_sq, to_sq = (move.to_square, move.from_square) if is_reverse_animation else (move.from_square, move.to_square)
        start_x, start_y = self.get_square_coords(from_sq)
        end_x, end_y = self.get_square_coords(to_sq)

        animated_image = self.piece_images.get(piece_symbol)
        if not animated_image:
            self._finalize_animation_and_update()
            return

        animating_piece_id = self.board_canvas.create_image(start_x, start_y, anchor=tk.NW, image=animated_image, tags="anim_piece")
        self.board_canvas.tag_raise(animating_piece_id)

        self.board_canvas.delete(f"piece_at_{from_sq}")
        if not is_reverse_animation and captured:
            self.board_canvas.delete(f"piece_at_{to_sq}")

        dx = (end_x - start_x) / ANIMATION_STEPS
        dy = (end_y - start_y) / ANIMATION_STEPS

        def animation_step(step: int) -> None:
            if step <= ANIMATION_STEPS:
                self.board_canvas.move(animating_piece_id, dx, dy)
                self.root.after(ANIMATION_DELAY, lambda: animation_step(step + 1))
            else:
                self.board_canvas.delete(animating_piece_id)
                self._finalize_animation_and_update(played_sound=is_reverse_animation, captured=captured)

        animation_step(1)

    def _finalize_animation_and_update(self, played_sound: bool = False, captured: bool = False) -> None:
        self.is_animating = False
        if not played_sound:
            self.play_sound(captured)
        self.update_board_display()
        self.update_info_panel()
        self.update_navigation_buttons()
        self._sync_variation_tree_selection()

    def get_best_moves_from_treeview(self) -> List[chess.Move]:
        moves: List[chess.Move] = []
        for item in self.eval_tree.get_children():
            move_san = self.eval_tree.item(item, "values")[1]
            try:
                moves.append(self.board_state.parse_san(move_san))
            except Exception:
                continue
        return moves

    def get_animated_piece_symbol(self, move: chess.Move, is_undo: bool = False) -> Optional[str]:
        if is_undo:
            piece = self.board_state.piece_at(move.to_square)
            if piece:
                return piece.symbol()
            if move.promotion:
                return "P" if self.board_state.turn == chess.BLACK else "p"
        else:
            if move.promotion:
                promotion_symbol = chess.piece_symbol(move.promotion)
                return promotion_symbol.upper() if self.board_state.turn == chess.WHITE else promotion_symbol.lower()

            piece = self.board_state.piece_at(move.from_square)
            if piece:
                return piece.symbol()
        return None

    def create_move_obj(self, from_sq: int, to_sq: int) -> Optional[chess.Move]:
        move = chess.Move(from_sq, to_sq)
        piece = self.board_state.piece_at(from_sq)
        if piece and piece.piece_type == chess.PAWN:
            is_white_promo = chess.square_rank(to_sq) == 7 and piece.color == chess.WHITE
            is_black_promo = chess.square_rank(to_sq) == 0 and piece.color == chess.BLACK
            if is_white_promo or is_black_promo:
                promo = simpledialog.askstring("Превращение", "В какую фигуру (q, r, b, n)?", initialvalue="q")
                if promo and promo.lower() in "qrbn":
                    move.promotion = {
                        "q": chess.QUEEN,
                        "r": chess.ROOK,
                        "b": chess.BISHOP,
                        "n": chess.KNIGHT,
                    }[promo.lower()]
                else:
                    return None
        return move
