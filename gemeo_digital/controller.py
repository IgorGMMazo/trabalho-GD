# ================================================================
#  GÊMEO DIGITAL — CONTROLADOR
#  Cérebro do sistema: recebe lux, calcula dimmer, publica comando.
#
#  Lógica de controle idêntica ao control.py de referência
#  (controlador P com deadband), porém desacoplada do transporte
#  através da camada Bus.
#
#    ASSINA   → granja/sensor/lux/+
#    PUBLICA  → granja/atuador/dimmer/{id}
#    PUBLICA  → granja/status/{id}
# ================================================================

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Tuple

from .bus import Bus
from .config import Config

log = logging.getLogger("control")


# ────────────────────────────────────────────────────────────────
#  ESTADO POR SENSOR
# ────────────────────────────────────────────────────────────────
@dataclass
class SensorState:
    sensor_id: str
    lux: float = 0.0
    dimmer_pct: float = 50.0
    watts: float = 0.0
    status: str = "AGUARDANDO"
    ultimo_update: str = ""
    total_mensagens: int = 0


# ────────────────────────────────────────────────────────────────
#  LÓGICA DE CONTROLE — P COM DEADBAND (igual ao control.py)
# ────────────────────────────────────────────────────────────────
def calcular_dimmer(lux_medido: float, dimmer_atual: float, cfg: Config) -> Tuple[float, str]:
    erro = cfg.lux_alvo - lux_medido

    if abs(erro) <= cfg.deadband:
        return dimmer_atual, "ESTAVEL"

    ajuste = cfg.kp * erro
    novo_dimmer = dimmer_atual + ajuste
    novo_dimmer = max(cfg.dimmer_min, min(cfg.dimmer_max, novo_dimmer))

    if lux_medido < cfg.lux_min:
        status = "bem_abaixo_do_esperado"
    elif lux_medido < cfg.lux_alvo - cfg.deadband:
        status = "abaixo_do_esperado"
    elif lux_medido > cfg.lux_max:
        status = "bem_acima_do_esperado"
    elif lux_medido > cfg.lux_alvo + cfg.deadband:
        status = "acima_do_esperado"
    else:
        status = "estado_ideal"

    return round(novo_dimmer, 2), status


def calcular_watts(dimmer_pct: float, cfg: Config) -> float:
    return round((dimmer_pct / 100.0) * cfg.potencia_w, 3)


# ────────────────────────────────────────────────────────────────
#  CONTROLADOR
# ────────────────────────────────────────────────────────────────
class GranjaController:
    def __init__(self, bus: Bus, cfg: Config) -> None:
        self._bus = bus
        self._cfg = cfg
        self._estados: Dict[str, SensorState] = {}
        self._lock = threading.Lock()

    def start(self) -> None:
        self._bus.subscribe(self._cfg.topic_sub, self._on_message)
        log.info("Controlador ativo — assinando '%s'", self._cfg.topic_sub)

    @property
    def estados(self) -> Dict[str, SensorState]:
        return self._estados

    # ── Recepção ─────────────────────────────────────────────────
    def _on_message(self, topic: str, payload: str) -> None:
        try:
            sensor_id = topic.split("/")[-1]
            raw = payload.strip()
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
            log.error("Erro ao processar mensagem '%s': %s", topic, exc)

    # ── Processamento ────────────────────────────────────────────
    def _processar(self, sensor_id: str, lux: float) -> None:
        with self._lock:
            if sensor_id not in self._estados:
                self._estados[sensor_id] = SensorState(
                    sensor_id=sensor_id, dimmer_pct=self._cfg.dimmer_inicial
                )
                log.info("Novo sensor detectado: '%s'", sensor_id)

            estado = self._estados[sensor_id]
            novo_dimmer, status = calcular_dimmer(lux, estado.dimmer_pct, self._cfg)
            watts = calcular_watts(novo_dimmer, self._cfg)

            estado.lux = round(lux, 2)
            estado.dimmer_pct = novo_dimmer
            estado.watts = watts
            estado.status = status
            estado.ultimo_update = datetime.now().isoformat(timespec="seconds")
            estado.total_mensagens += 1

        self._publicar(sensor_id, novo_dimmer, status, lux, watts)
        log.info("[%s] lux=%.1f → dimmer=%.1f%% (%s) | %.2fW",
                 sensor_id, lux, novo_dimmer, status, watts)

    def _publicar(self, sensor_id: str, dimmer_pct: float, status: str,
                  lux: float, watts: float) -> None:
        cmd_topic = self._cfg.topic_dim.format(id=sensor_id)
        self._bus.publish(cmd_topic, json.dumps({
            "sensor_id": sensor_id,
            "dimmer_pct": dimmer_pct,
            "watts": watts,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }))

        status_topic = self._cfg.topic_status.format(id=sensor_id)
        self._bus.publish(status_topic, json.dumps({
            "sensor_id": sensor_id,
            "lux": lux,
            "lux_alvo": self._cfg.lux_alvo,
            "dimmer_pct": dimmer_pct,
            "watts": watts,
            "status": status,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }))
