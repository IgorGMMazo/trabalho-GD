# ================================================================
#  GÊMEO DIGITAL — GRANJA AVÍCOLA (pacote)
#
#  Gêmeo digital reativo de três eixos (luz, clima, gases) sobre um
#  ambiente físico compartilhado, com supervisor de conflitos de
#  atuadores guiado por bem-estar animal.
# ================================================================

from .config import Config, FAIXAS, FaixaVida, Limiares
from .environment import Ambiente, ComandosAtuadores, CondicoesExternas, calcular_itu, ponto_de_orvalho
from .sensors import SensorLux, SensorClima, SensorGas
from .controllers import LuzController, GasController, ClimaController
from .supervisor import Supervisor, Decisao
from .twin import GemeoDigital, MotorCenarios, CENARIOS

__all__ = [
    "Config", "FAIXAS", "FaixaVida", "Limiares",
    "Ambiente", "ComandosAtuadores", "CondicoesExternas", "calcular_itu", "ponto_de_orvalho",
    "SensorLux", "SensorClima", "SensorGas",
    "LuzController", "GasController", "ClimaController",
    "Supervisor", "Decisao",
    "GemeoDigital", "MotorCenarios", "CENARIOS",
]
