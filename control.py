# ================================================================
#  GÊMEO DIGITAL — CONTROL.PY
#  Cérebro do sistema: recebe lux, calcula dimmer, publica comando
#
#  Tópicos MQTT:
#    SUBSCRIBE → granja/sensor/lux/+        (wildcard: N sensores)
#    PUBLISH   → granja/atuador/dimmer/{id}
#    PUBLISH   → granja/status/{id}         (para o dashboard)
#
#  Execução: python control.py
# ================================================================

from __future__ import annotations

import json
import logging
import time
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict

import paho.mqtt.client as mqtt

# ────────────────────────────────────────────────────────────────
#  Escolhendo periodo galinhas
# ────────────────────────────────────────────────────────────────
while True:
    print("Qual fase de vida os animais (Galinhas/Pintos) estão?\n1 - Chegada ( Primeiros 7 dias )\n2 - Crescimento ( 7 dias em diante )\n3 - Fase final ( Perto do abate)")
    faixa = int(input())
    if faixa == 1:
        alvo = 35
        alvo_min = 25
        alvo_max = 45
        break
    elif faixa == 2:
        alvo = 10
        alvo_min = 4
        alvo_max =  16
        break
    elif faixa == 3:
        alvo = 90
        alvo_min = 110
        alvo_max = 75
        break
    else:
        print("Coloque uns dos valores válidos ( 1, 2 ou 3)")  


# ────────────────────────────────────────────────────────────────
#  LOGGING
# ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("control")

# ────────────────────────────────────────────────────────────────
#  CONFIGURAÇÃO CENTRAL
# ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Config:
    # Broker
    broker: str        = "broker.hivemq.com"
    port: int          = 1883
    keepalive: int     = 60

    # Tópicos
    topic_sub: str     = "granja/sensor/lux/1"
    topic_dim: str     = "granja/atuador/dimmer/1"
    topic_status: str  = "granja/status/{id}"

    # Física da lâmpada (por sensor/zona)
    potencia_w: float  = 20.0       # Watts nominais da lâmpada
    lux_alvo: float    = alvo       # Recomendação Embrapa para frango de corte
    lux_min: float     = alvo_min        # Abaixo disso → lâmpada no máximo
    lux_max: float     = alvo_max      # Acima disso  → lâmpada apagada

    # Controle proporcional
    kp: float          = 2.5        # Ganho proporcional
    deadband: float    = 1.5        # ±1.5 lux → não age (evita oscilação)
    dimmer_min: float  = 0.0        # % mínimo do dimmer
    dimmer_max: float  = 100.0      # % máximo do dimmer
    dimmer_inicial: float = 50.0    # Estado inicial antes da 1ª leitura

    # Publicação
    publish_interval_s: float = 1.0  # Intervalo mínimo entre publicações


CFG = Config()

# ────────────────────────────────────────────────────────────────
#  ESTADO POR SENSOR
# ────────────────────────────────────────────────────────────────
@dataclass
class SensorState:
    sensor_id: str
    lux: float             = 0.0
    dimmer_pct: float      = CFG.dimmer_inicial
    watts: float           = 0.0
    status: str            = "AGUARDANDO"
    ultimo_update: str     = ""
    total_mensagens: int   = 0


# ────────────────────────────────────────────────────────────────
#  LÓGICA DE CONTROLE — CONTROLADOR PROPORCIONAL COM DEADBAND
# ────────────────────────────────────────────────────────────────
def calcular_dimmer(lux_medido: float, dimmer_atual: float) -> tuple[float, str]:
    """
    Controlador P com deadband.

    Lógica:
      - Se dentro do deadband → mantém dimmer atual (sem oscilação)
      - Se abaixo do alvo    → aumenta dimmer proporcionalmente
      - Se acima do alvo     → reduz dimmer proporcionalmente
      - Clamp em [dimmer_min, dimmer_max]

    Retorna: (novo_dimmer_pct, status_string)
    """
    erro = CFG.lux_alvo - lux_medido

    # Deadband: erro pequeno demais → não mexe
    if abs(erro) <= CFG.deadband:
        return dimmer_atual, "ESTAVEL"

    # Ajuste proporcional
    ajuste = CFG.kp * erro
    novo_dimmer = dimmer_atual + ajuste
    novo_dimmer = max(CFG.dimmer_min, min(CFG.dimmer_max, novo_dimmer))

    # Status semântico
    if lux_medido < CFG.lux_min:
        status = "bem_abaixo_do_esperado"
    elif lux_medido < CFG.lux_alvo - CFG.deadband:
        status = "abaixo_do_esperado"
    elif lux_medido > CFG.lux_max:
        status = "bem_acima_do_esperado"
    elif lux_medido > CFG.lux_alvo + CFG.deadband:
        status = "acima_do_esperado"
    else:
        status = "estado_ideal"

    return round(novo_dimmer, 2), status


