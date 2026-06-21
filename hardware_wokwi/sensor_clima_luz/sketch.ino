// ============================================================
//  GÊMEO DIGITAL — MÓDULO SENSOR (referência do hardware Wokwi)
//  Projeto Wokwi: 466268938818177025
//  Microcontrolador : ESP32 DevKit V1
//  Sensores         : BH1750 (I2C — SDA=GPIO21, SCL=GPIO22)
//                     DHT22  (1-Wire — DATA=GPIO15)
//
//  Tópicos MQTT:
//    PUBLICA  → granja/sensor/lux/1       (luminosidade)
//    PUBLICA  → granja/sensor/clima/1     (temperatura, umidade, ITU)
//    ASSINA   → granja/atuador/dimmer/1   (feedback da lâmpada)
//
//  Modelo físico (lux):
//    lux_total = lux_natural (slider) + lux_lampada (dimmer)
//
//  Índice de Temperatura e Umidade (ITU):
//    ITU = Tbs + 0.36 * Tpo + 41.5
//    onde Tpo é o ponto de orvalho pela fórmula de Magnus a partir
//    de temperatura (Tbs) e umidade relativa (UR).
//
//  >>> Esta é a réplica fiel em Python deste firmware:
//      gemeo_digital/sensors.py  (SensorLux + SensorClima)
//      gemeo_digital/environment.py  (calcular_itu / ponto_de_orvalho)
// ============================================================

#include <WiFi.h>
#include <PubSubClient.h>
#include <BH1750.h>
#include <Wire.h>
#include <DHT.h>
#include <ArduinoJson.h>
#include <math.h>

const char* WIFI_SSID     = "Wokwi-GUEST";
const char* WIFI_PASSWORD = "";

const char* MQTT_BROKER   = "broker.hivemq.com";
const int   MQTT_PORT     = 1883;
const char* TOPIC_LUX     = "granja/sensor/lux/1";
const char* TOPIC_CLIMA   = "granja/sensor/clima/1";
const char* TOPIC_ASSINA  = "granja/atuador/dimmer/1";
const int   PUBLISH_MS    = 3000;

const char* SENSOR_ID = "1";
const float LUX_MAX_LAMPADA = 15.0;

#define SDA_PIN  21
#define SCL_PIN  22
#define DHT_PIN  15
#define DHT_TYPE DHT22

// Limiares de ITU (aves adultas): <74 conforto | 74-78 alerta | >78 crítico

volatile float lux_lampada = 0.0;

WiFiClient   espClient;
PubSubClient mqttClient(espClient);
BH1750       lightMeter;
DHT          dht(DHT_PIN, DHT_TYPE);

unsigned long ultimaPublicacao = 0;

// Ruído gaussiano (σ = 0.5 lux) — Box-Muller
float adicionarRuido(float lux) {
  float u1    = (float)random(1, 1000) / 1000.0;
  float u2    = (float)random(1, 1000) / 1000.0;
  float ruido = sqrt(-2.0 * log(u1)) * cos(2.0 * PI * u2);
  return lux + ruido * 0.5;
}

// Ponto de orvalho (fórmula de Magnus)
float calcularTdp(float temperatura, float umidade) {
  const float a = 17.27, b = 237.7;
  float alpha = (a * temperatura) / (b + temperatura) + log(umidade / 100.0);
  return (b * alpha) / (a - alpha);
}

// ITU = Tbs + 0.36 * Tpo + 41.5
float calcularITU(float temperatura, float umidade) {
  return temperatura + 0.36 * calcularTdp(temperatura, umidade) + 41.5;
}

const char* zonaITU(float itu) {
  if (itu < 74.0) return "conforto";
  if (itu < 79.0) return "alerta";
  return "critico";
}

void onMensagem(char* topic, byte* payload, unsigned int length) {
  String raw = "";
  for (unsigned int i = 0; i < length; i++) raw += (char)payload[i];
  StaticJsonDocument<200> doc;
  if (deserializeJson(doc, raw) != DeserializationError::Ok) return;
  float dimmer_pct = doc["dimmer_pct"] | 0.0;
  lux_lampada      = (dimmer_pct / 100.0) * LUX_MAX_LAMPADA;
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
  dht.begin();
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

    // BLOCO 1 — LUMINOSIDADE
    float lux_natural = lightMeter.readLightLevel();
    float lux = adicionarRuido(lux_natural + lux_lampada);
    if (lux < 0.0) lux = 0.0;
    {
      StaticJsonDocument<256> doc;
      doc["sensor_id"] = SENSOR_ID;
      doc["lux"] = round(lux * 100.0) / 100.0;
      doc["lux_natural"] = round(lux_natural * 100.0) / 100.0;
      doc["lux_lampada"] = round(lux_lampada * 100.0) / 100.0;
      char payload[256]; serializeJson(doc, payload);
      mqttClient.publish(TOPIC_LUX, payload);
    }

    // BLOCO 2 — CLIMA (DHT22 precisa >=2s entre leituras; PUBLISH_MS=3000)
    float temperatura = dht.readTemperature();
    float umidade     = dht.readHumidity();
    if (!isnan(temperatura) && !isnan(umidade)) {
      float tdp = calcularTdp(temperatura, umidade);
      float itu = calcularITU(temperatura, umidade);
      StaticJsonDocument<300> doc;
      doc["sensor_id"]     = SENSOR_ID;
      doc["temperatura_C"] = round(temperatura * 10.0) / 10.0;
      doc["umidade_pct"]   = round(umidade * 10.0) / 10.0;
      doc["tdp_C"]         = round(tdp * 10.0) / 10.0;
      doc["ITU"]           = round(itu * 10.0) / 10.0;
      doc["alerta"]        = zonaITU(itu);
      char payload[300]; serializeJson(doc, payload);
      mqttClient.publish(TOPIC_CLIMA, payload);
    }
  }
}
