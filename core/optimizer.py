"""
core/optimizer.py - Dottor Modem v11.0
Ottimizzazione attiva della rete Windows: Nagle, QoS/DSCP, NIC, DNS.
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import winreg
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


BACKUP_DIR = Path(os.environ.get("USERPROFILE", ".")) / "DottorModem_Backups"
BACKUP_DIR.mkdir(exist_ok=True)


def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def _run_ps(command: str, timeout: int = 45):
    try:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        c = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command],
            capture_output=True, text=True, timeout=timeout, creationflags=flags,
        )
        return c.returncode, c.stdout.strip(), c.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


@dataclass
class OptimizationResult:
    name: str
    success: bool
    message: str
    changed: list = field(default_factory=list)


class NetworkOptimizer:
    QOS_POLICY_NAME = "DottorModem_Gaming_QoS"
    NAGLE_KEYS = ("TcpAckFrequency", "TCPNoDelay")
    TCP_BASE = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"

    def __init__(self):
        if not is_admin():
            raise PermissionError(
                "Dottor Modem deve essere eseguito come Amministratore per applicare le ottimizzazioni."
            )
        self.backup_path: Optional[Path] = None

    def _save_backup(self, data: dict) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = BACKUP_DIR / ("backup_" + stamp + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self.backup_path = path
        return path

    def _iter_tcp_interfaces(self):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self.TCP_BASE) as root:
                i = 0
                while True:
                    try:
                        yield winreg.EnumKey(root, i)
                    except OSError:
                        break
                    i += 1
        except OSError:
            return

    def disable_nagle(self) -> OptimizationResult:
        backup = {}
        changed = []
        for iface in self._iter_tcp_interfaces():
            try:
                path = self.TCP_BASE + "\\" + iface
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
                    for name in self.NAGLE_KEYS:
                        try:
                            val, _ = winreg.QueryValueEx(k, name)
                            backup.setdefault(iface, {})[name] = val
                        except FileNotFoundError:
                            pass
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_SET_VALUE) as k:
                    winreg.SetValueEx(k, "TcpAckFrequency", 0, winreg.REG_DWORD, 1)
                    winreg.SetValueEx(k, "TCPNoDelay", 0, winreg.REG_DWORD, 1)
                    changed.append(iface)
            except OSError:
                continue
        self._save_backup({"nagle": backup})
        return OptimizationResult(
            "Disabilitazione algoritmo di Nagle",
            len(changed) > 0,
            "Applicato su " + str(len(changed)) + " interfacce. Riavvia il PC per rendere effettivo.",
            changed,
        )

    def restore_nagle(self, backup: dict) -> OptimizationResult:
        for iface in self._iter_tcp_interfaces():
            try:
                path = self.TCP_BASE + "\\" + iface
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_SET_VALUE) as k:
                    for name in self.NAGLE_KEYS:
                        try:
                            winreg.DeleteValue(k, name)
                        except FileNotFoundError:
                            pass
            except OSError:
                continue
        for iface, values in (backup or {}).items():
            try:
                path = self.TCP_BASE + "\\" + iface
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_SET_VALUE) as k:
                    for name, val in values.items():
                        winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, int(val))
            except OSError:
                continue
        return OptimizationResult("Ripristino Nagle", True, "Valori originali ripristinati.")

    def enable_qos_dscp(self, dscp: int = 46) -> OptimizationResult:
        ps = (
            "Remove-NetQosPolicy -Name '" + self.QOS_POLICY_NAME + "' -Confirm:$false -ErrorAction SilentlyContinue; "
            "New-NetQosPolicy -Name '" + self.QOS_POLICY_NAME + "' -NetworkProfile All -DSCPAction " + str(dscp) + " -Precedence 1 | Out-Null; "
            "if ($?) { 'OK' } else { 'FAIL' }"
        )
        rc, out, err = _run_ps(ps)
        ok = rc == 0 and "OK" in out
        return OptimizationResult(
            "Policy QoS / DSCP " + str(dscp),
            ok,
            ("Policy '" + self.QOS_POLICY_NAME + "' creata con DSCP " + str(dscp) + ".") if ok else ("Errore: " + (err or out)),
        )

    def disable_qos(self) -> OptimizationResult:
        ps = "Remove-NetQosPolicy -Name '" + self.QOS_POLICY_NAME + "' -Confirm:$false -ErrorAction SilentlyContinue; 'OK'"
        rc, out, _ = _run_ps(ps)
        return OptimizationResult("Rimozione policy QoS", rc == 0,
                                  "Policy QoS rimossa." if rc == 0 else "Errore.")

    def optimize_nic(self) -> OptimizationResult:
        ps = """
