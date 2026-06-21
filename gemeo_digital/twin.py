# ================================================================
#  GÊMEO DIGITAL — ORQUESTRADOR (o "gêmeo" propriamente dito)
#
#  Junta tudo num laço de simulação determinístico:
#
#    ambiente → sensores → controladores → supervisor → atuadores → ambiente
#       ▲                                                              │
#       └──────────────── ciclo fechado (feedback) ───────────────────┘
#
#  Um MOTOR DE CENÁRIOS varia as condições externas (clima do dia,
#  sujeira da cama, ciclo dia/noite) de forma CÍCLICA, para a banca
#  ver cada problema surgir e o gêmeo reagir — incluindo o conflito
#  central frio×amônia. Também aceita injeções manuais do dashboard.
# ================================================================

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .config import Config
from .controllers import ClimaController, GasController, LuzController
from .environment import Ambiente, ComandosAtuadores, CondicoesExternas
from .sensors import SensorClima, SensorGas, SensorLux
from .supervisor import Supervisor


# ────────────────────────────────────────────────────────────────
#  CENÁRIOS (condições externas-alvo). O motor faz a transição suave.
# ────────────────────────────────────────────────────────────────
@dataclass
class Cenario:
    nome: str
    descricao: str
    temp_ext: float
    umid_ext: float
    sujeira_cama: float
    luz_dia: bool           # se True, lux_nat segue o ciclo dia/noite; se False, noite
    duracao_s: float        # quanto dura no modo automático/cíclico


CENARIOS: List[Cenario] = [
    Cenario("Operação normal", "Clima ameno, cama limpa, dia claro.",
            temp_ext=24.0, umid_ext=60.0, sujeira_cama=0.7, luz_dia=True, duracao_s=20),
    Cenario("Acúmulo de amônia", "Cama saturada eleva o NH₃ — exaustor entra em ação.",
            temp_ext=24.0, umid_ext=68.0, sujeira_cama=2.0, luz_dia=True, duracao_s=22),
    Cenario("Onda de calor", "Calor externo eleva temperatura e ITU — resfriamento + sinergia com gases.",
            temp_ext=35.0, umid_ext=70.0, sujeira_cama=1.3, luz_dia=True, duracao_s=22),
    Cenario("Noite fria", "Temperatura externa cai — aquecedor protege as aves.",
            temp_ext=12.0, umid_ext=55.0, sujeira_cama=0.9, luz_dia=False, duracao_s=20),
    Cenario("Conflito crítico: frio + amônia tóxica",
            "Noite fria E cama saturada ao mesmo tempo — o supervisor arbitra para não matar de frio.",
            temp_ext=10.0, umid_ext=72.0, sujeira_cama=2.0, luz_dia=False, duracao_s=26),
]


class MotorCenarios:
    """Faz a transição suave entre cenários e gera as condições externas."""

    def __init__(self) -> None:
        self.modo_auto = True
        self.indice = 0
        self.t_no_cenario = 0.0
        self.atual = CondicoesExternas(
            temp_ext=CENARIOS[0].temp_ext,
            umid_ext=CENARIOS[0].umid_ext,
            sujeira_cama=CENARIOS[0].sujeira_cama,
        )
        self._cenario_alvo = CENARIOS[0]

    @property
    def cenario_atual(self) -> Cenario:
        return self._cenario_alvo

    def selecionar(self, indice: int) -> None:
        self.indice = indice % len(CENARIOS)
        self._cenario_alvo = CENARIOS[self.indice]
        self.t_no_cenario = 0.0

    def proximo(self) -> None:
        self.selecionar(self.indice + 1)

    def _aprox(self, atual: float, alvo: float, taxa: float, dt: float) -> float:
        # transição exponencial suave (1ª ordem)
        return atual + (alvo - atual) * min(1.0, taxa * dt)

    def step(self, t_global: float, dt: float) -> CondicoesExternas:
        self.t_no_cenario += dt
        c = self._cenario_alvo

        # Avança cenário no modo automático/cíclico
        if self.modo_auto and self.t_no_cenario >= c.duracao_s:
            self.proximo()
            c = self._cenario_alvo

        # Transição suave das condições externas
        self.atual.temp_ext = self._aprox(self.atual.temp_ext, c.temp_ext, 0.25, dt)
        self.atual.umid_ext = self._aprox(self.atual.umid_ext, c.umid_ext, 0.25, dt)
        self.atual.sujeira_cama = self._aprox(self.atual.sujeira_cama, c.sujeira_cama, 0.20, dt)

        # Luz natural: ciclo dia/noite (senoide, período ~60 s) ou noite
        if c.luz_dia:
            ciclo = 0.5 + 0.5 * math.sin(2 * math.pi * t_global / 60.0)
            self.atual.lux_nat = max(0.5, 30.0 * ciclo)
        else:
            self.atual.lux_nat = 0.5  # noite
        return self.atual


