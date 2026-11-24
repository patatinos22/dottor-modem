# Dottor Modem

Strumento desktop per **Windows** scritto in Python puro (zero dipendenze esterne) con interfaccia moderna e intuitiva per diagnosticare in tempo reale velocità, reattività, stabilità della linea e DNS.

## Caratteristiche Principali
- **Interfaccia a 3 Schede Pulite:**
  - **Panoramica:** Stato della linea in linguaggio chiaro, test velocità rapido di 5 secondi, 3 metriche chiave (*Velocità in Mbps*, *Reattività Ping*, *Stabilità %*) e grafico ad area.
  - **Ripara & DNS:** Mappa visiva del percorso di rete (`PC ➔ Modem ➔ Internet ➔ Siti Web`) e cambio rapido tra **Cloudflare (`1.1.1.1`)**, **Google (`8.8.8.8`)** e **Automatico**.
  - **Dettagli:** Monitoraggio applicazioni connesse ed esportazione telemetria in CSV (`dottor_modem_log.csv`).
- **Modalità Mini-Monitor:** Riduce l'app a una piccola barra fissabile in primo piano.
- **Sonde Native Windows (`iphlpapi.dll`):** Ping ICMP e lettura contatori di rete direttamente in memoria senza processi esterni.

## Avvio Rapido
Richiede **Python 3.10+** su Windows 10/11 (nessun pacchetto esterno necessario):

```powershell
python main.py
