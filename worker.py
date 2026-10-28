#!/usr/bin/env python3
"""
worker.py — Suscriptor MQTT + almacenamiento SQLite para telemonitoreo
Recibe datos del ESP32, los normaliza, los guarda en SQLite
y evalúa rangos clínicos para generar alertas automáticas.
"""

import paho.mqtt.client as mqtt
import sqlite3
import time
import logging
import os
import ssl
from datetime import datetime

# ─── Configuración ────────────────────────────────────────────────────────────
MQTT_BROKER   = "localhost"
MQTT_PORT     = 8883
MQTT_BASE     = "salud/paciente1"
MQTT_USER     = "worker"
MQTT_PASS     = "tele2024wk"
MQTT_TLS_CA   = os.path.join(os.path.dirname(__file__), "certs/ca.crt")
DB_PATH       = os.path.join(os.path.dirname(__file__), "telemonitoreo.db")
LOG_LEVEL     = logging.INFO

# Rangos por defecto (se sobreescriben desde la DB)
RANGOS_DEFAULT = {
    "bpm":                  {"min": 60,   "max": 100},
    "temperatura_corporal": {"min": 36.0, "max": 37.5},
    "temperatura_ambiente": {"min": 15.0, "max": 30.0},
    "humedad_ambiente":     {"min": 30.0, "max": 80.0},
}

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [worker] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("worker")

# ─── Estado en memoria ────────────────────────────────────────────────────────
ultimo = {
    "ts": None,
    "bpm": None,
    "temperatura_corporal": None,
    "temperatura_ambiente": None,
    "humedad_ambiente": None,
    "aceleracion": None,
    "alerta": "ninguna",
    "estado": "desconocido",
}

# Última alerta publicada por el worker (para evitar spam)
_ultima_alerta_worker = "ninguna"

# Cliente MQTT global (para publicar alertas)
_mqtt_client = None


# ─── Base de datos ────────────────────────────────────────────────────────────
def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS lecturas (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            ts                     TEXT NOT NULL,
            bpm                    REAL,
            temperatura_corporal   REAL,
            temperatura_ambiente   REAL,
            humedad_ambiente       REAL,
            aceleracion            TEXT,
            alerta                 TEXT,
            estado                 TEXT DEFAULT 'online'
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rangos (
            parametro  TEXT PRIMARY KEY,
            valor_min  REAL NOT NULL,
            valor_max  REAL NOT NULL
        )
    """)
    for param, vals in RANGOS_DEFAULT.items():
        cur.execute("""
            INSERT OR IGNORE INTO rangos (parametro, valor_min, valor_max)
            VALUES (?, ?, ?)
        """, (param, vals["min"], vals["max"]))
    con.commit()
    con.close()
    log.info("Base de datos inicializada en %s", DB_PATH)


def get_rangos():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT parametro, valor_min, valor_max FROM rangos")
    rows = cur.fetchall()
    con.close()
    return {r["parametro"]: {"min": r["valor_min"], "max": r["valor_max"]} for r in rows}


def insert_lectura(data: dict):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        INSERT INTO lecturas
            (ts, bpm, temperatura_corporal, temperatura_ambiente,
             humedad_ambiente, aceleracion, alerta, estado)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("ts", datetime.utcnow().isoformat()),
        data.get("bpm"),
        data.get("temperatura_corporal"),
        data.get("temperatura_ambiente"),
        data.get("humedad_ambiente"),
        data.get("aceleracion"),
        data.get("alerta"),
        data.get("estado", "online"),
    ))
    con.commit()
    con.close()


# ─── Evaluación de rangos ─────────────────────────────────────────────────────
def evaluar_rangos():
    """
    Compara los valores actuales contra los rangos guardados en la DB.
    Si algún valor está fuera de rango, publica una alerta vía MQTT.
    Si todo está normal y había alerta activa, publica 'ninguna'.
    Solo publica cuando el estado de alerta cambia (evita spam).
    """
    global _ultima_alerta_worker
    if _mqtt_client is None:
        return

    rangos = get_rangos()
    alerta = "ninguna"

    bpm   = ultimo.get("bpm")
    tcorp = ultimo.get("temperatura_corporal")

    if bpm is not None and "bpm" in rangos:
        r = rangos["bpm"]
        if bpm < r["min"] or bpm > r["max"]:
            alerta = "bpm_fuera_rango"

    if tcorp is not None and "temperatura_corporal" in rangos:
        r = rangos["temperatura_corporal"]
        if tcorp < r["min"] or tcorp > r["max"]:
            alerta = "temperatura_corporal_fuera_rango"

    # Solo publicar si el estado de alerta cambió
    if alerta != _ultima_alerta_worker:
        _ultima_alerta_worker = alerta
        _mqtt_client.publish(f"{MQTT_BASE}/alerta", alerta, qos=1, retain=False)
        log.info("Alerta worker → %s", alerta)


# ─── Utilidades ───────────────────────────────────────────────────────────────
def safe_float(value: str):
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return None


# ─── Callbacks MQTT ───────────────────────────────────────────────────────────
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        log.info("Conectado a Mosquitto (rc=0)")
        client.subscribe(f"{MQTT_BASE}/#", qos=1)
        log.info("Suscrito a %s/#", MQTT_BASE)
    else:
        log.error("Error de conexión MQTT rc=%d", rc)


def on_message(client, userdata, msg):
    topic    = msg.topic
    payload  = msg.payload.decode("utf-8", errors="replace").strip()
    subtopic = topic.replace(f"{MQTT_BASE}/", "")

    log.debug("MQTT %s → %s", subtopic, payload)

    if subtopic == "estado":
        ultimo["estado"] = payload
        return

    mapping = {
        "bpm":                  "bpm",
        "temperatura_corporal": "temperatura_corporal",
        "temperatura_ambiente": "temperatura_ambiente",
        "humedad_ambiente":     "humedad_ambiente",
        "aceleracion":          "aceleracion",
        "alerta":               "alerta",
    }

    campo = mapping.get(subtopic)
    if campo is None:
        return

    numericos = ("bpm", "temperatura_corporal", "temperatura_ambiente", "humedad_ambiente")
    if campo in numericos:
        ultimo[campo] = safe_float(payload)
    else:
        ultimo[campo] = payload

    ultimo["ts"] = datetime.utcnow().isoformat()

    # Guardar y evaluar rangos al recibir signos vitales clave
    if subtopic in ("bpm", "temperatura_corporal"):
        evaluar_rangos()
        insert_lectura(ultimo.copy())
        log.info("Lectura: bpm=%s  T_corp=%s",
                 ultimo.get("bpm"), ultimo.get("temperatura_corporal"))


def on_disconnect(client, userdata, rc):
    if rc != 0:
        log.warning("Desconectado inesperadamente (rc=%d). Reconectando…", rc)


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    global _mqtt_client
    init_db()

    client = mqtt.Client(client_id="telemonitoreo-worker", clean_session=True)
    client.on_connect    = on_connect
    client.on_message    = on_message
    client.on_disconnect = on_disconnect
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.tls_set(ca_certs=MQTT_TLS_CA, tls_version=ssl.PROTOCOL_TLSv1_2)
    client.tls_insecure_set(False)
    _mqtt_client = client

    while True:
        try:
            client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            client.loop_forever()
        except Exception as exc:
            log.error("Error MQTT: %s — reintentando en 5 s", exc)
            time.sleep(5)


if __name__ == "__main__":
    main()
