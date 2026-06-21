// ============================================================
//  GÊMEO DIGITAL — MÓDULO SENSOR  (referência do hardware Wokwi)
//  Projeto: https://wokwi.com/projects/466033186398196737
//  ESP32 DevKit V1 + BH1750 (I2C: SDA=GPIO21, SCL=GPIO22)
//
//  PUBLICA → granja/sensor/lux/1
//  ASSINA  → granja/atuador/dimmer/1
//  Modelo: lux_total = lux_natural(slider) + lux_lampada(dimmer)
//          + ruído gaussiano(σ=0.5). Réplica em sensor.py.
// ============================================================
#include <WiFi.h>
#include <PubSubClient.h>
#include <BH1750.h>
#include <Wire.h>
#include <ArduinoJson.h>

const char* WIFI_SSID     = "Wokwi-GUEST";
const char* WIFI_PASSWORD = "";
const char* MQTT_BROKER   = "broker.hivemq.com";
const int   MQTT_PORT     = 1883;
const char* TOPIC_PUBLICA = "granja/sensor/lux/1";
const char* TOPIC_ASSINA  = "granja/atuador/dimmer/1";
const int   PUBLISH_MS    = 3000;
const char* SENSOR_ID     = "1";
const float LUX_MAX_LAMPADA = 15.0;

volatile float lux_lampada = 0.0;
#define SDA_PIN 21
#define SCL_PIN 22

WiFiClient   espClient;
PubSubClient mqttClient(espClient);
BH1750       lightMeter;
unsigned long ultimaPublicacao = 0;

float adicionarRuido(float lux) {
  float u1 = (float)random(1, 1000) / 1000.0;
  float u2 = (float)random(1, 1000) / 1000.0;
  float ruido = sqrt(-2.0 * log(u1)) * cos(2.0 * PI * u2);
  return lux + ruido * 0.5;
}

void onMensagem(char* topic, byte* payload, unsigned int length) {
  String raw = "";
  for (unsigned int i = 0; i < length; i++) raw += (char)payload[i];
  StaticJsonDocument<200> doc;
  if (deserializeJson(doc, raw) != DeserializationError::Ok) return;
  float dimmer_pct = doc["dimmer_pct"] | 0.0;
  lux_lampada = (dimmer_pct / 100.0) * LUX_MAX_LAMPADA;
}

void conectarWifi() {
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  int t = 0;
  while (WiFi.status() != WL_CONNECTED && t < 20) { delay(500); t++; }
}

void reconectarMQTT() {
  while (!mqttClient.connected()) {
    String clientId = "ESP32-Sensor-" + String(SENSOR_ID) + "-" + String(random(0xFFFF), HEX);
    if (mqttClient.connect(clientId.c_str())) {
      mqttClient.subscribe(TOPIC_ASSINA);
    } else { delay(3000); }
  }
}

void setup() {
  Serial.begin(115200);
  Wire.begin(SDA_PIN, SCL_PIN);
  lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE);
  conectarWifi();
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setCallback(onMensagem);
}

void loop() {
  if (!mqttClient.connected()) reconectarMQTT();
  mqttClient.loop();
  unsigned long agora = millis();
  if (agora - ultimaPublicacao >= PUBLISH_MS) {
    ultimaPublicacao = agora;
    float lux_natural = lightMeter.readLightLevel();
    float lux_total = lux_natural + lux_lampada;
    float lux = adicionarRuido(lux_total);
    if (lux < 0.0) lux = 0.0;
    StaticJsonDocument<256> doc;
    doc["sensor_id"]    = SENSOR_ID;
    doc["lux"]          = round(lux * 100.0) / 100.0;
    doc["lux_natural"]  = round(lux_natural * 100.0) / 100.0;
    doc["lux_lampada"]  = round(lux_lampada * 100.0) / 100.0;
    doc["rssi"]         = WiFi.RSSI();
    doc["uptime_s"]     = (int)(agora / 1000.0);
    doc["timestamp_ms"] = agora;
    char payload[256];
    serializeJson(doc, payload);
    mqttClient.publish(TOPIC_PUBLICA, payload);
  }
}
