"""
ui/optimizer_tab.py - Dottor Modem v11.1
Tab Ottimizzatore riscritta per utenti non tecnici.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, messagebox

from core.optimizer import NetworkOptimizer, is_admin


# ---------------- Palette ----------------
BG          = "#f4f6fa"
CARD_BG     = "#ffffff"
HEADER_BG   = "#1e3a8a"
HEADER_FG   = "#ffffff"
ACCENT      = "#2563eb"
SUCCESS     = "#16a34a"
WARNING     = "#d97706"
DANGER      = "#dc2626"
TEXT_MAIN   = "#1f2937"
TEXT_MUTED  = "#6b7280"

# ---------------- Traduzioni ----------------
PROFILE_INFO = [
    {
        "key": "gaming",
        "emoji": "🎮",
        "title": "Gaming",
        "subtitle": "Gioco online fluido",
        "desc": "Riduce il ritardo del gioco e dà priorità ai pacchetti dei videogiochi.",
        "detail": "Cosa fa:\n• Riduce il lag del gioco\n• Dà priorità al traffico del gioco\n• Rende la connessione più stabile\n• Usa DNS più veloci\n\nConsigliato se giochi a FPS, MOBA o giochi competitivi.",
        "dscp": 46, "nagle": True, "nic": True, "dns": True,
    },
    {
        "key": "download",
        "emoji": "⬇️",
        "title": "Download",
        "subtitle": "Scaricare più veloce",
        "desc": "Massimizza la velocità quando scarichi file grandi.",
        "detail": "Cosa fa:\n• Rimuove le priorità per non rallentare lo scaricamento\n• Usa DNS più veloci per aprire prima i siti\n\nConsigliato mentre scarichi giochi, film o aggiornamenti.",
        "dscp": 0, "nagle": False, "nic": False, "dns": True,
    },
    {
        "key": "streaming",
        "emoji": "📺",
        "title": "Streaming",
        "subtitle": "Video senza blocchi",
        "desc": "Priorità ai video su Twitch, YouTube, Netflix.",
        "detail": "Cosa fa:\n• Dà priorità al traffico video\n• Riduce i buffering\n• Usa DNS più veloci\n\nConsigliato se guardi o fai streaming.",
        "dscp": 34, "nagle": False, "nic": False, "dns": True,
    },
    {
        "key": "daily",
        "emoji": "💼",
        "title": "Uso quotidiano",
        "subtitle": "Navigazione bilanciata",
        "desc": "Bilanciato per navigare, lavorare e videochiamate.",
        "detail": "Cosa fa:\n• Ottimizza la scheda di rete\n• Usa DNS più veloci\n\nConsigliato per l'uso normale del PC.",
        "dscp": 0, "nagle": False, "nic": True, "dns": True,
    },
]

ADVANCED_ACTIONS = [
    {
        "key": "nagle",
        "emoji": "⚡",
        "title": "Riduci il ritardo del gioco",
        "desc": "Disattiva l'algoritmo di Nagle (tecnico: TcpAckFrequency + TCPNoDelay).",
        "runner": lambda o: o.disable_nagle(),
    },
    {
        "key": "qos_on",
        "emoji": "🚦",
        "title": "Dai priorità ai giochi",
        "desc": "Attiva la priorità ai pacchetti con marcatura DSCP 46.",
        "runner": lambda o: o.enable_qos_dscp(46),
    },
    {
        "key": "nic",
        "emoji": "🔌",
        "title": "Ottimizza la scheda di rete",
        "desc": "Disattiva risparmio energetico e risparmio energetico Ethernet.",
        "runner": lambda o: o.optimize_nic(),
    },
    {
        "key": "dns_cf",
        "emoji": "🌐",
        "title": "Navigazione più veloce (DNS)",
        "desc": "Imposta i DNS Cloudflare (1.1.1.1) sull'adattatore attivo.",
        "runner": lambda o: o.set_dns_cloudflare(),
    },
    {
        "key": "qos_off",
        "emoji": "🛑",
        "title": "Togli priorità pacchetti",
        "desc": "Rimuove la priorità QoS se l'hai attivata in passato.",
        "runner": lambda o: o.disable_qos(),
    },
    {
        "key": "dns_auto",
        "emoji": "🔄",
        "title": "DNS automatico",
        "desc": "Torna al DNS fornito dal tuo operatore.",
        "runner": lambda o: o.set_dns_auto(),
    },
]


# ---------------- Traduzione risultati ----------------
def simplify(result) -> tuple[str, str]:
    """Ritorna (icona, testo_semplice) da mostrare nel log."""
    name = (result.name or "").lower()
    msg = result.message or ""
    if "nagle" in name:
        if result.success:
            return "✅", "Lag di gioco ridotto. Riavvia il PC per applicare."
        return "⚠️", "Non sono riuscito a ridurre il lag. Prova come Amministratore."
    if "qos" in name and "dscp" in name:
        if result.success:
            return "✅", "Priorità ai pacchetti attivata. I giochi hanno la precedenza."
        return "⚠️", "Non sono riuscito ad attivare la priorità. Verifica di essere Amministratore."
    if "rimozione policy qos" in name:
        if result.success:
            return "✅", "Priorità pacchetti rimossa."
        return "⚠️", "Non sono riuscito a rimuovere la priorità."
    if "scheda di rete" in name:
        if result.success:
            return "✅", "Scheda di rete ottimizzata."
        return "⚠️", "Alcune impostazioni della scheda non sono modificabili."
    if "dns" in name and "cloudflare" in name:
        if result.success:
            return "✅", "Navigazione più veloce (DNS Cloudflare attivo)."
        return "⚠️", "Nessuna scheda di rete attiva trovata."
    if "dns" in name and "automatico" in name:
        if result.success:
            return "✅", "DNS tornato automatico."
        return "⚠️", "Non sono riuscito a ripristinare il DNS automatico."
    return ("✅" if result.success else "⚠️"), msg


# ---------------- Tab ----------------
class OptimizerTab(ttk.Frame):
    def __init__(self, master, **kwargs):
        super().__init__(master, style="Main.TFrame", **kwargs)
        self.optimizer = None
        self._build_style()
        self._build_ui()

    # ---------- stile ----------
    def _build_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Main.TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD_BG)
        style.configure("Header.TFrame", background=HEADER_BG)
        style.configure("Header.TLabel", background=HEADER_BG, foreground=HEADER_FG, font=("Segoe UI", 18, "bold"))
        style.configure("HeaderSub.TLabel", background=HEADER_BG, foreground="#c7d2fe", font=("Segoe UI", 10))
        style.configure("Section.TLabel", background=BG, foreground=TEXT_MAIN, font=("Segoe UI", 12, "bold"))
        style.configure("Body.TLabel", background=CARD_BG, foreground=TEXT_MAIN, font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=CARD_BG, foreground=TEXT_MAIN, font=("Segoe UI", 12, "bold"))
        style.configure("Sub.TLabel", background=CARD_BG, foreground=TEXT_MUTED, font=("Segoe UI", 9))
        style.configure("StatusOk.TLabel", background=BG, foreground=SUCCESS, font=("Segoe UI", 10, "bold"))
        style.configure("StatusNo.TLabel", background=BG, foreground=DANGER, font=("Segoe UI", 10, "bold"))
        style.configure("Big.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 10))
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 10),
                        foreground="#ffffff", background=ACCENT)
        style.configure("Restore.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 10),
                        foreground="#ffffff", background=DANGER)

    # ---------- layout ----------
    def _build_ui(self):
        # Header
        header = ttk.Frame(self, style="Header.TFrame", padding=(20, 16))
        header.pack(fill="x")
        ttk.Label(header, text="🚀 Ottimizzatore Rete", style="Header.TLabel").pack(anchor="w")
        ttk.Label(header,
                  text="Scegli un profilo. Nessuna conoscenza tecnica richiesta.",
                  style="HeaderSub.TLabel").pack(anchor="w", pady=(4, 0))

        # Avviso admin
        admin_ok = is_admin()
        if not admin_ok:
            warn = tk.Frame(self, bg="#fef3c7", highlightbackground=WARNING, highlightthickness=1)
            warn.pack(fill="x", padx=16, pady=(12, 0))
            tk.Label(warn, text="⚠️  Avvia Dottor Modem come Amministratore per usare l'ottimizzatore",
                     bg="#fef3c7", fg="#92400e", font=("Segoe UI", 10, "bold"),
                     padx=12, pady=10).pack(anchor="w")

        # Profili
        ttk.Label(self, text="1. Scegli cosa vuoi fare", style="Section.TLabel").pack(anchor="w", padx=20, pady=(16, 8))
        profiles_row = tk.Frame(self, bg=BG)
        profiles_row.pack(fill="x", padx=16)
        for i, info in enumerate(PROFILE_INFO):
            self._make_profile_card(profiles_row, info, admin_ok).grid(row=0, column=i, padx=6, sticky="nsew")
            profiles_row.columnconfigure(i, weight=1)

        # Azioni avanzate (collassabili)
        self.adv_visible = tk.BooleanVar(value=False)
        toggle_frame = tk.Frame(self, bg=BG)
        toggle_frame.pack(fill="x", padx=20, pady=(18, 4))
        tk.Checkbutton(toggle_frame, text="  Mostra opzioni avanzate",
                       variable=self.adv_visible, command=self._toggle_advanced,
                       bg=BG, fg=TEXT_MAIN, font=("Segoe UI", 10, "bold"),
                       activebackground=BG, selectcolor=BG,
                       highlightthickness=0, bd=0).pack(anchor="w")

        self.adv_frame = tk.Frame(self, bg=BG)
        for i, info in enumerate(ADVANCED_ACTIONS):
            r, c = divmod(i, 3)
            card = self._make_action_card(self.adv_frame, info, admin_ok)
            card.grid(row=r, column=c, padx=6, pady=4, sticky="nsew")
            self.adv_frame.columnconfigure(c, weight=1)

        # Ripristina
        restore_frame = tk.Frame(self, bg=BG)
        restore_frame.pack(fill="x", padx=20, pady=(18, 6))
        btn = tk.Button(restore_frame, text="🔙  Ripristina tutte le impostazioni di Windows",
                        bg=DANGER, fg="white", font=("Segoe UI", 10, "bold"),
                        relief="flat", padx=16, pady=10, cursor="hand2",
                        command=self._confirm_rollback,
                        state="normal" if admin_ok else "disabled")
        btn.pack(anchor="w")

        # Log
        ttk.Label(self, text="2. Cosa è successo", style="Section.TLabel").pack(anchor="w", padx=20, pady=(18, 6))
        log_wrap = tk.Frame(self, bg=CARD_BG, highlightbackground="#e5e7eb", highlightthickness=1)
        log_wrap.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        self.log = tk.Text(log_wrap, height=8, state="disabled", wrap="word",
                           font=("Consolas", 10), bg=CARD_BG, fg=TEXT_MAIN,
                           relief="flat", padx=10, pady=8)
        self.log.pack(fill="both", expand=True, side="left")
        sb = ttk.Scrollbar(log_wrap, command=self.log.yview)
        sb.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=sb.set)

        # Tag colori log
        self.log.tag_config("ok", foreground=SUCCESS)
        self.log.tag_config("warn", foreground=WARNING)
        self.log.tag_config("err", foreground=DANGER)
        self.log.tag_config("info", foreground=TEXT_MUTED)

        # Progress
        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.pack(fill="x", padx=16, pady=(0, 12))

    # ---------- card profilo ----------
    def _make_profile_card(self, parent, info, admin_ok) -> tk.Frame:
        card = tk.Frame(parent, bg=CARD_BG, highlightbackground="#e5e7eb", highlightthickness=1)
        inner = tk.Frame(card, bg=CARD_BG)
        inner.pack(fill="both", expand=True, padx=14, pady=14)

        tk.Label(inner, text=info["emoji"], bg=CARD_BG, font=("Segoe UI Emoji", 26)).pack(anchor="w")
        tk.Label(inner, text=info["title"], bg=CARD_BG, fg=TEXT_MAIN,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(6, 0))
        tk.Label(inner, text=info["subtitle"], bg=CARD_BG, fg=ACCENT,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        tk.Label(inner, text=info["desc"], bg=CARD_BG, fg=TEXT_MUTED,
                 font=("Segoe UI", 9), wraplength=200, justify="left").pack(anchor="w", pady=(6, 10))

        btn_row = tk.Frame(inner, bg=CARD_BG)
        btn_row.pack(fill="x", side="bottom")

        apply_btn = tk.Button(btn_row, text="Attiva",
                              bg=ACCENT, fg="white", font=("Segoe UI", 10, "bold"),
                              relief="flat", padx=12, pady=8, cursor="hand2",
                              command=lambda: self._apply_profile(info),
                              state="normal" if admin_ok else "disabled")
        apply_btn.pack(side="left", fill="x", expand=True)

        info_btn = tk.Button(btn_row, text="ℹ️", bg="#e5e7eb", fg=TEXT_MAIN,
                             font=("Segoe UI", 10, "bold"), relief="flat", padx=10, pady=8,
                             cursor="hand2", command=lambda: messagebox.showinfo(info["title"], info["detail"]))
        info_btn.pack(side="left", padx=(6, 0))

        return card

    # ---------- card azione avanzata ----------
    def _make_action_card(self, parent, info, admin_ok) -> tk.Frame:
        card = tk.Frame(parent, bg=CARD_BG, highlightbackground="#e5e7eb", highlightthickness=1)
        inner = tk.Frame(card, bg=CARD_BG)
        inner.pack(fill="both", expand=True, padx=10, pady=10)

        head = tk.Frame(inner, bg=CARD_BG)
        head.pack(fill="x")
        tk.Label(head, text=info["emoji"], bg=CARD_BG, font=("Segoe UI Emoji", 16)).pack(side="left")
        tk.Label(head, text=info["title"], bg=CARD_BG, fg=TEXT_MAIN,
                 font=("Segoe UI", 10, "bold")).pack(side="left", padx=(6, 0))

        tk.Label(inner, text=info["desc"], bg=CARD_BG, fg=TEXT_MUTED,
                 font=("Segoe UI", 8), wraplength=200, justify="left").pack(anchor="w", pady=(4, 8))

        tk.Button(inner, text="Esegui", bg="#e5e7eb", fg=TEXT_MAIN,
                  font=("Segoe UI", 9, "bold"), relief="flat", padx=10, pady=6,
                  cursor="hand2", command=lambda i=info: self._run_action(i),
                  state="normal" if admin_ok else "disabled").pack(anchor="e")
        return card

    def _toggle_advanced(self):
        if self.adv_visible.get():
            self.adv_frame.pack(fill="x", padx=16, pady=(0, 4))
        else:
            self.adv_frame.pack_forget()

    # ---------- logica ----------
    def _log(self, icon: str, text: str, tag: str = "info"):
        self.log.configure(state="normal")
        self.log.insert("end", f"{icon} {text}\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _ensure(self) -> bool:
        if self.optimizer is None:
            try:
                self.optimizer = NetworkOptimizer()
            except PermissionError as e:
                messagebox.showerror("Permessi insufficienti", str(e))
                return False
        return True

    def _run_async(self, fn):
        if not self._ensure():
            return
        self.progress.start(10)

        def worker():
            try:
                result = fn()
            except Exception as e:
                self.after(0, lambda err=e: self._done([], str(err)))
                return
            items = result if isinstance(result, list) else [result]
            self.after(0, lambda res=items: self._done(res, None))

        threading.Thread(target=worker, daemon=True).start()

    def _done(self, items, err):
        self.progress.stop()
        if err:
            self._log("❌", "Errore: " + err, "err")
            return
        for r in items:
            icon, text = simplify(r)
            tag = "ok" if r.success else "warn"
            self._log(icon, text, tag)

    def _apply_profile(self, info):
        if not self._ensure():
            return
        self._log("🚀", f"Applico il profilo \"{info['title']}\"...", "info")

        def run():
            res = []
            if info["nagle"]:
                res.append(self.optimizer.disable_nagle())
            if info["dscp"] > 0:
                res.append(self.optimizer.enable_qos_dscp(info["dscp"]))
            else:
                res.append(self.optimizer.disable_qos())
            if info["nic"]:
                res.append(self.optimizer.optimize_nic())
            if info["dns"]:
                res.append(self.optimizer.set_dns_cloudflare())
            return res

        self._run_async(run)

    def _run_action(self, info):
        if not self._ensure():
            return
        self._log("▶️", f"Eseguo: {info['title']}...", "info")
        self._run_async(lambda: info["runner"](self.optimizer))

    def _confirm_rollback(self):
        if not self._ensure():
            return
        if not messagebox.askyesno(
            "Ripristina tutto",
            "Vuoi davvero riportare Windows alle impostazioni originali?\n\n"
            "Verranno disattivate tutte le ottimizzazioni fatte da Dottor Modem."
        ):
            return
        self._log("🔙", "Ripristino impostazioni originali...", "info")
        self._run_async(self.optimizer.rollback_all)
