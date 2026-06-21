# ================================================================
#  GÊMEO DIGITAL — AMBIENTE FÍSICO COMPARTILHADO (galpão)
#
#  Este é o coração do gêmeo digital: um modelo dinâmico do AR DENTRO
#  DO GALPÃO que os três eixos compartilham. Todos os atuadores
#  escrevem aqui e todos os sensores leem daqui — por isso um atuador
#  acionado para resolver UM problema inevitavelmente afeta os outros.
#
#  Variáveis de estado (a "verdade" do galpão):
#     temp_C    — temperatura interna do ar
#     umid_pct  — umidade relativa interna
#     nh3_ppm   — concentração de amônia
#     lux_nat   — luz natural que entra (exógena: ciclo dia/noite)
#
#  Entradas exógenas (clima externo / manejo):
#     temp_ext, umid_ext   — ar externo
#     sujeira_cama         — fator de geração de NH3 (0..2) da cama
#     lux_nat              — luz natural instantânea
#
#  Entradas dos atuadores (frações 0..1):
#     exaustor, cortina, aquecedor, lampada
#
#  Modelo de 1ª ordem (Newton + fontes), integração de Euler.
#  ACOPLAMENTOS (cross-effects) explícitos e defensáveis:
#     • exaustor/cortina  → ↓temp, ↓umid, ↓NH3   (ventilação)
#     • aquecedor         → ↑temp, ↓umid, ↑NH3   (calor volatiliza amônia)
#     • lâmpada           → ↑temp (pequeno)       (luz incandescente esquenta)
# ================================================================

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .config import FisicaAmbiente


# ────────────────────────────────────────────────────────────────
#  FUNÇÕES DE CLIMA (idênticas ao firmware do sensor de clima)
# ────────────────────────────────────────────────────────────────
def ponto_de_orvalho(temp_C: float, umid_pct: float) -> float:
    """Ponto de orvalho pela fórmula de Magnus (a=17.27, b=237.7)."""
    a, b = 17.27, 237.7
    umid = max(1.0, min(100.0, umid_pct))
    alpha = (a * temp_C) / (b + temp_C) + math.log(umid / 100.0)
    return (b * alpha) / (a - alpha)


def calcular_itu(temp_C: float, umid_pct: float) -> float:
    """Índice de Temperatura e Umidade (ITU/THI de Thom).

    ITU = Tbs + 0.36 * Tpo + 41.5   (mesma fórmula do sketch do DHT22).
    """
    tpo = ponto_de_orvalho(temp_C, umid_pct)
    return temp_C + 0.36 * tpo + 41.5


# ────────────────────────────────────────────────────────────────
#  ENTRADAS DOS ATUADORES (frações 0..1)
# ────────────────────────────────────────────────────────────────
@dataclass
class ComandosAtuadores:
    exaustor: float = 0.15   # fração de potência do exaustor
    cortina: float = 0.0     # fração de abertura da cortina (servo)
    aquecedor: float = 0.0   # fração de potência do aquecedor
    lampada: float = 0.0     # fração do dimmer da lâmpada


# ────────────────────────────────────────────────────────────────
#  CONDIÇÕES EXTERNAS (exógenas)
# ────────────────────────────────────────────────────────────────
@dataclass
class CondicoesExternas:
    temp_ext: float = 24.0
    umid_ext: float = 60.0
    sujeira_cama: float = 1.0    # 0..2 — quão "carregada" de amônia está a cama
    lux_nat: float = 5.0         # lux de luz natural entrando


# ────────────────────────────────────────────────────────────────
#  AMBIENTE
# ────────────────────────────────────────────────────────────────
class Ambiente:
    def __init__(
        self,
        fisica: FisicaAmbiente,
        temp_C: float = 26.0,
        umid_pct: float = 60.0,
        nh3_ppm: float = 6.0,
    ) -> None:
        self.f = fisica
        self.temp_C = temp_C
        self.umid_pct = umid_pct
        self.nh3_ppm = nh3_ppm
        self.lux_nat = 5.0
        # guardado p/ telemetria/depuração
        self.fluxo_ar = 0.0

    # ── Fluxo de ar resultante dos atuadores de ventilação ───────
    def _fluxo_ar(self, cmd: ComandosAtuadores) -> float:
        return (cmd.exaustor * self.f.peso_exaustor
                + cmd.cortina * self.f.peso_cortina)

    # ── Geração instantânea de NH3 (depende de temp/umid/cama) ───
    def _geracao_nh3(self, ext: CondicoesExternas) -> float:
        fator_temp = 1.0 + self.f.nh3_sens_temp * max(0.0, self.temp_C - 20.0)
        fator_umid = 1.0 + self.f.nh3_sens_umid * max(0.0, self.umid_pct - 50.0)
        return self.f.nh3_geracao_cama * ext.sujeira_cama * fator_temp * fator_umid

    # ── Um passo de integração (dt em segundos) ──────────────────
    def step(self, cmd: ComandosAtuadores, ext: CondicoesExternas, dt: float) -> None:
        f = self.f
        self.lux_nat = ext.lux_nat
        fluxo = self._fluxo_ar(cmd)
        self.fluxo_ar = fluxo

        # ── TEMPERATURA ──────────────────────────────────────────
        #   dT/dt = G*(temp_ext - temp) + S
        G_temp = f.temp_fuga_base + f.temp_ganho_vent * fluxo
        S_temp = (f.temp_fonte_metabolica
                  + f.temp_fonte_aquecedor * cmd.aquecedor
                  + f.temp_fonte_lampada * cmd.lampada)
        self.temp_C += (G_temp * (ext.temp_ext - self.temp_C) + S_temp) * dt

        # ── UMIDADE ──────────────────────────────────────────────
        G_umid = f.umid_fuga_base + f.umid_ganho_vent * fluxo
        S_umid = f.umid_fonte_aves - f.umid_seca_aquecedor * cmd.aquecedor
        self.umid_pct += (G_umid * (ext.umid_ext - self.umid_pct) + S_umid) * dt
        self.umid_pct = max(5.0, min(99.0, self.umid_pct))

        # ── AMÔNIA (NH3) ─────────────────────────────────────────
        remocao = (f.nh3_remocao_base + f.nh3_remocao_vent * fluxo)
        geracao = self._geracao_nh3(ext)
        self.nh3_ppm += (geracao - remocao * self.nh3_ppm) * dt
        self.nh3_ppm = max(0.0, self.nh3_ppm)

    # ── Índices derivados ────────────────────────────────────────
    @property
    def itu(self) -> float:
        return calcular_itu(self.temp_C, self.umid_pct)

    @property
    def ponto_orvalho(self) -> float:
        return ponto_de_orvalho(self.temp_C, self.umid_pct)

    def snapshot(self) -> dict:
        return {
            "temp_C": round(self.temp_C, 2),
            "umid_pct": round(self.umid_pct, 1),
            "nh3_ppm": round(self.nh3_ppm, 2),
            "lux_nat": round(self.lux_nat, 2),
            "itu": round(self.itu, 1),
            "ponto_orvalho": round(self.ponto_orvalho, 1),
            "fluxo_ar": round(self.fluxo_ar, 3),
        }
