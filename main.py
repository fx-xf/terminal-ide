# main.py
from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, Input, Static, DirectoryTree, TextArea
from textual.reactive import reactive


class StatusBar(Static):
    """Простой статус-виджет слева внизу."""

    path: reactive[str] = reactive("")

    def watch_path(self, value: str) -> None:  # type: ignore[override]
        self.update(f"[b]Текущая директория:[/b] {value}")


class Preview(TextArea):
    """Правый просмотрщик файла (read-only)."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.read_only = True
        self.syntax = ""

    def show_file(self, path: Path) -> None:
        try:
            text = path.read_text(errors="replace")
        except UnicodeDecodeError:
            text = "[Бинарный файл — предварительный просмотр отключён]"
        except Exception as e:
            text = f"[Ошибка чтения: {e}]"
        # Ограничим объём, чтобы не лагала TUI
        if len(text) > 5000:
            text = text[:5000] + "[Обрезано: файл длиннее 5000 символов]"
        # Подсветка по расширению
        self.syntax = _guess_syntax(path)
        self.load_text(text)


def _guess_syntax(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".py": "python",
        ".md": "markdown",
        ".json": "json",
        ".toml": "toml",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".ts": "typescript",
        ".js": "javascript",
        ".css": "css",
        ".html": "html",
        ".xml": "xml",
        ".sh": "bash",
    }.get(ext, "")


class TerminalIDE(App):
    CSS = """
    Screen { layout: vertical; }

    .body { height: 1fr; }

    DirectoryTree { width: 40%; border: solid $accent 20%; }

    Preview { width: 1fr; border: tall $primary 10%; }

    StatusBar { height: 3; color: $text; background: $panel; padding: 0 1; }

    #toolbar { height: 3; dock: top; background: $panel-darken-1; padding: 0 1; }
    """

    BINDINGS = [
        ("q", "quit", "Выйти"),
        ("r", "refresh_tree", "Обновить"),
        ("tab", "focus_next", "След. фокус"),
        ("shift+tab", "focus_previous", "Пред. фокус"),
        ("h", "go_up", "Вверх (родитель)"),
        ("a", "toggle_hidden", "Скрытые"),
        ("/", "focus_filter", "Фильтр"),
    ]

    def __init__(self, start_path: Path | None = None) -> None:
        super().__init__()
        self.start_path = Path.cwd() if start_path is None else start_path
        self.show_hidden = False
        self.dir_tree: DirectoryTree | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        # Примитивная "панель инструментов" с фильтром
        with Horizontal(id="toolbar"):
            yield Static("[b]Terminal IDE[/b] • стрелки/Enter — навигация • h — вверх • a — скрытые • r — обновить • / — фильтр")
            self.filter_input = Input(placeholder="Быстрый фильтр по имени…")
            yield self.filter_input

        with Horizontal(classes="body"):
            self.dir_tree = DirectoryTree(self.start_path, id="dir_tree")  # не используем имя `tree`, чтобы не конфликтовать с App.tree
            yield self.dir_tree

            with Vertical():
                self.preview = Preview(id="preview")
                yield self.preview
                self.status = StatusBar()
                yield self.status

        yield Footer()

    def on_mount(self) -> None:
        if self.dir_tree:
            self.dir_tree.focus()
        self.status.path = str(self.start_path)

    # ===== ДЕЙСТВИЯ =====
    def action_refresh_tree(self) -> None:
        # Переинициализация дерева — совместимо с разными версиями Textual
        current = self._current_dir()
        if self.dir_tree:
            try:
                self.dir_tree.remove()
            except Exception:
                pass
        new_tree = DirectoryTree(current, id="dir_tree")
        try:
            new_tree.show_hidden = self.show_hidden
        except Exception:
            pass
        self.dir_tree = new_tree
        self.mount(self.dir_tree, before=self.preview)
        self.status.path = str(current)
        self.refresh(layout=True)

    def action_go_up(self) -> None:
        parent = self._current_dir().parent
        try:
            if self.dir_tree:
                self.dir_tree.load_directory(parent)
        except Exception:
            # Фоллбэк — пересоздаём дерево
            try:
                if self.dir_tree:
                    self.dir_tree.remove()
            except Exception:
                pass
            self.dir_tree = DirectoryTree(parent, id="dir_tree")
            self.mount(self.dir_tree, before=self.preview)
        self.status.path = str(parent)

    def action_toggle_hidden(self) -> None:
        self.show_hidden = not self.show_hidden
        # Не все версии имеют свойство show_hidden — оборачиваем в try
        try:
            if self.dir_tree:
                self.dir_tree.show_hidden = self.show_hidden
        except Exception:
            pass
        self.action_refresh_tree()

    def action_focus_filter(self) -> None:
        self.filter_input.focus()

    # ===== ВСПОМОГАТЕЛЬНОЕ =====
    def _current_dir(self) -> Path:
        tree = self.dir_tree
        if not tree:
            return self.start_path
        node = getattr(tree, "cursor_node", None)
        path = getattr(node, "data", self.start_path) if node else self.start_path
        path = path if isinstance(path, Path) else self.start_path
        return path if path.is_dir() else path.parent

    # ===== СОБЫТИЯ =====
    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        self.status.path = str(event.path)

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        self.status.path = str(event.path.parent)
        self.preview.show_file(event.path)

    def on_input_changed(self, event: Input.Changed) -> None:
        query = event.value.strip().lower()
        self._apply_filter(query)

    def _apply_filter(self, query: str) -> None:
        # Очень простой фильтр: скрываем узлы, не содержащие подстроку в имени (кроме корня)
        tree = self.dir_tree
        if not tree:
            return
        root = getattr(tree, "root", None)
        if not root:
            return
        for node in root.walk():
            if node is root:
                node.show = True
                continue
            name = node.label.plain.lower() if hasattr(node.label, "plain") else str(node.label).lower()
            node.show = query in name if query else True


if __name__ == "__main__":
    TerminalIDE().run()
