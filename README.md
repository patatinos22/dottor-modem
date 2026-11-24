# Dottor Modem v10.0

Strumento desktop per **Windows** scritto in Python puro (**zero dipendenze esterne**) con interfaccia moderna e intuitiva per diagnosticare in tempo reale velocità, reattività, Wi-Fi, percorsi di rete MTR e DNS.

## Novità Principali (v10.0)
- **Diagnosi Wi-Fi & Doppio Bufferbloat:** Rileva qualità del segnale Wi-Fi (`%`) e banda (`2.4 GHz` / `5 GHz`), distinguendo durante lo Speedtest se un eventuale rallentamento sotto carico nasce in casa (Wi-Fi/Router) oppure sulla linea dell'operatore (ISP).
- **Profili Server Gaming:** Test di latenza selezionabili verso **Cloudflare**, **Google**, **Quad9**, **Valorant EU**, **CS2 EU** e **AWS Francoforte**.
- **MTR Live Continuo:** Sonda ogni `1.5s` in parallelo tutti gli hop (`TTL 1..8`) tramite `iphlpapi.dll`, calcolando perdita pacchetti `%`, ping attuale e media per ogni nodo.
- **System Tray & Notifiche Native Windows:** Si riduce nell'area di notifica accanto all'orologio con icona di stato dinamica (verde/gialla/rossa), menu rapido e notifiche desktop su disconnessione, ripristino e speedtest.

## Avvio Rapido
Richiede **Python 3.10+** su Windows 10/11 (nessun pacchetto `pip` necessario):

```powershell
python main.py

```


## Ottimizzatore Rete (novita v11.0)

Nuova scheda **Ottimizzatore** (standalone con `python main_optimizer.py`) che aggiunge interventi *attivi* alla sola diagnosi:

- **Algoritmo di Nagle off** (`TcpAckFrequency` + `TCPNoDelay`) - riduce la latenza TCP nei giochi.
- **QoS / DSCP tagging** tramite `New-NetQosPolicy` (EF 46 gaming, AF41 34 streaming).
- **Scheda di rete**: disattiva risparmio energetico e Energy-Efficient Ethernet.
- **DNS Cloudflare** (1.1.1.1 / 1.0.0.1) sull'adattatore attivo.
- **Profili rapidi**: Gaming, Download, Streaming, Quotidiano.
- **Rollback completo** alle impostazioni predefinite.

Backup automatico in `%USERPROFILE%\DottorModem_Backups\backup_YYYYMMDD_HHMMSS.json`.
Richiede privilegi di amministratore. Riavvia il PC dopo aver disattivato Nagle.
