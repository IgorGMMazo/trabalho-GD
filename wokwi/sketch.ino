/* ================================================================
 *  GÊMEO DIGITAL — SENSOR DE GASES (NH3) NO ESP32 / WOKWI
 *  ----------------------------------------------------------------
 *  Sensor real de referência: MQ-135 / MQ-137 (amônia).
 *  No Wokwi o MQ-135 não existe como peça, então o sinal analógico
 *  é SIMULADO por um potenciômetro:
 *      ADC (0..4095)  ->  NH3 (0..50 ppm)
 *  Gire o potenciômetro durante a apresentação para simular o
 *  acúmulo de amônia e ver o exaustor reagir em tempo real.
 *
 *  Fluxo:
 *    1) Lê o ADC do potenciômetro  (simula a saída do MQ-135)
 *    2) Converte para ppm de NH3
 *    3) Publica via MQTT  ->  granja/sensor/gas/1
 *    4) Recebe o comando do cérebro (gas_control.py)
 *         <-  granja/atuador/exaustor/1
 *    5) Aciona o LED do EXAUSTOR (brilho = % de potência) e o
 *       LED de ALERTA (vermelho) quando NH3 >= 25 ppm.
 *
 *  Bibliotecas (Wokwi -> Library Manager / libraries.txt):
 *    - PubSubClient (Nick O'Leary)
 *    - ArduinoJson  (Benoit Blanchon)
 * ================================================================ */

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ── Identidade deste sensor ──────────────────────────────────────
const char* SENSOR_ID = "1";

// ── Rede (Wokwi fornece internet pela rede "Wokwi-GUEST") ────────
const char* WIFI_SSID = "Wokwi-GUEST";
const char* WIFI_PASS = "";

// ── Broker MQTT (o MESMO do control.py / gas_control.py) ─────────
const char* MQTT_BROKER = "broker.hivemq.com";
const int   MQTT_PORT   = 1883;

// ── Tópicos ──────────────────────────────────────────────────────
const char* TOPIC_PUB_GAS   = "granja/sensor/gas/1";
const char* TOPIC_SUB_EXAUS = "granja/atuador/exaustor/1";

// ── Pinos ────────────────────────────────────────────────────────
const int PIN_POT      = 34;   // Potenciômetro = saída analógica do "MQ-135"
const int PIN_EXAUSTOR = 25;   // LED branco/azul: brilho = potência do exaustor
const int PIN_ALERTA   = 26;   // LED vermelho: alerta de amônia crítica

// ── PWM (LEDC) p/ controlar brilho do LED do exaustor ────────────
const int LEDC_CANAL = 0;
const int LEDC_FREQ  = 5000;
const int LEDC_RES   = 8;      // 8 bits -> 0..255

// Compatibilidade: o core ESP32 3.x trocou a API do LEDC.
//  - 3.x:  ledcAttach(pino, freq, res)   e  ledcWrite(pino, duty)
//  - 2.x:  ledcSetup(canal,...) + ledcAttachPin(pino,canal) + ledcWrite(canal,duty)
void pwmSetup(int pino) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcAttach(pino, LEDC_FREQ, LEDC_RES);
#else
  ledcSetup(LEDC_CANAL, LEDC_FREQ, LEDC_RES);
  ledcAttachPin(pino, LEDC_CANAL);
#endif
}

void pwmWrite(int pino, int duty) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcWrite(pino, duty);
#else
  ledcWrite(LEDC_CANAL, duty);
#endif
}

// ── Escala de conversão ADC -> ppm ───────────────────────────────
const float PPM_MAX = 50.0;    // 4095 do ADC equivale a 50 ppm de NH3

// ── Modo de operação do sensor ───────────────────────────────────
//   true  -> AUTO: o ESP32 gera o NH3 sozinho (senoide + ruído),
//            igual ao gas_sim.py. Os LEDs animam sem girar o pot.
//   false -> MANUAL: lê o potenciômetro (você controla girando o knob).
#define MODO_AUTO true

// ── Intervalo de publicação ──────────────────────────────────────
const unsigned long INTERVALO_MS = 2000;
unsigned long ultimoEnvio = 0;

WiFiClient   wifiClient;
PubSubClient mqtt(wifiClient);

// ─────────────────────────────────────────────────────────────────
//  Conexão WiFi
// ─────────────────────────────────────────────────────────────────
void conectarWiFi() {
  Serial.print("Conectando ao WiFi");
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(250);
    Serial.print(".");
  }
  Serial.printf("\nWiFi OK — IP: %s\n", WiFi.localIP().toString().c_str());
}