def calcular_watts(dimmer_pct: float) -> float:
    """Consumo real = percentual do dimmer × potência nominal."""
    return round((dimmer_pct / 100.0) * CFG.potencia_w, 3)


# ────────────────────────────────────────────────────────────────
#  CONTROLADOR MQTT
# ────────────────────────────────────────────────────────────────
class GranjaController:
    def __init__(self) -> None:
        self._estados: Dict[str, SensorState] = {}
        self._lock = threading.Lock()

        self._client = mqtt.Client(
            client_id=f"controle-granja-{int(time.time())}",
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message    = self._on_message

    # ── Callbacks MQTT ───────────────────────────────────────────

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code == 0:
            log.info("Broker conectado — assinando '%s'", CFG.topic_sub)
            client.subscribe(CFG.topic_sub, qos=1)
        else:
            log.error("Falha na conexão: código %s", reason_code)

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties) -> None:
        log.warning("Desconectado (código %s) — reconectando...", reason_code)

    def _on_message(self, client, userdata, msg: mqtt.MQTTMessage) -> None:
        """
        Processa mensagem recebida.

        Tópico esperado: granja/sensor/lux/{sensor_id}
        Payload esperado (JSON):
          { "lux": 18.4, "timestamp": "..." }
          ou apenas um float puro como string "18.4"
        """
        try:
            # Extrai sensor_id do tópico  (última parte)
            sensor_id = msg.topic.split("/")[-1]

            # Decodifica payload — aceita JSON ou float puro
            raw = msg.payload.decode("utf-8").strip()
            try:
                data = json.loads(raw)
                lux = float(data.get("lux", data) if isinstance(data, dict) else data)
            except (json.JSONDecodeError, ValueError):
                lux = float(raw)

            if lux < 0:
                log.warning("[%s] Lux negativo ignorado: %.2f", sensor_id, lux)
                return

            self._processar(sensor_id, lux)

        except Exception as exc:
            log.error("Erro ao processar mensagem '%s': %s", msg.topic, exc)

    # ── Processamento ────────────────────────────────────────────

    def _processar(self, sensor_id: str, lux: float) -> None:
        with self._lock:
            # Inicializa estado se sensor novo
            if sensor_id not in self._estados:
                self._estados[sensor_id] = SensorState(sensor_id=sensor_id)
                log.info("Novo sensor detectado: '%s'", sensor_id)

            estado = self._estados[sensor_id]

            # Calcula novo dimmer e status
            novo_dimmer, status = calcular_dimmer(lux, estado.dimmer_pct)
            watts = calcular_watts(novo_dimmer)

            # Atualiza estado
            estado.lux            = round(lux, 2)
            estado.dimmer_pct     = novo_dimmer
            estado.watts          = watts
            estado.status         = status
            estado.ultimo_update  = datetime.now().isoformat(timespec="seconds")
            estado.total_mensagens += 1

        # Publica fora do lock (I/O não bloqueia estado)
        self._publicar(sensor_id, novo_dimmer, status, lux, watts)

        log.info(
            "[%s] lux=%.1f → dimmer=%.1f%% (%s) | %.2fW",
            sensor_id, lux, novo_dimmer, status, watts,
        )

    def _publicar(
        self,
        sensor_id: str,
        dimmer_pct: float,
        status: str,
        lux: float,
        watts: float,
    ) -> None:
        # ── Comando para o atuador (lâmpada) ────────────────────
        cmd_topic = CFG.topic_dim.format(id=sensor_id)
        cmd_payload = json.dumps({
            "sensor_id":  sensor_id,
            "dimmer_pct": dimmer_pct,
            "watts":      watts,
            "timestamp":  datetime.now().isoformat(timespec="seconds"),
        })
        self._client.publish(cmd_topic, cmd_payload, qos=1)

        # ── Status completo para o dashboard ────────────────────
        status_topic = CFG.topic_status.format(id=sensor_id)
        status_payload = json.dumps({
            "sensor_id":  sensor_id,
            "lux":        lux,
            "lux_alvo":   CFG.lux_alvo,
            "dimmer_pct": dimmer_pct,
            "watts":      watts,
            "status":     status,
            "timestamp":  datetime.now().isoformat(timespec="seconds"),
        })
        self._client.publish(status_topic, status_payload, qos=1)

    # ── Execução ─────────────────────────────────────────────────

    def run(self) -> None:
        log.info("Iniciando controlador — broker: %s:%d", CFG.broker, CFG.port)
        self._client.connect_async(CFG.broker, CFG.port, keepalive=CFG.keepalive)
        self._client.loop_start()  # thread interna do paho

        try:
            while True:
                time.sleep(5)
                with self._lock:
                    n = len(self._estados)
                if n:
                    log.info("Sensores ativos: %d", n)
        except KeyboardInterrupt:
            log.info("Encerrando...")
        finally:
            self._client.loop_stop()
            self._client.disconnect()


# ────────────────────────────────────────────────────────────────
#  ENTRYPOINT
# ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    GranjaController().run()