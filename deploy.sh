#!/bin/bash
# deploy.sh — Despliegue de seguridad (TLS + autenticación) para telemonitoreo
# Ejecutar en la Raspberry Pi (Electiva4) como:
#   sudo bash deploy.sh
#
# Requisitos previos:
#   - openssl instalado (viene por defecto en Raspberry Pi OS).
#   - Debe copiarse junto con worker.py y templates/dashboard.html ya
#     actualizados a /home/bvc/telemonitoreo/.
#
# El script genera la CA y el certificado del broker en /tmp/tele-certs/
# si no existen todavía, y luego los instala en su ubicación final.

set -euo pipefail

APP_DIR="/home/bvc/telemonitoreo"
CERT_SRC="/tmp/tele-certs"
CERT_DST="${APP_DIR}/certs"
PASSWD_FILE="${APP_DIR}/mqtt_passwd"
BROKER_IP="192.168.18.83"
BROKER_CN="Electiva4.local"

if [[ "$EUID" -ne 0 ]]; then
    echo "Este script debe ejecutarse con sudo/root." >&2
    exit 1
fi

echo "==> 1. Generando certificados TLS en ${CERT_SRC}"
mkdir -p "${CERT_SRC}"
if [[ -f "${CERT_SRC}/ca.crt" && -f "${CERT_SRC}/broker.crt" && -f "${CERT_SRC}/broker.key" ]]; then
    echo "    Certificados ya existen en ${CERT_SRC}, se reutilizan."
else
    # CA autofirmada, validez 3650 días
    openssl genrsa -out "${CERT_SRC}/ca.key" 4096
    openssl req -x509 -new -nodes -sha256 -days 3650 \
        -key "${CERT_SRC}/ca.key" -out "${CERT_SRC}/ca.crt" \
        -subj "/CN=Telemonitoreo-CA"

    # Clave y CSR del broker
    openssl genrsa -out "${CERT_SRC}/broker.key" 2048
    openssl req -new -sha256 \
        -key "${CERT_SRC}/broker.key" -out "${CERT_SRC}/broker.csr" \
        -subj "/CN=${BROKER_CN}"

    # SANs: IP del broker + DNS Electiva4.local + localhost
    cat > "${CERT_SRC}/broker_ext.cnf" <<EOF
subjectAltName = IP:${BROKER_IP},DNS:${BROKER_CN},DNS:localhost
EOF

    # Certificado del broker firmado por la CA, validez 3650 días
    openssl x509 -req -sha256 -days 3650 \
        -in "${CERT_SRC}/broker.csr" \
        -CA "${CERT_SRC}/ca.crt" -CAkey "${CERT_SRC}/ca.key" -CAcreateserial \
        -out "${CERT_SRC}/broker.crt" \
        -extfile "${CERT_SRC}/broker_ext.cnf"

    rm -f "${CERT_SRC}/broker.csr" "${CERT_SRC}/broker_ext.cnf"
fi

echo "==> 2. Copiando certificados a ${CERT_DST}"
mkdir -p "${CERT_DST}"
cp "${CERT_SRC}/ca.crt"     "${CERT_DST}/ca.crt"
cp "${CERT_SRC}/broker.crt" "${CERT_DST}/broker.crt"
cp "${CERT_SRC}/broker.key" "${CERT_DST}/broker.key"

echo "==> 3. Ajustando propietario y permisos"
chown -R mosquitto:mosquitto "${CERT_DST}"
chmod 644 "${CERT_DST}/ca.crt" "${CERT_DST}/broker.crt"
chmod 640 "${CERT_DST}/broker.key"

# El usuario 'bvc' (worker.py) también necesita leer la CA para validar el broker
chmod 644 "${CERT_DST}/ca.crt"

echo "==> 4. Escribiendo /etc/mosquitto/conf.d/Electiva4.conf (listener 1883/TLS)"
tee /etc/mosquitto/conf.d/Electiva4.conf > /dev/null <<EOF
listener 1883
protocol mqtt
allow_anonymous false
password_file ${PASSWD_FILE}
cafile   ${CERT_DST}/ca.crt
certfile ${CERT_DST}/broker.crt
keyfile  ${CERT_DST}/broker.key
tls_version tlsv1.2
EOF

echo "==> 5. Escribiendo /etc/mosquitto/conf.d/telemonitoreo.conf (listener 9001/WSS)"
tee /etc/mosquitto/conf.d/telemonitoreo.conf > /dev/null <<EOF
listener 9001
protocol websockets
allow_anonymous false
password_file ${PASSWD_FILE}
cafile   ${CERT_DST}/ca.crt
certfile ${CERT_DST}/broker.crt
keyfile  ${CERT_DST}/broker.key
tls_version tlsv1.2
EOF

echo "==> 6. Creando archivo de contraseñas MQTT (${PASSWD_FILE})"
mosquitto_passwd -b -c "${PASSWD_FILE}" esp32  "tele2024esp"
mosquitto_passwd -b    "${PASSWD_FILE}" worker "tele2024wk"
chown mosquitto:mosquitto "${PASSWD_FILE}"
chmod 640 "${PASSWD_FILE}"

echo "==> 7. Reiniciando Mosquitto"
systemctl restart mosquitto

echo "==> 8. Reiniciando servicios de la aplicación"
systemctl restart tele-worker tele-flask

echo "==> 9. Verificando estado de los servicios"
systemctl is-active mosquitto tele-worker tele-flask

echo
echo "Despliegue completado."
echo "Recuerda: el ESP32 debe actualizarse para usar TLS (ver ESP32_TLS_README.md)"
echo "y el navegador debe aceptar el certificado autofirmado visitando una vez:"
echo "  https://192.168.18.83:9001"
