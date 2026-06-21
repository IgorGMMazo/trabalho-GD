# ================================================================
#  GÊMEO DIGITAL — GRANJA AVÍCOLA · CONFIGURAÇÃO CENTRAL
#
#  Reúne, num só lugar, TODOS os parâmetros do ecossistema dos três
#  eixos do gêmeo digital:
#
#     LUZ    — BH1750 (lux)          → lâmpada (dimmer)
#     CLIMA  — DHT22  (temp/umid/ITU)→ aquecedor + ventilação/cortina
#     GASES  — MQ-135 (NH3 ppm)      → exaustor
#
#  Os três eixos COMPARTILHAM o mesmo ambiente físico (galpão), por
#  isso os limiares zootécnicos, a física do ambiente e as faixas de
#  vida das aves ficam centralizados aqui.
#
#  Bases zootécnicas (ver README e slides para referências):
#    NH3:  < 10 ppm saudável | 20-25 limite | > 25 lesão respiratória
#    ITU:  < 74 conforto | 74-78 alerta | > 78 crítico (estresse térmico)
#    Temp: curva de aquecimento do pinto (32 °C no 1º dia → ~21 °C abate)
#    Lux:  alto na chegada (estimular consumo) → baixo no crescimento
# ================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


# ────────────────────────────────────────────────────────────────
#  FAIXAS DE VIDA DAS AVES
#
#  Cada fase tem alvos próprios de iluminância (lux) e de temperatura
#  (°C), além de um TETO DE VENTILAÇÃO SEGURO — o ponto central do
#  projeto: pintinhos na chegada não toleram exaustor a 100 %, senão
#  morrem de frio. O supervisor usa `vent_max_seguro` para nunca
#  resfriar as aves além do tolerável, mesmo com amônia alta.
# ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class FaixaVida:
    nome: str
    # Iluminância (lux)
    lux_alvo: float
    lux_min: float
    lux_max: float
    # Temperatura (°C) — banda de conforto da fase
    temp_alvo: float
    temp_min: float          # abaixo disso → aquecedor entra forte (risco de frio)
    temp_max: float          # acima disso  → resfriamento (risco de calor)
    # Teto de ventilação que o supervisor pode aplicar sem matar de frio
    vent_max_seguro: float   # % máximo do exaustor permitido nesta fase


# OBS.: a fase 3 do `control.py` original usava lux_alvo=90 com min/max
# invertidos (min=110, max=75). Isso é zootecnicamente incorreto — frangos
# de corte são mantidos em luz baixa (5-20 lux) na fase final para reduzir
# atividade e arranhões. Corrigimos para 20 lux e documentamos o achado
# (ver README › "Análise crítica" e slides).
FAIXAS: Dict[int, FaixaVida] = {
    1: FaixaVida(
        "Chegada (1-7 dias)",
        lux_alvo=35.0, lux_min=25.0, lux_max=45.0,
        temp_alvo=32.0, temp_min=30.0, temp_max=34.0,
        vent_max_seguro=35.0,     # pintinho é frágil ao frio
    ),
    2: FaixaVida(
        "Crescimento (7-28 dias)",
        lux_alvo=10.0, lux_min=4.0, lux_max=16.0,
        temp_alvo=26.0, temp_min=23.0, temp_max=29.0,
        vent_max_seguro=80.0,
    ),
    3: FaixaVida(
        "Final (perto do abate)",
        lux_alvo=20.0, lux_min=10.0, lux_max=30.0,   # corrigido (era 90)
        temp_alvo=21.0, temp_min=18.0, temp_max=25.0,
        vent_max_seguro=100.0,    # ave adulta tolera ventilação plena
    ),
}


# ────────────────────────────────────────────────────────────────
#  LIMIARES ZOOTÉCNICOS (independentes da fase)
# ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Limiares:
    # Amônia (ppm de NH3)
    nh3_alvo: float = 10.0
    nh3_atencao: float = 20.0
    nh3_critico: float = 25.0
    # Índice de Temperatura e Umidade (ITU / THI de Thom)
    itu_conforto: float = 74.0   # abaixo → conforto
    itu_critico: float = 78.0    # acima  → estresse térmico crítico


