# Migración del ESP32 a MQTT con TLS (puerto 8883)

Este documento describe los cambios que hay que hacer en el firmware del
ESP32 (Arduino IDE) para que se conecte al broker Mosquitto ya asegurado
con TLS y autenticación, en vez de MQTT plano en el puerto 1883.

## Resumen de cambios

1. Usar `WiFiClientSecure` en lugar de `WiFiClient`.
2. Cargar `ca.crt` (la CA autofirmada generada en el Pi) como `const char*`
   en el sketch, y pasarlo con `setCACert()`.
3. Cambiar el puerto del broker de `1883` a `8883`.
4. Agregar credenciales con `client.setCredentials("esp32", "tele2024esp")`
   (si usas la librería `PubSubClient`, esto se hace pasando usuario y
   contraseña a `client.connect(...)`, ya que `PubSubClient` no tiene un
   método `setCredentials` propiamente dicho — ver nota más abajo).

## 1. Obtener el contenido de ca.crt

En el Pi, después de ejecutar `deploy.sh`, el certificado de la CA está en:

```
/home/bvc/telemonitoreo/certs/ca.crt
```

Imprímelo para copiarlo:

```bash
cat /home/bvc/telemonitoreo/certs/ca.crt
```

Copia el bloque completo, incluyendo las líneas `-----BEGIN CERTIFICATE-----`
y `-----END CERTIFICATE-----`.

## 2. Pegar la CA en el sketch como const char*

En Arduino IDE, agrega esto cerca del inicio del sketch (antes de `setup()`),
reemplazando el contenido de ejemplo por el que copiaste del Pi:

```cpp
// ca.crt de la CA autofirmada de Telemonitoreo (ver /home/bvc/telemonitoreo/certs/ca.crt)
static const char ca_cert[] PROGMEM = R"EOF(
-----BEGIN CERTIFICATE-----
MIIFazCCA1OgAwIBAgIUX... (pega aquí el contenido real de ca.crt) ...
-----END CERTIFICATE-----
)EOF";
```

> Usar un *raw string literal* (`R"EOF( ... )EOF"`) evita tener que escapar
> los saltos de línea del certificado manualmente.

## 3. Cambiar WiFiClient por WiFiClientSecure

Reemplaza las declaraciones globales:

```cpp
// Antes:
#include <WiFi.h>
#include <PubSubClient.h>
WiFiClient espClient;
PubSubClient client(espClient);

// Después:
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
WiFiClientSecure espClientSecure;
PubSubClient client(espClientSecure);
```

## 4. Configurar la CA y el puerto TLS

En `setup()`, antes de intentar conectar al broker:

```cpp
void setup() {
  // ... conexión WiFi existente ...

  espClientSecure.setCACert(ca_cert);   // valida el certificado del broker contra esta CA

  client.setServer("192.168.18.83", 8883);   // antes: 1883
  client.setCallback(mqttCallback);
}
```

> Nota: `setCACert` requiere que el ESP32 tenga la hora correcta (NTP) para
> validar la vigencia del certificado. Si no usas NTP, puedes usar
> `espClientSecure.setInsecure()` en su lugar (sin validar la cadena de
> certificación), pero esto reduce la seguridad y solo se recomienda para
> pruebas.

## 5. Agregar las credenciales MQTT (usuario esp32)

`PubSubClient` no expone `setCredentials()`; las credenciales se pasan
directamente en la llamada a `connect()`. Actualiza tu función de reconexión:

```cpp
const char* mqtt_user = "esp32";
const char* mqtt_pass = "tele2024esp";

void reconnectMQTT() {
  while (!client.connected()) {
    Serial.print("Conectando a MQTT...");
    // client_id, usuario, contraseña
    if (client.connect("ESP32-Paciente1", mqtt_user, mqtt_pass)) {
      Serial.println("conectado");
      client.publish("salud/paciente1/estado", "online");
    } else {
      Serial.print("falló, rc=");
      Serial.print(client.state());
      Serial.println(" reintentando en 5s");
      delay(5000);
    }
  }
}
```

## 6. Checklist final

- [ ] `WiFiClientSecure` reemplaza a `WiFiClient`.
- [ ] `ca_cert` pegado como `const char*` (contenido real de `ca.crt` del Pi).
- [ ] `espClientSecure.setCACert(ca_cert);` llamado antes de conectar.
- [ ] Puerto del broker cambiado de `1883` a `8883`.
- [ ] `client.connect(client_id, "esp32", "tele2024esp")` con las credenciales.
- [ ] Hora sincronizada por NTP (si se valida la fecha del certificado).
- [ ] Probado: el ESP32 logra conectar y publicar en `salud/paciente1/#`
      viendo los logs de `tele-worker` en el Pi (`journalctl -u tele-worker -f`).
