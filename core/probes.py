from collections import Counter
import csv
import ctypes
import re
import socket
import ssl
import struct
import subprocess
import time
import urllib.request

DNS_TEST_DOMAIN = "one.one.one.one"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

TARGETS = {
    "Cloudflare (1.1.1.1)": "1.1.1.1",
    "Google (8.8.8.8)": "8.8.8.8",
    "Quad9 (9.9.9.9)": "9.9.9.9",
}

SPEEDTEST_URLS = [
    "https://speed.cloudflare.com/__down?bytes=100000000",
    "https://proof.ovh.net/files/100Mb.dat",
    "http://ipv4.download.thinkbroadband.com/100MB.zip",
]

GOOGLE_DNS = ["8.8.8.8", "8.8.4.4"]
CLOUDFLARE_DNS = ["1.1.1.1", "1.0.0.1"]

IGNORED_SYSTEM_PROCS = {
    "System",
    "Idle",
    "svchost.exe",
    "lsass.exe",
    "services.exe",
    "wininit.exe",
    "spoolsv.exe",
    "RuntimeBroker.exe",
    "SearchHost.exe",
}

AV_PROCS = {
    "avp.exe": "Kaspersky",
    "avpui.exe": "Kaspersky",
    "MsMpEng.exe": "Defender",
    "bdagent.exe": "Bitdefender",
    "avgsvc.exe": "AVG",
    "avastsvc.exe": "Avast",
}

# --- API NATIVE WINDOWS ---
_ws2_32 = ctypes.WinDLL("ws2_32")
_iphlpapi = ctypes.WinDLL("iphlpapi")

_ws2_32.inet_addr.argtypes = [ctypes.c_char_p]
_ws2_32.inet_addr.restype = ctypes.c_uint32

_iphlpapi.IcmpCreateFile.restype = ctypes.c_void_p
_iphlpapi.IcmpCloseHandle.argtypes = [ctypes.c_void_p]
_iphlpapi.IcmpSendEcho.argtypes = [
    ctypes.c_void_p,
    ctypes.c_uint32,
    ctypes.c_void_p,
    ctypes.c_uint16,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_uint32,
    ctypes.c_uint32,
]
_iphlpapi.IcmpSendEcho.restype = ctypes.c_uint32

_iphlpapi.GetIfTable.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_bool]
_iphlpapi.GetIfTable.restype = ctypes.c_uint32


def run_cmd(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=NO_WINDOW,
        check=False,
    )


