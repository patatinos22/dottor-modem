"""Shell con sidebar e routing tra pagine."""
import customtkinter as ctk
from ctkfontawesome import icon_to_ctkimage
from core.optimizer import NetworkOptimizer, is_admin
from ui.pages.dashboard_page import DashboardPage
from ui.pages.optimizer_page import OptimizerPage
from ui.pages.speedtest_page import SpeedtestPage


class AppShell(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Dottor Modem")
        self.configure(fg_color="#111827")
        w, h = 1180, 800
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        self.minsize(1000, 700)

        self.opt = None
        if is_admin():
            try: self.opt = NetworkOptimizer()
            except Exception: pass

        self._icons = []
        self._build_sidebar()
        self.pages = {
            "dashboard": DashboardPage(self.content, self.opt),
            "optimizer": OptimizerPage(self.content, self.opt),
            "speedtest": SpeedtestPage(self.content, self.opt),
        }
        for p in self.pages.values():
            p.grid(row=0, column=0, sticky="nsew")
        self.show("dashboard")

    def _icon(self, name, size=20, color="#9ca3af"):
        img = icon_to_ctkimage(name, fill=color, scale_to_width=size)
        self._icons.append(img)
        return img

    def _build_sidebar(self):
        self.grid_columnconfigure(0, weight=0, minsize=200)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        side = ctk.CTkFrame(self, fg_color="#1f2937", corner_radius=0)
        side.grid(row=0, column=0, sticky="nsew")

        ctk.CTkLabel(side, text="Dottor Modem", font=("Segoe UI", 16, "bold")).pack(pady=(24, 4))
        ctk.CTkLabel(side, text="v12.2", text_color="#6b7280", font=("Segoe UI", 9)).pack(pady=(0, 20))

        for key, icon, label in [
            ("dashboard", "gauge", "Dashboard"),
            ("optimizer", "sliders-h", "Ottimizzazione"),
            ("speedtest", "wifi", "Speedtest"),
        ]:
            btn = ctk.CTkButton(side, text=f"  {label}", image=self._icon(icon), compound="left",
                                anchor="w", fg_color="transparent", hover_color="#374151",
                                text_color="#e5e7eb", font=("Segoe UI", 12),
                                command=lambda k=key: self.show(k))
            btn.pack(fill="x", padx=10, pady=3)

        status = "Admin OK" if is_admin() else "Avvia come Admin"
        color = "#16a34a" if is_admin() else "#f59e0b"
        ctk.CTkLabel(side, text=status, text_color=color, font=("Segoe UI", 10, "bold")).pack(side="bottom", pady=16)

        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

    def show(self, name):
        self.pages[name].tkraise()

