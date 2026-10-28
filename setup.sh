#!/usr/bin/env bash
# setup.sh — Instala y configura el sistema de telemonitoreo en Raspberry Pi / Orange Pi
# Uso: sudo bash setup.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

PROYECTO_DIR="$(cd "$(dirname "$0")" && pwd)"
USER_ACTUAL="${SUDO_USER:-$(whoami)}"
SERVICE_USER="$USER_ACTUAL"

echo "============================================================"
echo "  Instalación — Telemonitoreo de Signos Vitales"
echo "  Directorio: $PROYECTO_DIR"
echo "  Usuario de servicio: $SERVICE_USER"
echo "============================================================"

# ── 1. Dependencias del sistema ───────────────────────────────────
echo ""
echo "▶ 1/6  Actualizando paquetes e instalando dependencias…"
apt-get update -qq
apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    mosquitto mosquitto-clients \
    sqlite3 curl

# ── 2. Entorno virtual Python ─────────────────────────────────────
echo ""
echo "▶ 2/6  Creando entorno virtual Python…"
python3 -m venv "$PROYECTO_DIR/venv"
"$PROYECTO_DIR/venv/bin/pip" install --upgrade pip -q
"$PROYECTO_DIR/venv/bin/pip" install -r "$PROYECTO_DIR/requirements.txt" -q

echo "   ✓ Flask y paho-mqtt instalados"

# ── 3. Configurar Mosquitto (MQTT + WebSocket) ────────────────────
echo ""
echo "▶ 3/6  Configurando Mosquitto con WebSocket en puerto 9001…"

MOSQ_CONF="/etc/mosquitto/conf.d/telemonitoreo.conf"
cat > "$MOSQ_CONF" <<'EOF'
# Listener MQTT estándar
listener 1883
allow_anonymous true

# Listener WebSocket para el navegador
listener 9001
protocol websockets
allow_anonymous true
EOF

echo "   ✓ Mosquitto configurado en /etc/mosquitto/conf.d/telemonitoreo.conf"

systemctl enable mosquitto
systemctl restart mosquitto
sleep 1

if systemctl is-active --quiet mosquitto; then
    echo "   ✓ Mosquitto activo"
else
    echo "   ✗ Mosquitto no arrancó — revisa: journalctl -u mosquitto -n 20"
fi

# ── 4. Servicios systemd ───────────────────────────────────────────
echo ""
echo "▶ 4/6  Creando servicios systemd…"

# ─ Worker ─
cat > /etc/systemd/system/tele-worker.service <<EOF
[Unit]
Description=Telemonitoreo — Worker MQTT → SQLite
After=network.target mosquitto.service
Wants=mosquitto.service

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$PROYECTO_DIR
ExecStart=$PROYECTO_DIR/venv/bin/python3 $PROYECTO_DIR/worker.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# ─ Flask ─
cat > /etc/systemd/system/tele-flask.service <<EOF
[Unit]
Description=Telemonitoreo — Dashboard Flask
After=network.target tele-worker.service
Wants=tele-worker.service

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$PROYECTO_DIR
ExecStart=$PROYECTO_DIR/venv/bin/python3 $PROYECTO_DIR/app.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable tele-worker.service tele-flask.service
systemctl restart tele-worker.service tele-flask.service

sleep 2

echo ""
echo "▶ 5/6  Verificando servicios…"
for svc in tele-worker tele-flask mosquitto; do
    if systemctl is-active --quiet "$svc"; then
        echo "   ✓ $svc  — activo"
    else
        echo "   ✗ $svc  — inactivo — revisa: journalctl -u $svc -n 20"
    fi
done

# ── 5. Prueba de conectividad MQTT ────────────────────────────────
echo ""
echo "▶ 6/6  Prueba rápida de MQTT…"
mosquitto_pub -h localhost -p 1883 -t "salud/paciente1/estado" -m "online" 2>/dev/null && \
    echo "   ✓ Publicación MQTT OK" || echo "   ✗ No se pudo publicar en MQTT"

# ── Resumen ───────────────────────────────────────────────────────
IP_LOCAL=$(hostname -I | awk '{print $1}')
echo ""
echo "============================================================"
echo "  ✅ Instalación completada"
echo ""
echo "  Dashboard:   http://${IP_LOCAL}:5000"
echo "  MQTT broker: ${IP_LOCAL}:1883"
echo "  WS broker:   ${IP_LOCAL}:9001"
echo ""
echo "  Comandos útiles:"
echo "    journalctl -u tele-worker -f    # logs del worker"
echo "    journalctl -u tele-flask  -f    # logs de Flask"
echo "    mosquitto_sub -h localhost -t 'salud/paciente1/#' -v"
echo "============================================================"
