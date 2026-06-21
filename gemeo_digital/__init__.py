"""Gêmeo Digital — ecossistema interno de controle de iluminação de granja.

Componentes:
    config.Config        — parâmetros e faixas de vida das aves
    bus.LocalBus/MqttBus — transporte por tópicos (interno ou MQTT real)
    controller           — cérebro (controle P com deadband)
    sensor.SensorBH1750  — simulação do ESP32 + BH1750
    atuador.AtuadorLED   — simulação do ESP32 + LED dimerizável
"""

from .config import Config, FAIXAS, FaixaVida
from .bus import Bus, LocalBus, MqttBus, topic_matches
from .controller import GranjaController, calcular_dimmer, calcular_watts, SensorState
from .sensor import SensorBH1750
from .atuador import AtuadorLED, dimmer_para_pwm, estado_lampada, EstadoAtuador

__all__ = [
    "Config", "FAIXAS", "FaixaVida",
    "Bus", "LocalBus", "MqttBus", "topic_matches",
    "GranjaController", "calcular_dimmer", "calcular_watts", "SensorState",
    "SensorBH1750",
    "AtuadorLED", "dimmer_para_pwm", "estado_lampada", "EstadoAtuador",
]
