# Sensor de Gases (NH₃) — ESP32 no Wokwi

Simula o sensor **MQ-135 / MQ-137** de amônia. Como o Wokwi não tem a peça
MQ-135, o sinal analógico é simulado por um **potenciômetro**.

## Como rodar no Wokwi

1. Acesse <https://wokwi.com> → **New Project** → **ESP32**.
2. Substitua o conteúdo de `sketch.ino` pelo arquivo desta pasta.
3. Abra a aba `diagram.json` e cole o conteúdo daqui (monta pot + 2 LEDs).
4. No painel **Library Manager** (ícone de cubo), adicione:
   - `PubSubClient`
   - `ArduinoJson`
   (ou deixe que o Wokwi resolva a partir do `#include`).
5. Clique em **▶ Play**.

## O que acontece

- O ESP32 conecta na rede **Wokwi-GUEST** (internet liberada pelo Wokwi).
- Conecta no broker `broker.hivemq.com:1883`.
- A cada 2 s lê o potenciômetro → converte para **0–50 ppm de NH₃** →
  publica em `granja/sensor/gas/1`.
- Recebe o comando do `gas_control.py` em `granja/atuador/exaustor/1`:
  - **LED ciano (EXAUSTOR):** brilho proporcional à potência do exaustor.
  - **LED vermelho (ALERTA):** acende quando NH₃ ≥ 25 ppm.

## Dois modos (no topo do sketch: `#define MODO_AUTO`)

- **`true` (AUTO, padrão):** o ESP32 gera o NH₃ sozinho (senoide 5↔30 ppm +
  ruído), igual ao `gas_sim.py`. Os LEDs animam sem você tocar em nada — bom
  para deixar rodando na tela.
- **`false` (MANUAL):** lê o **potenciômetro**. Você gira o knob e controla o
  nível de amônia na hora — bom para interagir com a banca.

## Na apresentação

Com `MODO_AUTO false`, **gire o potenciômetro** para simular o acúmulo de
amônia. Ao passar de ~25 ppm, o LED vermelho acende e o ciano vai a 100% —
demonstrando o **feedback loop** do gêmeo digital em tempo real.

## Pinagem

| ESP32 | Componente            |
|-------|-----------------------|
| 3V3   | Potenciômetro VCC     |
| GND   | Potenciômetro GND     |
| 34    | Potenciômetro SIG (ADC) |
| 25    | LED Exaustor (via R 220Ω) |
| 26    | LED Alerta  (via R 220Ω)  |
