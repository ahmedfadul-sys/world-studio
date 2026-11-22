"""Runs the whole studio: supervisor + shell + window. Exit code 75 means "restart me" (after an update)."""
from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser

import uvicorn

from . import paths, updater
from .shellserver import create_shell
from .supervisor import Supervisor, free_port, load_modules

RESTART = 75


def main() -> int:
    mods = load_modules(paths.CODE_ROOT)
    sup = Supervisor(mods)
    result = {"code": 0}
    server_holder: dict = {}

    def stop(code: int = 0):
        result["code"] = code
        if server_holder.get("server"):
            server_holder["server"].should_exit = True

    shell = create_shell(sup, paths.CODE_ROOT, on_restart=lambda: stop(RESTART), on_quit=lambda: stop(0))
    port = free_port(int(os.environ.get("STUDIO_PORT", "8100")))
    sup.start_all(wait_s=float(os.environ.get("STUDIO_START_WAIT", "60")))
    cfg = uvicorn.Config(shell, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(cfg)
    server_holder["server"] = server
    t = threading.Thread(target=server.run, daemon=True, name="shell")
    t.start()
    while not server.started and t.is_alive():
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}/"
    print(f"World Studio {paths.read_version()} → {url}", flush=True)

    window_mode = os.environ.get("STUDIO_WINDOW", "auto")
    opened_window = False
    if window_mode in ("auto", "native"):
        try:
            import webview                                   # type: ignore  # noqa: PLC0415
            w = webview.create_window("World Studio", url, width=1500, height=950, min_size=(1000, 650), text_select=True)
            w.events.closed += lambda: stop(result["code"])
            opened_window = True
            webview.start()                                  # blocks until the window is closed
        except Exception as e:  # noqa: BLE001
            if window_mode == "native":
                print("native window unavailable:", e, flush=True)
    if not opened_window:
        if window_mode != "none":
            webbrowser.open(url)
        # browser mode: leave when the page stops pinging (tab closed) or when /quit is called
        st = shell.state.shell
        while t.is_alive():
            time.sleep(1)
            if st["pinged"] and time.time() - st["last_ping"] > 45:
                break
    stop(result["code"])
    t.join(timeout=5)
    sup.stop_all()
    return result["code"]


if __name__ == "__main__":
    sys.exit(main())
