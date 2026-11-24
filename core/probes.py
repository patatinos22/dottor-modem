import ctypes
from ctypes import wintypes
from concurrent.futures import ThreadPoolExecutor
import re
import socket
import struct
import subprocess
import time
import urllib.request

TARGETS: dict[str, str] = {
    "Cloudflare (1.1.1.1)": "1.1.1.1",
    "Google (8.8.8.8)": "8.8.8.8",
    "Quad9 (9.9.9.9)": "9.9.9.9",
    "Gaming EU - Valorant": "162.249.72.1",
    "Gaming EU - CS2": "155.133.248.34",
    "Gaming EU - AWS Francoforte": "3.120.0.1",
}

SPEEDTEST_URLS: tuple[str, ...] = (
    "https://speed.cloudflare.com/__down?bytes=50000000",
    "https://proof.ovh.net/files/10Mb.dat",
)

DNS_PRESETS: dict[str, tuple[str, list[str]]] = {
    "cloudflare": ("Cloudflare (1.1.1.1)", ["1.1.1.1", "1.0.0.1"]),
    "google": ("Google (8.8.8.8)", ["8.8.8.8", "8.8.4.4"]),
}

PROCESS_FRIENDLY_NAMES: dict[str, str] = {
    "chrome.exe": "Google Chrome",
    "msedge.exe": "Microsoft Edge",
    "firefox.exe": "Mozilla Firefox",
    "brave.exe": "Brave Browser",
    "opera.exe": "Opera Browser",
    "steam.exe": "Steam (Download/Giochi)",
    "steamwebhelper.exe": "Steam Web",
    "epicgameslauncher.exe": "Epic Games Launcher",
    "battle.net.exe": "Battle.net",
    "riotclientservices.exe": "Riot Client",
    "discord.exe": "Discord (Voce/Chat)",
    "teams.exe": "Microsoft Teams",
    "ms-teams.exe": "Microsoft Teams",
    "zoom.exe": "Zoom",
    "qbittorrent.exe": "qBittorrent (P2P)",
    "utorrent.exe": "uTorrent (P2P)",
    "onedrive.exe": "Microsoft OneDrive",
    "dropbox.exe": "Dropbox",
    "googledrivesync.exe": "Google Drive",
    "svchost.exe": "Windows Update / Servizi",
    "deliveryoptimization.exe": "Windows Update P2P",
    "spotify.exe": "Spotify",
}

CREATE_NO_WINDOW = 0x08000000

_iphlpapi = ctypes.WinDLL("iphlpapi")
_kernel32 = ctypes.WinDLL("kernel32")


class IP_OPTION_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("Ttl", ctypes.c_ubyte),
        ("Tos", ctypes.c_ubyte),
        ("Flags", ctypes.c_ubyte),
        ("OptionsSize", ctypes.c_ubyte),
        ("OptionsData", ctypes.c_void_p),
    ]


class ICMP_ECHO_REPLY(ctypes.Structure):
    _fields_ = [
        ("Address", ctypes.c_uint32),
        ("Status", ctypes.c_uint32),
        ("RoundTripTime", ctypes.c_uint32),
        ("DataSize", ctypes.c_uint16),
        ("Reserved", ctypes.c_uint16),
        ("Data", ctypes.c_void_p),
        ("Options", IP_OPTION_INFORMATION),
    ]


_iphlpapi.IcmpCreateFile.restype = wintypes.HANDLE
_iphlpapi.IcmpCloseHandle.argtypes = [wintypes.HANDLE]
_iphlpapi.IcmpCloseHandle.restype = wintypes.BOOL
_iphlpapi.IcmpSendEcho.argtypes = [
    wintypes.HANDLE,
    ctypes.c_uint32,
    ctypes.c_void_p,
    wintypes.WORD,
    ctypes.POINTER(IP_OPTION_INFORMATION),
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
]
_iphlpapi.IcmpSendEcho.restype = wintypes.DWORD


def _ip_str_to_int(ip_str: str) -> int:
    return struct.unpack("<I", socket.inet_aton(ip_str))[0]


def _ip_int_to_str(ip_int: int) -> str:
    return socket.inet_ntoa(struct.pack("<I", ip_int))


