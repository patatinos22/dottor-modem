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
    DEFAULT_LATENCY_WARN_MS,
    JITTER_WARN_MS,
    LOG_FILE,
    MAX_CONSECUTIVE_FAILS,
    RESET_COOLDOWN_SEC,
    BaselineTracker,
    CsvTelemetryLogger,
    LiveMtrTracker,
    build_friendly_status,
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
    get_wifi_info,
    native_ping,
    probe_dns,
    probe_mtr_hops,
    read_network_counters,
    reset_network_stack,
    run_speedtest_stream,
    set_dns_servers,
)
from ui.tray import WinSystemTray

POLL_INTERVAL_SEC = 1.0
SPEEDTEST_DURATION_SEC = 5.0

BG_APP = "#0f172a"
BG_CARD = "#1e293b"
BG_CARD_ALT = "#263349"
BG_HOVER = "#334155"
BORDER = "#334155"
FG_PRIMARY = "#f8fafc"
FG_SECONDARY = "#cbd5e1"
FG_MUTED = "#94a3b8"

ACCENT_BLUE = "#3b82f6"
ACCENT_BLUE_HOVER = "#2563eb"
ACCENT_CYAN = "#38bdf8"

STATUS_OK = "#10b981"
STATUS_OK_BG = "#064e3b"
STATUS_WARN = "#f59e0b"
STATUS_WARN_BG = "#78350f"
STATUS_ERR = "#ef4444"
STATUS_ERR_BG = "#7f1d1d"


def enable_high_dpi() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


class ToolTip:
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
        x = min(self.widget.winfo_rootx() + 12, self.widget.winfo_screenwidth() - 340)
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip_win = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        frame = tk.Frame(tw, bg="#0b1120", highlightbackground=ACCENT_CYAN, highlightthickness=1, padx=10, pady=6)
        frame.pack()
        tk.Label(frame, text=self.text, justify="left", bg="#0b1120", fg=FG_PRIMARY, font=("Segoe UI", 9), wraplength=310).pack()

    def _hide(self, _event=None) -> None:
        if self.tip_win:
            self.tip_win.destroy()
            self.tip_win = None


class DottorModemApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Dottor Modem v10.0")
        self.root.geometry("1020x680")
        self.root.minsize(900, 620)
        self.root.configure(bg=BG_APP)

        self.running = True
        self.paused = False
        self.compact_mode = False
        self.always_on_top = False
        self.active_page = "home"
        self.lock = threading.Lock()
        self.last_reset_ts = 0.0
        self.tray_hint_shown = False

        self.csv_logger = CsvTelemetryLogger(LOG_FILE, flush_interval_sec=15.0)
        self.baseline = BaselineTracker(maxlen=40)
        self.mtr_tracker = LiveMtrTracker(window=25)
        self.mtr_live_enabled = False
        self.mtr_rows_cached: list[tuple[int, str, str, str, str, str]] = []

        self.speedtest_running = False
        self.speedtest_live_mbps = 0.0
        self.speedtest_last_mbps: float | None = None
        self.speedtest_banner_until = 0.0
        self.speedtest_banner_data: tuple[str, str, str, str] | None = None

        self.router_ip = get_default_gateway()
        self.iface_name = get_active_interface_name()
        self.is_admin = check_is_admin()
        self.wifi_info = get_wifi_info()

        self.current_target_label = "Cloudflare (1.1.1.1)"
        self.current_target_ip = TARGETS[self.current_target_label]

        self.dns_servers = get_current_dns_servers(self.iface_name)
        self.dns_label, self.dns_kind = describe_dns_provider(self.dns_servers)

        self.hist_internet: deque[float | None] = deque([None] * 60, maxlen=60)
        self.win_inet: deque[float] = deque(maxlen=15)
        self.win_outcomes: deque[bool] = deque(maxlen=25)
        self.win_jitters: deque[float] = deque(maxlen=30)

        self.suspects: list[tuple[str, str, int]] = []
        self.pending_logs: deque[tuple[str, str]] = deque(maxlen=100)
        self.prev_online_state: bool | None = None

        self.latest_snapshot = {
            "level": "AVVIO", "sev": "ok", "icon": "⏳",
            "title": "Controllo della linea in corso...",
            "subtitle": "Attendi un paio di secondi per la prima analisi completa.",
            "inet_ms": None, "router_ms": None, "jitter_ms": 0.0, "loss_pct": 0.0,
            "dns_ms": None, "grade": "A+", "down_mbs": 0.0, "down_mbps": 0.0,
            "up_mbps": 0.0, "hw_errors": 0, "baseline_ms": None, "warn_ms": DEFAULT_LATENCY_WARN_MS,
        }

        self._setup_styles()
        self._build_ui()
        self._update_dns_labels()
        self._switch_page("home")

        self.tray = WinSystemTray(
            on_open=lambda: self.root.after(0, self._restore_from_tray),
            on_speedtest=lambda: self.root.after(0, self._tray_trigger_speedtest),
            on_cycle_dns=lambda: self.root.after(0, self._action_cycle_dns),
            on_exit=lambda: self.root.after(0, self._quit_completely),
        )

        self.log_message("INFO", f"Dottor Modem v10.0 avviato su {self.iface_name} (Modem: {self.router_ip})")

        self.worker = threading.Thread(target=self._monitor_worker, daemon=True)
        self.worker.start()

        self.mtr_worker = threading.Thread(target=self._mtr_loop_worker, daemon=True)
        self.mtr_worker.start()

        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close_to_tray)
        self.root.after(250, self._refresh_ui)

    def _setup_styles(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Clean.Treeview", background=BG_CARD, foreground=FG_PRIMARY, fieldbackground=BG_CARD, borderwidth=0, rowheight=29, font=("Segoe UI", 9))
        style.configure("Clean.Treeview.Heading", background=BG_CARD_ALT, foreground=FG_SECONDARY, relief="flat", font=("Segoe UI", 9, "bold"))
        style.map("Clean.Treeview", background=[("selected", BG_HOVER)])
        style.configure("Dark.TCombobox", fieldbackground=BG_CARD_ALT, background=BG_CARD_ALT, foreground=FG_PRIMARY, arrowcolor=ACCENT_CYAN, borderwidth=0)

    def _make_btn(self, parent: tk.Widget, text: str, command, bg: str = BG_CARD_ALT, fg: str = FG_PRIMARY, hover_bg: str = BG_HOVER, padx: int = 14, pady: int = 7, font_size: int = 9, tooltip: str = "") -> tk.Button:
        btn = tk.Button(parent, text=text, command=command, bg=bg, fg=fg, activebackground=hover_bg, activeforeground=fg, relief="flat", bd=0, padx=padx, pady=pady, font=("Segoe UI", font_size, "bold"), cursor="hand2")
        btn._base_bg = bg  # type: ignore[attr-defined]
        btn.bind("<Enter>", lambda _e: btn.configure(bg=hover_bg), add="+")
        btn.bind("<Leave>", lambda _e: btn.configure(bg=getattr(btn, "_base_bg", bg)), add="+")
        if tooltip:
            ToolTip(btn, tooltip)
        return btn

    def _build_ui(self) -> None:
        navbar = tk.Frame(self.root, bg=BG_APP, padx=24, pady=14)
        navbar.pack(fill="x")

        brand = tk.Frame(navbar, bg=BG_APP)
        brand.pack(side="left")
        tk.Label(brand, text="◉", bg=BG_APP, fg=ACCENT_CYAN, font=("Segoe UI", 15, "bold")).pack(side="left")
        tk.Label(brand, text=" Dottor Modem", bg=BG_APP, fg=FG_PRIMARY, font=("Segoe UI", 13, "bold")).pack(side="left")

        self.nav_frame = tk.Frame(navbar, bg=BG_CARD, padx=4, pady=4)
        self.nav_frame.pack(side="left", padx=(28, 0))

        self.nav_buttons: dict[str, tk.Button] = {}
        for page_id, label in (("home", "🏠  Panoramica"), ("tools", "🛠️  Ripara & MTR"), ("details", "📋  Dettagli")):
            b = tk.Button(self.nav_frame, text=label, command=lambda p=page_id: self._switch_page(p), bg=BG_CARD, fg=FG_MUTED, activebackground=BG_CARD_ALT, activeforeground=FG_PRIMARY, relief="flat", bd=0, padx=14, pady=5, font=("Segoe UI", 9, "bold"), cursor="hand2")
            b.pack(side="left", padx=2)
            self.nav_buttons[page_id] = b

        right_nav = tk.Frame(navbar, bg=BG_APP)
        right_nav.pack(side="right")

        self.lbl_wifi_badge = tk.Label(right_nav, text="🔌 Cavo / Wi-Fi", bg=BG_CARD, fg=FG_SECONDARY, font=("Segoe UI", 8, "bold"), padx=10, pady=5)
        self.lbl_wifi_badge.pack(side="left", padx=(0, 8))

        self.lbl_pill_status = tk.Label(right_nav, text="●  Verifica...", bg=BG_CARD, fg=ACCENT_CYAN, font=("Segoe UI", 9, "bold"), padx=12, pady=5)
        self.lbl_pill_status.pack(side="left", padx=(0, 8))

        self.btn_compact = self._make_btn(right_nav, "🗗 Mini", self._action_toggle_compact, bg=BG_CARD, fg=FG_SECONDARY, padx=10, pady=5, tooltip="Riduci a una piccola barra compatta.")
        self.btn_compact.pack(side="left", padx=(0, 6))

        self._make_btn(right_nav, "✕ Esci", self._quit_completely, bg=BG_CARD, fg=FG_MUTED, hover_bg=STATUS_ERR_BG, padx=9, pady=5, tooltip="Chiude completamente Dottor Modem.").pack(side="left")

        self.compact_view = tk.Frame(self.root, bg=BG_CARD, padx=20, pady=14)
        top_c = tk.Frame(self.compact_view, bg=BG_CARD)
        top_c.pack(fill="x")
        self.lbl_compact_title = tk.Label(top_c, text="✨ Connessione Veloce e Stabile", bg=BG_CARD, fg=FG_PRIMARY, font=("Segoe UI", 11, "bold"))
        self.lbl_compact_title.pack(side="left")
        self.btn_pin = self._make_btn(top_c, "📌 Fissa sopra", self._action_toggle_topmost, bg=BG_CARD_ALT, fg=FG_SECONDARY, padx=10, pady=3, font_size=8)
        self.btn_pin.pack(side="right")
        self.lbl_compact_metrics = tk.Label(self.compact_view, text="Velocità: 0.0 Mbps   •   Ping: -- ms   •   Stabilità: 100%", bg=BG_CARD, fg=FG_SECONDARY, font=("Segoe UI", 9))
        self.lbl_compact_metrics.pack(anchor="w", pady=(6, 0))

        self.pages_container = tk.Frame(self.root, bg=BG_APP, padx=24, pady=4)
        self.pages_container.pack(fill="both", expand=True)

        self.page_home = tk.Frame(self.pages_container, bg=BG_APP)
        self.page_tools = tk.Frame(self.pages_container, bg=BG_APP)
        self.page_details = tk.Frame(self.pages_container, bg=BG_APP)

        self._build_page_home()
        self._build_page_tools()
        self._build_page_details()

    def _build_page_home(self) -> None:
        self.hero_card = tk.Frame(self.page_home, bg=BG_CARD, padx=24, pady=18)
        self.hero_card.pack(fill="x", pady=(0, 14))

        hero_left = tk.Frame(self.hero_card, bg=BG_CARD)
        hero_left.pack(side="left", fill="both", expand=True)

        title_line = tk.Frame(hero_left, bg=BG_CARD)
        title_line.pack(anchor="w")
        self.lbl_hero_icon = tk.Label(title_line, text="⏳", bg=BG_CARD, fg=FG_PRIMARY, font=("Segoe UI", 20))
        self.lbl_hero_icon.pack(side="left", padx=(0, 10))
        self.lbl_hero_title = tk.Label(title_line, text="Controllo della linea in corso...", bg=BG_CARD, fg=FG_PRIMARY, font=("Segoe UI", 15, "bold"))
        self.lbl_hero_title.pack(side="left")

        self.lbl_hero_sub = tk.Label(hero_left, text="Attendi un paio di secondi per la prima analisi completa.", bg=BG_CARD, fg=FG_SECONDARY, font=("Segoe UI", 10), wraplength=540, justify="left")
        self.lbl_hero_sub.pack(anchor="w", pady=(6, 0))

        hero_actions = tk.Frame(self.hero_card, bg=BG_CARD)
        hero_actions.pack(side="right", padx=(16, 0))

        self.btn_speedtest = self._make_btn(hero_actions, "🚀  Misura Velocità (5s)", self._action_run_speedtest, bg=ACCENT_BLUE, fg="#ffffff", hover_bg=ACCENT_BLUE_HOVER, padx=18, pady=9, font_size=10)
        self.btn_speedtest.pack(fill="x", pady=(0, 7))

        self.btn_quick_dns = self._make_btn(hero_actions, "🌐  DNS: Verifica...", self._action_cycle_dns, bg=BG_CARD_ALT, fg=FG_SECONDARY, padx=14, pady=5, font_size=9)
        self.btn_quick_dns.pack(fill="x")

        cards_row = tk.Frame(self.page_home, bg=BG_APP)
        cards_row.pack(fill="x", pady=(0, 14))
        for col in range(3):
            cards_row.columnconfigure(col, weight=1, uniform="home_cards")

        self.card_speed_val, self.card_speed_sub = self._create_big_metric(cards_row, 0, "VELOCITÀ SCARICAMENTO", "0.0 Mbps", "In attesa di traffico o test", "Velocità attuale in Megabit al secondo.")
        self.card_ping_val, self.card_ping_sub = self._create_big_metric(cards_row, 1, "REATTIVITÀ (PING)", "-- ms", "Modem in casa: -- ms", "Più questo numero è basso, più la linea è reattiva.")
        self.card_stab_val, self.card_stab_sub = self._create_big_metric(cards_row, 2, "STABILITÀ & WI-FI", "100%", "Qualità: Analisi...", "Percentuale di pacchetti consegnati senza errori e qualità segnale Wi-Fi.")

        chart_box = tk.Frame(self.page_home, bg=BG_CARD, padx=18, pady=14)
        chart_box.pack(fill="both", expand=True, pady=(0, 18))

        chart_top = tk.Frame(chart_box, bg=BG_CARD)
        chart_top.pack(fill="x", pady=(0, 8))
        tk.Label(chart_top, text="ANDAMENTO REATTIVITÀ (ULTIMI 60 SECONDI)", bg=BG_CARD, fg=FG_MUTED, font=("Segoe UI", 8, "bold")).pack(side="left")

        target_box = tk.Frame(chart_top, bg=BG_CARD)
        target_box.pack(side="right")
        tk.Label(target_box, text="Server Test: ", bg=BG_CARD, fg=FG_MUTED, font=("Segoe UI", 8, "bold")).pack(side="left")

        self.cmb_target = ttk.Combobox(target_box, values=list(TARGETS.keys()), state="readonly", width=26, style="Dark.TCombobox", font=("Segoe UI", 8, "bold"))
        self.cmb_target.set(self.current_target_label)
        self.cmb_target.bind("<<ComboboxSelected>>", self._on_target_selected)
        self.cmb_target.pack(side="left")

        self.canvas = tk.Canvas(chart_box, bg="#131c2e", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._draw_area_chart())

    def _create_big_metric(self, parent: tk.Frame, col: int, label: str, val: str, sub: str, tooltip: str) -> tuple[tk.Label, tk.Label]:
        pad_l = 0 if col == 0 else 8
        pad_r = 0 if col == 2 else 8
        card = tk.Frame(parent, bg=BG_CARD, padx=20, pady=15)
        card.grid(row=0, column=col, sticky="nsew", padx=(pad_l, pad_r))
        lbl_top = tk.Label(card, text=label, bg=BG_CARD, fg=FG_MUTED, font=("Segoe UI", 8, "bold"))
        lbl_top.pack(anchor="w")
        lbl_val = tk.Label(card, text=val, bg=BG_CARD, fg=FG_PRIMARY, font=("Segoe UI", 21, "bold"))
        lbl_val.pack(anchor="w", pady=(5, 3))
        lbl_sub = tk.Label(card, text=sub, bg=BG_CARD, fg=FG_SECONDARY, font=("Segoe UI", 9))
        lbl_sub.pack(anchor="w")
        for w in (card, lbl_top, lbl_val, lbl_sub):
            ToolTip(w, tooltip)
        return lbl_val, lbl_sub

    def _build_page_tools(self) -> None:
        path_card = tk.Frame(self.page_tools, bg=BG_CARD, padx=20, pady=14)
        path_card.pack(fill="x", pady=(0, 14))
        tk.Label(path_card, text="DOVE PASSA LA TUA CONNESSIONE (CONTROLLO IN TEMPO REALE)", bg=BG_CARD, fg=FG_MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(0, 10))

        steps_row = tk.Frame(path_card, bg=BG_CARD)
        steps_row.pack(fill="x")
        for i in range(4):
            steps_row.columnconfigure(i, weight=1, uniform="path_steps")

        self.node_nic = self._create_path_node(steps_row, 0, "💻  Scheda / Wi-Fi", self.iface_name)
        self.node_modem = self._create_path_node(steps_row, 1, "📡  Modem Casa", self.router_ip)
        self.node_wan = self._create_path_node(steps_row, 2, "🌍  Linea Internet", self.current_target_ip)
        self.node_dns = self._create_path_node(steps_row, 3, "🔎  Apertura Siti", self.dns_label)

        cols = tk.Frame(self.page_tools, bg=BG_APP)
        cols.pack(fill="both", expand=True, pady=(0, 18))
        cols.columnconfigure(0, weight=44, uniform="tool_cols")
        cols.columnconfigure(1, weight=56, uniform="tool_cols")

        left_col = tk.Frame(cols, bg=BG_CARD, padx=18, pady=15)
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        tk.Label(left_col, text="Velocizza apertura siti (DNS)", bg=BG_CARD, fg=FG_PRIMARY, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        tk.Label(left_col, text="Se i siti web impiegano troppo ad aprirsi, seleziona un server DNS più rapido:", bg=BG_CARD, fg=FG_SECONDARY, font=("Segoe UI", 9), wraplength=360, justify="left").pack(anchor="w", pady=(4, 10))

        dns_btn_row = tk.Frame(left_col, bg=BG_CARD)
        dns_btn_row.pack(fill="x", pady=(0, 10))

        self.btn_set_cf = self._make_btn(dns_btn_row, "Cloudflare (1.1.1.1)", lambda: self._action_set_dns("cloudflare"), padx=10, pady=6, font_size=8)
        self.btn_set_cf.pack(side="left", padx=(0, 5))
        self.btn_set_gg = self._make_btn(dns_btn_row, "Google (8.8.8.8)", lambda: self._action_set_dns("google"), padx=10, pady=6, font_size=8)
        self.btn_set_gg.pack(side="left", padx=(0, 5))
        self.btn_set_auto = self._make_btn(dns_btn_row, "Automatico", lambda: self._action_set_dns("dhcp"), padx=10, pady=6, font_size=8)
        self.btn_set_auto.pack(side="left")

        if not self.is_admin:
            self._make_btn(left_col, "⚡ Sblocca permessi Amministratore per cambiare DNS", self._action_elevate_admin, bg=STATUS_WARN_BG, fg="#fde68a", hover_bg="#92400e", padx=12, pady=6, font_size=8).pack(anchor="w", pady=(0, 10))

        tk.Frame(left_col, bg=BORDER, height=1).pack(fill="x", pady=10)
        tk.Label(left_col, text="Ripristino Scheda di Rete", bg=BG_CARD, fg=FG_PRIMARY, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        tk.Label(left_col, text="Pulisce la memoria DNS o rinnova l'indirizzo IP locale del computer.", bg=BG_CARD, fg=FG_SECONDARY, font=("Segoe UI", 9), wraplength=360, justify="left").pack(anchor="w", pady=(4, 10))

        reset_row = tk.Frame(left_col, bg=BG_CARD)
        reset_row.pack(fill="x")
        self._make_btn(reset_row, "🧹 Pulisci Memoria Siti", self._action_flush_dns, padx=11, pady=6, font_size=8).pack(side="left", padx=(0, 8))
        self._make_btn(reset_row, "🔄 Riavvia Scheda Rete", self._action_full_reset, fg="#fca5a5", padx=11, pady=6, font_size=8).pack(side="left")

        right_col = tk.Frame(cols, bg=BG_CARD, padx=18, pady=15)
        right_col.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        hdr_r = tk.Frame(right_col, bg=BG_CARD)
        hdr_r.pack(fill="x")
        tk.Label(hdr_r, text="MTR Live — Analisi Nodi Continua", bg=BG_CARD, fg=FG_PRIMARY, font=("Segoe UI", 11, "bold")).pack(side="left")

        self.btn_mtr_toggle = self._make_btn(hdr_r, "▶ Avvia MTR Live", self._action_toggle_mtr, bg=ACCENT_BLUE, fg="#ffffff", hover_bg=ACCENT_BLUE_HOVER, padx=12, pady=5, font_size=8)
        self.btn_mtr_toggle.pack(side="right")

        tk.Label(right_col, text="Misura ogni 1.5s ping e perdita pacchetti di ogni singolo nodo fino al server selezionato.", bg=BG_CARD, fg=FG_SECONDARY, font=("Segoe UI", 9), wraplength=460, justify="left").pack(anchor="w", pady=(4, 8))

        self.tree_mtr = ttk.Treeview(right_col, columns=("hop", "zone", "ip", "loss", "last", "avg"), show="headings", style="Clean.Treeview", height=7)
        self.tree_mtr.heading("hop", text="#")
        self.tree_mtr.heading("zone", text="Tratta")
        self.tree_mtr.heading("ip", text="IP Nodo")
        self.tree_mtr.heading("loss", text="Persi")
        self.tree_mtr.heading("last", text="Attuale")
        self.tree_mtr.heading("avg", text="Media")

        self.tree_mtr.column("hop", anchor="center", width=30)
        self.tree_mtr.column("zone", anchor="w", width=155)
        self.tree_mtr.column("ip", anchor="w", width=105)
        self.tree_mtr.column("loss", anchor="center", width=50)
        self.tree_mtr.column("last", anchor="center", width=65)
        self.tree_mtr.column("avg", anchor="center", width=60)
        self.tree_mtr.pack(fill="both", expand=True)
        self.tree_mtr.insert("", "end", values=("-", "Premi 'Avvia MTR Live'", "-", "-", "-", "-"))

    def _create_path_node(self, parent: tk.Frame, col: int, title: str, sub: str) -> tuple[tk.Label, tk.Label]:
        pad_l = 0 if col == 0 else 6
        pad_r = 0 if col == 3 else 6
        box = tk.Frame(parent, bg=BG_CARD_ALT, padx=14, pady=10)
        box.grid(row=0, column=col, sticky="nsew", padx=(pad_l, pad_r))
        tk.Label(box, text=title, bg=BG_CARD_ALT, fg=FG_PRIMARY, font=("Segoe UI", 10, "bold")).pack(anchor="w")
        lbl_sub = tk.Label(box, text=sub, bg=BG_CARD_ALT, fg=FG_MUTED, font=("Segoe UI", 8))
        lbl_sub.pack(anchor="w", pady=(2, 5))
        lbl_badge = tk.Label(box, text="⏳ Verifica...", bg=BG_CARD_ALT, fg=ACCENT_CYAN, font=("Segoe UI", 9, "bold"))
        lbl_badge.pack(anchor="w")
        return lbl_badge, lbl_sub

    def _build_page_details(self) -> None:
        top_split = tk.Frame(self.page_details, bg=BG_APP)
        top_split.pack(fill="both", expand=True, pady=(0, 18))
        top_split.columnconfigure(0, weight=1, uniform="det_cols")
        top_split.columnconfigure(1, weight=1, uniform="det_cols")

        procs_card = tk.Frame(top_split, bg=BG_CARD, padx=18, pady=14)
        procs_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        p_hdr = tk.Frame(procs_card, bg=BG_CARD)
        p_hdr.pack(fill="x", pady=(0, 8))
        tk.Label(p_hdr, text="Programmi connessi a Internet", bg=BG_CARD, fg=FG_PRIMARY, font=("Segoe UI", 10, "bold")).pack(side="left")

        self.tree_procs = ttk.Treeview(procs_card, columns=("proc", "kind", "tot"), show="headings", style="Clean.Treeview")
        self.tree_procs.heading("proc", text="Applicazione")
        self.tree_procs.heading("kind", text="Attività")
        self.tree_procs.heading("tot", text="Connessioni")
        self.tree_procs.column("proc", anchor="w", width=175)
        self.tree_procs.column("kind", anchor="w", width=145)
        self.tree_procs.column("tot", anchor="center", width=80)
        self.tree_procs.pack(fill="both", expand=True)

        log_card = tk.Frame(top_split, bg=BG_CARD, padx=18, pady=14)
        log_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        l_hdr = tk.Frame(log_card, bg=BG_CARD)
        l_hdr.pack(fill="x", pady=(0, 8))
        tk.Label(l_hdr, text="Registro Eventi", bg=BG_CARD, fg=FG_PRIMARY, font=("Segoe UI", 10, "bold")).pack(side="left")

        self.btn_pause = self._make_btn(l_hdr, "⏸ Pausa", self._action_toggle_pause, bg=BG_CARD_ALT, fg=FG_SECONDARY, padx=8, pady=3, font_size=8)
        self.btn_pause.pack(side="right", padx=(6, 0))
        self._make_btn(l_hdr, "📂 Apri Excel (CSV)", self._action_open_csv, bg=BG_CARD_ALT, fg=FG_SECONDARY, padx=8, pady=3, font_size=8).pack(side="right")

        self.txt_log = tk.Text(log_card, bg="#131c2e", fg=FG_SECONDARY, font=("Segoe UI", 9), relief="flat", padx=10, pady=8, state="disabled", wrap="word")
        self.txt_log.pack(fill="both", expand=True)
        self.txt_log.tag_configure("ERR", foreground=STATUS_ERR)
        self.txt_log.tag_configure("WARN", foreground=STATUS_WARN)
        self.txt_log.tag_configure("OK", foreground=STATUS_OK)
        self.txt_log.tag_configure("INFO", foreground=ACCENT_CYAN)

    def _switch_page(self, page_id: str) -> None:
        self.active_page = page_id
        for pid, btn in self.nav_buttons.items():
            btn.configure(bg=ACCENT_BLUE if pid == page_id else BG_CARD, fg="#ffffff" if pid == page_id else FG_MUTED)
        self.page_home.pack_forget()
        self.page_tools.pack_forget()
        self.page_details.pack_forget()
        if page_id == "home":
            self.page_home.pack(fill="both", expand=True)
            self.root.after(50, self._draw_area_chart)
        elif page_id == "tools":
            self.page_tools.pack(fill="both", expand=True)
        else:
            self.page_details.pack(fill="both", expand=True)
            threading.Thread(target=self._refresh_processes_now, daemon=True).start()

    def _update_dns_labels(self) -> None:
        short_name = "Cloudflare" if self.dns_kind == "cloudflare" else ("Google" if self.dns_kind == "google" else "Automatico")
        self.btn_quick_dns.configure(text=f"🌐  DNS: {short_name} ↻")
        self.node_dns[1].configure(text=self.dns_label)
        for btn, kind in ((self.btn_set_cf, "cloudflare"), (self.btn_set_gg, "google"), (self.btn_set_auto, "dhcp")):
            if self.dns_kind == kind:
                btn._base_bg = STATUS_OK_BG  # type: ignore[attr-defined]
                btn.configure(bg=STATUS_OK_BG, fg="#6ee7b7")
            else:
                btn._base_bg = BG_CARD_ALT  # type: ignore[attr-defined]
                btn.configure(bg=BG_CARD_ALT, fg=FG_PRIMARY)

    def log_message(self, level: str, message: str) -> None:
        now_short = datetime.now().strftime("%H:%M:%S")
        with self.lock:
            self.pending_logs.append((level, f"{now_short}  •  {message}"))

    def _on_window_close_to_tray(self) -> None:
        if self.tray.active:
            self.root.withdraw()
            if not self.tray_hint_shown:
                self.tray_hint_shown = True
                self.tray.notify("Dottor Modem in background", "Il monitoraggio continua nella barra accanto all'orologio.", "info")
        else:
            self._quit_completely()

    def _restore_from_tray(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _tray_trigger_speedtest(self) -> None:
        self._restore_from_tray()
        self._switch_page("home")
        self._action_run_speedtest()

    def _quit_completely(self) -> None:
        self.running = False
        self.csv_logger.flush()
        self.tray.stop()
        self.root.destroy()

    def _on_target_selected(self, _event=None) -> None:
        sel = self.cmb_target.get()
        if sel in TARGETS:
            self.current_target_label = sel
            self.current_target_ip = TARGETS[sel]
            self.node_wan[1].configure(text=self.current_target_ip)
            with self.lock:
                self.mtr_tracker.reset()
                self.mtr_rows_cached = []
            self.log_message("INFO", f"Server di test impostato su {sel}")

    def _action_toggle_mtr(self) -> None:
        self.mtr_live_enabled = not self.mtr_live_enabled
        if self.mtr_live_enabled:
            with self.lock:
                self.mtr_tracker.reset()
            self.btn_mtr_toggle._base_bg = STATUS_OK_BG  # type: ignore[attr-defined]
            self.btn_mtr_toggle.configure(bg=STATUS_OK_BG, fg="#6ee7b7", text="⏹ Ferma MTR Live")
            self.log_message("INFO", f"Avviato MTR Live verso {self.current_target_ip}")
        else:
            self.btn_mtr_toggle._base_bg = ACCENT_BLUE  # type: ignore[attr-defined]
            self.btn_mtr_toggle.configure(bg=ACCENT_BLUE, fg="#ffffff", text="▶ Avvia MTR Live")

    def _action_toggle_compact(self) -> None:
        self.compact_mode = not self.compact_mode
        if self.compact_mode:
            self.nav_frame.pack_forget()
            self.pages_container.pack_forget()
            self.compact_view.pack(fill="x", padx=24, pady=(0, 16))
            self.btn_compact.configure(text="🗖 Espandi")
            self.root.minsize(480, 145)
            self.root.geometry("580x155")
        else:
            self.compact_view.pack_forget()
            self.nav_frame.pack(side="left", padx=(28, 0))
            self.pages_container.pack(fill="both", expand=True)
            self.btn_compact.configure(text="🗗 Mini")
            self.root.minsize(900, 620)
            self.root.geometry("1020x680")
            self._switch_page(self.active_page)

    def _action_toggle_topmost(self) -> None:
        self.always_on_top = not self.always_on_top
        self.root.attributes("-topmost", self.always_on_top)
        if self.always_on_top:
            self.btn_pin._base_bg = STATUS_OK_BG  # type: ignore[attr-defined]
            self.btn_pin.configure(bg=STATUS_OK_BG, fg="#6ee7b7", text="📌 Fissato")
        else:
            self.btn_pin._base_bg = BG_CARD_ALT  # type: ignore[attr-defined]
            self.btn_pin.configure(bg=BG_CARD_ALT, fg=FG_SECONDARY, text="📌 Fissa sopra")

    def _refresh_processes_now(self) -> None:
        procs = get_network_processes(limit=15)
        with self.lock:
            self.suspects = procs

    def _action_run_speedtest(self) -> None:
        if self.speedtest_running:
            return
        self.speedtest_running = True
        self.speedtest_live_mbps = 0.0
        self.btn_speedtest.configure(state="disabled", text="⏳  Misurazione (5.0s)...")
        threading.Thread(target=self._run_speedtest_worker, daemon=True).start()

    def _run_speedtest_worker(self) -> None:
        with self.lock:
            idle_inet = self.latest_snapshot["baseline_ms"] or self.latest_snapshot["inet_ms"]
            idle_router = self.latest_snapshot["router_ms"]

        self.log_message("INFO", "Avvio test velocità + analisi Bufferbloat (5 secondi)...")

        def on_progress(rem: float, mbps_now: float) -> None:
            with self.lock:
                self.speedtest_live_mbps = mbps_now
                self.speedtest_banner_until = time.time() + 2.0
                self.speedtest_banner_data = ("warn", "🚀", f"Test velocità in corso: {mbps_now:.1f} Mbps", f"Tempo rimanente: {rem:.1f}s — Verifico tenuta di Modem e Operatore sotto carico...")
            self.root.after(0, lambda r=rem: self.btn_speedtest.configure(text=f"⏳  Test ({r:.1f}s)..."))

        def get_cur_pings() -> tuple[float | None, float | None]:
            with self.lock:
                return self.latest_snapshot["router_ms"], self.latest_snapshot["inet_ms"]

        success, total_bytes, elapsed, loaded_r, loaded_i = run_speedtest_stream(SPEEDTEST_DURATION_SEC, on_progress, get_cur_pings, lambda: self.running)

        if success and total_bytes > 0:
            final_mbps = (total_bytes * 8.0) / (elapsed * 1_000_000.0)
            final_mbs = total_bytes / (elapsed * 1_048_576.0)
            sev = "ok"
            bloat_note = "Nessun Bufferbloat: modem e linea restano reattivi anche alla massima velocità."

            delta_r = ((sum(loaded_r) / len(loaded_r)) - idle_router) if (idle_router is not None and loaded_r) else 0.0
            delta_i = ((sum(loaded_i) / len(loaded_i)) - idle_inet) if (idle_inet is not None and loaded_i) else 0.0

            if delta_r > 25.0:
                sev = "warn"
                bloat_note = f"Collo di bottiglia in casa (Wi-Fi/Router +{delta_r:.0f} ms sotto sforzo). Usa il cavo Ethernet."
            elif delta_i > 65.0:
                sev = "warn"
                bloat_note = f"Bufferbloat linea Operatore (ping +{delta_i:.0f} ms sotto carico). Limita i download all'85%."
            elif idle_inet is not None and loaded_i:
                bloat_note = f"Ping riposo: {idle_inet:.0f} ms • Sotto carico: {(sum(loaded_i)/len(loaded_i)):.0f} ms (Ottima tenuta)."

            with self.lock:
                self.speedtest_last_mbps = final_mbps
                self.speedtest_banner_data = (sev, "🏁", f"Velocità Massima: {final_mbps:.1f} Mbps ({final_mbs:.1f} MB/s)", bloat_note)
                self.speedtest_banner_until = time.time() + 15.0

            self.log_message("OK", f"Speedtest: {final_mbps:.1f} Mbps — {bloat_note}")
            self.tray.notify("Speedtest Completato", f"Velocità massima: {final_mbps:.1f} Mbps", "info")
        else:
            with self.lock:
                self.speedtest_banner_data = ("err", "❌", "Test di velocità non riuscito", "Verifica che la connessione Internet sia attiva e riprova.")
                self.speedtest_banner_until = time.time() + 8.0
            self.log_message("ERR", "Test di velocità fallito.")

        self.speedtest_running = False
        self.root.after(0, lambda: self.btn_speedtest.configure(state="normal", text="🚀  Misura Velocità (5s)"))

    def _action_elevate_admin(self) -> None:
        entry_script = os.path.abspath(sys.argv[0])
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, f'"{entry_script}"', os.path.dirname(entry_script), 1)
        if ret > 32:
            self._quit_completely()

    def _action_cycle_dns(self) -> None:
        next_mode = "google" if self.dns_kind == "cloudflare" else ("dhcp" if self.dns_kind == "google" else "cloudflare")
        self._action_set_dns(next_mode)

    def _action_set_dns(self, mode: str) -> None:
        if not self.is_admin:
            if messagebox.askyesno("Permessi Amministratore", "Per cambiare i DNS di Windows servono i permessi di Amministratore.\n\nVuoi riavviare Dottor Modem come Amministratore?"):
                self._action_elevate_admin()
            return
        threading.Thread(target=self._run_set_dns, args=(mode,), daemon=True).start()

    def _run_set_dns(self, mode: str) -> None:
        ok, msg = set_dns_servers(self.iface_name, mode)
        if ok:
            self.dns_servers = get_current_dns_servers(self.iface_name)
            self.dns_label, self.dns_kind = describe_dns_provider(self.dns_servers)
            self.log_message("OK", f"{msg} + Cache pulita.")
            self.root.after(0, self._update_dns_labels)
        else:
            self.log_message("ERR", "Impossibile cambiare i server DNS.")

    def _action_flush_dns(self) -> None:
        threading.Thread(target=self._run_flush_dns, daemon=True).start()

    def _run_flush_dns(self) -> None:
        flush_dns_cache()
        self.log_message("OK", "Memoria DNS pulita con successo.")

    def _action_full_reset(self) -> None:
        if not messagebox.askyesno("Riavvia Scheda di Rete", "La connessione verrà sospesa per circa 5 secondi per rinnovare l'indirizzo IP.\n\nVuoi continuare?"):
            return
        threading.Thread(target=self._run_full_reset, daemon=True).start()

    def _run_full_reset(self) -> None:
        self.last_reset_ts = time.time()
        self.log_message("WARN", "Riavvio scheda di rete in corso...")
        reset_network_stack()
        with self.lock:
            self.win_outcomes.clear()
        self.log_message("OK", "Scheda di rete ripristinata.")

    def _action_toggle_pause(self) -> None:
        with self.lock:
            self.paused = not self.paused
            paused = self.paused
        self.btn_pause.configure(text="▶ Riprendi" if paused else "⏸ Pausa")

    def _action_open_csv(self) -> None:
        self.csv_logger.flush()
        path = os.path.abspath(LOG_FILE)
        if os.path.exists(path):
            os.startfile(path)
        else:
            messagebox.showinfo("File Excel", "Nessun dato registrato ancora.")

    def _mtr_loop_worker(self) -> None:
        while self.running:
            if not self.mtr_live_enabled or self.paused:
                time.sleep(0.35)
                continue
            target = self.current_target_ip
            raw_hops = probe_mtr_hops(target, self.router_ip, max_hops=8)
            with self.lock:
                self.mtr_rows_cached = self.mtr_tracker.update(raw_hops)
            time.sleep(1.5)

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

                if tick % 5 == 0:
                    self.wifi_info = get_wifi_info()

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
                down_mbps = (down_mbs * 1_048_576 * 8) / 1_000_000.0
                up_mbps = (up_mbs * 1_048_576 * 8) / 1_000_000.0
                prev_rx, prev_tx, prev_time = curr_rx, curr_tx, now_perf

                if tick % 3 == 0 and i_ms is not None:
                    dns_ms = probe_dns()
                else:
                    with self.lock:
                        dns_ms = self.latest_snapshot["dns_ms"]

                with self.lock:
                    self.hist_internet.append(i_ms)
                    self.win_outcomes.append(i_ms is not None)
                    if i_ms is not None:
                        self.win_inet.append(i_ms)
                        jitter = statistics.stdev(self.win_inet) if len(self.win_inet) >= 2 else 0.0
                        self.win_jitters.append(jitter)
                    else:
                        jitter = self.win_jitters[-1] if self.win_jitters else 0.0

                    loss_pct = (self.win_outcomes.count(False) / len(self.win_outcomes)) * 100.0
                    self.baseline.update(i_ms, down_mbs, loss_pct)
                    base_ms = self.baseline.baseline_ms
                    warn_ms = self.baseline.dynamic_warn_ms
                    grade = compute_line_grade(self.win_inet, self.win_jitters, self.win_outcomes)

                is_stressed = (i_ms is None) or (loss_pct > 0) or (i_ms > warn_ms) or (down_mbps >= 15.0)
                if tick % (3 if is_stressed else 12) == 0:
                    procs = get_network_processes(limit=15)
                    with self.lock:
                        self.suspects = procs
                else:
                    with self.lock:
                        procs = list(self.suspects)

                active_apps = [n for n, _k, _tot in procs if "(" not in n]
                top_app = active_apps[0] if active_apps else ""
                procs_str = ", ".join(active_apps[:3])

                sev, icon, title, subtitle = build_friendly_status(
                    r_ms, i_ms, jitter, loss_pct, dns_ms, down_mbps, top_app, warn_ms, self.wifi_info
                )

                is_currently_online = (r_ms is not None) and (i_ms is not None)
                if self.prev_online_state is not None and is_currently_online != self.prev_online_state:
                    if not is_currently_online:
                        self.tray.notify("Connessione Interrotta", title, "err")
                    else:
                        self.tray.notify("Connessione Ripristinata", "La linea Internet è tornata online.", "info")
                self.prev_online_state = is_currently_online

                if r_ms is None:
                    fail_streak += 1
                    level = "ERRORE MODEM"
                    self.log_message("ERR", f"Modem {self.router_ip} non raggiungibile ({fail_streak}/{MAX_CONSECUTIVE_FAILS})")
                elif i_ms is None:
                    fail_streak += 1
                    level = "OFFLINE"
                    self.log_message("ERR", f"Linea Internet assente ({fail_streak}/{MAX_CONSECUTIVE_FAILS})")
                elif dns_ms is None:
                    level = "ERRORE DNS"
                    self.log_message("WARN", "DNS bloccati: pulizia automatica cache...")
                    self._run_flush_dns()
                else:
                    fail_streak = 0
                    if loss_pct > 0:
                        level = "INSTABILE"
                        if tick % 4 == 0:
                            self.log_message("ERR", f"Perdita dati rilevata: {loss_pct:.0f}%")
                    elif i_ms > warn_ms or jitter > JITTER_WARN_MS:
                        level = "LENTA"
                        if tick % 5 == 0 and not self.speedtest_running:
                            self.log_message("WARN", f"Rallentamento: Ping {i_ms:.0f} ms (Download {down_mbps:.1f} Mbps)")
                    else:
                        level = "ONLINE"

                if fail_streak >= MAX_CONSECUTIVE_FAILS and (time.time() - self.last_reset_ts > RESET_COOLDOWN_SEC):
                    self._run_full_reset()
                    fail_streak = 0

                self.csv_logger.append([level, f"{r_ms:.1f}" if r_ms is not None else "TIMEOUT", f"{i_ms:.1f}" if i_ms is not None else "TIMEOUT", f"{jitter:.1f}", f"{loss_pct:.0f}", f"{down_mbs:.2f}", f"{up_mbs:.2f}", f"{dns_ms:.1f}" if dns_ms is not None else "ERRORE", procs_str])

                with self.lock:
                    self.latest_snapshot = {
                        "level": level, "sev": sev, "icon": icon, "title": title, "subtitle": subtitle,
                        "inet_ms": i_ms, "router_ms": r_ms, "jitter_ms": jitter, "loss_pct": loss_pct,
                        "dns_ms": dns_ms, "grade": grade, "down_mbs": down_mbs, "down_mbps": down_mbps,
                        "up_mbps": up_mbps, "hw_errors": hw_errs, "baseline_ms": base_ms, "warn_ms": warn_ms,
                    }

                tick += 1
                elapsed = time.perf_counter() - t_start
                time.sleep(max(0.05, POLL_INTERVAL_SEC - elapsed))

    def _refresh_ui(self) -> None:
        if not self.running:
            return

        with self.lock:
            snap = dict(self.latest_snapshot)
            procs = list(self.suspects)
            mtr_rows = list(self.mtr_rows_cached)
            logs_to_flush = list(self.pending_logs)
            self.pending_logs.clear()
            paused = self.paused
            st_running = self.speedtest_running
            st_live = self.speedtest_live_mbps
            st_last = self.speedtest_last_mbps
            st_until = self.speedtest_banner_until
            st_banner = self.speedtest_banner_data

        i_ms = snap["inet_ms"]
        r_ms = snap["router_ms"]
        down_mbps = snap["down_mbps"]
        down_mbs = snap["down_mbs"]
        loss_pct = snap["loss_pct"]
        stability_pct = max(0, int(round(100.0 - loss_pct)))

        wifi_conn = bool(self.wifi_info.get("connected"))
        wifi_sig = self.wifi_info.get("signal_pct")
        wifi_band = str(self.wifi_info.get("band") or "")
        if wifi_conn and isinstance(wifi_sig, int):
            w_col = STATUS_OK if wifi_sig >= 70 else (STATUS_WARN if wifi_sig >= 50 else STATUS_ERR)
            self.lbl_wifi_badge.configure(text=f"📶 Wi-Fi {wifi_band} • {wifi_sig}%", fg=w_col)
        else:
            self.lbl_wifi_badge.configure(text=f"🔌 {self.iface_name}", fg=FG_SECONDARY)

        p_txt = f"{i_ms:.0f} ms" if i_ms is not None else "Offline"
        self.tray.update_status(snap["sev"], f"Dottor Modem • Ping: {p_txt} • Down: {down_mbps:.1f} Mbps")

        if st_running:
            self.lbl_pill_status.configure(text="●  Test Velocità", bg="#3b0764", fg="#e9d5ff")
        elif paused:
            self.lbl_pill_status.configure(text="●  In Pausa", bg=BG_CARD, fg=FG_MUTED)
        elif snap["sev"] == "ok":
            self.lbl_pill_status.configure(text="●  Online", bg=STATUS_OK_BG, fg="#6ee7b7")
        elif snap["sev"] == "warn":
            self.lbl_pill_status.configure(text="●  Attenzione", bg=STATUS_WARN_BG, fg="#fde68a")
        else:
            self.lbl_pill_status.configure(text="●  Problema Rete", bg=STATUS_ERR_BG, fg="#fecaca")

        if st_banner and time.time() < st_until:
            sev, icon, title, subtitle = st_banner
        else:
            sev, icon, title, subtitle = snap["sev"], snap["icon"], snap["title"], snap["subtitle"]

        self.lbl_compact_title.configure(text=f"{icon}  {title}")
        spd_txt = f"{st_live:.1f} Mbps" if st_running else f"{down_mbps:.1f} Mbps"
        self.lbl_compact_metrics.configure(text=f"Velocità: {spd_txt}   •   Ping: {p_txt}   •   Stabilità: {stability_pct}%")

        if self.compact_mode:
            self.root.after(250, self._refresh_ui)
            return

        self.lbl_hero_icon.configure(text=icon)
        self.lbl_hero_title.configure(text=title)
        self.lbl_hero_sub.configure(text=subtitle)

        if st_running:
            self.card_speed_val.configure(text=f"{st_live:.1f} Mbps", fg=ACCENT_CYAN)
            self.card_speed_sub.configure(text="Misurazione massima in corso...")
        else:
            self.card_speed_val.configure(text=f"{down_mbps:.1f} Mbps", fg=ACCENT_CYAN if down_mbps > 5.0 else FG_PRIMARY)
            self.card_speed_sub.configure(text=f"Max rilevato: {st_last:.1f} Mbps" if st_last is not None else f"Traffico attuale: {down_mbs:.1f} MB/s")

        if i_ms is not None:
            p_col = STATUS_ERR if i_ms > 150 else (STATUS_WARN if i_ms > snap["warn_ms"] else FG_PRIMARY)
            self.card_ping_val.configure(text=f"{i_ms:.0f} ms", fg=p_col)
        else:
            self.card_ping_val.configure(text="Assente", fg=STATUS_ERR)
        self.card_ping_sub.configure(text=f"Modem in casa: {r_ms:.0f} ms" if r_ms is not None else "Modem non raggiungibile")

        s_col = STATUS_OK if stability_pct == 100 else (STATUS_WARN if stability_pct >= 90 else STATUS_ERR)
        self.card_stab_val.configure(text=f"{stability_pct}%", fg=s_col)
        if wifi_conn and isinstance(wifi_sig, int):
            self.card_stab_sub.configure(text=f"Wi-Fi {wifi_band}: {wifi_sig}% • Voto {snap['grade'].split()[0]}")
        else:
            self.card_stab_sub.configure(text=f"Qualità linea: {snap['grade']}")

        self.node_nic[0].configure(
            text=(f"🟢 Wi-Fi {wifi_sig}%" if (wifi_conn and isinstance(wifi_sig, int)) else "🟢 Cavo OK") if snap["hw_errors"] == 0 else f"🟡 {snap['hw_errors']} errori",
            fg=STATUS_OK if snap["hw_errors"] == 0 else STATUS_WARN,
        )
        self.node_modem[0].configure(text=f"🟢 OK ({r_ms:.0f} ms)" if r_ms is not None else "🔴 Irraggiungibile", fg=STATUS_OK if r_ms is not None else STATUS_ERR)
        if i_ms is None or loss_pct > 0:
            self.node_wan[0].configure(text="🔴 Instabile", fg=STATUS_ERR)
        elif i_ms > snap["warn_ms"]:
            self.node_wan[0].configure(text=f"🟡 Lenta ({i_ms:.0f} ms)", fg=STATUS_WARN)
        else:
            self.node_wan[0].configure(text=f"🟢 Veloce ({i_ms:.0f} ms)", fg=STATUS_OK)

        dns_ms = snap["dns_ms"]
        self.node_dns[0].configure(text=f"🟢 OK ({dns_ms:.0f} ms)" if dns_ms is not None else "🔴 Bloccati", fg=STATUS_OK if dns_ms is not None else STATUS_ERR)

        if self.active_page == "tools" and self.mtr_live_enabled and mtr_rows:
            for item in self.tree_mtr.get_children():
                self.tree_mtr.delete(item)
            for row in mtr_rows:
                self.tree_mtr.insert("", "end", values=row)

        if self.active_page == "details":
            for item in self.tree_procs.get_children():
                self.tree_procs.delete(item)
            for name, kind, tot_c in procs:
                self.tree_procs.insert("", "end", values=(name, kind, tot_c))

        if logs_to_flush:
            self.txt_log.configure(state="normal")
            for lvl, text in logs_to_flush:
                tag = lvl if lvl in ("ERR", "WARN", "OK", "INFO") else "INFO"
                self.txt_log.insert("end", text + "\n", tag)
            self.txt_log.see("end")
            self.txt_log.configure(state="disabled")

        if self.active_page == "home":
            self._draw_area_chart()

        self.root.after(250, self._refresh_ui)

    def _draw_area_chart(self) -> None:
        c = self.canvas
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 80 or h < 60:
            return
        c.delete("all")
        with self.lock:
            pts = list(self.hist_internet)

        pad_l, pad_r, pad_t, pad_b = 44, 16, 14, 24
        plot_w = w - pad_l - pad_r
        plot_h = h - pad_t - pad_b

        valid = [v for v in pts if v is not None]
        max_y = max(100.0, (max(valid) * 1.2) if valid else 100.0)
        max_y = float(((int(max_y) + 49) // 50) * 50)

        def y_pos(val: float) -> float:
            clamped = max(0.0, min(val, max_y))
            return pad_t + plot_h - (clamped / max_y) * plot_h

        for i in range(3):
            val = (max_y / 2) * i
            y = y_pos(val)
            c.create_line(pad_l, y, w - pad_r, y, fill="#1e293b", width=1)
            c.create_text(pad_l - 8, y, text=f"{int(val)} ms", fill=FG_MUTED, anchor="e", font=("Segoe UI", 8))

        n = len(pts)
        if n >= 2:
            segments: list[list[tuple[float, float]]] = []
            cur_seg: list[tuple[float, float]] = []
            for idx, val in enumerate(pts):
                x = pad_l + (idx / (n - 1)) * plot_w
                if val is None:
                    if cur_seg:
                        segments.append(cur_seg)
                        cur_seg = []
                else:
                    cur_seg.append((x, y_pos(val)))
            if cur_seg:
                segments.append(cur_seg)

            base_y = pad_t + plot_h
            for seg in segments:
                if len(seg) >= 2:
                    poly_coords = [seg[0][0], base_y]
                    for px, py in seg:
                        poly_coords.extend([px, py])
                    poly_coords.extend([seg[-1][0], base_y])
                    c.create_polygon(*poly_coords, fill="#172a4a", outline="")
                    line_coords = []
                    for px, py in seg:
                        line_coords.extend([px, py])
                    c.create_line(*line_coords, fill=ACCENT_CYAN, width=2.5, smooth=True)
                elif len(seg) == 1:
                    px, py = seg[0]
                    c.create_oval(px - 3, py - 3, px + 3, py + 3, fill=ACCENT_CYAN, outline="")

        c.create_text(pad_l, h - 9, text="1 minuto fa", fill=FG_MUTED, anchor="w", font=("Segoe UI", 8))
        c.create_text(w - pad_r, h - 9, text="Adesso", fill=FG_MUTED, anchor="e", font=("Segoe UI", 8))
