from collections import deque
import csv
from datetime import datetime
import os
import statistics
import time

DEFAULT_LATENCY_WARN_MS = 65.0
JITTER_WARN_MS = 18.0
MAX_CONSECUTIVE_FAILS = 5
RESET_COOLDOWN_SEC = 45.0
LOG_FILE = "dottor_modem_log.csv"


class BaselineTracker:
    def __init__(self, maxlen: int = 40) -> None:
        self.samples: deque[float] = deque(maxlen=maxlen)

    def update(self, ping_ms: float | None, down_mbs: float, loss_pct: float) -> None:
        if ping_ms is not None and down_mbs < 0.8 and loss_pct == 0.0:
            self.samples.append(ping_ms)

    @property
    def baseline_ms(self) -> float | None:
        if len(self.samples) < 5:
            return None
        return float(statistics.median(self.samples))

    @property
    def dynamic_warn_ms(self) -> float:
        base = self.baseline_ms
        if base is None:
            return DEFAULT_LATENCY_WARN_MS
        return max(45.0, min(140.0, base * 1.85 + 15.0))


class LiveMtrTracker:
    def __init__(self, window: int = 25) -> None:
        self.window = window
        self.hops: dict[int, dict] = {}

    def update(self, probe_rows: list[tuple[int, str, str | None, float | None]]) -> list[tuple[int, str, str, str, str, str]]:
        seen_ttls = set()
        for ttl, zone, ip, rtt in probe_rows:
            seen_ttls.add(ttl)
            entry = self.hops.setdefault(
                ttl,
                {"ip": ip or "*", "zone": zone, "outcomes": deque(maxlen=self.window), "rtts": deque(maxlen=self.window)},
            )
            if ip:
                entry["ip"] = ip
                entry["zone"] = zone
            entry["outcomes"].append(rtt is not None)
            if rtt is not None:
                entry["rtts"].append(rtt)

        for old_ttl in [t for t in self.hops if t not in seen_ttls]:
            del self.hops[old_ttl]

        formatted: list[tuple[int, str, str, str, str, str]] = []
        for ttl in sorted(self.hops.keys()):
            e = self.hops[ttl]
            outcomes = e["outcomes"]
            rtts = e["rtts"]
            loss_pct = (outcomes.count(False) / len(outcomes)) * 100.0 if outcomes else 0.0
            last_str = f"{rtts[-1]:.0f} ms" if (outcomes and outcomes[-1] and rtts) else "Timeout"
            avg_str = f"{(sum(rtts) / len(rtts)):.0f} ms" if rtts else "--"
            formatted.append((ttl, e["zone"], e["ip"], f"{loss_pct:.0f}%", last_str, avg_str))
        return formatted

    def reset(self) -> None:
        self.hops.clear()


class CsvTelemetryLogger:
    HEADER = ["Data_Ora", "Stato", "Ping_Modem_ms", "Ping_Internet_ms", "Jitter_ms", "Packet_Loss_pct", "Download_MBs", "Upload_MBs", "DNS_ms", "App_Attive"]

    def __init__(self, filepath: str, flush_interval_sec: float = 15.0) -> None:
        self.filepath = filepath
        self.flush_interval_sec = flush_interval_sec
        self.buffer: list[list[str]] = []
        self.last_flush = time.time()

    def append(self, row_without_ts: list[str]) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.buffer.append([ts] + row_without_ts)
        if time.time() - self.last_flush >= self.flush_interval_sec:
            self.flush()

    def flush(self) -> None:
        if not self.buffer:
            return
        try:
            file_exists = os.path.exists(self.filepath) and os.path.getsize(self.filepath) > 0
            with open(self.filepath, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f, delimiter=";")
                if not file_exists:
                    writer.writerow(self.HEADER)
                writer.writerows(self.buffer)
            self.buffer.clear()
            self.last_flush = time.time()
        except Exception:
            pass


