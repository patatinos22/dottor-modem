"""
main_optimizer.py - Dottor Modem v11.0
Launcher standalone per la scheda Ottimizzatore (chiede UAC automatico).
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
    ok = messagebox.askyesno("Privilegi richiesti",
                             "L'Ottimizzatore richiede privilegi amministratore.\nRiavviare?")
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
    root.geometry("900x700")
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    OptimizerTab(root).pack(fill="both", expand=True)
    root.mainloop()


if __name__ == "__main__":
    main()
