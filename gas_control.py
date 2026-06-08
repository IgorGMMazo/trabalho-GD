# ================================================================
#  GÊMEO DIGITAL — GAS_CONTROL.PY
#  Cérebro da vertente de GASES (Amônia / NH3)
#  Recebe ppm de NH3, calcula potência do exaustor, publica comando
#
#  Sensor real de referência: MQ-135 / MQ-137 (focado em NH3)
#  No Wokwi o sensor é simulado por um potenciômetro (ADC 0-4095 → ppm).
#
#  Tópicos MQTT:
#    SUBSCRIBE → granja/sensor/gas/+          (wildcard: N sensores)
#    PUBLISH   → granja/atuador/exaustor/{id}  (comando p/ o exaustor)
#    PUBLISH   → granja/status/gas/{id}        (estado completo p/ o dashboard)
#
#  Execução: python gas_control.py
# ================================================================

from __future__ import annotations

import json
import logging
import time
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Dict

import paho.mqtt.client as mqtt

# ────────────────────────────────────────────────────────────────
#  LOGGING
# ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("gas_control")

# ────────────────────────────────────────────────────────────────
#  CONFIGURAÇÃO CENTRAL
#
#  Limiares de NH3 (amônia) em ppm — base zootécnica:
#    < 10 ppm  → ambiente saudável (alvo)
#    10-20 ppm → desconforto, irritação ocular incipiente
#    20-25 ppm → atenção: queda de imunidade e ganho de peso
#    > 25 ppm  → CRÍTICO: lesões no trato respiratório (cf. fluxo)
# ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Config:
    # Broker (mesmo do control.py — sistema integrado)
    broker: str        = "broker.hivemq.com"
    port: int          = 1883
    keepalive: int     = 60

    # Tópicos
    topic_sub: str     = "granja/sensor/gas/+"
    topic_exaustor: str = "granja/atuador/exaustor/{id}"
    topic_status: str  = "granja/status/gas/{id}"

    # Limiares de amônia (ppm)
    nh3_alvo: float    = 10.0   # Abaixo disso → exaustor em repouso (ventilação mínima)
    nh3_atencao: float = 20.0   # Faixa de atenção
    nh3_critico: float = 25.0   # Limiar de lesão → exaustor máximo + ALERTA

    # Controle proporcional do exaustor (% de potência)
    kp: float          = 8.0    # Ganho: cada 1 ppm acima do alvo soma 8% no exaustor
    deadband: float    = 1.0    # ±1 ppm → não reage (evita liga/desliga do motor)
    base_ventilacao: float = 15.0   # Ventilação mínima permanente (renovação de ar)
    exaustor_min: float = 0.0
    exaustor_max: float = 100.0

    # Publicação
    publish_interval_s: float = 1.0


CFG = Config()

# ────────────────────────────────────────────────────────────────
#  ESTADO POR SENSOR
# ────────────────────────────────────────────────────────────────
@dataclass
class GasState:
    sensor_id: str
    ppm: float            = 0.0
    exaustor_pct: float   = CFG.base_ventilacao
    status: str           = "AGUARDANDO"
    alerta: bool          = False
    ultimo_update: str    = ""
    total_mensagens: int  = 0


# ────────────────────────────────────────────────────────────────
#  LÓGICA DE CONTROLE — PROPORCIONAL COM DEADBAND + BASE
# ────────────────────────────────────────────────────────────────
def calcular_exaustor(ppm: float, exaustor_atual: float) -> tuple[float, str, bool]:
    """
    Controlador P para o exaustor.

    Estratégia:
      - Sempre mantém uma ventilação base (renovação de ar).
      - Acima do alvo de NH3, aumenta a potência proporcionalmente ao excesso.
      - Acima do limiar crítico (25 ppm) → exaustor no máximo + ALERTA.
      - Deadband evita o motor ficar ligando/desligando por ruído do sensor.

    Retorna: (exaustor_pct, status_string, alerta_bool)
    """
    # Excesso de amônia acima do alvo saudável
    excesso = ppm - CFG.nh3_alvo

    # Ambiente saudável dentro do deadband → só ventilação base
    if excesso <= CFG.deadband:
        return CFG.base_ventilacao, "bom", False

    # Crítico: lesão respiratória — força máximo independente do proporcional
    if ppm >= CFG.nh3_critico:
        return CFG.exaustor_max, "critico", True

    # Faixa intermediária: proporcional ao excesso, somado à base
    alvo_exaustor = CFG.base_ventilacao + CFG.kp * excesso
    alvo_exaustor = max(CFG.exaustor_min, min(CFG.exaustor_max, alvo_exaustor))

    status = "atencao" if ppm >= CFG.nh3_atencao else "elevado"
    return round(alvo_exaustor, 2), status, False