def native_ping(host: str, timeout_ms: int = 900) -> float | None:
    try:
        dest_ip = socket.gethostbyname(host)
        addr = _ip_str_to_int(dest_ip)
    except Exception:
        return None

    handle = _iphlpapi.IcmpCreateFile()
    if not handle or handle == wintypes.HANDLE(-1).value:
        return None

    try:
        payload = b"DottorModemPing10"
        reply_size = ctypes.sizeof(ICMP_ECHO_REPLY) + len(payload) + 32
        reply_buf = ctypes.create_string_buffer(reply_size)

        t0 = time.perf_counter()
        count = _iphlpapi.IcmpSendEcho(
            handle, addr, payload, len(payload), None, reply_buf, reply_size, timeout_ms
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        if count == 0:
            return None

        reply = ICMP_ECHO_REPLY.from_buffer_copy(reply_buf)
        if reply.Status != 0:
            return None
        rtt = float(reply.RoundTripTime)
        return rtt if rtt > 0 else round(max(0.5, elapsed_ms), 1)
    except Exception:
        return None
    finally:
        _iphlpapi.IcmpCloseHandle(handle)


def native_ping_ttl(host: str, ttl: int, timeout_ms: int = 650) -> tuple[str | None, float | None, bool]:
    try:
        dest_ip = socket.gethostbyname(host)
        addr = _ip_str_to_int(dest_ip)
    except Exception:
        return None, None, False

    handle = _iphlpapi.IcmpCreateFile()
    if not handle or handle == wintypes.HANDLE(-1).value:
        return None, None, False

    try:
        payload = b"DottorModemMTR"
        opts = IP_OPTION_INFORMATION(Ttl=ttl, Tos=0, Flags=0, OptionsSize=0, OptionsData=None)
        reply_size = ctypes.sizeof(ICMP_ECHO_REPLY) + len(payload) + 64
        reply_buf = ctypes.create_string_buffer(reply_size)

        t0 = time.perf_counter()
        count = _iphlpapi.IcmpSendEcho(
            handle, addr, payload, len(payload), ctypes.byref(opts), reply_buf, reply_size, timeout_ms
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        if count == 0:
            return None, None, False

        reply = ICMP_ECHO_REPLY.from_buffer_copy(reply_buf)
        if reply.Status in (0, 11013):
            hop_ip = _ip_int_to_str(reply.Address)
            rtt = float(reply.RoundTripTime)
            rtt_val = rtt if rtt > 0 else round(max(0.5, elapsed_ms), 1)
            reached = (reply.Status == 0) or (hop_ip == dest_ip)
            return hop_ip, rtt_val, reached
        return None, None, False
    except Exception:
        return None, None, False
    finally:
        _iphlpapi.IcmpCloseHandle(handle)


def classify_hop_ip(hop_num: int, ip: str | None, router_ip: str) -> str:
    if not ip:
        return "Nodo silenzioso (Firewall)"
    if hop_num == 1 or ip == router_ip:
        return "Modem / Router Casa"
    parts = ip.split(".")
    if len(parts) == 4:
        try:
            a, b = int(parts[0]), int(parts[1])
            if a == 10 or (a == 192 and b == 168) or (a == 172 and 16 <= b <= 31):
                return "Rete Locale / ONT"
            if a == 100 and 64 <= b <= 127:
                return "Nodo Operatore (CGNAT)"
        except ValueError:
            pass
    return "Centrale / Dorsale Internet"


def probe_mtr_hops(target_ip: str, router_ip: str, max_hops: int = 8) -> list[tuple[int, str, str | None, float | None]]:
    results: list[tuple[int, str, str | None, float | None]] = []
    with ThreadPoolExecutor(max_workers=max_hops) as pool:
        futures = {ttl: pool.submit(native_ping_ttl, target_ip, ttl, 650) for ttl in range(1, max_hops + 1)}
        for ttl in range(1, max_hops + 1):
            hop_ip, rtt_ms, reached = futures[ttl].result()
            zone = classify_hop_ip(ttl, hop_ip, router_ip)
            results.append((ttl, zone, hop_ip, rtt_ms))
            if reached:
                break
    return results


class MIB_IFROW(ctypes.Structure):
    _fields_ = [
        ("wszName", wintypes.WCHAR * 256),
        ("dwIndex", wintypes.DWORD),
        ("dwType", wintypes.DWORD),
        ("dwMtu", wintypes.DWORD),
        ("dwSpeed", wintypes.DWORD),
        ("dwPhysAddrLen", wintypes.DWORD),
        ("bPhysAddr", ctypes.c_ubyte * 8),
        ("dwAdminStatus", wintypes.DWORD),
        ("dwOperStatus", wintypes.DWORD),
        ("dwLastChange", wintypes.DWORD),
        ("dwInOctets", wintypes.DWORD),
        ("dwInUcastPkts", wintypes.DWORD),
        ("dwInNUcastPkts", wintypes.DWORD),
        ("dwInDiscards", wintypes.DWORD),
        ("dwInErrors", wintypes.DWORD),
        ("dwInUnknownProtos", wintypes.DWORD),
        ("dwOutOctets", wintypes.DWORD),
        ("dwOutUcastPkts", wintypes.DWORD),
        ("dwOutNUcastPkts", wintypes.DWORD),
        ("dwOutDiscards", wintypes.DWORD),
        ("dwOutErrors", wintypes.DWORD),
        ("dwOutQLen", wintypes.DWORD),
        ("dwDescrLen", wintypes.DWORD),
        ("bDescr", ctypes.c_char * 256),
    ]


def read_network_counters() -> tuple[int, int, int]:
    try:
        size = wintypes.DWORD(0)
        _iphlpapi.GetIfTable(None, ctypes.byref(size), False)
        if size.value == 0:
            return 0, 0, 0
        buf = ctypes.create_string_buffer(size.value)
        if _iphlpapi.GetIfTable(buf, ctypes.byref(size), False) != 0:
            return 0, 0, 0

        num_entries = struct.unpack_from("<I", buf.raw, 0)[0]
        row_size = ctypes.sizeof(MIB_IFROW)
        offset = 4
        rx_total = 0
        tx_total = 0
        err_total = 0

        for _ in range(num_entries):
            if offset + row_size > len(buf.raw):
                break
            row = MIB_IFROW.from_buffer_copy(buf.raw, offset)
            offset += row_size
            if row.dwType != 24 and row.dwOperStatus == 1:
                rx_total += row.dwInOctets
                tx_total += row.dwOutOctets
                err_total += row.dwInErrors + row.dwOutErrors + row.dwInDiscards
        return rx_total, tx_total, err_total
    except Exception:
        return 0, 0, 0


def check_is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _run_cmd(args: list[str], timeout: float = 4.0) -> str:
    try:
        res = subprocess.run(
            args, capture_output=True, text=True, encoding="utf-8", errors="ignore",
            timeout=timeout, creationflags=CREATE_NO_WINDOW
        )
        return res.stdout or ""
    except Exception:
        return ""


def get_default_gateway() -> str:
    out = _run_cmd(["route", "print", "0.0.0.0"])
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
            gw = parts[2]
            if re.match(r"^\d+\.\d+\.\d+\.\d+$", gw) and gw != "0.0.0.0":
                return gw
    return "192.168.1.1"


def get_active_interface_name() -> str:
    out = _run_cmd(["netsh", "interface", "show", "interface"])
    candidates: list[str] = []
    for line in out.splitlines():
        low = line.lower()
        if ("connesso" in low or "connected" in low) and ("dedicato" in low or "dedicated" in low):
            parts = re.split(r"\s{2,}", line.strip())
            if len(parts) >= 4:
                candidates.append(parts[-1])
    for c in candidates:
        if "wi-fi" in c.lower() or "ethernet" in c.lower():
            return c
    return candidates[0] if candidates else "Wi-Fi"


def get_wifi_info() -> dict[str, object]:
    out = _run_cmd(["netsh", "wlan", "show", "interfaces"], timeout=2.5)
    info: dict[str, object] = {"connected": False, "ssid": "", "signal_pct": None, "band": "", "channel": "", "rx_mbps": ""}
    if not out:
        return info
    for line in out.splitlines():
        if ":" not in line:
            continue
        k, v = [p.strip() for p in line.split(":", 1)]
        kl = k.lower()
        if kl in ("stato", "state"):
            info["connected"] = ("connesso" in v.lower() or "connected" in v.lower()) and "disconnesso" not in v.lower() and "disconnected" not in v.lower()
        elif kl == "ssid":
            info["ssid"] = v
        elif kl in ("segnale", "signal"):
            m = re.search(r"(\d+)", v)
            if m:
                info["signal_pct"] = int(m.group(1))
        elif kl in ("canale", "channel"):
            info["channel"] = v
            m = re.search(r"(\d+)", v)
            if m:
                ch = int(m.group(1))
                info["band"] = "5 GHz" if ch > 14 else "2.4 GHz"
        elif "ricezione" in kl or "receive rate" in kl:
            info["rx_mbps"] = v
    return info


def get_current_dns_servers(iface_name: str) -> list[str]:
    out = _run_cmd(["netsh", "interface", "ip", "show", "dns", f'name={iface_name}'])
    ips = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", out)
    return ips[:2]


def describe_dns_provider(servers: list[str]) -> tuple[str, str]:
    if not servers:
        return "Automatico (Router/ISP)", "dhcp"
    first = servers[0]
    if first in ("1.1.1.1", "1.0.0.1"):
        return "Cloudflare (1.1.1.1)", "cloudflare"
    if first in ("8.8.8.8", "8.8.4.4"):
        return "Google (8.8.8.8)", "google"
    return f"Personalizzato ({first})", "custom"


def set_dns_servers(iface_name: str, mode: str) -> tuple[bool, str]:
    if mode == "dhcp":
        r = subprocess.run(["netsh", "interface", "ip", "set", "dns", f'name={iface_name}', "source=dhcp"], capture_output=True, creationflags=CREATE_NO_WINDOW)
        flush_dns_cache()
        return r.returncode == 0, "DNS reimpostati su Automatico (DHCP)"
    if mode not in DNS_PRESETS:
        return False, "Modalità DNS non valida"
    label, ips = DNS_PRESETS[mode]
    r1 = subprocess.run(["netsh", "interface", "ip", "set", "dns", f'name={iface_name}', "source=static", f"addr={ips[0]}", "register=primary"], capture_output=True, creationflags=CREATE_NO_WINDOW)
    if r1.returncode != 0:
        return False, f"Errore impostazione DNS {label}"
    if len(ips) > 1:
        subprocess.run(["netsh", "interface", "ip", "add", "dns", f'name={iface_name}', f"addr={ips[1]}", "index=2"], capture_output=True, creationflags=CREATE_NO_WINDOW)
    flush_dns_cache()
    return True, f"DNS attivati su {label}"


def flush_dns_cache() -> None:
    subprocess.run(["ipconfig", "/flushdns"], capture_output=True, creationflags=CREATE_NO_WINDOW)


def reset_network_stack() -> None:
    subprocess.run(["ipconfig", "/release"], capture_output=True, creationflags=CREATE_NO_WINDOW)
    time.sleep(0.8)
    subprocess.run(["ipconfig", "/renew"], capture_output=True, creationflags=CREATE_NO_WINDOW)
    flush_dns_cache()


def probe_dns(domain: str = "www.google.com") -> float | None:
    t0 = time.perf_counter()
    try:
        socket.getaddrinfo(domain, 443, proto=socket.IPPROTO_TCP)
        return round((time.perf_counter() - t0) * 1000.0, 1)
    except Exception:
        return None


def get_network_processes(limit: int = 15) -> list[tuple[str, str, int]]:
    net_out = _run_cmd(["netstat", "-ano", "-p", "TCP"], timeout=3.0)
    pid_counts: dict[str, int] = {}
    for line in net_out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] == "TCP" and parts[3] == "ESTABLISHED":
            pid = parts[4]
            if pid != "0":
                pid_counts[pid] = pid_counts.get(pid, 0) + 1
    if not pid_counts:
        return []
    task_out = _run_cmd(["tasklist", "/FO", "CSV", "/NH"], timeout=3.0)
    pid_names: dict[str, str] = {}
    for line in task_out.splitlines():
        cols = [c.strip('"') for c in line.split('","')]
        if len(cols) >= 2:
            pid_names[cols[1]] = cols[0]
    agg: dict[str, int] = {}
    for pid, cnt in pid_counts.items():
        exe = pid_names.get(pid, f"PID {pid}")
        agg[exe] = agg.get(exe, 0) + cnt
    rows: list[tuple[str, str, int]] = []
    for exe, total in sorted(agg.items(), key=lambda x: x[1], reverse=True)[:limit]:
        friendly = PROCESS_FRIENDLY_NAMES.get(exe.lower(), exe)
        kind = "Sistema / Servizi" if exe.lower() in ("svchost.exe", "system") else "App / Internet"
        rows.append((friendly, kind, total))
    return rows


def run_speedtest_stream(
    duration_sec: float, on_progress, get_cur_pings, is_running_fn
) -> tuple[bool, int, float, list[float], list[float]]:
    loaded_router_pings: list[float] = []
    loaded_inet_pings: list[float] = []
    for url in SPEEDTEST_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "DottorModem/10.0"})
            with urllib.request.urlopen(req, timeout=6.0) as resp:
                t0 = time.perf_counter()
                last_ui = t0
                total_bytes = 0
                while is_running_fn():
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    now = time.perf_counter()
                    elapsed = now - t0
                    if now - last_ui >= 0.25:
                        rem = max(0.0, duration_sec - elapsed)
                        mbps_now = (total_bytes * 8.0) / (max(0.1, elapsed) * 1_000_000.0)
                        on_progress(rem, mbps_now)
                        r_p, i_p = get_cur_pings()
                        if r_p is not None:
                            loaded_router_pings.append(r_p)
                        if i_p is not None:
                            loaded_inet_pings.append(i_p)
                        last_ui = now
                    if elapsed >= duration_sec:
                        break
                final_elapsed = max(0.2, time.perf_counter() - t0)
                if total_bytes > 50_000:
                    return True, total_bytes, final_elapsed, loaded_router_pings, loaded_inet_pings
        except Exception:
            continue
    return False, 0, 0.0, loaded_router_pings, loaded_inet_pings
