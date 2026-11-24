from collections import deque
from concurrent.futures import ThreadPoolExecutor
import ctypes
from datetime import datetime
import os
import statistics
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from core.diagnostics import (
    JITTER_WARN_MS,
    LATENCY_WARN_MS,
    LOG_FILE,
    MAX_CONSECUTIVE_FAILS,
    RESET_COOLDOWN_SEC,
    CsvTelemetryLogger,
    build_human_diagnosis,
    compute_line_grade,
)
from core.probes import (
    TARGETS,
    check_is_admin,
    describe_dns_provider,
    flush_dns_cache,
    get_active_interface_name,
    get_current_dns_servers,
    get_default_gateway,
    get_network_processes,
    native_ping,
    probe_dns,
    read_network_counters,
    reset_network_stack,
    run_speedtest_stream,
    run_traceroute,
    set_dns_servers,
)

POLL_INTERVAL_SEC = 1.0
SPEEDTEST_DURATION_SEC = 5.0

# Palette ad alto contrasto
BG_MAIN = "#0b1120"
BG_CARD = "#111827"
BG_ELEV = "#1e293b"
BG_HOVER = "#2c3b52"
BORDER = "#334155"
FG_TEXT = "#f8fafc"
FG_SUB = "#cbd5e1"
FG_MUTED = "#94a3b8"
COL_OK = "#10b981"
COL_WARN = "#f59e0b"
COL_ERR = "#ef4444"
COL_ACCENT = "#38bdf8"
COL_PURPLE = "#a78bfa"


def enable_high_dpi() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


class ToolTip:
    """Mostra un fumetto esplicativo al passaggio del mouse su qualsiasi widget."""

    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.tip_win: tk.Toplevel | None = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _show(self, _event=None) -> None:
        if self.tip_win or not self.text:
            return
        x = self.widget.winfo_rootx() + 14
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip_win = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        frame = tk.Frame(tw, bg="#0f172a", highlightbackground=COL_ACCENT, highlightthickness=1, padx=10, pady=6)
        frame.pack()
        tk.Label(
            frame,
            text=self.text,
            justify="left",
            bg="#0f172a",
            fg=FG_TEXT,
            font=("Segoe UI", 9),
            wraplength=340,
        ).pack()

    def _hide(self, _event=None) -> None:
        if self.tip_win:
            self.tip_win.destroy()
            self.tip_win = None


class DottorModemApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Dottor Modem v7.2 — Diagnostica Rete & Speedtest")
        self.root.geometry("1260x820")
        self.root.minsize(1040, 720)
        self.root.configure(bg=BG_MAIN)

        self.running = True
        self.paused = False
        self.lock = threading.Lock()
        self.last_reset_ts = 0.0
        self.csv_logger = CsvTelemetryLogger(LOG_FILE, flush_interval_sec=15.0)

        # Stato Speedtest 5s
        self.speedtest_running = False
        self.speedtest_live_mbps = 0.0
        self.speedtest_last_mbps: float | None = None
        self.speedtest_banner_until = 0.0
        self.speedtest_banner_data: tuple[str, str, str] | None = None

        self.router_ip = get_default_gateway()
        self.iface_name = get_active_interface_name()
        self.is_admin = check_is_admin()
        self.current_target_label = "Cloudflare (1.1.1.1)"
        self.current_target_ip = TARGETS[self.current_target_label]

        self.dns_servers = get_current_dns_servers(self.iface_name)
        self.dns_label, self.dns_kind = describe_dns_provider(self.dns_servers)

        self.hist_internet: deque[float | None] = deque([None] * 90, maxlen=90)
        self.hist_router: deque[float | None] = deque([None] * 90, maxlen=90)
        self.hist_jitter: deque[float | None] = deque([None] * 90, maxlen=90)
        self.hist_down_mbps: deque[float] = deque([0.0] * 90, maxlen=90)

        self.win_inet: deque[float] = deque(maxlen=15)
        self.win_outcomes: deque[bool] = deque(maxlen=25)
        self.win_jitters: deque[float] = deque(maxlen=30)

        self.all_valid_inet: list[float] = []
        self.total_rx_mb = 0.0
        self.suspects: list[tuple[str, str, int]] = []
        self.pending_logs: deque[tuple[str, str]] = deque(maxlen=120)

        self.latest_snapshot = {
            "level": "AVVIO",
            "diag_sev": "ok",
            "diag_title": "⏳ Avvio controlli diagnostici in corso...",
            "diag_advice": "Attendi 2 secondi per la prima misurazione completa della linea.",
            "inet_ms": None,
            "router_ms": None,
            "jitter_ms": 0.0,
            "loss_pct": 0.0,
            "dns_ms": None,
            "grade": "Analisi...",
            "down_mbs": 0.0,
            "up_mbs": 0.0,
            "hw_errors": 0,
        }

        self._setup_styles()
        self._build_ui()
        self._update_dns_ui_state()

        self.log_message("AVVIO", f"Diagnostica avviata | Scheda: {self.iface_name} | Modem: {self.router_ip} | DNS: {self.dns_label}")

        self.worker = threading.Thread(target=self._monitor_worker, daemon=True)
        self.worker.start()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(250, self._refresh_ui)

    def _setup_styles(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Dark.Treeview",
            background=BG_CARD,
            foreground=FG_TEXT,
            fieldbackground=BG_CARD,
            borderwidth=0,
            rowheight=27,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Dark.Treeview.Heading",
            background=BG_ELEV,
            foreground=COL_ACCENT,
            relief="flat",
            font=("Segoe UI", 9, "bold"),
        )
        style.map("Dark.Treeview", background=[("selected", "#334155")])

        style.configure("Dark.TNotebook", background=BG_CARD, borderwidth=0)
        style.configure(
            "Dark.TNotebook.Tab",
            background=BG_ELEV,
            foreground=FG_MUTED,
            padding=[12, 7],
            font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "Dark.TNotebook.Tab",
            background=[("selected", BG_CARD)],
            foreground=[("selected", COL_ACCENT)],
        )

    def _make_button(
        self,
        parent: tk.Widget,
        text: str,
        command,
        tooltip: str,
        bg: str = BG_ELEV,
        fg: str = FG_TEXT,
        hover_bg: str = BG_HOVER,
    ) -> tk.Button:
        btn = tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=hover_bg,
            activeforeground=fg,
            relief="flat",
            bd=0,
            padx=11,
            pady=6,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )
        btn.bind("<Enter>", lambda _e: btn.configure(bg=hover_bg), add="+")
        btn.bind("<Leave>", lambda _e: self._restore_btn_color(btn, bg), add="+")
        btn._default_bg = bg  # type: ignore[attr-defined]
        ToolTip(btn, tooltip)
        return btn

    def _restore_btn_color(self, btn: tk.Button, fallback_bg: str) -> None:
        btn.configure(bg=getattr(btn, "_default_bg", fallback_bg))

    def _build_ui(self) -> None:
        # --- 1. INTESTAZIONE ---
        header = tk.Frame(self.root, bg=BG_MAIN, padx=18, pady=10)
        header.pack(fill="x")

        left_hdr = tk.Frame(header, bg=BG_MAIN)
        left_hdr.pack(side="left")

        title_row = tk.Frame(left_hdr, bg=BG_MAIN)
        title_row.pack(anchor="w")
        tk.Label(title_row, text="DOTTOR MODEM", bg=BG_MAIN, fg=FG_TEXT, font=("Segoe UI", 16, "bold")).pack(side="left")
        tk.Label(title_row, text="  v7.2", bg=BG_MAIN, fg=COL_ACCENT, font=("Segoe UI", 11, "bold")).pack(side="left", pady=(3, 0))

        self.lbl_subhdr = tk.Label(
            left_hdr,
            text=f"Connessione: {self.iface_name}   •   Modem: {self.router_ip}   •   DNS: {self.dns_label}",
            bg=BG_MAIN,
            fg=FG_MUTED,
            font=("Segoe UI", 9),
        )
        self.lbl_subhdr.pack(anchor="w", pady=(2, 0))

        right_hdr = tk.Frame(header, bg=BG_MAIN)
        right_hdr.pack(side="right")

        if not self.is_admin:
            btn_adm = self._make_button(
                right_hdr,
                "⚡ Sblocca Cambio DNS (Admin)",
                self._action_elevate_admin,
                "Riavvia Dottor Modem con i permessi di Amministratore di Windows per poter cambiare i server DNS con un clic.",
                bg="#78350f",
                fg="#fde68a",
                hover_bg="#92400e",
            )
            btn_adm.pack(side="left", padx=(0, 10))

        self.lbl_badge = tk.Label(
            right_hdr,
            text="  AVVIO  ",
            bg="#1e3a5f",
            fg=COL_ACCENT,
            font=("Segoe UI", 10, "bold"),
            padx=14,
            pady=6,
        )
        self.lbl_badge.pack(side="left")

        # --- 2. BANNER DIAGNOSI IN TEMPO REALE ---
        self.diag_box = tk.Frame(
            self.root,
            bg="#064e3b",
            highlightbackground=COL_OK,
            highlightthickness=1,
            padx=16,
            pady=10,
        )
        self.diag_box.pack(fill="x", padx=18, pady=(0, 10))

        self.lbl_diag_title = tk.Label(
            self.diag_box,
            text="⏳ Avvio controlli diagnostici in corso...",
            bg="#064e3b",
            fg="#ffffff",
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        )
        self.lbl_diag_title.pack(fill="x")

        self.lbl_diag_advice = tk.Label(
            self.diag_box,
            text="Attendi 2 secondi per la prima misurazione completa della linea.",
            bg="#064e3b",
            fg="#d1fae5",
            font=("Segoe UI", 9),
            anchor="w",
        )
        self.lbl_diag_advice.pack(fill="x", pady=(2, 0))

        # --- 3. PANNELLO PULSANTI ---
        actions_wrapper = tk.Frame(self.root, bg=BG_MAIN, padx=18, pady=0)
        actions_wrapper.pack(fill="x", pady=(0, 8))
        actions_wrapper.columnconfigure(0, weight=47)
        actions_wrapper.columnconfigure(1, weight=53)

        dns_card = tk.Frame(actions_wrapper, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1, padx=12, pady=9)
        dns_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        dns_top = tk.Frame(dns_card, bg=BG_CARD)
        dns_top.pack(fill="x", pady=(0, 6))
        tk.Label(dns_top, text="SERVER DNS (VELOCITÀ APERTURA SITI)", bg=BG_CARD, fg=FG_MUTED, font=("Segoe UI", 8, "bold")).pack(side="left")
        self.lbl_dns_pill = tk.Label(dns_top, text=self.dns_label, bg="#0f172a", fg=COL_ACCENT, padx=8, pady=2, font=("Segoe UI", 8, "bold"))
        self.lbl_dns_pill.pack(side="right")

        dns_btns = tk.Frame(dns_card, bg=BG_CARD)
        dns_btns.pack(fill="x")

        self.btn_dns_toggle = self._make_button(
            dns_btns,
            "⇄ Alterna Google / Cloudflare",
            self._action_toggle_google_cloudflare,
            "Cambia immediatamente i DNS tra Google (8.8.8.8) e Cloudflare (1.1.1.1) e svuota la cache DNS.",
            bg="#0284c7",
            fg="#ffffff",
            hover_bg="#0369a1",
        )
        self.btn_dns_toggle.pack(side="left", padx=(0, 6))

        self.btn_dns_cf = self._make_button(
            dns_btns,
            "Cloudflare (1.1.1.1)",
            lambda: self._action_set_dns("cloudflare"),
            "Imposta i DNS Cloudflare (1.1.1.1 e 1.0.0.1): i più rapidi e orientati alla privacy.",
        )
        self.btn_dns_cf.pack(side="left", padx=(0, 6))

        self.btn_dns_gg = self._make_button(
            dns_btns,
            "Google (8.8.8.8)",
            lambda: self._action_set_dns("google"),
            "Imposta i DNS Google (8.8.8.8 e 8.8.4.4): molto stabili e compatibili con tutti i servizi.",
        )
        self.btn_dns_gg.pack(side="left", padx=(0, 6))

        self.btn_dns_dhcp = self._make_button(
            dns_btns,
            "Automatico",
            lambda: self._action_set_dns("dhcp"),
            "Ripristina i DNS automatici forniti dal tuo modem/operatore.",
        )
        self.btn_dns_dhcp.pack(side="left")

        fix_card = tk.Frame(actions_wrapper, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1, padx=12, pady=9)
        fix_card.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        fix_top = tk.Frame(fix_card, bg=BG_CARD)
        fix_top.pack(fill="x", pady=(0, 6))
        tk.Label(fix_top, text="TEST VELOCITÀ E RIPARAZIONE RAPIDA", bg=BG_CARD, fg=FG_MUTED, font=("Segoe UI", 8, "bold")).pack(side="left")

        self.btn_target = self._make_button(
            fix_top,
            "Server Test: 1.1.1.1 ↻",
            self._action_cycle_target,
            "Clicca per cambiare il server esterno usato per misurare il ping (Cloudflare, Google o Quad9).",
            bg="#0f172a",
            fg=FG_SUB,
            hover_bg=BG_ELEV,
        )
        self.btn_target.configure(padx=8, pady=1, font=("Segoe UI", 8, "bold"))
        self.btn_target.pack(side="right")

        fix_btns = tk.Frame(fix_card, bg=BG_CARD)
        fix_btns.pack(fill="x")

        self.btn_speedtest = self._make_button(
            fix_btns,
            "🚀 Misura Velocità Massima",
            self._action_run_speedtest,
            "Scarica un file di prova per 5 secondi per misurare la velocità reale in Mbps della linea e verificare il Bufferbloat sotto carico.",
            bg="#5b21b6",
            fg="#ffffff",
            hover_bg="#6d28d9",
        )
        self.btn_speedtest.pack(side="left", padx=(0, 6))

        self._make_button(
            fix_btns,
            "🧹 Pulisci DNS",
            self._action_flush_dns,
            "Cancella gli indirizzi web memorizzati su Windows (ipconfig /flushdns). Utile se un sito non carica, senza disconnetterti.",
        ).pack(side="left", padx=(0, 6))

        self._make_button(
            fix_btns,
            "🧭 Controlla Nodi",
            self._action_run_tracert,
            "Esegue un tracciamento (tracert) per scoprire se un rallentamento dipende dal tuo modem o dalla centrale dell'operatore.",
        ).pack(side="left", padx=(0, 6))

        self._make_button(
            fix_btns,
            "🔄 Reset IP",
            self._action_full_reset,
            "Rinnova l'indirizzo IP locale e resetta la connessione del PC. Attenzione: interrompe per 5 secondi eventuali download.",
            fg="#fca5a5",
        ).pack(side="left", padx=(0, 6))

        self.btn_pause = self._make_button(
            fix_btns,
            "⏸ Pausa",
            self._action_toggle_pause,
            "Mette in pausa o riprende il monitoraggio ogni secondo.",
        )
        self.btn_pause.pack(side="right")

        # --- 4. 5 SCHEDE KPI ---
        kpi_frame = tk.Frame(self.root, bg=BG_MAIN, padx=18, pady=2)
        kpi_frame.pack(fill="x")
        for i in range(5):
            kpi_frame.columnconfigure(i, weight=1, uniform="kpi")

        self.kpi_inet_val, self.kpi_inet_sub = self._create_kpi_card(
            kpi_frame,
            0,
            "TEMPO RISPOSTA INTERNET",
            "-- ms",
            "Min: -- | Max: --",
            5,
            "Ping verso Internet: sotto i 50 ms è ottimo; sopra i 100 ms indica coda o saturazione della linea.",
        )
        self.kpi_router_val, self.kpi_router_sub = self._create_kpi_card(
            kpi_frame,
            1,
            "RISPOSTA MODEM IN CASA",
            "-- ms",
            f"IP: {self.router_ip}",
            5,
            "Tempo di risposta del tuo modem/router: deve essere 1-5 ms via cavo (o 2-15 ms in Wi-Fi).",
        )
        self.kpi_bw_val, self.kpi_bw_sub = self._create_kpi_card(
            kpi_frame,
            2,
            "VELOCITÀ SCARICAMENTO",
            "0.0 MB/s",
            "Invio: 0.0 MB/s",
            5,
            "Velocità istantanea di scaricamento. Premi 'Misura Velocità Massima' per misurare i Mbps massimi della linea.",
        )
        self.kpi_jitter_val, self.kpi_jitter_sub = self._create_kpi_card(
            kpi_frame,
            3,
            "STABILITÀ (JITTER / LOSS)",
            "-- ms",
            "Dati persi: 0%",
            5,
            "Il Jitter misura quanto oscilla il ping: più è vicino a 0 ms, più la linea è stabile.",
        )
        self.kpi_grade_val, self.kpi_grade_sub = self._create_kpi_card(
            kpi_frame,
            4,
            "VOTO QUALITÀ LINEA",
            "Analisi...",
            "Risposta DNS: -- ms",
            5,
            "Valutazione complessiva da A+ (perfetta) a F (critica) basata su ping, stabilità e perdita pacchetti.",
        )

        # --- 5. CORPO CENTRALE ---
        mid_frame = tk.Frame(self.root, bg=BG_MAIN, padx=18, pady=8)
        mid_frame.pack(fill="both", expand=True)
        mid_frame.columnconfigure(0, weight=64)
        mid_frame.columnconfigure(1, weight=36)
        mid_frame.rowconfigure(0, weight=1)

        chart_card = tk.Frame(mid_frame, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1, padx=12, pady=10)
        chart_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        chart_hdr = tk.Frame(chart_card, bg=BG_CARD)
        chart_hdr.pack(fill="x", pady=(0, 6))
        tk.Label(
            chart_hdr,
            text="ANDAMENTO IN TEMPO REALE (ULTIMI 90 SECONDI)",
            bg=BG_CARD,
            fg=FG_MUTED,
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left")

        legend = tk.Frame(chart_hdr, bg=BG_CARD)
        legend.pack(side="right")
        for color, label in (
            (COL_ACCENT, "Ping Internet"),
            (COL_WARN, "Oscillazione (Jitter)"),
            (COL_OK, "Modem"),
            (COL_PURPLE, "Download MB/s"),
        ):
            tk.Label(legend, text=f"● {label}  ", bg=BG_CARD, fg=color, font=("Segoe UI", 8, "bold")).pack(side="left")

        self.canvas = tk.Canvas(chart_card, bg="#070d19", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._draw_chart())

        right_card = tk.Frame(mid_frame, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1, padx=8, pady=8)
        right_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        self.notebook = ttk.Notebook(right_card, style="Dark.TNotebook")
        self.notebook.pack(fill="both", expand=True)

        tab_check = tk.Frame(self.notebook, bg=BG_CARD, padx=10, pady=10)
        self.notebook.add(tab_check, text="🩺 Check-up Rete")

        self.chk_nic = self._create_check_row(tab_check, "1. Scheda di Rete PC", f"Interfaccia: {self.iface_name}")
        self.chk_modem = self._create_check_row(tab_check, "2. Collegamento al Modem", f"Indirizzo: {self.router_ip}")
        self.chk_wan = self._create_check_row(tab_check, "3. Linea Internet Esterna", "Verifica verso server esterni")
        self.chk_dns = self._create_check_row(tab_check, "4. Traduzione Nomi (DNS)", f"Attivo: {self.dns_label}")

        tab_procs = tk.Frame(self.notebook, bg=BG_CARD)
        self.notebook.add(tab_procs, text="📊 Programmi Attivi")

        self.tree_procs = ttk.Treeview(
            tab_procs,
            columns=("proc", "kind", "tot"),
            show="headings",
            style="Dark.Treeview",
        )
        self.tree_procs.heading("proc", text="Programma")
        self.tree_procs.heading("kind", text="Tipo Attività")
        self.tree_procs.heading("tot", text="Conn.")
        self.tree_procs.column("proc", anchor="w", width=155)
        self.tree_procs.column("kind", anchor="w", width=135)
        self.tree_procs.column("tot", anchor="center", width=50)
        self.tree_procs.pack(fill="both", expand=True, pady=(6, 0))

        tab_trace = tk.Frame(self.notebook, bg=BG_CARD)
        self.notebook.add(tab_trace, text="🧭 Percorso Nodi")

        self.tree_trace = ttk.Treeview(
            tab_trace,
            columns=("hop", "zone", "ms", "ip"),
            show="headings",
            style="Dark.Treeview",
        )
        self.tree_trace.heading("hop", text="#")
        self.tree_trace.heading("zone", text="Tratta")
        self.tree_trace.heading("ms", text="Ritardo")
        self.tree_trace.heading("ip", text="IP Nodo")
        self.tree_trace.column("hop", anchor="center", width=30)
        self.tree_trace.column("zone", anchor="w", width=140)
        self.tree_trace.column("ms", anchor="center", width=65)
        self.tree_trace.column("ip", anchor="w", width=105)
        self.tree_trace.pack(fill="both", expand=True, pady=(6, 0))
        self.tree_trace.insert("", "end", values=("-", "Premi 'Controlla Nodi'", "-", "-"))

        # --- 6. REGISTRO EVENTI ---
        log_card = tk.Frame(self.root, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1, padx=12, pady=8)
        log_card.pack(fill="x", padx=18, pady=(0, 14))

        log_hdr = tk.Frame(log_card, bg=BG_CARD)
        log_hdr.pack(fill="x", pady=(0, 4))
        tk.Label(
            log_hdr,
            text="CRONOLOGIA EVENTI E ANOMALIE (SALVATA IN DOTTOR_MODEM_LOG.CSV)",
            bg=BG_CARD,
            fg=FG_MUTED,
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left")

        btn_csv = self._make_button(
            log_hdr,
            "📂 Apri Storico Excel (CSV)",
            self._action_open_csv,
            "Salva e apre il file CSV con tutte le misurazioni registrate.",
            bg=BG_ELEV,
            fg=FG_SUB,
        )
        btn_csv.configure(padx=8, pady=1, font=("Segoe UI", 8, "bold"))
        btn_csv.pack(side="right")

        self.txt_log = tk.Text(
            log_card,
            height=4,
            bg="#070d19",
            fg=FG_TEXT,
            font=("Consolas", 9),
            relief="flat",
            state="disabled",
            wrap="none",
        )
        self.txt_log.pack(fill="x")
        self.txt_log.tag_configure("ERR", foreground=COL_ERR)
        self.txt_log.tag_configure("WARN", foreground=COL_WARN)
        self.txt_log.tag_configure("OK", foreground=COL_OK)
        self.txt_log.tag_configure("INFO", foreground=COL_ACCENT)

    def _create_kpi_card(
        self, parent: tk.Frame, col: int, title: str, val: str, sub: str, total_cols: int, tooltip: str
    ) -> tuple[tk.Label, tk.Label]:
        pad_l = 0 if col == 0 else 5
        pad_r = 0 if col == total_cols - 1 else 5
        card = tk.Frame(parent, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1, padx=12, pady=8)
        card.grid(row=0, column=col, sticky="nsew", padx=(pad_l, pad_r))

        lbl_t = tk.Label(card, text=title, bg=BG_CARD, fg=FG_MUTED, font=("Segoe UI", 8, "bold"))
        lbl_t.pack(anchor="w")
        lbl_val = tk.Label(card, text=val, bg=BG_CARD, fg=FG_TEXT, font=("Segoe UI", 16, "bold"))
        lbl_val.pack(anchor="w", pady=(2, 1))
        lbl_sub = tk.Label(card, text=sub, bg=BG_CARD, fg=FG_MUTED, font=("Segoe UI", 8))
        lbl_sub.pack(anchor="w")

        for w in (card, lbl_t, lbl_val, lbl_sub):
            ToolTip(w, tooltip)
        return lbl_val, lbl_sub

    def _create_check_row(self, parent: tk.Frame, title: str, subtitle: str) -> tuple[tk.Label, tk.Label]:
        row = tk.Frame(parent, bg=BG_ELEV, padx=10, pady=8)
        row.pack(fill="x", pady=(0, 7))

        left = tk.Frame(row, bg=BG_ELEV)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text=title, bg=BG_ELEV, fg=FG_TEXT, font=("Segoe UI", 9, "bold")).pack(anchor="w")
        lbl_sub = tk.Label(left, text=subtitle, bg=BG_ELEV, fg=FG_MUTED, font=("Segoe UI", 8))
        lbl_sub.pack(anchor="w")

        lbl_state = tk.Label(row, text="⏳ Verifica", bg=BG_ELEV, fg=COL_ACCENT, font=("Segoe UI", 9, "bold"))
        lbl_state.pack(side="right")
        return lbl_state, lbl_sub

    def _update_dns_ui_state(self) -> None:
        self.lbl_dns_pill.configure(text=self.dns_label)
        self.lbl_subhdr.configure(
            text=f"Connessione: {self.iface_name}   •   Modem: {self.router_ip}   •   DNS: {self.dns_label}"
        )
        self.chk_dns[1].configure(text=f"Attivo: {self.dns_label}")

        for btn in (self.btn_dns_cf, self.btn_dns_gg, self.btn_dns_dhcp):
            btn._default_bg = BG_ELEV  # type: ignore[attr-defined]
            btn.configure(bg=BG_ELEV, fg=FG_TEXT)

        if self.dns_kind == "google":
            self.btn_dns_toggle.configure(text="⇄ Passa a Cloudflare (1.1.1.1)")
            self.btn_dns_gg._default_bg = "#065f46"  # type: ignore[attr-defined]
            self.btn_dns_gg.configure(bg="#065f46", fg="#6ee7b7")
        elif self.dns_kind == "cloudflare":
            self.btn_dns_toggle.configure(text="⇄ Passa a Google (8.8.8.8)")
            self.btn_dns_cf._default_bg = "#065f46"  # type: ignore[attr-defined]
            self.btn_dns_cf.configure(bg="#065f46", fg="#6ee7b7")
        else:
            self.btn_dns_toggle.configure(text="⇄ Alterna Google / Cloudflare")
            self.btn_dns_dhcp._default_bg = "#1e3a5f"  # type: ignore[attr-defined]
            self.btn_dns_dhcp.configure(bg="#1e3a5f", fg=COL_ACCENT)

    def log_message(self, level: str, message: str) -> None:
        now_short = datetime.now().strftime("%H:%M:%S")
        line = f"[{now_short}] [{level:<17}] {message}"
        with self.lock:
            self.pending_logs.append((level, line))

    # --- SPEEDTEST 5 SECONDI ---
    def _action_run_speedtest(self) -> None:
        if self.speedtest_running:
            return
        self.speedtest_running = True
        self.speedtest_live_mbps = 0.0
        self.btn_speedtest.configure(state="disabled", text="⏳ Test 5.0s...")
        threading.Thread(target=self._run_speedtest_worker, daemon=True).start()

    def _run_speedtest_worker(self) -> None:
        with self.lock:
            idle_ping = self.latest_snapshot["inet_ms"]

        self.log_message("SPEEDTEST", "Avvio test di velocità massima (scaricamento per 5 secondi)...")

        def on_progress(rem: float, mbps_now: float) -> None:
            with self.lock:
                self.speedtest_live_mbps = mbps_now
                self.speedtest_banner_until = time.time() + 2.0
                self.speedtest_banner_data = (
                    "warn",
                    f"🚀 Test velocità in corso ({rem:.1f}s rimanenti) — Velocità rilevata: {mbps_now:.1f} Mbps",
                    "Sto saturando la linea per misurare la banda reale e la tenuta del router sotto sforzo...",
                )
            self.root.after(0, lambda r=rem: self.btn_speedtest.configure(text=f"⏳ Test ({r:.1f}s)..."))

        def get_cur_ping() -> float | None:
            with self.lock:
                return self.latest_snapshot["inet_ms"]

        success, total_bytes, elapsed, loaded_pings = run_speedtest_stream(
            SPEEDTEST_DURATION_SEC, on_progress, get_cur_ping, lambda: self.running
        )

        if success and total_bytes > 0:
            final_mbps = (total_bytes * 8.0) / (elapsed * 1_000_000.0)
            final_mbs = total_bytes / (elapsed * 1_048_576.0)
            downloaded_mb = total_bytes / 1_048_576.0

            bloat_txt = ""
            sev = "ok"
            if idle_ping is not None and loaded_pings:
                avg_loaded = sum(loaded_pings) / len(loaded_pings)
                delta = avg_loaded - idle_ping
                if delta > 80.0:
                    sev = "warn"
                    bloat_txt = f" | Ping: {idle_ping:.0f} ms → {avg_loaded:.0f} ms (+{delta:.0f} ms Bufferbloat alto)"
                elif delta > 30.0:
                    bloat_txt = f" | Ping: {idle_ping:.0f} ms → {avg_loaded:.0f} ms (+{delta:.0f} ms Bufferbloat lieve)"
                else:
                    bloat_txt = f" | Ping stabile: {idle_ping:.0f} ms → {avg_loaded:.0f} ms"

            title = f"🏁 Velocità Massima Misurata: {final_mbps:.1f} Mbps ({final_mbs:.1f} MB/s){bloat_txt}"
            advice = (
                f"Scaricati {downloaded_mb:.1f} MB in {elapsed:.1f}s. "
                + (
                    "Sotto sforzo massimo il ping sale molto: limita i download all'85% se giochi online."
                    if sev == "warn"
                    else "Ottima tenuta della linea anche alla massima velocità."
                )
            )
            with self.lock:
                self.speedtest_last_mbps = final_mbps
                self.speedtest_banner_data = (sev, title, advice)
                self.speedtest_banner_until = time.time() + 14.0

            self.log_message("SPEEDTEST", f"Risultato: {final_mbps:.1f} Mbps ({final_mbs:.1f} MB/s){bloat_txt}")
        else:
            with self.lock:
                self.speedtest_banner_data = (
                    "err",
                    "❌ Impossibile completare il test di velocità",
                    "Verifica che la connessione Internet sia attiva e riprova.",
                )
                self.speedtest_banner_until = time.time() + 8.0
            self.log_message("ERRORE", "Test di velocità fallito: server di prova non raggiungibile.")

        self.speedtest_running = False
        self.root.after(0, lambda: self.btn_speedtest.configure(state="normal", text="🚀 Misura Velocità Massima"))

    # --- ALTRE AZIONI UTENTE ---
    def _action_elevate_admin(self) -> None:
        entry_script = os.path.abspath(sys.argv[0])
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, f'"{entry_script}"', os.path.dirname(entry_script), 1
        )
        if ret > 32:
            self._on_close()

    def _action_toggle_google_cloudflare(self) -> None:
        target_mode = "cloudflare" if self.dns_kind == "google" else "google"
        self._action_set_dns(target_mode)

    def _action_set_dns(self, mode: str) -> None:
        if not self.is_admin:
            if messagebox.askyesno(
                "Permessi Amministratore Richiesti",
                "Per cambiare i server DNS di Windows servono i permessi di Amministratore.\n\nVuoi riavviare subito Dottor Modem come Amministratore?",
            ):
                self._action_elevate_admin()
            return
        threading.Thread(target=self._run_set_dns, args=(mode,), daemon=True).start()

    def _run_set_dns(self, mode: str) -> None:
        ok, msg = set_dns_servers(self.iface_name, mode)
        if ok:
            self.dns_servers = get_current_dns_servers(self.iface_name)
            self.dns_label, self.dns_kind = describe_dns_provider(self.dns_servers)
            self.log_message("FIX DNS", f"{msg} + Cache DNS pulita.")
            self.root.after(0, self._update_dns_ui_state)
        else:
            self.log_message("ERRORE", f"Impossibile modificare i DNS su '{self.iface_name}'.")

    def _action_flush_dns(self) -> None:
        threading.Thread(target=self._run_flush_dns, daemon=True).start()

    def _run_flush_dns(self) -> None:
        flush_dns_cache()
        self.log_message("FIX DNS", "Memoria DNS pulita con successo.")

    def _action_full_reset(self) -> None:
        if not messagebox.askyesno(
            "Conferma Riavvio Scheda di Rete",
            "Questa operazione disconnetterà il PC per circa 5 secondi per rinnovare l'indirizzo IP e pulire la rete.\n\nVuoi procedere?",
        ):
            return
        threading.Thread(target=self._run_full_reset, daemon=True).start()

    def _run_full_reset(self) -> None:
        self.last_reset_ts = time.time()
        self.log_message("FIX RETE", "Riavvio scheda di rete (rinnovo IP e DNS)...")
        reset_network_stack()
        with self.lock:
            self.win_outcomes.clear()
        self.log_message("OK", "Scheda di rete ripristinata.")

    def _action_cycle_target(self) -> None:
        keys = list(TARGETS.keys())
        idx = (keys.index(self.current_target_label) + 1) % len(keys)
        self.current_target_label = keys[idx]
        self.current_target_ip = TARGETS[self.current_target_label]
        self.btn_target.configure(text=f"Server Test: {self.current_target_ip} ↻")
        self.log_message("INFO", f"Server di test cambiato in {self.current_target_label}")

    def _action_run_tracert(self) -> None:
        self.notebook.select(2)
        for item in self.tree_trace.get_children():
            self.tree_trace.delete(item)
        self.tree_trace.insert("", "end", values=("...", "Analisi nodi in corso...", "", ""))
        threading.Thread(target=self._run_tracert_worker, daemon=True).start()

    def _run_tracert_worker(self) -> None:
        target = self.current_target_ip
        self.log_message("INFO", f"Controllo percorso nodi verso {target}...")
        rows = run_traceroute(target, max_hops=8)

        def update_tree() -> None:
            for item in self.tree_trace.get_children():
                self.tree_trace.delete(item)
            if not rows:
                self.tree_trace.insert("", "end", values=("-", "Nessun dato rilevato", "-", "-"))
            else:
                for r in rows:
                    self.tree_trace.insert("", "end", values=r)

        self.root.after(0, update_tree)
        self.log_message("OK", f"Analisi percorso completata ({len(rows)} nodi controllati).")

    def _action_toggle_pause(self) -> None:
        with self.lock:
            self.paused = not self.paused
            paused = self.paused
        self.btn_pause.configure(text="▶ Riprendi" if paused else "⏸ Pausa")
        self.log_message("INFO", "Monitoraggio in pausa." if paused else "Monitoraggio ripreso.")

    def _action_open_csv(self) -> None:
        self.csv_logger.flush()
        path = os.path.abspath(LOG_FILE)
        if os.path.exists(path):
            os.startfile(path)
        else:
            messagebox.showinfo("Storico CSV", "Nessun dato registrato ancora.")

    # --- WORKER 1HZ ---
    def _monitor_worker(self) -> None:
        tick = 0
        fail_streak = 0
        prev_rx, prev_tx, _ = read_network_counters()
        prev_time = time.perf_counter()

        with ThreadPoolExecutor(max_workers=2) as pool:
            while self.running:
                t_start = time.perf_counter()

                with self.lock:
                    is_paused = self.paused

                if is_paused:
                    time.sleep(0.25)
                    prev_rx, prev_tx, _ = read_network_counters()
                    prev_time = time.perf_counter()
                    continue

                target_ip = self.current_target_ip
                f_router = pool.submit(native_ping, self.router_ip, 700)
                f_inet = pool.submit(native_ping, target_ip, 950)
                r_ms = f_router.result()
                i_ms = f_inet.result()

                now_perf = time.perf_counter()
                curr_rx, curr_tx, hw_errs = read_network_counters()
                dt = max(0.1, now_perf - prev_time)
                d_rx = (curr_rx - prev_rx) & 0xFFFFFFFF
                d_tx = (curr_tx - prev_tx) & 0xFFFFFFFF
                down_mbs = (d_rx / (1024 * 1024)) / dt if d_rx < 500_000_000 else 0.0
                up_mbs = (d_tx / (1024 * 1024)) / dt if d_tx < 500_000_000 else 0.0
                self.total_rx_mb += down_mbs * dt
                prev_rx, prev_tx, prev_time = curr_rx, curr_tx, now_perf

                if tick % 3 == 0 and i_ms is not None:
                    dns_ms = probe_dns()
                else:
                    with self.lock:
                        dns_ms = self.latest_snapshot["dns_ms"]

                if tick % 3 == 0:
                    procs = get_network_processes(limit=12)
                    with self.lock:
                        self.suspects = procs
                else:
                    with self.lock:
                        procs = list(self.suspects)

                active_apps = [n for n, _k, _tot in procs if "(" not in n]
                top_app = active_apps[0] if active_apps else ""
                procs_str = ", ".join(active_apps[:3])

                with self.lock:
                    self.hist_router.append(r_ms)
                    self.hist_internet.append(i_ms)
                    self.hist_down_mbps.append(round(down_mbs, 2))
                    self.win_outcomes.append(i_ms is not None)

                    if i_ms is not None:
                        self.win_inet.append(i_ms)
                        self.all_valid_inet.append(i_ms)
                        jitter = statistics.stdev(self.win_inet) if len(self.win_inet) >= 2 else 0.0
                        self.win_jitters.append(jitter)
                    else:
                        jitter = self.win_jitters[-1] if self.win_jitters else 0.0

                    self.hist_jitter.append(round(jitter, 1) if i_ms is not None else None)
                    loss_pct = (self.win_outcomes.count(False) / len(self.win_outcomes)) * 100.0
                    grade = compute_line_grade(self.win_inet, self.win_jitters, self.win_outcomes)

                diag_sev, diag_title, diag_advice = build_human_diagnosis(
                    r_ms, i_ms, jitter, loss_pct, dns_ms, down_mbs, top_app
                )

                if r_ms is None:
                    fail_streak += 1
                    level = "ERRORE MODEM"
                    self.log_message(level, f"Modem {self.router_ip} non raggiungibile ({fail_streak}/{MAX_CONSECUTIVE_FAILS})")
                elif i_ms is None:
                    fail_streak += 1
                    level = "INTERNET ASSENTE"
                    self.log_message(level, f"Modem OK ({r_ms:.0f} ms), linea esterna assente ({fail_streak}/{MAX_CONSECUTIVE_FAILS})")
                elif dns_ms is None:
                    level = "ERRORE DNS"
                    self.log_message(level, "Server DNS non rispondono: pulizia cache in corso...")
                    self._run_flush_dns()
                else:
                    fail_streak = 0
                    if loss_pct > 0:
                        level = "PERDITA DATI"
                        if tick % 3 == 0:
                            self.log_message(level, f"Loss {loss_pct:.0f}% — Ping: {i_ms:.0f} ms | Download: {down_mbs:.1f} MB/s")
                    elif r_ms > LATENCY_WARN_MS or i_ms > LATENCY_WARN_MS or jitter > JITTER_WARN_MS:
                        level = "RALLENTAMENTO"
                        if tick % 4 == 0 and not self.speedtest_running:
                            self.log_message(
                                level,
                                f"Ping: {i_ms:.0f} ms | Jitter: {jitter:.1f} ms | Download: {down_mbs:.1f} MB/s",
                            )
                    else:
                        level = "OTTIMO"

                if fail_streak >= MAX_CONSECUTIVE_FAILS and (time.time() - self.last_reset_ts > RESET_COOLDOWN_SEC):
                    self._run_full_reset()
                    fail_streak = 0

                self.csv_logger.append([
                    level,
                    f"{r_ms:.1f}" if r_ms is not None else "TIMEOUT",
                    f"{i_ms:.1f}" if i_ms is not None else "TIMEOUT",
                    f"{jitter:.1f}",
                    f"{loss_pct:.0f}",
                    f"{down_mbs:.2f}",
                    f"{up_mbs:.2f}",
                    f"{dns_ms:.1f}" if dns_ms is not None else "ERRORE",
                    procs_str,
                ])

                with self.lock:
                    self.latest_snapshot = {
                        "level": level,
                        "diag_sev": diag_sev,
                        "diag_title": diag_title,
                        "diag_advice": diag_advice,
                        "inet_ms": i_ms,
                        "router_ms": r_ms,
                        "jitter_ms": jitter,
                        "loss_pct": loss_pct,
                        "dns_ms": dns_ms,
                        "grade": grade,
                        "down_mbs": down_mbs,
                        "up_mbs": up_mbs,
                        "hw_errors": hw_errs,
                    }

                tick += 1
                elapsed = time.perf_counter() - t_start
                time.sleep(max(0.05, POLL_INTERVAL_SEC - elapsed))

    # --- AGGIORNAMENTO UI ---
    def _refresh_ui(self) -> None:
        if not self.running:
            return

        with self.lock:
            snap = dict(self.latest_snapshot)
            procs = list(self.suspects)
            logs_to_flush = list(self.pending_logs)
            self.pending_logs.clear()
            min_lat = min(self.all_valid_inet) if self.all_valid_inet else None
            max_lat = max(self.all_valid_inet) if self.all_valid_inet else None
            paused = self.paused
            st_running = self.speedtest_running
            st_live = self.speedtest_live_mbps
            st_last = self.speedtest_last_mbps
            st_until = self.speedtest_banner_until
            st_banner = self.speedtest_banner_data

        level = "SPEEDTEST" if st_running else ("IN PAUSA" if paused else snap["level"])
        if level == "OTTIMO":
            b_bg, b_fg = "#064e3b", COL_OK
        elif level == "SPEEDTEST":
            b_bg, b_fg = "#4c1d95", "#ddd6fe"
        elif "ERRORE" in level or "ASSENTE" in level or "PERDITA" in level:
            b_bg, b_fg = "#7f1d1d", COL_ERR
        elif level == "IN PAUSA":
            b_bg, b_fg = "#1e3a5f", COL_ACCENT
        else:
            b_bg, b_fg = "#78350f", COL_WARN
        self.lbl_badge.configure(text=f"  {level}  ", bg=b_bg, fg=b_fg)

        if st_banner and time.time() < st_until:
            sev, d_title, d_advice = st_banner
        else:
            sev, d_title, d_advice = snap["diag_sev"], snap["diag_title"], snap["diag_advice"]

        if sev == "ok":
            d_bg, d_border, d_sub = "#052e26", COL_OK, "#a7f3d0"
        elif sev == "warn":
            d_bg, d_border, d_sub = "#451a03", COL_WARN, "#fde68a"
        else:
            d_bg, d_border, d_sub = "#450a0a", COL_ERR, "#fecaca"

        self.diag_box.configure(bg=d_bg, highlightbackground=d_border)
        self.lbl_diag_title.configure(text=d_title, bg=d_bg)
        self.lbl_diag_advice.configure(text=d_advice, bg=d_bg, fg=d_sub)

        i_ms = snap["inet_ms"]
        if i_ms is not None:
            i_col = COL_ERR if i_ms > 150 else (COL_WARN if i_ms > LATENCY_WARN_MS else COL_ACCENT)
            self.kpi_inet_val.configure(text=f"{i_ms:.0f} ms", fg=i_col)
        else:
            self.kpi_inet_val.configure(text="ASSENTE", fg=COL_ERR)
        if min_lat is not None and max_lat is not None:
            self.kpi_inet_sub.configure(text=f"Min: {min_lat:.0f} ms • Max: {max_lat:.0f} ms")

        r_ms = snap["router_ms"]
        if r_ms is not None:
            self.kpi_router_val.configure(text=f"{r_ms:.0f} ms", fg=COL_WARN if r_ms > 20 else COL_OK)
        else:
            self.kpi_router_val.configure(text="ASSENTE", fg=COL_ERR)
        self.kpi_router_sub.configure(text=f"Errori cavo/scheda: {snap['hw_errors']}")

        down_mbs = snap["down_mbs"]
        up_mbs = snap["up_mbs"]
        if st_running:
            self.kpi_bw_val.configure(text=f"{st_live:.1f} Mbps", fg=COL_PURPLE)
            self.kpi_bw_sub.configure(text=f"Test in corso ({down_mbs:.1f} MB/s)")
        else:
            self.kpi_bw_val.configure(text=f"↓ {down_mbs:.1f} MB/s", fg=COL_PURPLE if down_mbs > 0.5 else FG_TEXT)
            if st_last is not None:
                self.kpi_bw_sub.configure(text=f"Max test: {st_last:.1f} Mbps • ↑ {up_mbs:.1f} MB/s")
            else:
                self.kpi_bw_sub.configure(text=f"↑ {up_mbs:.1f} MB/s • Tot: {self.total_rx_mb:.0f} MB")

        jit = snap["jitter_ms"]
        loss = snap["loss_pct"]
        self.kpi_jitter_val.configure(
            text=f"{jit:.1f} ms",
            fg=COL_ERR if loss > 0 else (COL_WARN if jit > JITTER_WARN_MS else FG_TEXT),
        )
        self.kpi_jitter_sub.configure(text=f"Dati persi (25s): {loss:.0f}%")

        grade = snap["grade"]
        g_col = COL_OK if grade.startswith(("A", "B")) else (COL_WARN if grade.startswith("C") else COL_ERR)
        self.kpi_grade_val.configure(text=grade, fg=g_col)
        dns_ms = snap["dns_ms"]
        self.kpi_grade_sub.configure(text=f"Risposta DNS: {dns_ms:.0f} ms" if dns_ms is not None else "DNS: Non risponde")

        self.chk_nic[0].configure(
            text="🟢 Attiva" if snap["hw_errors"] == 0 else f"🟡 {snap['hw_errors']} errori",
            fg=COL_OK if snap["hw_errors"] == 0 else COL_WARN,
        )
        self.chk_modem[0].configure(
            text=f"🟢 OK ({r_ms:.0f} ms)" if r_ms is not None else "🔴 Irraggiungibile",
            fg=COL_OK if r_ms is not None else COL_ERR,
        )
        if i_ms is None or loss > 0:
            self.chk_wan[0].configure(text="🔴 Instabile / Assente", fg=COL_ERR)
        elif i_ms > LATENCY_WARN_MS:
            self.chk_wan[0].configure(text=f"🟡 Rallentata ({i_ms:.0f} ms)", fg=COL_WARN)
        else:
            self.chk_wan[0].configure(text=f"🟢 Fluida ({i_ms:.0f} ms)", fg=COL_OK)

        self.chk_dns[0].configure(
            text=f"🟢 OK ({dns_ms:.0f} ms)" if dns_ms is not None else "🔴 Errore DNS",
            fg=COL_OK if dns_ms is not None else COL_ERR,
        )

        for item in self.tree_procs.get_children():
            self.tree_procs.delete(item)
        for name, kind, tot_c in procs:
            self.tree_procs.insert("", "end", values=(name, kind, tot_c))

        if logs_to_flush:
            self.txt_log.configure(state="normal")
            for lvl, text in logs_to_flush:
                tag = "ERR" if "ERRORE" in lvl or "ASSENTE" in lvl or "PERDITA" in lvl else (
                    "WARN" if "RALLENTAMENTO" in lvl or "FIX" in lvl else ("OK" if lvl in ("OK", "SPEEDTEST") else "INFO")
                )
                self.txt_log.insert("end", text + "\n", tag)
            self.txt_log.see("end")
            self.txt_log.configure(state="disabled")

        self._draw_chart()
        self.root.after(250, self._refresh_ui)

    def _draw_chart(self) -> None:
        c = self.canvas
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 60 or h < 80:
            return

        c.delete("all")

        with self.lock:
            inet_pts = list(self.hist_internet)
            rout_pts = list(self.hist_router)
            jitt_pts = list(self.hist_jitter)
            down_pts = list(self.hist_down_mbps)

        pad_l, pad_r, pad_t, pad_b = 46, 14, 14, 22
        split_gap = 12
        total_h = h - pad_t - pad_b - split_gap
        ping_h = total_h * 0.72
        bw_h = total_h * 0.28
        bw_top = pad_t + ping_h + split_gap
        plot_w = w - pad_l - pad_r

        valid_vals = [v for v in inet_pts + jitt_pts if v is not None]
        max_y = max(140.0, (max(valid_vals) * 1.15) if valid_vals else 140.0)
        max_y = float(((int(max_y) + 49) // 50) * 50)

        def y_ping(val: float) -> float:
            clamped = max(0.0, min(val, max_y))
            return pad_t + ping_h - (clamped / max_y) * ping_h

        for i in range(4):
            val = (max_y / 3) * i
            y = y_ping(val)
            c.create_line(pad_l, y, w - pad_r, y, fill="#162032", width=1)
            c.create_text(pad_l - 6, y, text=f"{int(val)}ms", fill=FG_MUTED, anchor="e", font=("Consolas", 8))

        if LATENCY_WARN_MS <= max_y:
            y_warn = y_ping(LATENCY_WARN_MS)
            c.create_line(pad_l, y_warn, w - pad_r, y_warn, fill=COL_ERR, dash=(4, 4), width=1)
            c.create_text(w - pad_r - 4, y_warn - 8, text="Limite fluido (100ms)", fill=COL_ERR, anchor="e", font=("Segoe UI", 7, "bold"))

        n = len(inet_pts)
        if n >= 2:
            def plot_line(series: list[float | None], color: str, width: int = 2, mark_timeouts: bool = False) -> None:
                seg: list[float] = []
                for idx, val in enumerate(series):
                    x = pad_l + (idx / (n - 1)) * plot_w
                    if val is None:
                        if len(seg) >= 4:
                            c.create_line(*seg, fill=color, width=width)
                        seg = []
                        if mark_timeouts and idx > 0 and any(v is not None for v in series[:idx]):
                            c.create_oval(x - 3, pad_t + 2, x + 3, pad_t + 8, fill=COL_ERR, outline="")
                    else:
                        seg.extend([x, y_ping(val)])
                if len(seg) >= 4:
                    c.create_line(*seg, fill=color, width=width)

            plot_line(rout_pts, COL_OK, width=2)
            plot_line(jitt_pts, COL_WARN, width=2)
            plot_line(inet_pts, COL_ACCENT, width=2, mark_timeouts=True)

        c.create_line(pad_l, bw_top, w - pad_r, bw_top, fill="#1e293b", width=1)
        max_bw = max(5.0, max(down_pts) * 1.15 if down_pts else 5.0)
        c.create_text(pad_l - 6, bw_top + 6, text=f"{max_bw:.0f}MB", fill=COL_PURPLE, anchor="e", font=("Consolas", 7))
        c.create_text(pad_l - 6, bw_top + bw_h, text="0", fill=FG_MUTED, anchor="e", font=("Consolas", 7))

        if n >= 2:
            bar_w = max(2.0, (plot_w / n) * 0.72)
            for idx, mb in enumerate(down_pts):
                if mb <= 0.02:
                    continue
                x = pad_l + (idx / (n - 1)) * plot_w
                bar_h = min(bw_h, (mb / max_bw) * bw_h)
                c.create_rectangle(
                    x - bar_w / 2,
                    bw_top + bw_h - bar_h,
                    x + bar_w / 2,
                    bw_top + bw_h,
                    fill="#6d28d9",
                    outline="",
                )

        c.create_text(pad_l, h - 8, text="90 sec fa", fill=FG_MUTED, anchor="w", font=("Consolas", 8))
        c.create_text(pad_l + plot_w / 2, h - 8, text="45 sec fa", fill=FG_MUTED, anchor="center", font=("Consolas", 8))
        c.create_text(w - pad_r, h - 8, text="Adesso", fill=FG_MUTED, anchor="e", font=("Consolas", 8))

    def _on_close(self) -> None:
        self.running = False
        self.csv_logger.flush()
        self.root.destroy()
