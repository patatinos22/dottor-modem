"""
ui/optimizer_tab.py - Dottor Modem v11.0
Tab Ottimizzatore: profili rapidi + azioni singole.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, messagebox

from core.optimizer import NetworkOptimizer, is_admin


class OptimizerTab(ttk.Frame):
    PROFILES = [
        ("Gaming", 46, True, True, True, "Priorita massima pacchetti (EF 46), Nagle off, NIC, DNS."),
        ("Download", 0, False, False, True, "Throughput massimo: QoS off, Nagle lasciato."),
        ("Streaming", 34, False, False, True, "Priorita AF41 per video, DNS veloce."),
        ("Quotidiano", 0, False, True, True, "Bilanciato: NIC + DNS, no Nagle off."),
    ]

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.optimizer = None
        self._build_ui()

    def _build_ui(self):
        admin_ok = is_admin()
        ttk.Label(self, text="Ottimizzatore Rete",
                  font=("Segoe UI", 14, "bold")).pack(pady=(10, 4), anchor="w", padx=12)
        ttk.Label(self,
                  text=("[OK] Privilegi amministratore attivi" if admin_ok
                        else "[X] Avvia come Amministratore per usare l'ottimizzatore"),
                  foreground="green" if admin_ok else "red").pack(anchor="w", padx=12)

        pf = ttk.LabelFrame(self, text="Profili rapidi")
        pf.pack(fill="x", padx=12, pady=8)
        for i, (name, dscp, nagle, nic, dns, desc) in enumerate(self.PROFILES):
            ttk.Button(pf, text=name,
                       command=lambda n=name, d=dscp, ng=nagle, nk=nic, ns=dns:
                           self._apply_profile(n, d, ng, nk, ns),
                       state="normal" if admin_ok else "disabled",
                       ).grid(row=0, column=i, padx=6, pady=(6, 2), sticky="ew")
            pf.columnconfigure(i, weight=1)
            ttk.Label(pf, text=desc, wraplength=180,
                      font=("Segoe UI", 8), foreground="gray",
                      ).grid(row=1, column=i, padx=6, pady=(0, 6), sticky="nw")

        af = ttk.LabelFrame(self, text="Azioni singole")
        af.pack(fill="x", padx=12, pady=8)
        actions = [
            ("Disabilita Nagle", lambda: self.optimizer.disable_nagle()),
            ("QoS DSCP 46", lambda: self.optimizer.enable_qos_dscp(46)),
            ("Ottimizza NIC", lambda: self.optimizer.optimize_nic()),
            ("DNS Cloudflare", lambda: self.optimizer.set_dns_cloudflare()),
            ("Rollback", self._confirm_rollback),
        ]
        for i, (label, fn) in enumerate(actions):
            ttk.Button(af, text=label, command=lambda f=fn: self._run_async(f),
                       state="normal" if admin_ok else "disabled",
                       ).grid(row=0, column=i, padx=6, pady=6, sticky="ew")
            af.columnconfigure(i, weight=1)

        lf = ttk.LabelFrame(self, text="Log")
        lf.pack(fill="both", expand=True, padx=12, pady=8)
        self.log = tk.Text(lf, height=8, state="disabled", wrap="word",
                           font=("Consolas", 9), bg="#111", fg="#ddd")
        self.log.pack(fill="both", expand=True, padx=4, pady=4)

        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.pack(fill="x", padx=12, pady=(0, 8))

    def _log(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
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
            self._log("[ERR] " + err)
            return
        for r in items:
            self._log(("[OK] " if r.success else "[!] ") + r.name + ": " + r.message)

    def _apply_profile(self, name, dscp, nagle, nic, dns):
        if not self._ensure():
            return
        self._log("\n> Profilo: " + name)

        def run():
            res = []
            if nagle:
                res.append(self.optimizer.disable_nagle())
            if dscp > 0:
                res.append(self.optimizer.enable_qos_dscp(dscp))
            else:
                res.append(self.optimizer.disable_qos())
            if nic:
                res.append(self.optimizer.optimize_nic())
            if dns:
                res.append(self.optimizer.set_dns_cloudflare())
            return res

        self._run_async(run)

    def _confirm_rollback(self):
        if not self._ensure():
            return
        if not messagebox.askyesno("Conferma", "Ripristinare tutte le impostazioni predefinite?"):
            return []
        self._log("\n> Rollback in corso...")
        return self.optimizer.rollback_all()
