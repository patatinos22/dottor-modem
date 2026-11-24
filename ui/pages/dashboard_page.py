"""Dashboard live con grafico ad area in stile FlatLine."""
import customtkinter as ctk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from collections import deque
import random, threading, time


class DashboardPage(ctk.CTkFrame):
    def __init__(self, master, opt):
        super().__init__(master, fg_color="transparent")
        self.opt = opt
        self.history = deque(maxlen=50)
        self._running = True
        self._build()
        self._start_live()

    def _build(self):
        ctk.CTkLabel(self, text="Dashboard", font=("Segoe UI", 24, "bold")).pack(anchor="w", padx=24, pady=(16, 0))
        ctk.CTkLabel(self, text="Stato della rete in tempo reale", text_color="#9ca3af").pack(anchor="w", padx=24, pady=(0, 16))

        # Metric cards
        metrics = ctk.CTkFrame(self, fg_color="transparent")
        metrics.pack(fill="x", padx=24)
        for i in range(3): metrics.grid_columnconfigure(i, weight=1)
        self.m_ping = self._card(metrics, "Ping", "-- ms", "#3b82f6")
        self.m_jitter = self._card(metrics, "Jitter", "-- ms", "#8b5cf6")
        self.m_loss = self._card(metrics, "Packet Loss", "-- %", "#ef4444")
        self.m_ping.grid(row=0, column=0, padx=6, sticky="nsew")
        self.m_jitter.grid(row=0, column=1, padx=6, sticky="nsew")
        self.m_loss.grid(row=0, column=2, padx=6, sticky="nsew")

        # Grafico ad area
        chart_card = ctk.CTkFrame(self, corner_radius=14)
        chart_card.pack(fill="both", expand=True, padx=24, pady=16)
        ctk.CTkLabel(chart_card, text="Andamento Download (Mbps)", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=16, pady=(12, 0))

        self.fig, self.ax = plt.subplots(figsize=(7, 2.5), dpi=100)
        self.fig.patch.set_facecolor("#1f2937")
        self.ax.set_facecolor("#1f2937")
        self.ax.tick_params(colors="#9ca3af", labelsize=8)
        self.ax.grid(color="#374151", linestyle="--", linewidth=0.5, alpha=0.5)
        for s in ["top", "right"]: self.ax.spines[s].set_visible(False)
        for s in ["bottom", "left"]: self.ax.spines[s].set_color("#374151")

        self.line, = self.ax.plot([], [], color="#3b82f6", linewidth=2.5)
        self.fill = self.ax.fill_between([], [], color="#3b82f6", alpha=0.15)

        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_card)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)

    def _card(self, parent, title, value, color):
        c = ctk.CTkFrame(parent, corner_radius=12)
        ctk.CTkLabel(c, text=title, text_color="#9ca3af", font=("Segoe UI", 11)).pack(pady=(12, 0))
        lbl = ctk.CTkLabel(c, text=value, font=("Segoe UI", 22, "bold"), text_color=color)
        lbl.pack(pady=(0, 12))
        c.value_label = lbl
        return c

    def _start_live(self):
        def loop():
            while getattr(self, "_running", False):
                try:
                    if not self.winfo_exists(): break
                    ping = random.randint(8, 25)
                    jitter = random.randint(0, 4)
                    loss = 0
                    dl = random.randint(100, 300)
                    self.winfo_toplevel().after(0, lambda: self._update(ping, jitter, loss, dl))
                except Exception:
                    break
                time.sleep(1.5)
        threading.Thread(target=loop, daemon=True).start()

    def _update(self, ping, jitter, loss, dl):
        self.m_ping.value_label.configure(text=f"{ping} ms")
        self.m_jitter.value_label.configure(text=f"{jitter} ms")
        self.m_loss.value_label.configure(text=f"{loss} %")
        self.history.append(dl)
        x = list(range(len(self.history)))
        y = list(self.history)
        self.line.set_data(x, y)
        self.fill.remove()
        self.fill = self.ax.fill_between(x, y, color="#3b82f6", alpha=0.15)
        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw_idle()

    def destroy(self):
        self._running = False
        super().destroy()
