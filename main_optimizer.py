"""Launcher Ottimizzatore - Dottor Modem v12."""
import ctypes, sys, tkinter as tk
from tkinter import messagebox
import customtkinter as ctk


def is_admin():
    try: return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception: return False


def ensure_admin():
    if is_admin(): return
    root = tk.Tk(); root.withdraw()
    if messagebox.askyesno("Permessi", "Riavviare come Amministratore?"):
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, '"' + __file__ + '"', None, 1)
    root.destroy(); sys.exit(0)


def main():
    ensure_admin()
    from ui.optimizer_tab import OptimizerTab
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = ctk.CTk()
    app.title("Dottor Modem - Ottimizzatore")
    app.configure(fg_color="#111827")
    w, h = 1100, 820
    sw, sh = app.winfo_screenwidth(), app.winfo_screenheight()
    app.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
    app.minsize(1000, 720)
    OptimizerTab(app).pack(fill="both", expand=True)
    app.mainloop()


if __name__ == "__main__":
    main()
