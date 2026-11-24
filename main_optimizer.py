"""Launcher con shell Apple-style."""
import ctypes, sys, os, traceback
import tkinter as tk
from tkinter import messagebox

_HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(_HERE, "dottor_modem_error.log")


def is_admin():
    try: return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception: return False


def relaunch():
    script = os.path.abspath(sys.argv[0])
    ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, f'"{script}"', _HERE, 1)
    if ret <= 32:
        r = tk.Tk(); r.withdraw()
        messagebox.showerror("Errore", "Avvia PowerShell come Amministratore e digita:\npython main_optimizer.py")
        r.destroy()
    sys.exit(0)


def main():
    try:
        if not is_admin():
            relaunch()
            return
        from ui.app_shell import AppShell
        AppShell().mainloop()
    except Exception:
        tb = traceback.format_exc()
        with open(LOG, "w", encoding="utf-8") as f: f.write(tb)
        r = tk.Tk(); r.withdraw()
        messagebox.showerror("Errore", tb[:800] + "\n\nLog: " + LOG)
        r.destroy()


if __name__ == "__main__":
    main()
