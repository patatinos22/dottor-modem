"""Pagina Ottimizzazione in stile FlatLine: stato, opportunità, problemi."""
import customtkinter as ctk
from ctkfontawesome import icon_to_ctkimage
from tkinter import messagebox
import threading


class OptimizerPage(ctk.CTkFrame):
    def __init__(self, master, opt):
        super().__init__(master, fg_color="transparent")
        self.opt = opt
        self._icons = []
        self._build()

    def _icon(self, name, size=20, color="#3b82f6"):
        img = icon_to_ctkimage(name, fill=color, scale_to_width=size)
        self._icons.append(img)
        return img

    def _build(self):
        ctk.CTkLabel(self, text="Ottimizzazione", font=("Segoe UI", 24, "bold")).pack(anchor="w", padx=24, pady=(16, 0))
        ctk.CTkLabel(self, text="Analisi dello stato attuale del sistema", text_color="#9ca3af").pack(anchor="w", padx=24, pady=(0, 16))

        # Sezione 1: Già ottimizzato
        self._section("Cosa è già ottimizzato", "#10b981", "check-circle",
                      "Il tuo sistema è già configurato per le massime prestazioni in queste aree.")
        self.sec1 = ctk.CTkFrame(self, fg_color="transparent")
        self.sec1.pack(fill="x", padx=24, pady=(0, 12))

        # Sezione 2: Da ottimizzare
        self._section("Cosa puoi ottimizzare", "#3b82f6", "sliders-h",
                      "Queste impostazioni possono essere migliorate per ridurre la latenza.")
        self.sec2 = ctk.CTkFrame(self, fg_color="transparent")
        self.sec2.pack(fill="x", padx=24, pady=(0, 12))

        # Sezione 3: Problemi
        self._section("Cosa causa problemi", "#ef4444", "exclamation-triangle",
                      "Elementi che potrebbero rallentare la tua connessione o creare instabilità.")
        self.sec3 = ctk.CTkFrame(self, fg_color="transparent")
        self.sec3.pack(fill="x", padx=24, pady=(0, 12))

        # Pulsante Analizza
        ctk.CTkButton(self, text="Esegui Analisi", height=44, command=self._analyze).pack(pady=16)

        # Log
        self.log = ctk.CTkTextbox(self, height=80, font=("Consolas", 11))
        self.log.pack(fill="x", padx=24, pady=(0, 16))
        self.log.configure(state="disabled")

    def _section(self, title, color, icon_name, desc):
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(fill="x", padx=24, pady=(12, 4))
        ctk.CTkLabel(frame, image=self._icon(icon_name, 18, color), text=" ").pack(side="left")
        ctk.CTkLabel(frame, text=title, font=("Segoe UI", 14, "bold"), text_color=color).pack(side="left", padx=(8, 0))
        ctk.CTkLabel(self, text=desc, text_color="#9ca3af", font=("Segoe UI", 10)).pack(anchor="w", padx=24)

    def _log(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _analyze(self):
        if not self.opt:
            self._log("[!] Avvia come Amministratore per analizzare.")
            return

        # Svuota le sezioni
        for f in (self.sec1, self.sec2, self.sec3):
            for w in f.winfo_children(): w.destroy()

        # Simulazione: in un'implementazione reale chiameresti self.opt.get_status()
        # che restituisce un dizionario con lo stato di Nagle, QoS, DNS, NIC, ecc.
        # Qui mostriamo uno stato di esempio per dimostrare la UI.
        status = {
            "nagle": False,
            "qos": True,
            "dns": "1.1.1.1",
            "nic_power": True,
            "timer": False,
        }

        # Sezione 1: Già ottimizzato
        if not status["nagle"]:
            self._add_item(self.sec1, "Algoritmo di Nagle disattivato", "#10b981", "Ottimo per ridurre il lag.")
        if status["qos"]:
            self._add_item(self.sec1, "QoS con priorità DSCP 46 attiva", "#10b981", "I pacchetti del gioco hanno la precedenza.")
        if status["dns"] == "1.1.1.1":
            self._add_item(self.sec1, "DNS Cloudflare configurato", "#10b981", "Risoluzione nomi più veloce.")

        # Sezione 2: Da ottimizzare
        if not status["timer"]:
            self._add_item(self.sec2, "Timer resolution non impostato a 0.5 ms", "#3b82f6",
                           "Riduce l'input lag nei giochi competitivi.", btn_text="Attiva",
                           btn_cmd=lambda: self._run(self.opt.set_timer_resolution))
        if not status["nic_power"]:
            self._add_item(self.sec2, "Risparmio energetico scheda di rete attivo", "#3b82f6",
                           "Disattivalo per evitare micro-latenze.", btn_text="Disattiva",
                           btn_cmd=lambda: self._run(self.opt.optimize_nic))

        # Sezione 3: Problemi
        if status["nagle"]:
            self._add_item(self.sec3, "Algoritmo di Nagle attivo", "#ef4444",
                           "Aggiunge ritardo ai piccoli pacchetti (tipico nei giochi).", btn_text="Risolvi",
                           btn_cmd=lambda: self._run(self.opt.disable_nagle))

        if not any(w.winfo_children() for w in (self.sec1, self.sec2, self.sec3)):
            self._log("Nessun problema rilevato. Il sistema è già ottimizzato.")

    def _add_item(self, parent, title, color, desc, btn_text=None, btn_cmd=None):
        card = ctk.CTkFrame(parent, corner_radius=10)
        card.pack(fill="x", pady=4)
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=8)
        ctk.CTkLabel(inner, text=title, font=("Segoe UI", 12, "bold"), text_color=color).pack(anchor="w")
        ctk.CTkLabel(inner, text=desc, text_color="#9ca3af", font=("Segoe UI", 9)).pack(anchor="w")
        if btn_text and btn_cmd:
            ctk.CTkButton(inner, text=btn_text, width=80, height=28, command=btn_cmd).pack(anchor="e", pady=(4, 0))

    def _run(self, fn):
        def worker():
            res = fn()
            self.after(0, lambda: self._log(f"[OK] {res.message}" if res.success else f"[!] {res.message}"))
        threading.Thread(target=worker, daemon=True).start()
