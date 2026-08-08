import subprocess
import platform
import threading
import time
from typing import Optional, List, Tuple, Dict, Any
import queue
import re
import os

import chess

from config import (
    STOCKFISH_PATH_WINDOWS,
    STOCKFISH_PATH_UNIX,
)

def log_error(msg: str) -> None:
    print(f"[EngineHandler ERROR] {msg}")

class EngineHandler:
    def __init__(self, engine_path: Optional[str] = None, initial_skill_level: int = 20) -> None:
        if engine_path is None:
            self.engine_path = STOCKFISH_PATH_WINDOWS if platform.system() == "Windows" else STOCKFISH_PATH_UNIX
        else:
            self.engine_path = engine_path

        self.process: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._out_queue: "queue.Queue[str]" = queue.Queue()
        self._alive = threading.Event()
        self._command_lock = threading.RLock()
        self.skill_level = initial_skill_level
        self.is_ready = False
        self._start_engine()

    def _start_engine(self) -> None:
        if not os.path.exists(self.engine_path):
            hint = ""
            if platform.system() == "Darwin":
                hint = " Установите его: brew install stockfish, либо задайте STOCKFISH_PATH."
            log_error(f"Движок не найден: {self.engine_path}.{hint}")
            return
        if not os.access(self.engine_path, os.X_OK):
            log_error(f"Нет прав на запуск движка: {self.engine_path}. Выполните: chmod +x '{self.engine_path}'")
            return
        try:
            self.process = subprocess.Popen(
                [self.engine_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
        except Exception as e:
            log_error(f"Ошибка запуска движка: {e}")
            self.process = None
            return

        self._alive.set()
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

        self._send_command("uci")
        if not self._wait_for_token("uciok", timeout=3.0):
            log_error("Не получил uciok от движка.")
            return

        self.set_skill_level(self.skill_level)
        self.set_multi_pv(3)

        self._send_command("isready")
        if not self._wait_for_token("readyok", timeout=2.0):
            log_error("Движок не ответил readyok.")
            return

        self.is_ready = True

    def _reader_loop(self) -> None:
        if not self.process or not self.process.stdout:
            return
        try:
            while self._alive.is_set():
                line = self.process.stdout.readline()
                if not line:
                    if self.process.poll() is not None:
                        self._alive.clear()
                        break
                    time.sleep(0.01)
                    continue
                line = line.strip()
                if line:
                    self._out_queue.put(line)
        except Exception as e:
            log_error(f"Reader loop exception: {e}")
            self._alive.clear()

    def _send_command(self, command: str) -> None:
        if not self.process or not self.process.stdin:
            return
        try:
            self.process.stdin.write(command + "\n")
            self.process.stdin.flush()
        except Exception as e:
            log_error(f"Failed to send command '{command}': {e}")

    def _collect_until(self, stop_tokens: Optional[List[str]] = None, timeout: float = 2.0) -> List[str]:
        stop_tokens = stop_tokens or []
        collected = []
        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                line = self._out_queue.get(timeout=0.05)
                collected.append(line)
                for tok in stop_tokens:
                    if tok in line:
                        return collected
            except queue.Empty:
                continue
        return collected

    def _wait_for_token(self, token: str, timeout: float = 2.0) -> bool:
        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                line = self._out_queue.get(timeout=0.05)
                if token in line:
                    return True
            except queue.Empty:
                continue
        return False

    def set_skill_level(self, level: int) -> None:
        if not self.process:
            return
        with self._command_lock:
            level = max(0, min(20, int(level)))
            self.skill_level = level
            self._send_command(f"setoption name Skill Level value {self.skill_level}")

    def set_multi_pv(self, num_pvs: int) -> None:
        if not self.process:
            return
        with self._command_lock:
            num_pvs = max(1, min(10, int(num_pvs)))
            self._send_command(f"setoption name MultiPV value {num_pvs}")

    def set_position_from_fen(self, fen_string: str) -> None:
        if not self.process:
            return
        with self._command_lock:
            self._send_command(f"position fen {fen_string}")

    def get_analysis(self, movetime_ms: int = 1000) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        if not self.process or not self.is_ready:
            return [], None

        with self._command_lock:
            return self._get_analysis_locked(movetime_ms=movetime_ms)

    def _get_analysis_locked(self, movetime_ms: int) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        # self._command_lock.
        self._drain_queue_quick()
        self._send_command(f"go movetime {int(movetime_ms)}")

        latest_by_pv: Dict[int, Dict[str, Any]] = {}
        best_move: Optional[str] = None

        timeout = max(1.0, movetime_ms / 1000.0 + 1.0)
        end_time = time.time() + timeout

        score_re = re.compile(r"score (cp|mate) (-?\d+)")
        multipv_re = re.compile(r"multipv (\d+)")
        depth_re = re.compile(r"\bdepth (\d+)")
        pv_re = re.compile(r"\bpv\b (.+)$")

        while time.time() < end_time:
            try:
                line = self._out_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if line.startswith("info"):
                try:
                    mpv = 1
                    mv_uci = None
                    score_cp = None
                    score_mate = None
                    depth = 0

                    m_mpv = multipv_re.search(line)
                    if m_mpv:
                        mpv = int(m_mpv.group(1))

                    m_depth = depth_re.search(line)
                    if m_depth:
                        depth = int(m_depth.group(1))

                    m_score = score_re.search(line)
                    if m_score:
                        if m_score.group(1) == "cp":
                            score_cp = int(m_score.group(2))
                        else:
                            score_mate = int(m_score.group(2))

                    m_pv = pv_re.search(line)
                    if m_pv:
                        pv_moves = m_pv.group(1).split()
                        if pv_moves:
                            mv_uci = pv_moves[0]

                    candidate = {
                        'pv': mpv,
                        'depth': depth,
                        'score_cp': score_cp,
                        'score_mate': score_mate,
                        'move_uci': mv_uci,
                        'raw': line
                    }

                    prev = latest_by_pv.get(mpv)
                    if (
                        prev is None or
                        candidate['depth'] >= prev.get('depth', 0) or
                        (candidate['move_uci'] and not prev.get('move_uci'))
                    ):
                        latest_by_pv[mpv] = candidate
                except Exception:
                    continue
            elif line.startswith("bestmove"):
                parts = line.split()
                if len(parts) >= 2:
                    best_move = parts[1]
                break
            else:
                continue

        parsed_lines = list(latest_by_pv.values())
        parsed_lines.sort(key=lambda x: x.get('pv', 1))
        parsed_lines = parsed_lines[:5]
        return parsed_lines, best_move

    def analyze_position(self, fen_string: str, movetime_ms: int = 1000) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        if not self.process or not self.is_ready:
            return [], None
        with self._command_lock:
            self._send_command(f"position fen {fen_string}")
            return self._get_analysis_locked(movetime_ms=movetime_ms)

    def get_threat(self, fen_string: str, movetime_ms: int = 500) -> Optional[str]:
        if not self.process or not self.is_ready:
            return None
        try:
            board = chess.Board(fen_string)
            if board.is_game_over():
                return None

            with self._command_lock:
                self._send_command(f"position fen {fen_string}")
                _, best = self._get_analysis_locked(movetime_ms=movetime_ms)
                return best
        except Exception as e:
            log_error(f"Ошибка get_threat: {e}")
            return None

    def quit_engine(self) -> None:
        if not self.process:
            return
        try:
            with self._command_lock:
                self._send_command("quit")
                time.sleep(0.05)
                if self.process.poll() is None:
                    self.process.terminate()
                self._alive.clear()
                self.process.wait(timeout=1.0)
        except Exception:
            try:
                if self.process and self.process.poll() is None:
                    self.process.kill()
            except Exception:
                pass
        finally:
            self.process = None
            self.is_ready = False

    def _drain_queue_quick(self) -> None:
        try:
            while True:
                self._out_queue.get_nowait()
        except queue.Empty:
            pass