$results=@()
$adapters=Get-NetAdapter -Physical | Where-Object { $_.Status -eq 'Up' }
foreach($a in $adapters){
    $props=Get-NetAdapterAdvancedProperty -Name $a.Name -EA SilentlyContinue
    $changed=@()
    $names=@('Energy-Efficient Ethernet','Energy Efficient Ethernet','Green Ethernet','Ultra Low Power Mode')
    foreach($n in $names){
        $p=$props|Where-Object{$_.DisplayName -eq $n}|Select-Object -First 1
        if($p){try{Set-NetAdapterAdvancedProperty -Name $a.Name -DisplayName $n -DisplayValue 'Disabled' -EA Stop;$changed+=$n}catch{}}
    }
    $pw=Get-NetAdapterPowerManagement -Name $a.Name -EA SilentlyContinue
    if($pw){try{Set-NetAdapterPowerManagement -Name $a.Name -AllowComputerToTurnOffDevice Disabled -EA Stop;$changed+='PowerSave'}catch{}}
    if($changed.Count -gt 0){$results+=($a.Name+': '+($changed -join ', '))}
}
if($results.Count -eq 0){'NO_CHANGES'}else{$results -join '; '}
"""
        rc, out, err = _run_ps(ps, timeout=60)
        if rc != 0:
            return OptimizationResult("Scheda di rete", False, err or "Errore PowerShell.")
        if "NO_CHANGES" in out:
            return OptimizationResult("Scheda di rete", True,
                "La tua scheda di rete non ha opzioni di risparmio energetico da disattivare: e' gia' ottimizzata.")
        return OptimizationResult("Scheda di rete", True, out)


    def set_dns_cloudflare(self) -> OptimizationResult:
        ps = (
            "$a = Get-NetAdapter | Where-Object { $_.Status -eq 'Up' -and $_.InterfaceDescription -notlike '*Virtual*' } | Select-Object -First 1; "
            "if (-not $a) { 'NO_ADAPTER'; exit }; "
            "Set-DnsClientServerAddress -InterfaceIndex $a.ifIndex -ServerAddresses ('1.1.1.1','1.0.0.1'); "
            "Clear-DnsClientCache; 'OK:' + $a.Name"
        )
        rc, out, _ = _run_ps(ps)
        ok = "OK:" in out
        name = out.split(":", 1)[1] if ok else "n/d"
        return OptimizationResult("DNS Cloudflare", ok,
                                  ("DNS impostato su '" + name + "' (1.1.1.1 / 1.0.0.1).") if ok else "Nessun adattatore.")

    def set_dns_auto(self) -> OptimizationResult:
        ps = (
            "$a = Get-NetAdapter | Where-Object { $_.Status -eq 'Up' -and $_.InterfaceDescription -notlike '*Virtual*' } | Select-Object -First 1; "
            "if (-not $a) { 'NO_ADAPTER'; exit }; "
            "Set-DnsClientServerAddress -InterfaceIndex $a.ifIndex -ResetServerAddresses; 'OK'"
        )
        rc, out, _ = _run_ps(ps)
        return OptimizationResult("DNS automatico", "OK" in out,
                                  "DNS ripristinato su DHCP." if "OK" in out else "Nessun adattatore.")

    def restore_nic(self) -> OptimizationResult:
        ps = (
            "$adapters = Get-NetAdapter -Physical | Where-Object { $_.Status -eq 'Up' }; "
            "foreach ($a in $adapters) { "
            "try { Set-NetAdapterPowerManagement -Name $a.Name -AllowComputerToTurnOffDevice Enabled -ErrorAction SilentlyContinue } catch {} "
            "} 'OK'"
        )
        rc, _, _ = _run_ps(ps)
        return OptimizationResult("Ripristino NIC", rc == 0, "Impostazioni predefinite ripristinate.")

    def rollback_all(self) -> list:
        results = [self.disable_qos(), self.restore_nic(), self.set_dns_auto()]
        if self.backup_path and self.backup_path.exists():
            try:
                with open(self.backup_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "nagle" in data:
                    results.append(self.restore_nagle(data["nagle"]))
            except Exception:
                pass
        return results

    def set_timer_resolution(self, ms: float = 0.5) -> OptimizationResult:
        """Imposta NtSetTimerResolution in modo persistente (thread keeper)."""
        try:
            import ctypes
            from ctypes import wintypes
            ntdll = ctypes.WinDLL("ntdll")
            ntdll.NtSetTimerResolution.argtypes = [wintypes.ULONG, wintypes.BOOLEAN, ctypes.POINTER(wintypes.ULONG)]
            target = int(ms * 10000)
            current = wintypes.ULONG()
            status = ntdll.NtSetTimerResolution(target, True, ctypes.byref(current))
            if status != 0:
                return OptimizationResult("Timer", False,
                    "Windows ha rifiutato (NTSTATUS 0x" + format(status & 0xFFFFFFFF, "08X") + ").")
            actual = current.value / 10000.0
            self._timer_active = True
            self._start_timer_keeper()
            return OptimizationResult("Timer", True,
                "Timer a " + str(round(actual, 2)) + " ms. Input lag ridotto (resta attivo finche' l'app e' aperta).")
        except Exception as e:
            return OptimizationResult("Timer", False, str(e))

    def _start_timer_keeper(self):
        if getattr(self, "_timer_keeper", None) is not None:
            return
        import threading, time as _t, ctypes
        from ctypes import wintypes
        ntdll = ctypes.WinDLL("ntdll")
        ntdll.NtSetTimerResolution.argtypes = [wintypes.ULONG, wintypes.BOOLEAN, ctypes.POINTER(wintypes.ULONG)]
        def loop():
            while getattr(self, "_timer_active", False):
                try:
                    c = wintypes.ULONG()
                    ntdll.NtSetTimerResolution(5000, True, ctypes.byref(c))
                except Exception:
                    pass
                _t.sleep(5)
        self._timer_keeper = threading.Thread(target=loop, daemon=True)
        self._timer_keeper.start()


    def run_speedtest(self) -> dict:
        try:
            import speedtest
            st = speedtest.Speedtest()
            st.get_best_server()
            d = st.download() / 1_000_000
            u = st.upload() / 1_000_000
            p = st.results.ping
            return {"download": round(d, 1), "upload": round(u, 1), "ping": round(p, 0), "ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}


