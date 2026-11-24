# Dottor Modem

Strumento desktop per **Windows** scritto in Python puro (zero dipendenze esterne) per diagnosticare in tempo reale latenza, bufferbloat, packet loss, DNS e utilizzo della banda.

## Struttura del Progetto
- `main.py`: punto di ingresso dell'applicazione
- `core/probes.py`: ping nativo Windows (`iphlpapi.dll`), speedtest 5s, tracert e gestione DNS
- `core/diagnostics.py`: motore diagnostico in italiano, pagella linea e logger CSV bufferizzato
- `ui/dashboard.py`: interfaccia grafica `tkinter` e grafico real-time

## Avvio Rapido
```powershell
python main.py
