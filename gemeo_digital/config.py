# ================================================================
#  GÊMEO DIGITAL — CONFIGURAÇÃO CENTRAL
#
#  Concentra todos os parâmetros do ecossistema (broker, tópicos,
#  física da lâmpada, ganhos do controlador) e as faixas de vida
#  das aves — exatamente como no control.py de referência.
# ================================================================

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


# ────────────────────────────────────────────────────────────────
#  FAIXAS DE VIDA (presets do control.py de referência)
#
#  OBS.: a fase 3 mantém os valores originais do control.py
#  (min=110, max=75 — invertidos no arquivo de referência).
#  Preservamos para fidelidade; o controle usa apenas `alvo`.
# ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class FaixaVida:
    nome: str
    alvo: float
    alvo_min: float
    alvo_max: float


FAIXAS: Dict[int, FaixaVida] = {
    1: FaixaVida("Chegada (primeiros 7 dias)", alvo=35.0, alvo_min=25.0, alvo_max=45.0),
    2: FaixaVida("Crescimento (7 dias em diante)", alvo=10.0, alvo_min=4.0, alvo_max=16.0),
    3: FaixaVida("Fase final (perto do abate)", alvo=90.0, alvo_min=110.0, alvo_max=75.0),
}


# ────────────────────────────────────────────────────────────────
#  CONFIGURAÇÃO DO CONTROLADOR
# ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Config:
    # Broker (usado apenas pelo MqttBus)
    broker: str = "broker.hivemq.com"
    port: int = 1883
    keepalive: int = 60

    # Tópicos MQTT (idênticos aos do hardware Wokwi)
    topic_sub: str = "granja/sensor/lux/+"      # wildcard: N sensores
    topic_dim: str = "granja/atuador/dimmer/{id}"
    topic_status: str = "granja/status/{id}"

    # Física da lâmpada (por zona)
    potencia_w: float = 20.0          # Watts nominais
    lux_max_lampada: float = 15.0     # Lux entregues a 100% (igual ao firmware)

    # Alvos de iluminância (preenchidos pela faixa de vida)
    lux_alvo: float = 10.0
    lux_min: float = 4.0
    lux_max: float = 16.0

    # Controlador proporcional com deadband
    kp: float = 2.5
    deadband: float = 1.5
    dimmer_min: float = 0.0
    dimmer_max: float = 100.0
    dimmer_inicial: float = 50.0

    def com_faixa(self, faixa: int) -> "Config":
        """Devolve uma cópia com os alvos da faixa de vida escolhida."""
        f = FAIXAS[faixa]
        return Config(
            broker=self.broker, port=self.port, keepalive=self.keepalive,
            topic_sub=self.topic_sub, topic_dim=self.topic_dim, topic_status=self.topic_status,
            potencia_w=self.potencia_w, lux_max_lampada=self.lux_max_lampada,
            lux_alvo=f.alvo, lux_min=f.alvo_min, lux_max=f.alvo_max,
            kp=self.kp, deadband=self.deadband,
            dimmer_min=self.dimmer_min, dimmer_max=self.dimmer_max,
            dimmer_inicial=self.dimmer_inicial,
        )
