# ================================================================
#  GÊMEO DIGITAL — SUPERVISOR (arbitragem de conflitos)
#
#  Os três controladores propõem demandas olhando só o próprio eixo.
#  Mas os atuadores agem num AMBIENTE COMPARTILHADO e alguns são
#  fisicamente o mesmo recurso:
#
#     • O EXAUSTOR é demandado tanto pelo eixo GASES (tirar NH₃) quanto
#       pelo eixo CLIMA (resfriar) — é UM só ventilador.
#     • Ventilar resfria → conflita com o AQUECEDOR (que o clima pede
#       no frio) e pode MATAR pintinhos de frio.
#     • Aquecer eleva a volatilização de NH₃ → piora os GASES.
#
#  O supervisor resolve esses conflitos com uma HIERARQUIA DE
#  BEM-ESTAR ANIMAL (do mais grave ao menos grave):
#
#     1º  Risco térmico letal  (frio em pintinhos / calor extremo)
#     2º  Amônia tóxica        (NH₃ ≥ crítico)
#     3º  Conforto lumínico    (lux)
#
#  A regra de ouro: NUNCA resfriar além do `vent_max_seguro` da fase
#  para combater amônia — em vez disso, ventila o tolerável e
#  COMPENSA com aquecedor, registrando o conflito.
# ================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .config import Config
from .controllers import DemandaClima, DemandaGas, DemandaLuz
from .sensors import LeituraClima, LeituraGas, LeituraLux


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


@dataclass
class Decisao:
    # Comandos finais aplicados aos atuadores (% de potência/abertura)
    exaustor_pct: float
    cortina_pct: float
    aquecedor_pct: float
    lampada_pct: float
    # Raciocínio do supervisor
    modo_termico: str               # frio | calor | neutro
    conflitos: List[str] = field(default_factory=list)
    sinergias: List[str] = field(default_factory=list)
    alerta_global: bool = False


class Supervisor:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def decidir(
        self,
        leitura_luz: LeituraLux, demanda_luz: DemandaLuz,
        leitura_gas: LeituraGas, demanda_gas: DemandaGas,
        leitura_clima: LeituraClima, demanda_clima: DemandaClima,
    ) -> Decisao:
        fase = self.cfg.fase
        lim = self.cfg.limiares
        ganhos = self.cfg.ganhos

        conflitos: List[str] = []
        sinergias: List[str] = []
        alerta = False

        vent_gas = demanda_gas.vent_pct
        vent_clima = demanda_clima.vent_pct
        teto_frio = fase.vent_max_seguro
        nh3 = leitura_gas.ppm
        temp = leitura_clima.temp_C

        lampada = demanda_luz.dimmer_pct  # luz tem prioridade mais baixa → passa direto

        # ============================================================
        #  1) REGIME TÉRMICO  (prioridade máxima)
        # ============================================================
        if demanda_clima.status == "frio":
            # -------- FRIO: proteger as aves do resfriamento ---------
            modo = "frio"
            aquecedor = demanda_clima.aquecedor_pct
            cortina = 0.0  # cortina fechada no frio

            if nh3 >= lim.nh3_critico:
                # CONFLITO CENTRAL: amônia tóxica × frio letal.
                # Ventila só até o teto seguro da fase e COMPENSA com calor.
                exaustor = min(vent_gas, teto_frio)
                aquecedor = _clamp(aquecedor + 0.8 * exaustor, 0.0, 100.0)
                alerta = True
                conflitos.append(
                    f"⚠️ CONFLITO amônia×frio: NH₃ {nh3:.1f} ppm (tóxico) pediria exaustor "
                    f"{vent_gas:.0f}%, mas as aves estão com frio. Ventilação LIMITADA ao "
                    f"teto seguro da fase ({teto_frio:.0f}%) e aquecedor elevado para "
                    f"{aquecedor:.0f}% para compensar a perda de calor.")
            elif leitura_gas.estado in ("atencao", "elevado"):
                # NH₃ elevado, mas não tóxico → priоriza o calor; mantém só
                # uma ventilação de renovação reduzida.
                exaustor = min(vent_gas, ganhos.gas_base_ventilacao, teto_frio)
                conflitos.append(
                    f"NH₃ {nh3:.1f} ppm elevado, porém as aves têm prioridade térmica: "
                    f"exaustor mantido em renovação mínima ({exaustor:.0f}%) e aquecimento "
                    f"preservado.")
            else:
                # Ar saudável → só renovação mínima, foco total no aquecimento.
                exaustor = min(ganhos.gas_base_ventilacao, teto_frio)

            if demanda_clima.alerta:
                alerta = True

        elif demanda_clima.status in ("calor", "calor_critico"):
            # -------- CALOR: ventilar resfria E limpa NH₃ (sinergia) -
            modo = "calor"
            aquecedor = 0.0  # nunca aquecer enquanto resfria
            exaustor = max(vent_clima, vent_gas)
            cortina = max(demanda_clima.cortina_pct, 0.0)
            if leitura_gas.estado in ("atencao", "elevado", "critico"):
                sinergias.append(
                    f"✅ Sinergia: ventilação contra o calor (ITU {leitura_clima.itu:.1f}) "
                    f"também remove o NH₃ ({nh3:.1f} ppm) — um atuador resolve dois eixos.")
            if demanda_clima.status == "calor_critico":
                alerta = True
            if demanda_gas.alerta:
                alerta = True

        else:
            # -------- NEUTRO: térmico ok → exaustor segue os GASES ---
            modo = "neutro"
            aquecedor = 0.0
            cortina = 0.0
            exaustor = vent_gas
            if demanda_gas.alerta:
                alerta = True
            # Pré-proteção: se ventilar muito puxaria a temperatura abaixo
            # do conforto, limita ao teto seguro e avisa.
            if exaustor > teto_frio and temp < fase.temp_alvo:
                conflitos.append(
                    f"NH₃ pediria exaustor {exaustor:.0f}%, mas isso esfriaria o galpão "
                    f"(temp {temp:.1f}°C perto do limite). Ventilação limitada a {teto_frio:.0f}%.")
                exaustor = teto_frio

        # ============================================================
        #  2) EFEITO CRUZADO DA LÂMPADA (luz → calor)
        # ============================================================
        if modo == "calor" and lampada >= 70.0:
            sinergias.append(
                f"ℹ️ A lâmpada a {lampada:.0f}% adiciona calor ao galpão (efeito cruzado luz→clima). "
                f"Em lâmpada incandescente, considerar LED reduziria a carga térmica.")

        # ============================================================
        #  3) EFEITO CRUZADO DO AQUECEDOR (calor → mais NH₃)
        # ============================================================
        if modo == "frio" and aquecedor >= 50.0 and leitura_gas.estado != "bom":
            conflitos.append(
                f"ℹ️ Aquecedor a {aquecedor:.0f}% tende a volatilizar mais amônia da cama "
                f"(efeito cruzado clima→gases) — NH₃ monitorado de perto.")

        return Decisao(
            exaustor_pct=round(_clamp(exaustor, 0.0, 100.0), 1),
            cortina_pct=round(_clamp(cortina, 0.0, 100.0), 1),
            aquecedor_pct=round(_clamp(aquecedor, 0.0, 100.0), 1),
            lampada_pct=round(_clamp(lampada, 0.0, 100.0), 1),
            modo_termico=modo,
            conflitos=conflitos,
            sinergias=sinergias,
            alerta_global=alerta,
        )
