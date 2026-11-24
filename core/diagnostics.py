from collections import deque
import csv
from datetime import datetime
import os
import statistics
import threading
import time

DEFAULT_LATENCY_WARN_MS = 100.0
JITTER_WARN_MS = 30.0
MAX_CONSECUTIVE_FAILS = 10
RESET_COOLDOWN_SEC = 60.0
LOG_FILE = "dottor_modem_log.csv"


class BaselineTracker:
    """Apprende il ping reale a riposo della linea per adattare automaticamente le soglie di allarme."""

    def __init__(self, maxlen: int = 40) -> None:
        self.calm_samples: deque[float] = deque(maxlen=maxlen)

    def update(self, inet_ms: float | None, down_mbs: float, loss_pct: float) -> None:
        if inet_ms is not None and down_mbs < 0.5 and loss_pct == 0.0:
            self.calm_samples.append(inet_ms)

    @property
    def baseline_ms(self) -> float | None:
        if len(self.calm_samples) < 3:
            return None
        return float(statistics.median(self.calm_samples))

    @property
    def dynamic_warn_ms(self) -> float:
        base = self.baseline_ms
        if base is None:
            return DEFAULT_LATENCY_WARN_MS
        return max(70.0, min(130.0, base * 2.6))


def compute_line_grade(latencies: deque[float], jitters: deque[float], outcomes: deque[bool]) -> str:
    if not outcomes:
        return "Analisi..."
    valid_lats = [x for x in latencies if x is not None]
    if not valid_lats:
        return "F • Assente"

    avg_lat = sum(valid_lats) / len(valid_lats)
    avg_jit = sum(jitters) / len(jitters) if jitters else 0.0
    loss_pct = (outcomes.count(False) / len(outcomes)) * 100.0

    if loss_pct >= 8.0 or avg_lat >= 180.0:
        return "F • Critica"
    if loss_pct > 2.0 or avg_lat >= 120.0 or avg_jit >= 40.0:
        return "D • Satura"
    if avg_lat >= 75.0 or avg_jit >= 25.0:
        return "C • Discreta"
    if avg_lat >= 45.0 or avg_jit >= 12.0:
        return "B • Buona"
    if avg_lat >= 25.0:
        return "A • Ottima"
    return "A+ • Perfetta"


def build_human_diagnosis(
    r_ms: float | None,
    i_ms: float | None,
    jitter: float,
    loss_pct: float,
    dns_ms: float | None,
    down_mbs: float,
    top_app: str,
    warn_threshold_ms: float = DEFAULT_LATENCY_WARN_MS,
) -> tuple[str, str, str]:
    """Restituisce (severita: 'ok'|'warn'|'err', titolo_diagnostica, consiglio_pratico)."""
    if r_ms is None:
        return (
            "err",
            "🚨 Il PC non riesce a comunicare con il Modem/Router",
            "Controlla che il cavo Ethernet sia ben inserito o che il Wi-Fi sia connesso. Se il modem ha le spie spente, riavvialo.",
        )
    if i_ms is None:
        return (
            "err",
            "❌ Il Modem funziona, ma manca la linea Internet esterna",
            "Il collegamento in casa è perfetto, ma il segnale non arriva dall'operatore. Attendi 1 minuto o riavvia il modem.",
        )
    if dns_ms is None:
        return (
            "warn",
            "⚠️ Linea attiva, ma i server DNS non traducono i siti web",
            "Internet funziona ma i siti non si aprono. Clicca su 'Cambia DNS' in alto per passare subito a Cloudflare o Google.",
        )
    if loss_pct > 0:
        return (
            "err",
            f"🚨 Perdita di pacchetti rilevata ({loss_pct:.0f}% dei dati persi)",
            "La connessione sta scartando dati. Se stai scaricando file pesanti limita la banda, altrimenti controlla il cavo di rete.",
        )
    if i_ms > warn_threshold_ms or jitter > JITTER_WARN_MS:
        if down_mbs >= 2.0:
            app_hint = f" ({top_app})" if top_app else ""
            return (
                "warn",
                f"⚠️ Rallentamento da download intenso in corso ({down_mbs:.1f} MB/s)",
                f"Nessun guasto hardware: la linea è piena per il traffico attivo{app_hint}. Se vuoi giocare o navigare fluido, limita la velocità del download.",
            )
        return (
            "warn",
            f"⚠️ Latenza sopra la media ({i_ms:.0f} ms) o segnale instabile (Jitter {jitter:.0f} ms)",
            "Il modem in casa risponde bene, ma la rete dell'operatore è rallentata in questo momento. Usa 'Controlla Nodi' per verificare dove rallenta.",
        )
    return (
        "ok",
        "✅ Connessione Ottima e Reattiva — Nessun collo di bottiglia rilevato",
        f"Modem locale ({r_ms:.0f} ms) e Internet ({i_ms:.0f} ms) rispondono velocemente senza perdita di dati.",
    )


class CsvTelemetryLogger:
    """Bufferizza i campioni in memoria e li scrive su disco a blocchi per ridurre l'I/O su SSD."""

    HEADERS = [
        "Timestamp",
        "Stato",
        "Modem_ms",
        "Internet_ms",
        "Jitter_ms",
        "Loss_%",
        "Down_MBs",
        "Up_MBs",
        "DNS_ms",
        "App_Attive",
    ]

    def __init__(self, filepath: str = LOG_FILE, flush_interval_sec: float = 15.0) -> None:
        self.filepath = filepath
        self.flush_interval_sec = flush_interval_sec
        self._buffer: list[list[str]] = []
        self._lock = threading.Lock()
        self._last_flush = time.monotonic()

    def append(self, row: list[str]) -> None:
        should_flush = False
        with self._lock:
            self._buffer.append([datetime.now().strftime("%Y-%m-%d %H:%M:%S")] + row)
            if time.monotonic() - self._last_flush >= self.flush_interval_sec:
                should_flush = True
        if should_flush:
            self.flush()

    def flush(self) -> None:
        with self._lock:
            if not self._buffer:
                return
            rows = list(self._buffer)
            self._buffer.clear()
            self._last_flush = time.monotonic()

        try:
            exists = os.path.exists(self.filepath)
            with open(self.filepath, mode="a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if not exists:
                    writer.writerow(self.HEADERS)
                writer.writerows(rows)
        except Exception:
            pass
