"""
main_optimizer.py - Dottor Modem v11.1
Launcher standalone dell'Ottimizzatore (UAC automatico, UI ridisegnata).
"""
from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from tkinter import ttk, messagebox


def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def ensure_admin():
    if is_admin():
        return
    root = tk.Tk()
    root.withdraw()
    ok = messagebox.askyesno(
        "Permessi richiesti",
        "L'Ottimizzatore deve poter modificare le impostazioni di rete.\n\n"
        "Vuoi riavviarlo come Amministratore?"
    )
    if ok:
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, '"' + __file__ + '"', None, 1
        )
    root.destroy()
    sys.exit(0)


def main():
    ensure_admin()
    from ui.optimizer_tab import OptimizerTab

    root = tk.Tk()
    root.title("Dottor Modem - Ottimizzatore Rete")
    root.configure(bg="#f4f6fa")

    # Centra la finestra 1100x780
    w, h = 1100, 780
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    x, y = (sw - w) // 2, (sh - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")
    root.minsize(950, 700)

    try:
        ttk.Style().theme_use("clam")
    except tk.TclError:
        pass

    OptimizerTab(root).pack(fill="both", expand=True)
    root.mainloop()


if __name__ == "__main__":
    main()
