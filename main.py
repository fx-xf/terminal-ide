from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Input, Static, TextArea, Button, ListView, ListItem
from textual.reactive import reactive
from textual.screen import ModalScreen

# =====================
# МОДАЛЬНОЕ ОКНО ПОДТВЕРЖДЕНИЯ СОХРАНЕНИЯ
# =====================
class SaveConfirm(ModalScreen[str]):
    def compose(self) -> ComposeResult:  # type: ignore[override]
        with Vertical(id="confirm-root"):
            yield Static("У вас есть несохранённые изменения. Сохранить файл перед продолжением?", id="confirm-text")
            with Horizontal(id="confirm-buttons"):
                yield Button("Сохранить", id="save", variant="primary")
                yield Button("Не сохранять", id="discard")
                yield Button("Отмена", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:  # type: ignore[override]
        self.dismiss(event.button.id or "cancel")


class StatusBar(Static):
    path: reactive[str] = reactive("")
    dirty: reactive[bool] = reactive(False)

    def watch_path(self, value: str) -> None:  # type: ignore[override]
        self._repaint()

    def watch_dirty(self, value: bool) -> None:  # type: ignore[override]
        self._repaint()

    def _repaint(self) -> None:
        star = " *" if self.dirty else ""
        self.update(f"[b]Текущая директория:[/b] {self.path}{star}")


class Editor(TextArea):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.read_only = False
        self.syntax = ""

    def show_file(self, path: Path) -> None:
        try:
            text = path.read_text(errors="replace")
        except UnicodeDecodeError:
            text = "[Бинарный файл — редактирование отключено]"
        except Exception as e:
            text = f"[Ошибка чтения: {e}]"
        self.syntax = _guess_syntax(path)
        self.load_text(text)

    def get_text(self) -> str:
        for attr in ("text", "value"):
            if hasattr(self, attr):
                try:
                    return getattr(self, attr)
                except Exception:
                    pass
        try:
            return self.document.text  # type: ignore[attr-defined]
        except Exception:
            pass
        return ""


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


# =====================
# EXPLORER (в стиле mc): ListView с пунктом ".." наверху
# =====================
@dataclass
class ExplorerEntry:
    path: Path
    is_dir: bool
    is_up: bool = False  # это тот самый пункт ".."
    name: str = ""


class Explorer(ListView):
    current_path: reactive[Path] = reactive(Path.cwd())
    show_hidden: reactive[bool] = reactive(False)

    def __init__(self, root_path: Path) -> None:
        super().__init__(id="explorer")
        self.current_path = root_path.resolve()
        self._entries: List[ExplorerEntry] = []  # полный список без фильтра

    def on_mount(self) -> None:
        self.load_directory(self.current_path)

    # ---- Публичные API ----
    def load_directory(self, path: Path) -> None:
        path = path.resolve()
        if not path.exists() or not path.is_dir():
            return
        self.current_path = path
        self.clear()
        self._entries = []

        # Всегда добавляем пункт ".." первым
        up = path.parent if path.parent != path else path  # на корне ведёт в себя же
        up_entry = ExplorerEntry(path=up, is_dir=True, is_up=True, name="..")
        self._entries.append(up_entry)

        try:
            items = sorted(
                path.iterdir(),
                key=lambda p: (0 if p.is_dir() else 1, p.name.lower()),
            )
        except PermissionError:
            items = []

        for p in items:
            name = p.name + ("/" if p.is_dir() else "")
            if not self.show_hidden and name.startswith('.'):
                # скрытые (Unix): пропускаем
                continue
            self._entries.append(ExplorerEntry(path=p, is_dir=p.is_dir(), name=name))

        # Отрисовать (без фильтра)
        self._render_entries(self._entries)

    def apply_filter(self, query: str) -> None:
        if not query:
            self._render_entries(self._entries)
            return
        q = query.lower()
        filtered = [e for e in self._entries if e.is_up or q in e.name.lower()]
        self._render_entries(filtered)

    def get_selected_entry(self) -> Optional[ExplorerEntry]:
        try:
            idx = self.index
        except Exception:
            return None
        if idx is None:
            return None
        try:
            item = self.children[idx]
        except IndexError:
            return None
        return getattr(item, "data", None)

    # ---- Внутреннее ----
    def _render_entries(self, entries: List[ExplorerEntry]) -> None:
        self.clear()
        for e in entries:
            label = (".." if e.is_up else e.name)
            item = ListItem(Static(label))
            item.data = e  # прикрепим метаданные
            self.append(item)
        # выделяем первый
        try:
            if len(self.children) > 0:
                self.index = 0
        except Exception:
            pass


class TerminalIDE(App):
    CSS = """
    Screen { layout: vertical; }
    .body { height: 1fr; }
    #explorer { width: 40%; border: solid $accent 20%; }
    TextArea { width: 1fr; border: tall $primary 10%; }
    StatusBar { height: 3; color: $text; background: $panel; padding: 0 1; }
    #toolbar { height: 3; dock: top; background: $panel-darken-1; padding: 0 1; }
    #confirm-root { padding: 1; width: 80%; max-width: 80; border: round $accent; background: $panel; }
    #confirm-text { padding: 1; }
    #confirm-buttons { padding: 1; content-align: center middle; }
    """

    BINDINGS = [
        ("q", "quit", "Выйти"),
        ("r", "refresh_tree", "Обновить"),
        ("tab", "focus_next", "След. фокус"),
        ("shift+tab", "focus_previous", "Пред. фокус"),
        ("h", "go_up", "Вверх (родитель)"),
        ("a", "toggle_hidden", "Скрытые"),
        ("/", "focus_filter", "Фильтр"),
        ("ctrl+b", "toggle_focus", "Перекл. фокуса"),
        ("ctrl+s", "save_file", "Сохранить"),
        ("ctrl+shift+s", "save_file_as", "Сохранить как"),
        ("enter", "open_selected", "Открыть/Зайти"),
        ("backspace", "go_up", "Вверх"),
    ]

    def __init__(self, start_path: Optional[Path] = None) -> None:
        super().__init__()
        self.start_path = Path.cwd() if start_path is None else start_path
        self.show_hidden = False
        self.explorer: Explorer | None = None
        self.editor: Editor | None = None
        self.status: StatusBar | None = None
        self.current_file: Optional[Path] = None
        self._dirty: bool = False
        self._awaiting_save_path: bool = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="toolbar"):
            yield Static("[b]Terminal IDE[/b] • Enter — открыть/зайти • Backspace/h — вверх • a — скрытые • r — обновить • / — фильтр • Ctrl+S — сохранить • Ctrl+B — переключить фокус")
            self.filter_input = Input(placeholder="Быстрый фильтр по имени…")
            yield self.filter_input
        with Horizontal(classes="body"):
            self.explorer = Explorer(self.start_path)
            yield self.explorer
            with Vertical():
                self.editor = Editor(id="editor")
                yield self.editor
                self.status = StatusBar()
                yield self.status

    def on_mount(self) -> None:
        if self.explorer:
            self.explorer.focus()
        if self.status:
            self.status.path = str(self.start_path)

    # ===== ДЕЙСТВИЯ =====
    def action_refresh_tree(self) -> None:
        if self.explorer:
            self.explorer.load_directory(self.explorer.current_path)
        if self.status and self.explorer:
            self.status.path = str(self.explorer.current_path)

    def action_go_up(self) -> None:
        if not self.explorer:
            return
        parent = self.explorer.current_path.parent
        self.explorer.load_directory(parent)
        if self.status:
            self.status.path = str(parent)

    def action_toggle_hidden(self) -> None:
        if not self.explorer:
            return
        self.explorer.show_hidden = not self.explorer.show_hidden
        self.explorer.load_directory(self.explorer.current_path)

    def action_focus_filter(self) -> None:
        self.filter_input.focus()

    def action_focus_explorer(self) -> None:
        if self.explorer:
            self.explorer.focus()

    def action_focus_editor(self) -> None:
        if self.editor:
            self.editor.focus()

    def action_toggle_focus(self) -> None:
        # Если фокус в редакторе — переключаем в проводник, иначе в редактор
        try:
            focused = self.focused  # Textual предоставляет текущий виджет с фокусом
        except Exception:
            focused = None
        if focused is self.editor and self.explorer:
            self.explorer.focus()
        elif self.editor:
            self.editor.focus()

    def action_open_selected(self) -> None:
        # Поведение как в mc: Enter/→ по элементу — если папка/".." — зайти, если файл — открыть
        if not self.explorer:
            return
        entry = self.explorer.get_selected_entry()
        if not isinstance(entry, ExplorerEntry):
            return
        if entry.is_up:
            self.action_go_up()
        elif entry.is_dir:
            self.explorer.load_directory(entry.path)
            if self.status:
                self.status.path = str(entry.path)
        else:
            # файл — открыть в редакторе
            self._open_file(entry.path)

    # Клик мышью в списке — как Enter
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if getattr(event.list_view, "id", "") == "explorer":
            self.action_open_selected()

    # ---- Сохранение ----
    def action_save_file(self) -> None:
        if not self.editor:
            return
        if self.current_file is None:
            self.action_save_file_as()
            return
        self._write_to_path(self.current_file)

    def action_save_file_as(self) -> None:
        self.filter_input.placeholder = "Введите путь для сохранения и нажмите Enter…"
        self.filter_input.value = str(self.current_file or (self._current_dir() / "untitled.txt"))
        self.filter_input.focus()
        self._awaiting_save_path = True

    # ===== ПОМОГАЮЩЕЕ =====
    def _current_dir(self) -> Path:
        if self.explorer:
            return self.explorer.current_path
        return self.start_path

    def _set_dirty(self, value: bool) -> None:
        self._dirty = value
        if self.status:
            self.status.dirty = value

    def _write_to_path(self, path: Path) -> None:
        try:
            text = self.editor.get_text() if self.editor else ""
            path.write_text(text)
            self.current_file = path
            self._set_dirty(False)
            if self.status:
                self.status.path = str(path.parent)
            self.bell()
        except Exception as e:
            self.notify(f"Ошибка сохранения: {e}", severity="error")

    async def _confirm_unsaved(self) -> str:
        result = await self.push_screen_wait(SaveConfirm())
        return result or "cancel"

    async def _maybe_proceed_after_unsaved(self, next_file: Optional[Path] = None, quitting: bool = False) -> None:
        if not self._dirty:
            if quitting:
                self.exit()
                return
            if next_file is not None:
                self._open_file(next_file)
            return
        answer = await self._confirm_unsaved()
        if answer == "save":
            if self.current_file is None and next_file is not None:
                self.current_file = next_file
            if self.current_file is None:
                self.action_save_file_as()
                return
            self._write_to_path(self.current_file)
            if quitting:
                self.exit()
            elif next_file is not None:
                self._open_file(next_file)
        elif answer == "discard":
            if quitting:
                self.exit()
            elif next_file is not None:
                self._open_file(next_file)
        else:
            return

    def _open_file(self, path: Path) -> None:
        if not self.editor:
            return
        self.editor.show_file(path)
        self.current_file = path
        self._set_dirty(False)
        if self.status:
            self.status.path = str(path.parent)

    # ===== СОБЫТИЯ =====
    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        ta = getattr(event, "control", getattr(event, "sender", None))
        if ta is self.editor:
            self._set_dirty(True)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._awaiting_save_path:
            try:
                path = Path(event.value).expanduser().resolve()
                self._write_to_path(path)
            finally:
                self._awaiting_save_path = False
                self.filter_input.placeholder = "Быстрый фильтр по имени…"
                self.filter_input.value = ""
        else:
            query = event.value.strip().lower()
            if self.explorer:
                self.explorer.apply_filter(query)

    def on_input_changed(self, event: Input.Changed) -> None:
        if self._awaiting_save_path:
            return
        query = event.value.strip().lower()
        if self.explorer:
            self.explorer.apply_filter(query)

    async def action_quit(self) -> None:
        await self._maybe_proceed_after_unsaved(quitting=True)


if __name__ == "__main__":
    TerminalIDE().run()
