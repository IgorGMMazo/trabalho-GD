# ================================================================
#  GÊMEO DIGITAL — SENSOR BH1750 (simulação do ESP32)
#
#  Réplica em Python do firmware do projeto Wokwi:
#    466033186398196737
#
#  Modelo físico (idêntico ao sketch):
#    lux_total = lux_natural + lux_lampada + ruído gaussiano(σ=0.5)
#
#    lux_natural → luz ambiente (no Wokwi vinha do slider do BH1750;
#                  aqui é um valor configurável / função do tempo).
#    lux_lampada → (dimmer_pct / 100) * LUX_MAX_LAMPADA, atualizado
#                  pelo feedback do tópico de dimmer.
#
#    PUBLICA → granja/sensor/lux/{id}
#    ASSINA  → granja/atuador/dimmer/{id}
# ================================================================

from __future__ import annotations

import json
import logging
import math
import random
import threading
import time
from typing import Callable, Optional, Union

from .bus import Bus
from .config import Config

log = logging.getLogger("sensor")

# lux_natural pode ser um número fixo ou uma função do tempo (segundos)
LuxNatural = Union[float, Callable[[float], float]]


class SensorBH1750:
    def __init__(self, bus: Bus, cfg: Config, sensor_id: str = "1",
                 lux_natural: LuxNatural = 2.0,
                 noise_sigma: float = 0.5,
                 seed: Optional[int] = None) -> None:
        self._bus = bus
        self._cfg = cfg
        self.sensor_id = sensor_id
        self._lux_natural = lux_natural
        self._noise_sigma = noise_sigma
        self._rng = random.Random(seed)
        self._t0 = time.monotonic()

        # contribuição atual da lâmpada (atualizada pelo callback)
        self.lux_lampada = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self.topic_pub = f"granja/sensor/lux/{sensor_id}"
        self.topic_sub = self._cfg.topic_dim.format(id=sensor_id)

    # ── Ruído gaussiano (mesma fórmula Box-Muller do firmware) ────
    def _adicionar_ruido(self, lux: float) -> float:
        if self._noise_sigma <= 0:
            return lux
        u1 = max(self._rng.random(), 1e-9)
        u2 = self._rng.random()
        ruido = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
        return lux + ruido * self._noise_sigma

    def _ambiente(self, agora: float) -> float:
        if callable(self._lux_natural):
            return float(self._lux_natural(agora))
        return float(self._lux_natural)

    # ── Feedback do dimmer (igual ao onMensagem do sketch) ────────
    def _on_dimmer(self, topic: str, payload: str) -> None:
        try:
            doc = json.loads(payload)
            dimmer_pct = float(doc.get("dimmer_pct", 0.0))
        except (json.JSONDecodeError, ValueError, TypeError):
            return
        with self._lock:
            self.lux_lampada = (dimmer_pct / 100.0) * self._cfg.lux_max_lampada

    def start(self) -> None:
        self._bus.subscribe(self.topic_sub, self._on_dimmer)
        log.info("Sensor '%s' ativo — pub '%s' / sub '%s'",
                 self.sensor_id, self.topic_pub, self.topic_sub)

    # ── Uma leitura+publicação (chamável manualmente nos testes) ──
    def tick(self) -> dict:
        agora = time.monotonic() - self._t0
        lux_natural = self._ambiente(agora)
        with self._lock:
            lux_lampada = self.lux_lampada
        lux_total = lux_natural + lux_lampada
        lux = self._adicionar_ruido(lux_total)
        if lux < 0.0:
            lux = 0.0

        payload = {
            "sensor_id": self.sensor_id,
            "lux": round(lux, 2),
            "lux_natural": round(lux_natural, 2),
            "lux_lampada": round(lux_lampada, 2),
            "rssi": -55,
            "uptime_s": int(agora),
            "timestamp_ms": int(agora * 1000),
        }
        self._bus.publish(self.topic_pub, json.dumps(payload))
        log.info("[LUX] natural=%.2f lampada=%.2f total=%.2f",
                 lux_natural, lux_lampada, lux)
        return payload

    # ── Loop contínuo (publica a cada PUBLISH_MS, default 3 s) ────
    def run_forever(self, interval_s: float = 3.0) -> None:
        self.start()
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(interval_s)

    def start_thread(self, interval_s: float = 3.0) -> None:
        self._thread = threading.Thread(
            target=self.run_forever, args=(interval_s,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
