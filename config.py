import os

# Визуальные константы
BOARD_IMG_WIDTH = 600
BOARD_IMG_HEIGHT = 600
SQUARE_SIZE = BOARD_IMG_WIDTH // 8

# Панель информации справа
INFO_PANEL_WIDTH = 420
EVAL_BAR_HEIGHT = 28

# Ассеты
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
IMAGE_DIR = os.path.join(ASSETS_DIR, "images")
PIECE_DIR = os.path.join(IMAGE_DIR, "pieces")
SOUND_DIR = os.path.join(ASSETS_DIR, "sounds")
if not os.path.isdir(SOUND_DIR):
    legacy_sound_dir = os.path.join(ASSETS_DIR, "sound")
    if os.path.isdir(legacy_sound_dir):
        SOUND_DIR = legacy_sound_dir
PIECE_SYMBOL_TO_FILE = {
    'P': 'wp.png', 'N': 'wn.png', 'B': 'wb.png', 'R': 'wr.png', 'Q': 'wq.png', 'K': 'wk.png',
    'p': 'bp.png', 'n': 'bn.png', 'b': 'bb.png', 'r': 'br.png', 'q': 'bq.png', 'k': 'bk.png'
}

# Анимация
ANIMATION_STEPS = 10
ANIMATION_DELAY = 0

# Engine defaults
DEFAULT_ENGINE_SKILL = 20
DEFAULT_ENGINE_MULTIPV = 3
DEFAULT_ENGINE_MOVETIME_MS = 2000

# Путь к stockfish
_stockfish_from_env = os.getenv("STOCKFISH_PATH")
if _stockfish_from_env:
    STOCKFISH_PATH_WINDOWS = _stockfish_from_env
    STOCKFISH_PATH_UNIX = _stockfish_from_env
else:
    STOCKFISH_PATH_WINDOWS = os.path.join(BASE_DIR, "stockfish.exe")
    STOCKFISH_PATH_UNIX = os.path.join(BASE_DIR, "stockfish")

# Подсказки
BOARD_ONLY_HINTS = [
    "Подсказки:",
    "← / → : перемотка по ходам",
    "F : перевернуть доску",
    "A : проанализировать позицию",
    "T : показать угрозу",
    "Space : включить/выключить режим только доски"
]