def compute_line_grade(latencies: deque[float], jitters: deque[float], outcomes: deque[bool]) -> str:
    if not outcomes:
        return "Analisi..."
    loss = (outcomes.count(False) / len(outcomes)) * 100.0
    if loss >= 15.0:
        return "F (Critica)"
    if loss >= 4.0:
        return "D (Instabile)"
    if not latencies:
        return "F (Offline)"
    avg_lat = sum(latencies) / len(latencies)
    avg_jit = (sum(jitters) / len(jitters)) if jitters else 0.0
    score = 100.0 - (loss * 8.0) - (max(0.0, avg_lat - 25.0) * 0.45) - (max(0.0, avg_jit - 4.0) * 1.2)
    if score >= 90:
        return "A+ (Perfetta)"
    if score >= 80:
        return "A (Ottima)"
    if score >= 68:
        return "B (Buona)"
    if score >= 52:
        return "C (Discreta)"
    return "D (Lenta)"


def build_friendly_status(
    r_ms: float | None,
    i_ms: float | None,
    jitter: float,
    loss_pct: float,
    dns_ms: float | None,
    down_mbps: float,
    top_app: str,
    warn_ms: float,
    wifi_info: dict[str, object] | None = None,
) -> tuple[str, str, str, str]:
    wifi_connected = bool(wifi_info and wifi_info.get("connected"))
    wifi_sig = wifi_info.get("signal_pct") if wifi_connected else None
    wifi_band = str(wifi_info.get("band") or "") if wifi_connected else ""

    if r_ms is None:
        if wifi_connected and isinstance(wifi_sig, int) and wifi_sig < 40:
            return ("err", "📶", f"Segnale Wi-Fi troppo debole ({wifi_sig}%)", "Il PC ha perso il contatto con il modem per colpa della distanza o dei muri. Avvicinati al router.")
        return ("err", "🔌", "Nessun collegamento con il Modem", "Il PC non raggiunge il router di casa. Controlla il cavo di rete o verifica che il Wi-Fi sia attivo.")

    if i_ms is None:
        return ("err", "🌐", "Modem OK, ma manca Internet", "Il collegamento in casa funziona, ma la linea dell'operatore è assente. Attendi un minuto o riavvia il modem.")

    if dns_ms is None:
        return ("warn", "🔎", "I siti web non si aprono (Errore DNS)", "La linea è attiva ma i server DNS non rispondono. Vai su 'Ripara & MTR' e attiva Cloudflare (1.1.1.1).")

    if loss_pct > 0:
        if wifi_connected and isinstance(wifi_sig, int) and wifi_sig < 60:
            return ("err", "📶", f"Perdita dati per Wi-Fi debole ({wifi_sig}%)", f"Stai perdendo il {loss_pct:.0f}% dei pacchetti su rete {wifi_band}. Passa al cavo Ethernet o avvicinati al modem.")
        return ("err", "⚠️", f"Connessione instabile ({loss_pct:.0f}% dati persi)", "Alcuni pacchetti non arrivano a destinazione. Controlla download pesanti o interferenze sulla linea.")

    if r_ms > 22.0 and wifi_connected:
        sig_note = f" (segnale {wifi_sig}% su {wifi_band})" if isinstance(wifi_sig, int) else ""
        return ("warn", "📶", f"Ritardo nel Wi-Fi di casa ({r_ms:.0f} ms verso il modem)", f"Il rallentamento nasce tra PC e modem{sig_note}, prima ancora di uscire su Internet.")

    if i_ms > warn_ms or jitter > JITTER_WARN_MS:
        if down_mbps >= 15.0:
            app_txt = f" da {top_app}" if top_app else ""
            return ("warn", "📥", f"Linea occupata da un download ({down_mbps:.0f} Mbps)", f"Nessun guasto: stai scaricando dati{app_txt}. Il ping tornerà basso appena il download rallenta.")
        return ("warn", "🐢", f"Rallentamento sulla linea Operatore ({i_ms:.0f} ms)", "Il modem in casa risponde subito, ma la rete esterna dell'operatore ha latenza alta in questo momento.")

    if wifi_connected and isinstance(wifi_sig, int) and wifi_sig < 55:
        return ("ok", "📶", f"Connessione OK, ma Wi-Fi debole ({wifi_sig}%)", f"Al momento la linea regge, ma con {wifi_sig}% di segnale ({wifi_band}) potresti avere cali di velocità.")

    return ("ok", "✨", "Connessione Veloce e Stabile", "Tutto funziona al meglio: puoi navigare, guardare video in 4K e giocare online senza interruzioni.")
