"""Speedtest con gauge e monitoraggio live tramite psutil."""
import customtkinter as ctk
from tkdial import Meter
import threading, time, psutil


class SpeedtestPage(ctk.CTkFrame):
    def __init__(self, master, opt):
        super().__init__(master, fg_color="transparent")
        self.opt = opt
        self._running = False
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text="Speedtest", font=("Segoe UI", 24, "bold")).pack(anchor="w", padx=24, pady=(16, 0))
        ctk.CTkLabel(self, text="Misura la velocità della connessione", text_color="#9ca3af").pack(anchor="w", padx=24, pady=(0, 16))

        card = ctk.CTkFrame(self, corner_radius=14)
        card.pack(expand=True, padx=24, pady=8)

        self.meter = Meter(master=card, radius=150, start=0, end=1000,
                           fg="#1f2937", needle_color="#3b82f6",
                           text_color="#e5e7eb", border_width=0)
        self.meter.pack(padx=20, pady=20)

        self.live_label = ctk.CTkLabel(card, text="0.0 Mbps", font=("Segoe UI", 18, "bold"), text_color="#3b82f6")
        self.live_label.pack(pady=(0, 4))

        self.result = ctk.CTkLabel(card, text="Premi Esegui per iniziare",
                                   font=("Segoe UI", 12), text_color="#9ca3af")
        self.result.pack(pady=(0, 10))

        self.btn = ctk.CTkButton(card, text="Esegui Speedtest", height=40, command=self._start_test)
        self.btn.pack(pady=(0, 20), padx=20, fill="x")

    def _start_test(self):
        if not self.opt or self._running:
            return
        self._running = True
        self.btn.configure(state="disabled", text="Test in corso...")
        self.result.configure(text="")
        self.meter.set(0)
        self.live_label.configure(text="0.0 Mbps")

        def monitor():
            net = psutil.net_io_counters()
            last_bytes = net.bytes_recv
            last_time = time.time()
            while self._running:
                time.sleep(0.5)
                now = time.time()
                net = psutil.net_io_counters()
                delta_bytes = net.bytes_recv - last_bytes
                delta_time = now - last_time
                if delta_time > 0:
                    mbps = (delta_bytes * 8) / (delta_time * 1_000_000)
                    self.after(0, lambda m=mbps: self._update_live(m))
                last_bytes = net.bytes_recv
                last_time = now

        def run_test():
            # Avvia il monitoraggio in parallelo
            threading.Thread(target=monitor, daemon=True).start()
            # Esegui il test (bloccante)
            res = self.opt.run_speedtest()
            self._running = False
            self.after(0, lambda: self._finish(res))

        threading.Thread(target=run_test, daemon=True).start()

    def _update_live(self, mbps):
        if not self._running: return
        self.live_label.configure(text=f"{mbps:.1f} Mbps")
        self.meter.set(min(mbps, 1000))

    def _finish(self, res):
        self.btn.configure(state="normal", text="Esegui Speedtest")
        if res.get("ok"):
            self.meter.set(res["download"])
            self.result.configure(text=f'{res["download"]} ↓ / {res["upload"]} ↑ Mbps  |  Ping {res["ping"]} ms')
        else:
            self.result.configure(text="Errore: " + res.get("error", "sconosciuto"))
