# Sistema de Telemonitoreo de Signos Vitales

## Arquitectura

```
ESP32 ──(MQTT 1883)──► Mosquitto ──(MQTT 1883)──► worker.py ──► SQLite
                           │
                           └──(WebSocket 9001)──► Navegador
                                                    │
                           Flask :5000 ─────────────┘
                             ├── GET /          → dashboard.html
                             ├── GET /api/historial
                             ├── GET /api/rangos
                             └── POST /api/rangos
```

## Archivos

| Archivo | Descripción |
|---------|-------------|
| `worker.py` | Suscribe a Mosquitto, normaliza datos y guarda en SQLite |
| `app.py` | Servidor Flask — sirve el HTML y la API REST |
| `templates/dashboard.html` | Dashboard de tiempo real (mqtt.js + Chart.js) |
| `requirements.txt` | Dependencias Python (flask, paho-mqtt) |
| `setup.sh` | Instalación automática en la Raspberry Pi |
| `telemonitoreo.db` | Base de datos SQLite (se crea al iniciar) |

## Tópicos MQTT esperados

```
salud/paciente1/bpm                   → número entero/float
salud/paciente1/temperatura_corporal  → float (°C)
salud/paciente1/temperatura_ambiente  → float (°C)
salud/paciente1/humedad_ambiente      → float (%)
salud/paciente1/aceleracion           → string descriptivo
salud/paciente1/alerta                → movimiento_brusco | bpm_fuera_rango | temperatura_corporal_fuera_rango | ninguna | cancelada_por_usuario
salud/paciente1/estado                → online | offline  (LWT retenido)
```

## Servicios

- `tele-worker` — worker MQTT
- `tele-flask`  — servidor Flask

```bash
sudo systemctl status tele-worker tele-flask
sudo journalctl -u tele-worker -f
sudo journalctl -u tele-flask  -f
```

## API REST

```
GET  /api/historial?limit=60   # últimas lecturas
GET  /api/rangos               # rangos clínicos
POST /api/rangos               # actualizar rango
     Body: {"parametro":"bpm","min":55,"max":110}
GET  /api/estado               # última lectura
```
