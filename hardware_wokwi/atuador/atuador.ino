// ============================================================
//  GÊMEO DIGITAL — MÓDULO ATUADOR  (referência do hardware Wokwi)
//  Projeto: https://wokwi.com/projects/466029783767796737
//  ESP32 DevKit V1 + LED dimerizável (GPIO5, PWM 8-bit @5kHz)
//
//  ASSINA → granja/atuador/dimmer/1
//  Réplica em atuador.py.
// ============================================================
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

const char* WIFI_SSID    = "Wokwi-GUEST";
const char* WIFI_PASSWORD = "";
const char* MQTT_BROKER  = "broker.hivemq.com";
const int   MQTT_PORT    = 1883;
const char* TOPIC_DIMMER = "granja/atuador/dimmer/1";
const char* ATUADOR_ID   = "1";

#define LED_PIN       5
#define PWM_FREQ      5000
#define PWM_RESOLUCAO 8
#define LUX_MAX_LAMPADA 15.0

WiFiClient   espClient;
PubSubClient mqttClient(espClient);

int dimmerParaPWM(float pct) {
  if (pct <= 0.0)   return 0;
  if (pct >= 100.0) return 255;
  return (int)((pct / 100.0) * 255.0);
}

void onMensagem(char* topic, byte* payload, unsigned int length) {
  String raw = "";
  for (unsigned int i = 0; i < length; i++) raw += (char)payload[i];
  StaticJsonDocument<200> doc;
  if (deserializeJson(doc, raw)) return;
  float dimmer_pct = doc["dimmer_pct"] | 0.0;
  float watts      = doc["watts"]      | 0.0;
  int pwm = dimmerParaPWM(dimmer_pct);
  ledcWrite(LED_PIN, pwm);
  String estado;
  if      (dimmer_pct == 0.0)  estado = "APAGADA";
  else if (dimmer_pct < 30.0)  estado = "FRACA";
  else if (dimmer_pct < 70.0)  estado = "MEDIA";
  else if (dimmer_pct < 100.0) estado = "FORTE";
  else                          estado = "MAXIMA";
  Serial.print("[LAMPADA] dimmer="); Serial.print(dimmer_pct);
  Serial.print("% pwm="); Serial.print(pwm);
  Serial.print(" estado="); Serial.println(estado);
}

void conectarWifi() {
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  int t = 0;
  while (WiFi.status() != WL_CONNECTED && t < 20) { delay(500); t++; }
}

void reconectarMQTT() {
  while (!mqttClient.connected()) {
    String clientId = "ESP32-Atuador-" + String(ATUADOR_ID) + "-" + String(random(0xFFFF), HEX);
    if (mqttClient.connect(clientId.c_str())) {
      mqttClient.subscribe(TOPIC_DIMMER);
    } else { delay(3000); }
  }
}

void setup() {
  Serial.begin(115200);
  ledcAttach(LED_PIN, PWM_FREQ, PWM_RESOLUCAO);
  ledcWrite(LED_PIN, 0);
  conectarWifi();
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setCallback(onMensagem);
}

void loop() {
  if (!mqttClient.connected()) reconectarMQTT();
  mqttClient.loop();
}
