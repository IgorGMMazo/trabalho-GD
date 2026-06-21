// ============================================================
//  GÊMEO DIGITAL — MÓDULO ATUADOR (referência do hardware Wokwi)
//  Projeto Wokwi: 466273382801532929
//  Microcontrolador : ESP32 DevKit V1
//
//  O diagrama deste projeto (diagram.json) já traz, além da lâmpada:
//    • LED amarelo (D5)  — lâmpada / aquecedor (PWM)
//    • Servo      (D13)  — cortina de ventilação do eixo CLIMA
//    • LED vermelho(D12) — alerta de condição crítica
//
//  O firmware ABAIXO implementa o dimmer da lâmpada (assina o tópico
//  granja/atuador/dimmer/1). Os atuadores de clima (aquecedor, cortina
//  servo e alerta) estão modelados no gêmeo digital em Python —
//  gemeo_digital/supervisor.py + gemeo_digital/twin.py — que é onde a
//  arbitragem de conflitos entre eixos acontece. Este .ino fica aqui
//  como referência do hardware; estendê-lo para o servo/aquecedor é
//  trabalho direto (assinar granja/atuador/clima/1).
// ============================================================

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

const char* WIFI_SSID     = "Wokwi-GUEST";
const char* WIFI_PASSWORD = "";

const char* MQTT_BROKER   = "broker.hivemq.com";
const int   MQTT_PORT     = 1883;
const char* TOPIC_DIMMER  = "granja/atuador/dimmer/1";

const char* ATUADOR_ID = "1";

#define LED_PIN         5
#define PWM_FREQ        5000
#define PWM_RESOLUCAO   8
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
  int pwm = dimmerParaPWM(dimmer_pct);
  ledcWrite(LED_PIN, pwm);

  String estado;
  if      (dimmer_pct == 0.0)  estado = "APAGADA";
  else if (dimmer_pct < 30.0)  estado = "FRACA";
  else if (dimmer_pct < 70.0)  estado = "MEDIA";
  else if (dimmer_pct < 100.0) estado = "FORTE";
  else                          estado = "MAXIMA";
  Serial.printf("[LAMPADA] dimmer=%.0f%% pwm=%d estado=%s\n", dimmer_pct, pwm, estado.c_str());
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
