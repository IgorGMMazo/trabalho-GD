# ================================================================
#  GÊMEO DIGITAL — SENSORES (réplica em Python do firmware ESP32)
#
#  Cada sensor LÊ o ambiente físico compartilhado e devolve uma
#  medição com ruído, exatamente como o hardware no Wokwi:
#
#     SensorLux   → BH1750  : lux_total = lux_natural + lux_lampada + ruído
#     SensorClima → DHT22   : temperatura, umidade, ITU, ponto de orvalho
#     SensorGas   → MQ-135  : NH3 em ppm (com ruído gaussiano)
#
#  Os sensores são "burros": só medem. Toda a decisão é dos
#  controladores e do supervisor.
# ================================================================

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Optional

from .config import Config
from .environment import Ambiente, calcular_itu, ponto_de_orvalho


def _ruido_gaussiano(rng: random.Random, sigma: float) -> float:
    """Box-Muller — mesma fórmula do firmware (sketch BH1750)."""
    if sigma <= 0:
        return 0.0
    u1 = max(rng.random(), 1e-9)
    u2 = rng.random()
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2) * sigma


# ────────────────────────────────────────────────────────────────
#  SENSOR DE LUZ — BH1750
# ────────────────────────────────────────────────────────────────
@dataclass
class LeituraLux:
    lux: float
    lux_natural: float
    lux_lampada: float


class SensorLux:
    def __init__(self, cfg: Config, sigma: float = 0.5, seed: Optional[int] = None) -> None:
        self.cfg = cfg
        self.sigma = sigma
        self.rng = random.Random(seed)

    def ler(self, amb: Ambiente, lampada_frac: float) -> LeituraLux:
        lux_lampada = lampada_frac * self.cfg.ganhos.lux_max_lampada
        lux_total = amb.lux_nat + lux_lampada + _ruido_gaussiano(self.rng, self.sigma)
        return LeituraLux(
            lux=max(0.0, round(lux_total, 2)),
            lux_natural=round(amb.lux_nat, 2),
            lux_lampada=round(lux_lampada, 2),
        )


# ────────────────────────────────────────────────────────────────
#  SENSOR DE CLIMA — DHT22
# ────────────────────────────────────────────────────────────────
@dataclass
class LeituraClima:
    temp_C: float
    umid_pct: float
    tpo_C: float          # ponto de orvalho
    itu: float
    zona: str             # conforto | alerta | critico


class SensorClima:
    def __init__(self, cfg: Config, sigma_temp: float = 0.2,
                 sigma_umid: float = 0.8, seed: Optional[int] = None) -> None:
        self.cfg = cfg
        self.sigma_temp = sigma_temp
        self.sigma_umid = sigma_umid
        self.rng = random.Random(seed)

    def _zona(self, itu: float) -> str:
        lim = self.cfg.limiares
        if itu < lim.itu_conforto:
            return "conforto"
        if itu < lim.itu_critico:
            return "alerta"
        return "critico"

    def ler(self, amb: Ambiente) -> LeituraClima:
        temp = amb.temp_C + _ruido_gaussiano(self.rng, self.sigma_temp)
        umid = max(1.0, min(100.0, amb.umid_pct + _ruido_gaussiano(self.rng, self.sigma_umid)))
        tpo = ponto_de_orvalho(temp, umid)
        itu = calcular_itu(temp, umid)
        return LeituraClima(
            temp_C=round(temp, 1),
            umid_pct=round(umid, 1),
            tpo_C=round(tpo, 1),
            itu=round(itu, 1),
            zona=self._zona(itu),
        )


# ────────────────────────────────────────────────────────────────
#  SENSOR DE GASES — MQ-135 (NH3)
# ────────────────────────────────────────────────────────────────
@dataclass
class LeituraGas:
    ppm: float
    estado: str           # bom | elevado | atencao | critico


class SensorGas:
    def __init__(self, cfg: Config, sigma: float = 0.5, seed: Optional[int] = None) -> None:
        self.cfg = cfg
        self.sigma = sigma
        self.rng = random.Random(seed)

    def _estado(self, ppm: float) -> str:
        lim = self.cfg.limiares
        if ppm < lim.nh3_alvo:
            return "bom"
        if ppm < lim.nh3_atencao:
            return "elevado"
        if ppm < lim.nh3_critico:
            return "atencao"
        return "critico"

    def ler(self, amb: Ambiente) -> LeituraGas:
        ppm = max(0.0, amb.nh3_ppm + _ruido_gaussiano(self.rng, self.sigma))
        return LeituraGas(ppm=round(ppm, 2), estado=self._estado(ppm))