def check_is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def native_ping(host: str, timeout_ms: int = 900) -> float | None:
    """Invia un pacchetto ICMP tramite iphlpapi.dll senza avviare processi esterni."""
    try:
        ip_str = socket.gethostbyname(host)
        dest_addr = _ws2_32.inet_addr(ip_str.encode("ascii"))
        if dest_addr == 0xFFFFFFFF:
            return None

        handle = _iphlpapi.IcmpCreateFile()
        if not handle or handle == ctypes.c_void_p(-1).value:
            return None

        try:
            payload = b"DottorModemPing!"
            reply_buf = ctypes.create_string_buffer(1024)
            t0 = time.perf_counter()
            replies = _iphlpapi.IcmpSendEcho(
                handle, dest_addr, payload, len(payload), None, reply_buf, len(reply_buf), timeout_ms
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            if replies > 0:
                status, rtt = struct.unpack_from("<II", reply_buf.raw, 4)
                if status == 0:
                    return float(rtt) if rtt > 0 else round(max(0.2, elapsed_ms), 1)
        finally:
            _iphlpapi.IcmpCloseHandle(handle)
    except Exception:
        pass
    return None


def read_network_counters() -> tuple[int, int, int]:
    """Legge (byte_ricevuti, byte_inviati, errori_hardware) dalle schede attive."""
    try:
        size = ctypes.c_uint32(0)
        _iphlpapi.GetIfTable(None, ctypes.byref(size), False)
        if size.value == 0:
            return 0, 0, 0
        buf = ctypes.create_string_buffer(size.value)
        if _iphlpapi.GetIfTable(buf, ctypes.byref(size), False) != 0:
            return 0, 0, 0

        num_entries = struct.unpack_from("<I", buf.raw, 0)[0]
        row_size = 860
        rx_total = tx_total = err_total = 0

        for i in range(num_entries):
            offset = 4 + i * row_size
            if offset + row_size > len(buf.raw):
                break
            if_type = struct.unpack_from("<I", buf.raw, offset + 516)[0]
            oper_status = struct.unpack_from("<I", buf.raw, offset + 544)[0]
            if if_type in (6, 71) and oper_status == 5:
                in_octets, _, _, in_disc, in_err, _, out_octets, _, _, out_disc, out_err = struct.unpack_from(
                    "<11I", buf.raw, offset + 552
                )
                rx_total += in_octets
                tx_total += out_octets
                err_total += in_disc + in_err + out_disc + out_err
        return rx_total, tx_total, err_total
    except Exception:
        return 0, 0, 0


def get_default_gateway() -> str:
    res = run_cmd(["route", "print", "0.0.0.0"])
    match = re.search(r"0\.0\.0\.0\s+0\.0\.0\.0\s+(\d{1,3}(?:\.\d{1,3}){3})", res.stdout)
    return match.group(1) if match else "192.168.1.1"


def get_active_interface_name() -> str:
    ps_cmd = (
        "(Get-NetRoute -DestinationPrefix '0.0.0.0/0' | "
        "Sort-Object RouteMetric | Select-Object -First 1).InterfaceAlias"
    )
    res = run_cmd(["powershell", "-NoProfile", "-Command", ps_cmd])
    name = res.stdout.strip()
    return name if name else "Ethernet"


def get_current_dns_servers(iface_name: str) -> list[str]:
    ps_cmd = (
        f"(Get-DnsClientServerAddress -InterfaceAlias '{iface_name}' -AddressFamily IPv4 "
        "-ErrorAction SilentlyContinue).ServerAddresses"
    )
    res = run_cmd(["powershell", "-NoProfile", "-Command", ps_cmd])
    return [line.strip() for line in res.stdout.splitlines() if line.strip()]


def describe_dns_provider(servers: list[str]) -> tuple[str, str]:
    if not servers:
        return "Automatico (Router/DHCP)", "other"
    primary = servers[0]
    joined = ", ".join(servers[:2])
    if primary in ("8.8.8.8", "8.8.4.4"):
        return f"Google ({joined})", "google"
    if primary in ("1.1.1.1", "1.0.0.1"):
        return f"Cloudflare ({joined})", "cloudflare"
    if primary.startswith("192.168.") or primary.startswith("10."):
        return f"Operatore / Router ({joined})", "other"
    return f"Personalizzato ({joined})", "other"


def probe_dns(domain: str = DNS_TEST_DOMAIN) -> float | None:
    start = time.perf_counter()
    try:
        socket.gethostbyname(domain)
        return (time.perf_counter() - start) * 1000.0
    except socket.gaierror:
        return None


def get_network_processes(limit: int = 12) -> list[tuple[str, str, int]]:
    """Restituisce [(nome_app, tipo_traffico, totale_socket), ...]."""
    netstat = run_cmd(["netstat", "-ano"])
    tcp_counts: Counter[str] = Counter()
    udp_counts: Counter[str] = Counter()

    for line in netstat.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("TCP") and "ESTABLISHED" in stripped:
            parts = stripped.split()
            if parts and parts[-1].isdigit() and parts[-1] != "0":
                tcp_counts[parts[-1]] += 1
        elif stripped.startswith("UDP"):
            parts = stripped.split()
            if parts and parts[-1].isdigit() and parts[-1] != "0":
                udp_counts[parts[-1]] += 1

    all_pids = set(tcp_counts.keys()) | set(udp_counts.keys())
    if not all_pids:
        return []

    tasklist = run_cmd(["tasklist", "/FO", "CSV", "/NH"])
    pid_to_name: dict[str, str] = {}
    for row in csv.reader(tasklist.stdout.splitlines()):
        if len(row) >= 2:
            pid_to_name[row[1]] = row[0]

    agg: dict[str, list[int]] = {}
    for pid in all_pids:
        raw_name = pid_to_name.get(pid, f"PID:{pid}")
        if raw_name in IGNORED_SYSTEM_PROCS:
            continue
        label = f"{raw_name} ({AV_PROCS[raw_name]})" if raw_name in AV_PROCS else raw_name
        if label not in agg:
            agg[label] = [0, 0]
        agg[label][0] += tcp_counts[pid]
        agg[label][1] += udp_counts[pid]

    ranked = []
    for name, (t_c, u_c) in agg.items():
        if t_c > 0 and u_c > 0:
            kind = "Web + Streaming/P2P"
        elif u_c > 0:
            kind = "UDP / Gioco / P2P"
        else:
            kind = "Navigazione / Download"
        ranked.append((name, kind, t_c + u_c))

    ranked.sort(key=lambda x: x[2], reverse=True)
    return ranked[:limit]


def flush_dns_cache() -> None:
    run_cmd(["ipconfig", "/flushdns"])


def set_dns_servers(iface_name: str, mode: str) -> tuple[bool, str]:
    if mode == "google":
        r1 = run_cmd(["netsh", "interface", "ip", "set", "dns", f"name={iface_name}", "static", GOOGLE_DNS[0]])
        r2 = run_cmd(["netsh", "interface", "ip", "add", "dns", f"name={iface_name}", GOOGLE_DNS[1], "index=2"])
        ok = r1.returncode == 0 and r2.returncode == 0
        msg = f"DNS impostati su Google ({GOOGLE_DNS[0]} / {GOOGLE_DNS[1]})"
    elif mode == "cloudflare":
        r1 = run_cmd(["netsh", "interface", "ip", "set", "dns", f"name={iface_name}", "static", CLOUDFLARE_DNS[0]])
        r2 = run_cmd(["netsh", "interface", "ip", "add", "dns", f"name={iface_name}", CLOUDFLARE_DNS[1], "index=2"])
        ok = r1.returncode == 0 and r2.returncode == 0
        msg = f"DNS impostati su Cloudflare ({CLOUDFLARE_DNS[0]} / {CLOUDFLARE_DNS[1]})"
    else:
        r1 = run_cmd(["netsh", "interface", "ip", "set", "dns", f"name={iface_name}", "dhcp"])
        ok = r1.returncode == 0
        msg = "DNS ripristinati su Automatico (DHCP del modem)"

    flush_dns_cache()
    return ok, msg


def reset_network_stack() -> None:
    for cmd in (["ipconfig", "/flushdns"], ["ipconfig", "/release"], ["ipconfig", "/renew"]):
        run_cmd(cmd)


def run_traceroute(target_ip: str, max_hops: int = 8) -> list[tuple[int, str, str, str]]:
    res = run_cmd(["tracert", "-d", "-h", str(max_hops), "-w", "600", target_ip])
    rows = []
    for line in res.stdout.splitlines():
        m = re.match(r"^\s*(\d+)\s+(.+)$", line)
        if not m:
            continue
        hop_num = int(m.group(1))
        rest = m.group(2)
        ip_match = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", rest)
        ip_addr = ip_match.group(1) if ip_match else "Non risponde"
        times = [int(t) for t in re.findall(r"(\d+)\s*ms", rest)]
        ms_str = f"{sum(times)//len(times)} ms" if times else "--"

        if hop_num == 1:
            zone = "1. Modem in Casa"
        elif hop_num <= 3:
            zone = "2. Centrale Operatore"
        else:
            zone = "3. Rete Internet"
        rows.append((hop_num, zone, ms_str, ip_addr))
    return rows


def run_speedtest_stream(
    duration_sec: float,
    on_progress,
    get_current_ping,
    is_running,
) -> tuple[bool, int, float, list[float]]:
    """Scarica un flusso di test misurando banda reale e latenza sotto carico."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    total_bytes = 0
    elapsed = 0.0
    loaded_pings: list[float] = []

    for url in SPEEDTEST_URLS:
        if not is_running():
            break
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DottorModem/7.2"},
            )
            with urllib.request.urlopen(req, timeout=4.0, context=ctx) as resp:
                t_start = time.perf_counter()
                last_tick = t_start
                while is_running():
                    now = time.perf_counter()
                    elapsed = now - t_start
                    if elapsed >= duration_sec:
                        break
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    total_bytes += len(chunk)

                    if now - last_tick >= 0.25:
                        mbps_now = (total_bytes * 8.0) / (max(0.1, elapsed) * 1_000_000.0)
                        rem = max(0.0, duration_sec - elapsed)
                        cur_p = get_current_ping()
                        if cur_p is not None:
                            loaded_pings.append(cur_p)
                        on_progress(rem, mbps_now)
                        last_tick = now

                elapsed = max(0.1, time.perf_counter() - t_start)
                if total_bytes > 0:
                    return True, total_bytes, elapsed, loaded_pings
        except Exception:
            continue

    return False, 0, 0.0, []
