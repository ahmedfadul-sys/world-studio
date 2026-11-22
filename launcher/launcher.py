"""World Studio launcher (what the Start-menu shortcut runs). Uses only the standard library; shows a small progress window
while environments are prepared (first run: a few minutes; afterwards: instant) and then hands over to the studio."""
import os
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent / "app" if (HERE.parent / "app" / "studio").is_dir() else HERE.parent       # installed layout vs repo layout
sys.path.insert(0, str(ROOT))

from studio import bootstrap  # noqa: E402


def main() -> int:
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception:                       # no Tk: run headless
        return bootstrap.main()
    win = tk.Tk()
    win.title("World Studio")
    win.geometry("520x150")
    win.resizable(False, False)
    msg = tk.StringVar(value="Starting…")
    ttk.Label(win, text="World Studio", font=("Segoe UI", 14, "bold")).pack(pady=(14, 4))
    ttk.Label(win, textvariable=msg, wraplength=480).pack(pady=4)
    bar = ttk.Progressbar(win, mode="indeterminate", length=440)
    bar.pack(pady=8)
    bar.start(12)
    code = {"v": 0}

    def work():
        code["v"] = bootstrap.run_forever(lambda s: msg.set(s))
        win.after(0, win.destroy)

    threading.Thread(target=work, daemon=True).start()
    win.mainloop()
    return code["v"]


if __name__ == "__main__":
    sys.exit(main())
