# Dottor Modem

Strumento desktop per **Windows** scritto in Python puro (zero dipendenze esterne) per diagnosticare in tempo reale latenza, bufferbloat, packet loss, DNS e utilizzo della banda.

## Funzionalità Principali
- **Sonde Native Windows (`iphlpapi.dll`):** Esegue ping ICMP (`IcmpSendEcho`) e legge i contatori di traffico delle schede (`GetIfTable`) direttamente in memoria a 1 Hz senza avviare processi esterni.
- **Diagnosi Dinamica in Italiano:** Apprende la baseline a riposo della linea e distingue automaticamente tra guasto del modem locale, disconnessione ISP, problemi DNS o saturazione da download.
- **Modalità Compatta (Mini-Monitor):** Riduce l'interfaccia a una barra essenziale fissabile in primo piano mentre lavori o scarichi.
- **Cambio DNS Rapido:** Alterna con un clic tra **Cloudflare (`1.1.1.1`)**, **Google (`8.8.8.8`)** e **DHCP automatico**, con svuotamento della cache DNS.
- **Speedtest & Bufferbloat (5s):** Misura la velocità reale in Mbps e verifica l'aumento di latenza sotto carico.
- **Tracciamento Nodi (`Tracert`) & Monitor Processi:** Isola i rallentamenti tra modem locale, centrale dell'operatore e dorsale Internet.

## Struttura del Progetto
```text
├── main.py                  # Punto di ingresso dell'applicazione
├── core/
│   ├── probes.py            # API native Windows, speedtest, tracert e gestione DNS
│   └── diagnostics.py       # Motore diagnostico, baseline dinamica e logger CSV bufferizzato
└── ui/
    └── dashboard.py         # Interfaccia desktop tkinter, modalità compatta e grafico real-time
