# ================================================================
#  GÊMEO DIGITAL — ATUADOR / LÂMPADA (simulação do ESP32)
#
#  Réplica em Python do firmware do projeto Wokwi:
#    466029783767796737
#
#  Recebe o comando de dimmer, converte para PWM 8-bit (0–255) com
#  a mesma função do firmware e classifica o estado da lâmpada.
#
#    ASSINA → granja/atuador/dimmer/{id}
# ================================================================

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from .bus import Bus
from .config import Config

log = logging.getLogger("atuador")


def dimmer_para_pwm(pct: float) -> int:
    """Mesma conversão do firmware (dimmerParaPWM)."""
    if pct <= 0.0:
        return 0
    if pct >= 100.0:
        return 255
    return int((pct / 100.0) * 255.0)


def estado_lampada(pct: float) -> str:
    """Faixas idênticas ao firmware do atuador."""
    if pct == 0.0:
        return "APAGADA"
    if pct < 30.0:
        return "FRACA"
    if pct < 70.0:
        return "MEDIA"
    if pct < 100.0:
        return "FORTE"
    return "MAXIMA"


@dataclass
class EstadoAtuador:
    dimmer_pct: float = 0.0
    pwm: int = 0
    watts: float = 0.0
    lux_contribuicao: float = 0.0
    estado: str = "APAGADA"


class AtuadorLED:
    def __init__(self, bus: Bus, cfg: Config, atuador_id: str = "1") -> None:
        self._bus = bus
        self._cfg = cfg
        self.atuador_id = atuador_id
        self.estado = EstadoAtuador()
        self.topic_sub = self._cfg.topic_dim.format(id=atuador_id)

    def start(self) -> None:
        self._bus.subscribe(self.topic_sub, self._on_dimmer)
        log.info("Atuador '%s' ativo — assinando '%s'", self.atuador_id, self.topic_sub)

    def _on_dimmer(self, topic: str, payload: str) -> None:
        try:
            doc = json.loads(payload)
        except json.JSONDecodeError as exc:
            log.warning("JSON inválido: %s", exc)
            return

        dimmer_pct = float(doc.get("dimmer_pct", 0.0))
        watts = float(doc.get("watts", 0.0))

        pwm = dimmer_para_pwm(dimmer_pct)
        lux_contrib = (dimmer_pct / 100.0) * self._cfg.lux_max_lampada
        estado = estado_lampada(dimmer_pct)

        self.estado = EstadoAtuador(
            dimmer_pct=dimmer_pct, pwm=pwm, watts=watts,
            lux_contribuicao=round(lux_contrib, 2), estado=estado,
        )
        log.info("[LAMPADA] dimmer=%.1f%% pwm=%d/255 watts=%.2fW estado=%s",
                 dimmer_pct, pwm, watts, estado)