# ────────────────────────────────────────────────────────────────
#  GÊMEO DIGITAL
# ────────────────────────────────────────────────────────────────
class GemeoDigital:
    def __init__(self, cfg: Config, seed: Optional[int] = 7) -> None:
        self.cfg = cfg
        self.t = 0.0

        fase = cfg.fase
        self.ambiente = Ambiente(
            cfg.fisica,
            temp_C=fase.temp_alvo,
            umid_pct=60.0,
            nh3_ppm=6.0,
        )
        self.sensor_lux = SensorLux(cfg, seed=seed)
        self.sensor_clima = SensorClima(cfg, seed=(seed or 0) + 1)
        self.sensor_gas = SensorGas(cfg, seed=(seed or 0) + 2)

        self.ctrl_luz = LuzController(cfg)
        self.ctrl_gas = GasController(cfg)
        self.ctrl_clima = ClimaController(cfg)
        self.supervisor = Supervisor(cfg)

        self.motor = MotorCenarios()

        # comandos vigentes (frações) — partem da ventilação base
        self._cmd = ComandosAtuadores(
            exaustor=cfg.ganhos.gas_base_ventilacao / 100.0,
            cortina=0.0, aquecedor=0.0, lampada=0.5,
        )
        self.ultima_decisao = None
        self.historico: List[dict] = []

    # ── Troca de fase de vida (vindo do dashboard) ───────────────
    def mudar_faixa(self, faixa: int) -> None:
        self.cfg = self.cfg.com_faixa(faixa)
        for obj in (self.sensor_lux, self.sensor_clima, self.sensor_gas,
                    self.ctrl_luz, self.ctrl_gas, self.ctrl_clima, self.supervisor):
            obj.cfg = self.cfg

    # ── Um passo do gêmeo ────────────────────────────────────────
    def tick(self, dt: float) -> dict:
        self.t += dt

        # 0) condições externas (cenário cíclico)
        ext = self.motor.step(self.t, dt)

        # 1) sensores leem o ambiente
        leitura_luz = self.sensor_lux.ler(self.ambiente, self._cmd.lampada)
        leitura_clima = self.sensor_clima.ler(self.ambiente)
        leitura_gas = self.sensor_gas.ler(self.ambiente)

        # 2) controladores propõem demandas (cada um no seu eixo)
        dem_luz = self.ctrl_luz.passo(leitura_luz)
        dem_gas = self.ctrl_gas.passo(leitura_gas)
        dem_clima = self.ctrl_clima.passo(leitura_clima)

        # 3) supervisor arbitra os conflitos → decisão final
        dec = self.supervisor.decidir(
            leitura_luz, dem_luz,
            leitura_gas, dem_gas,
            leitura_clima, dem_clima,
        )
        self.ultima_decisao = dec

        # 4) atuadores aplicam (pct → fração) e o ambiente evolui
        self._cmd = ComandosAtuadores(
            exaustor=dec.exaustor_pct / 100.0,
            cortina=dec.cortina_pct / 100.0,
            aquecedor=dec.aquecedor_pct / 100.0,
            lampada=dec.lampada_pct / 100.0,
        )
        self.ambiente.step(self._cmd, ext, dt)

        # 5) monta o snapshot p/ o dashboard
        snap = self._snapshot(ext, leitura_luz, leitura_gas, leitura_clima,
                              dem_luz, dem_gas, dem_clima, dec)
        self.historico.append({
            "t": round(self.t, 1),
            "lux": leitura_luz.lux, "nh3": leitura_gas.ppm,
            "temp": leitura_clima.temp_C, "itu": leitura_clima.itu,
            "exaustor": dec.exaustor_pct, "aquecedor": dec.aquecedor_pct,
            "lampada": dec.lampada_pct, "cortina": dec.cortina_pct,
        })
        if len(self.historico) > 120:
            self.historico.pop(0)
        return snap

    # ── Semáforo de saúde por eixo (verde/amarelo/vermelho) ──────
    @staticmethod
    def _saude_luz(status: str) -> str:
        return {"ideal": "verde", "abaixo": "amarelo", "acima": "amarelo",
                "muito_baixo": "vermelho", "muito_alto": "vermelho"}.get(status, "amarelo")

    @staticmethod
    def _saude_gas(estado: str) -> str:
        return {"bom": "verde", "elevado": "amarelo", "atencao": "laranja",
                "critico": "vermelho"}.get(estado, "amarelo")

    @staticmethod
    def _saude_clima(status: str) -> str:
        return {"ideal": "verde", "calor": "amarelo", "frio": "amarelo",
                "calor_critico": "vermelho"}.get(status, "amarelo")

    def _snapshot(self, ext, leitura_luz, leitura_gas, leitura_clima,
                  dem_luz, dem_gas, dem_clima, dec) -> dict:
        fase = self.cfg.fase
        lim = self.cfg.limiares
        return {
            "t": round(self.t, 1),
            "faixa": self.cfg.faixa,
            "fase_nome": fase.nome,
            "cenario": {
                "nome": self.motor.cenario_atual.nome,
                "descricao": self.motor.cenario_atual.descricao,
                "indice": self.motor.indice,
                "auto": self.motor.modo_auto,
                "temp_ext": round(ext.temp_ext, 1),
                "umid_ext": round(ext.umid_ext, 1),
                "sujeira_cama": round(ext.sujeira_cama, 2),
            },
            "eixos": {
                "luz": {
                    "lux": leitura_luz.lux, "alvo": fase.lux_alvo,
                    "min": fase.lux_min, "max": fase.lux_max,
                    "lux_lampada": leitura_luz.lux_lampada,
                    "lux_natural": leitura_luz.lux_natural,
                    "status": dem_luz.status, "saude": self._saude_luz(dem_luz.status),
                    "explicacao": dem_luz.explicacao,
                },
                "clima": {
                    "temp": leitura_clima.temp_C, "umid": leitura_clima.umid_pct,
                    "itu": leitura_clima.itu, "tpo": leitura_clima.tpo_C,
                    "temp_alvo": fase.temp_alvo, "temp_min": fase.temp_min, "temp_max": fase.temp_max,
                    "itu_conforto": lim.itu_conforto, "itu_critico": lim.itu_critico,
                    "zona": leitura_clima.zona,
                    "status": dem_clima.status, "saude": self._saude_clima(dem_clima.status),
                    "explicacao": dem_clima.explicacao,
                },
                "gas": {
                    "ppm": leitura_gas.ppm,
                    "alvo": lim.nh3_alvo, "atencao": lim.nh3_atencao, "critico": lim.nh3_critico,
                    "estado": leitura_gas.estado, "saude": self._saude_gas(leitura_gas.estado),
                    "explicacao": dem_gas.explicacao,
                },
            },
            "atuadores": {
                "exaustor": dec.exaustor_pct,
                "cortina": dec.cortina_pct,
                "aquecedor": dec.aquecedor_pct,
                "lampada": dec.lampada_pct,
            },
            "supervisor": {
                "modo_termico": dec.modo_termico,
                "conflitos": dec.conflitos,
                "sinergias": dec.sinergias,
                "alerta_global": dec.alerta_global,
            },
            "historico": list(self.historico),
        }