# ────────────────────────────────────────────────────────────────
#  GANHOS DOS CONTROLADORES (controle proporcional + deadband)
# ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class GanhosControle:
    # LUZ
    luz_kp: float = 2.5
    luz_deadband: float = 1.5
    lux_max_lampada: float = 15.0     # lux entregues pela lâmpada a 100 %
    lampada_potencia_w: float = 20.0
    # GASES
    gas_kp: float = 8.0               # cada 1 ppm acima do alvo → +8 % de exaustor
    gas_deadband: float = 1.0
    gas_base_ventilacao: float = 15.0 # renovação mínima de ar permanente
    # CLIMA
    clima_kp_frio: float = 9.0        # %/°C de aquecedor por °C abaixo da banda
    clima_kp_calor: float = 12.0      # %/°C de ventilação por °C acima da banda
    clima_deadband: float = 0.5


# ────────────────────────────────────────────────────────────────
#  FÍSICA DO AMBIENTE COMPARTILHADO (galpão)
#
#  Modelo de 1ª ordem (Newton + fontes). Em regime permanente:
#       temp = temp_ext + S/G
#  onde G é a condutância ao exterior (a ventilação AUMENTA G) e S são
#  as fontes internas de calor (metabolismo + aquecedor + lâmpada).
#  As constantes foram calibradas para dinâmica visível em dt ≈ 0,5 s.
# ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class FisicaAmbiente:
    # ── Temperatura ──────────────────────────────────────────────
    temp_fuga_base: float = 0.010     # G base (perda passiva p/ o exterior) [1/s]
    temp_ganho_vent: float = 0.050    # quanto a ventilação soma em G [1/s por unidade de fluxo]
    temp_fonte_metabolica: float = 0.10   # calor das aves [°C/s]
    temp_fonte_aquecedor: float = 0.16    # aquecedor a 100 % [°C/s]
    temp_fonte_lampada: float = 0.012     # CALOR da lâmpada a 100 % [°C/s]  (cross-effect luz→clima)

    # ── Umidade relativa ─────────────────────────────────────────
    umid_fuga_base: float = 0.015
    umid_ganho_vent: float = 0.060
    umid_fonte_aves: float = 0.35     # respiração/dejetos elevam UR [%/s]
    umid_seca_aquecedor: float = 0.25 # aquecedor reduz UR [%/s a 100 %]

    # ── Amônia (NH3) ─────────────────────────────────────────────
    nh3_remocao_base: float = 0.010   # decaimento natural mínimo [1/s]
    nh3_remocao_vent: float = 0.090   # remoção pela ventilação [1/s por unidade de fluxo]
    nh3_geracao_cama: float = 0.55    # geração base da cama [ppm/s] (sujeira da cama)
    # Sensibilidade da geração de NH3 à temperatura e à umidade:
    #   geração sobe com o calor (volatilização) → aquecedor PIORA os gases
    nh3_sens_temp: float = 0.06       # +6 %/°C acima de 20 °C
    nh3_sens_umid: float = 0.010      # +1 %/% de UR acima de 50 %

    # ── Acoplamento dos atuadores no fluxo de ar ─────────────────
    #   fluxo_ar = exaustor_frac*peso_exaustor + cortina_frac*peso_cortina
    peso_exaustor: float = 1.0
    peso_cortina: float = 0.45        # cortina aberta ventila menos que o exaustor


# ────────────────────────────────────────────────────────────────
#  CONFIGURAÇÃO MQTT (mantida p/ compatibilidade com o hardware Wokwi;
#  NÃO é usada no modo offline padrão do gêmeo digital)
# ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class MqttCfg:
    broker: str = "broker.hivemq.com"
    port: int = 1883
    keepalive: int = 60
    topic_lux: str = "granja/sensor/lux/{id}"
    topic_clima: str = "granja/sensor/clima/{id}"
    topic_gas: str = "granja/sensor/gas/{id}"
    topic_dimmer: str = "granja/atuador/dimmer/{id}"
    topic_exaustor: str = "granja/atuador/exaustor/{id}"
    topic_clima_atuador: str = "granja/atuador/clima/{id}"
    topic_status: str = "granja/status/{id}"


# ────────────────────────────────────────────────────────────────
#  AGREGADOR
# ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Config:
    faixa: int = 2
    limiares: Limiares = field(default_factory=Limiares)
    ganhos: GanhosControle = field(default_factory=GanhosControle)
    fisica: FisicaAmbiente = field(default_factory=FisicaAmbiente)
    mqtt: MqttCfg = field(default_factory=MqttCfg)

    @property
    def fase(self) -> FaixaVida:
        return FAIXAS[self.faixa]

    def com_faixa(self, faixa: int) -> "Config":
        return Config(
            faixa=faixa,
            limiares=self.limiares,
            ganhos=self.ganhos,
            fisica=self.fisica,
            mqtt=self.mqtt,
        )
