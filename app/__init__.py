from .helpers import ensure_assets_exist

__all__ = ["ChessAnalyzerApp", "ensure_assets_exist"]


def __getattr__(name: str):
    if name == "ChessAnalyzerApp":
        from .app import ChessAnalyzerApp

        return ChessAnalyzerApp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