# ────────────────────────────────────────────────────────────────
#  CONTROLADOR MQTT
# ────────────────────────────────────────────────────────────────
class GasController:
    def __init__(self) -> None:
        self._estados: Dict[str, GasState] = {}
        self._lock = threading.Lock()

        self._client = mqtt.Client(
            client_id=f"controle-gas-{int(time.time())}",
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
        Tópico esperado: granja/sensor/gas/{sensor_id}
        Payload aceito (JSON):  {"ppm": 18.4, "timestamp": "..."}
                  ou float puro: "18.4"
        """
        try:
            sensor_id = msg.topic.split("/")[-1]
            raw = msg.payload.decode("utf-8").strip()
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    ppm = float(data.get("ppm", data.get("nh3")))
                else:
                    ppm = float(data)
            except (json.JSONDecodeError, ValueError, TypeError):
                ppm = float(raw)

            if ppm < 0:
                log.warning("[%s] ppm negativo ignorado: %.2f", sensor_id, ppm)
                return

            self._processar(sensor_id, ppm)

        except Exception as exc:
            log.error("Erro ao processar mensagem '%s': %s", msg.topic, exc)

    # ── Processamento ────────────────────────────────────────────

    def _processar(self, sensor_id: str, ppm: float) -> None:
        with self._lock:
            if sensor_id not in self._estados:
                self._estados[sensor_id] = GasState(sensor_id=sensor_id)
                log.info("Novo sensor de gás detectado: '%s'", sensor_id)

            estado = self._estados[sensor_id]

            exaustor, status, alerta = calcular_exaustor(ppm, estado.exaustor_pct)

            estado.ppm             = round(ppm, 2)
            estado.exaustor_pct    = exaustor
            estado.status          = status
            estado.alerta          = alerta
            estado.ultimo_update   = datetime.now().isoformat(timespec="seconds")
            estado.total_mensagens += 1

        self._publicar(sensor_id, ppm, exaustor, status, alerta)

        flag = "  ⚠️  ALERTA" if alerta else ""
        log.info(
            "[%s] NH3=%.1f ppm → exaustor=%.0f%% (%s)%s",
            sensor_id, ppm, exaustor, status, flag,
        )

    def _publicar(
        self,
        sensor_id: str,
        ppm: float,
        exaustor_pct: float,
        status: str,
        alerta: bool,
    ) -> None:
        # ── Comando para o atuador (exaustor) ───────────────────
        cmd_topic = CFG.topic_exaustor.format(id=sensor_id)
        cmd_payload = json.dumps({
            "sensor_id":    sensor_id,
            "exaustor_pct": exaustor_pct,
            "alerta":       alerta,
            "timestamp":    datetime.now().isoformat(timespec="seconds"),
        })
        self._client.publish(cmd_topic, cmd_payload, qos=1)

        # ── Status completo para o dashboard ────────────────────
        status_topic = CFG.topic_status.format(id=sensor_id)
        status_payload = json.dumps({
            "sensor_id":    sensor_id,
            "ppm":          ppm,
            "nh3_alvo":     CFG.nh3_alvo,
            "nh3_critico":  CFG.nh3_critico,
            "exaustor_pct": exaustor_pct,
            "status":       status,
            "alerta":       alerta,
            "timestamp":    datetime.now().isoformat(timespec="seconds"),
        })
        self._client.publish(status_topic, status_payload, qos=1)

    # ── Execução ─────────────────────────────────────────────────

    def run(self) -> None:
        log.info("Iniciando controlador de GASES — broker: %s:%d", CFG.broker, CFG.port)
        log.info("Limiares NH3: alvo=%.0f | atenção=%.0f | crítico=%.0f ppm",
                 CFG.nh3_alvo, CFG.nh3_atencao, CFG.nh3_critico)
        self._client.connect_async(CFG.broker, CFG.port, keepalive=CFG.keepalive)
        self._client.loop_start()

        try:
            while True:
                time.sleep(5)
                with self._lock:
                    n = len(self._estados)
                if n:
                    log.info("Sensores de gás ativos: %d", n)
        except KeyboardInterrupt:
            log.info("Encerrando...")
        finally:
            self._client.loop_stop()
            self._client.disconnect()


# ────────────────────────────────────────────────────────────────
#  ENTRYPOINT
# ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    GasController().run()
