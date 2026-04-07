import tkinter as tk
from tkinter import messagebox

from config import ASSETS_DIR
from app.app import ChessAnalyzerApp
from app.helpers import ensure_assets_exist


if __name__ == "__main__":
    root = tk.Tk()
    if not ensure_assets_exist():
        messagebox.showwarning("Внимание", f"Директория ассетов '{ASSETS_DIR}' не найдена. Некоторые ресурсы будут заменены заглушками.")
    app = ChessAnalyzerApp(root)
    root.mainloop()