// ─────────────────────────────────────────────────────────────────
//  Callback: recebe o comando do exaustor vindo do gas_control.py
//  Payload: {"exaustor_pct": 72.5, "alerta": true, ...}
// ─────────────────────────────────────────────────────────────────
void aoReceberComando(char* topic, byte* payload, unsigned int len) {
  StaticJsonDocument<256> doc;
  if (deserializeJson(doc, payload, len)) {
    Serial.println("[MQTT] Comando inválido (JSON)");
    return;
  }

  float exaustorPct = doc["exaustor_pct"] | 0.0;
  bool  alerta      = doc["alerta"] | false;

  // Brilho do LED do exaustor proporcional à potência (0..100% -> 0..255)
  int duty = (int)(exaustorPct / 100.0 * 255.0);
  duty = constrain(duty, 0, 255);
  pwmWrite(PIN_EXAUSTOR, duty);

  // LED de alerta
  digitalWrite(PIN_ALERTA, alerta ? HIGH : LOW);

  Serial.printf("[CMD] exaustor=%.0f%%  alerta=%s\n",
                exaustorPct, alerta ? "SIM" : "nao");
}

// ─────────────────────────────────────────────────────────────────
//  Reconexão MQTT
// ─────────────────────────────────────────────────────────────────
void conectarMQTT() {
  while (!mqtt.connected()) {
    String clientId = "esp32-gas-" + String(SENSOR_ID) + "-" + String(random(0xffff), HEX);
    Serial.printf("Conectando ao MQTT (%s)...", MQTT_BROKER);
    if (mqtt.connect(clientId.c_str())) {
      Serial.println(" OK");
      mqtt.subscribe(TOPIC_SUB_EXAUS);
      Serial.printf("Inscrito em: %s\n", TOPIC_SUB_EXAUS);
    } else {
      Serial.printf(" falhou (rc=%d). Nova tentativa em 2s\n", mqtt.state());
      delay(2000);
    }
  }
}

// ─────────────────────────────────────────────────────────────────
//  Leitura do sensor (potenciômetro -> ppm)
// ─────────────────────────────────────────────────────────────────
float lerNH3() {
  int adc = analogRead(PIN_POT);           // 0..4095
  float ppm = (adc / 4095.0) * PPM_MAX;    // 0..50 ppm
  return ppm;
}

// Gera NH3 sintético: senoide 5..30 ppm (período ~40s) + ruído leve.
// Mesma lógica do gas_sim.py, mas rodando dentro do ESP32.
float lerNH3Auto() {
  float t = millis() / 1000.0;
  float base  = 17.5 + 12.5 * sin(t * 0.16);   // oscila ~5 <-> 30 ppm
  float ruido = random(-50, 51) / 100.0;       // +/- 0.5 ppm (imperfeição)
  float ppm = base + ruido;
  return ppm < 0 ? 0 : ppm;
}

// ─────────────────────────────────────────────────────────────────
//  Publica leitura
// ─────────────────────────────────────────────────────────────────
void publicarLeitura(float ppm, int adc) {
  StaticJsonDocument<192> doc;
  doc["sensor_id"] = SENSOR_ID;
  doc["ppm"]       = round(ppm * 100) / 100.0;
  doc["raw_adc"]   = adc;
  doc["unidade"]   = "ppm_NH3";

  char buffer[192];
  size_t n = serializeJson(doc, buffer);
  mqtt.publish(TOPIC_PUB_GAS, buffer, n);

  Serial.printf("[PUB] %s  ->  NH3=%.1f ppm (adc=%d)\n", TOPIC_PUB_GAS, ppm, adc);
}

// ─────────────────────────────────────────────────────────────────
//  Setup
// ─────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(200);

  pinMode(PIN_ALERTA, OUTPUT);
  digitalWrite(PIN_ALERTA, LOW);

  pwmSetup(PIN_EXAUSTOR);
  pwmWrite(PIN_EXAUSTOR, 0);

  conectarWiFi();
  mqtt.setServer(MQTT_BROKER, MQTT_PORT);
  mqtt.setCallback(aoReceberComando);

  Serial.println("Sensor de GASES (NH3) iniciado.");
}

// ─────────────────────────────────────────────────────────────────
//  Loop
// ─────────────────────────────────────────────────────────────────
void loop() {
  if (!mqtt.connected()) conectarMQTT();
  mqtt.loop();

  unsigned long agora = millis();
  if (agora - ultimoEnvio >= INTERVALO_MS) {
    ultimoEnvio = agora;
    float ppm;
    int adc;
    if (MODO_AUTO) {
      ppm = lerNH3Auto();    // ESP32 gera os dados sozinho
      adc = -1;              // sem leitura física
    } else {
      adc = analogRead(PIN_POT);
      ppm = (adc / 4095.0) * PPM_MAX;
    }
    publicarLeitura(ppm, adc);
  }
}
