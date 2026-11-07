"""System tray integration for the Tk desktop window."""

from __future__ import annotations

import threading
from collections.abc import Callable

from PIL import Image
from importlib import resources


def load_app_icon() -> Image.Image:
    with resources.files("hourly_tracker").joinpath("assets", "hourly-tracker.png").open("rb") as file:
        return Image.open(file).copy()


class SystemTray:
    def __init__(
        self,
        on_show: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._on_show = on_show
        self._on_quit = on_quit
        self._icon = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        import pystray
        image = load_app_icon()

        menu = pystray.Menu(
            pystray.MenuItem("Open Hourly Tracker", self._show, default=True),
            pystray.MenuItem("Quit", self._quit),
        )
        self._icon = pystray.Icon(
            "hourly-tracker",
            image,
            "Hourly Tracker",
            menu,
        )
        self._thread = threading.Thread(
            target=self._icon.run,
            name="hourly-tracker-system-tray",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        icon = self._icon
        self._icon = None
        if icon is not None:
            icon.stop()

    def _show(self, icon=None, item=None) -> None:
        self._on_show()

    def _quit(self, icon=None, item=None) -> None:
        self._on_quit()
