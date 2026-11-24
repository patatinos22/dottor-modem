"""UI Ottimizzatore - Dottor Modem v12 - CustomTkinter."""
from __future__ import annotations
import threading
from tkinter import messagebox
import customtkinter as ctk
from core.optimizer import NetworkOptimizer, is_admin


PROFILES = [
    ("\U0001F3AE", "Gaming",    "Gioco fluido",    "Nagle off + QoS 46 + NIC + Timer + DNS", 46,  True,  True,  True,  True),
    ("\u2B07",     "Download",  "Scarica veloce",  "QoS off + DNS veloce",                    0,   False, False, False, True),
    ("\U0001F4FA", "Streaming", "Video stabili",   "QoS 34 + DNS veloce",                     34,  False, False, False, True),
    ("\U0001F4BC", "Quotidiano","Uso bilanciato",  "NIC ottimizzata + DNS veloce",            0,   False, True,  False, True),
]

ADVANCED = [
    ("\u26A1", "Riduci lag gioco",      "disable_nagle"),
    ("\U0001F6A6", "Priorita giochi",    "enable_qos_dscp"),
    ("\U0001F50C", "Ottimizza NIC",      "optimize_nic"),
    ("\u23F1", "Timer 0.5 ms",           "set_timer_resolution"),
    ("\U0001F310", "DNS Cloudflare",     "set_dns_cloudflare"),
    ("\U0001F519", "Ripristina tutto",   "rollback_all"),
]


class OptimizerTab(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self.opt = None
        self._build()

    def _build(self):
        admin = is_admin()
        # Header
        h = ctk.CTkFrame(self, fg_color="#1e3a8a", corner_radius=0, height=80)
        h.pack(fill="x")
        ctk.CTkLabel(h, text="Ottimizzatore Rete", font=("Segoe UI", 22, "bold")).pack(anchor="w", padx=24, pady=(14, 0))
        ctk.CTkLabel(h, text="Scegli un profilo. Nessuna conoscenza tecnica richiesta.",
                     font=("Segoe UI", 11), text_color="#c7d2fe").pack(anchor="w", padx=24, pady=(0, 14))

        if not admin:
            ctk.CTkLabel(self, text="Avvia come Amministratore per usare l'ottimizzatore",
                         text_color="#f59e0b", font=("Segoe UI", 12, "bold")).pack(pady=6)

        # Profili
        pf = ctk.CTkFrame(self, fg_color="transparent")
        pf.pack(fill="x", padx=16, pady=10)
        for i in range(4): pf.grid_columnconfigure(i, weight=1)
        for i, (em, t, sub, desc, dscp, ng, nic, tm, dns) in enumerate(PROFILES):
            c = ctk.CTkFrame(pf, corner_radius=10)
            c.grid(row=0, column=i, padx=6, sticky="nsew")
            ctk.CTkLabel(c, text=em, font=("Segoe UI Emoji", 28)).pack(pady=(10, 2))
            ctk.CTkLabel(c, text=t, font=("Segoe UI", 14, "bold")).pack()
            ctk.CTkLabel(c, text=sub, text_color="#93c5fd", font=("Segoe UI", 10)).pack()
            ctk.CTkLabel(c, text=desc, wraplength=170, text_color="#9ca3af",
                         font=("Segoe UI", 9)).pack(padx=6, pady=6)
            ctk.CTkButton(c, text="Attiva", width=110,
                          command=lambda a=(t, dscp, ng, nic, tm, dns): self._profile(*a),
                          state="normal" if admin else "disabled").pack(pady=(0, 10))

        # Avanzate
        af = ctk.CTkFrame(self)
        af.pack(fill="x", padx=16, pady=8)
        ctk.CTkLabel(af, text="Opzioni avanzate", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=10, pady=6)
        grid = ctk.CTkFrame(af, fg_color="transparent")
        grid.pack(fill="x", padx=6, pady=(0, 8))
        for i in range(3): grid.grid_columnconfigure(i, weight=1)
        for i, (em, label, fn) in enumerate(ADVANCED):
            r, c = divmod(i, 3)
            ctk.CTkButton(grid, text=f"{em}  {label}", height=44, font=("Segoe UI", 11),
                          command=lambda f=fn: self._action(f),
                          state="normal" if admin else "disabled"
                          ).grid(row=r, column=c, padx=4, pady=4, sticky="ew")

        # Speedtest
        sf = ctk.CTkFrame(self)
        sf.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(sf, text="Speedtest", font=("Segoe UI", 12, "bold")).pack(side="left", padx=12)
        self.st = ctk.CTkLabel(sf, text="-- Mbps / -- ms", font=("Consolas", 12))
        self.st.pack(side="left", padx=12)
        ctk.CTkButton(sf, text="Esegui", width=80, command=self._speed).pack(side="right", padx=12, pady=8)

        # Log
        lf = ctk.CTkFrame(self)
        lf.pack(fill="both", expand=True, padx=16, pady=6)
        ctk.CTkLabel(lf, text="Cosa e' successo", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=10, pady=(8, 4))
        self.log = ctk.CTkTextbox(lf, height=120, font=("Consolas", 11))
        self.log.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.log.configure(state="disabled")

    def _ensure(self):
        if self.opt is None:
            try: self.opt = NetworkOptimizer()
            except PermissionError as e:
                messagebox.showerror("Permessi", str(e)); return False
        return True

    def _log(self, icon, txt):
        self.log.configure(state="normal")
        self.log.insert("end", f"{icon} {txt}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _run(self, fn):
        if not self._ensure(): return
        def worker():
            try: res = fn()
            except Exception as e:
                self.after(0, lambda err=e: self._log("[X]", str(err))); return
            items = res if isinstance(res, list) else [res]
            for r in items:
                self.after(0, lambda rr=r: self._log("[OK]" if rr.success else "[!]", rr.message))
        threading.Thread(target=worker, daemon=True).start()

    def _profile(self, title, dscp, nagle, nic, timer, dns):
        if not self._ensure(): return
        self._log(">", f'Profilo "{title}"...')
        def run():
            r = []
            if nagle: r.append(self.opt.disable_nagle())
            if dscp > 0: r.append(self.opt.enable_qos_dscp(dscp))
            if nic: r.append(self.opt.optimize_nic())
            if timer: r.append(self.opt.set_timer_resolution())
            if dns: r.append(self.opt.set_dns_cloudflare())
            return r
        self._run(run)

    def _action(self, fn_name):
        if not self._ensure(): return
        self._log(">", fn_name + "...")
        self._run(lambda: getattr(self.opt, fn_name)())

    def _speed(self):
        if not self._ensure(): return
        self.st.configure(text="Test in corso...")
        def worker():
            r = self.opt.run_speedtest()
            if r.get("ok"):
                self.after(0, lambda: self.st.configure(
                    text=f'{r["download"]} giu / {r["upload"]} su Mbps | {r["ping"]} ms'))
            else:
                self.after(0, lambda: self.st.configure(text="Errore speedtest"))
        threading.Thread(target=worker, daemon=True).start()
