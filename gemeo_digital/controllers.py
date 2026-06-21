# ================================================================
#  GÊMEO DIGITAL — CONTROLADORES (um por eixo)
#
#  Cada controlador olha SÓ o seu sensor e calcula a DEMANDA de
#  atuação que resolveria o seu problema isoladamente (controle
#  proporcional com deadband). Eles NÃO acionam nada diretamente:
#  apenas propõem. Quem decide o que de fato vai ao ar — resolvendo
#  os conflitos entre eixos — é o `Supervisor`.
#
#  É essa separação (controlador propõe ↔ supervisor arbitra) que
#  transforma três malhas independentes num gêmeo digital coerente
#  com o ambiente físico compartilhado.
# ================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .config import Config
from .sensors import LeituraClima, LeituraGas, LeituraLux


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ════════════════════════════════════════════════════════════════
#  EIXO LUZ
# ════════════════════════════════════════════════════════════════
@dataclass
class DemandaLuz:
    dimmer_pct: float
    status: str
    explicacao: str
    watts: float = 0.0


class LuzController:
    """Controle P com deadband (idêntico ao control.py de referência)."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.dimmer_pct = 50.0

    def passo(self, leitura: LeituraLux) -> DemandaLuz:
        fase = self.cfg.fase
        g = self.cfg.ganhos
        erro = fase.lux_alvo - leitura.lux

        if abs(erro) <= g.luz_deadband:
            status = "ideal"
            expl = f"Iluminância {leitura.lux:.0f} lux dentro do alvo ({fase.lux_alvo:.0f} ± {g.luz_deadband:.0f})."
        else:
            self.dimmer_pct = _clamp(self.dimmer_pct + g.luz_kp * erro, 0.0, 100.0)
            if leitura.lux < fase.lux_min:
                status = "muito_baixo"
            elif leitura.lux < fase.lux_alvo:
                status = "abaixo"
            elif leitura.lux > fase.lux_max:
                status = "muito_alto"
            else:
                status = "acima"
            sentido = "aumentando" if erro > 0 else "reduzindo"
            expl = (f"Iluminância {leitura.lux:.0f} lux vs alvo {fase.lux_alvo:.0f} — "
                    f"{sentido} a lâmpada para {self.dimmer_pct:.0f}%.")

        watts = round(self.dimmer_pct / 100.0 * g.lampada_potencia_w, 1)
        return DemandaLuz(round(self.dimmer_pct, 1), status, expl, watts)


# ════════════════════════════════════════════════════════════════
#  EIXO GASES (NH3)
# ════════════════════════════════════════════════════════════════
@dataclass
class DemandaGas:
    vent_pct: float        # ventilação (exaustor) que o eixo gases QUER
    status: str
    alerta: bool
    explicacao: str


class GasController:
    """P sobre o excesso de NH3, somado a uma ventilação base permanente."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def passo(self, leitura: LeituraGas) -> DemandaGas:
        lim = self.cfg.limiares
        g = self.cfg.ganhos
        ppm = leitura.ppm
        excesso = ppm - lim.nh3_alvo

        if excesso <= g.gas_deadband:
            return DemandaGas(
                g.gas_base_ventilacao, "bom", False,
                f"NH₃ {ppm:.1f} ppm saudável (alvo < {lim.nh3_alvo:.0f}) — só ventilação base.")

        if ppm >= lim.nh3_critico:
            return DemandaGas(
                100.0, "critico", True,
                f"NH₃ {ppm:.1f} ppm CRÍTICO (≥ {lim.nh3_critico:.0f}) — risco de lesão "
                f"respiratória. Exaustor demandado a 100%.")

        vent = _clamp(g.gas_base_ventilacao + g.gas_kp * excesso, 0.0, 100.0)
        status = "atencao" if ppm >= lim.nh3_atencao else "elevado"
        return DemandaGas(
            round(vent, 1), status, False,
            f"NH₃ {ppm:.1f} ppm acima do alvo — exaustor demandado a {vent:.0f}%.")


# ════════════════════════════════════════════════════════════════
#  EIXO CLIMA (temperatura / umidade / ITU)
# ════════════════════════════════════════════════════════════════
@dataclass
class DemandaClima:
    aquecedor_pct: float   # aquecimento (frio)
    vent_pct: float        # ventilação/cortina que o eixo clima QUER (calor)
    cortina_pct: float     # abertura da cortina
    status: str            # frio | ideal | calor | calor_critico
    alerta: bool
    explicacao: str


class ClimaController:
    """
    Controle bidirecional:
      • temp abaixo da banda da fase  → AQUECEDOR (proporcional ao déficit)
      • temp acima da banda OU ITU alto → VENTILAÇÃO + CORTINA (proporcional)
      • ITU ≥ crítico → resfriamento máximo + ALERTA

    Em pintinhos (fase 1) o frio é o risco dominante; por isso o aquecedor
    tem ganho alto e a ventilação é depois LIMITADA pelo supervisor.
    """

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def passo(self, leitura: LeituraClima) -> DemandaClima:
        fase = self.cfg.fase
        lim = self.cfg.limiares
        g = self.cfg.ganhos
        temp = leitura.temp_C
        itu = leitura.itu

        # ── FRIO ─────────────────────────────────────────────────
        if temp < fase.temp_min - g.clima_deadband:
            deficit = fase.temp_alvo - temp
            aquecedor = _clamp(g.clima_kp_frio * deficit, 0.0, 100.0)
            return DemandaClima(
                aquecedor_pct=round(aquecedor, 1), vent_pct=0.0, cortina_pct=0.0,
                status="frio", alerta=(temp < fase.temp_min - 3.0),
                explicacao=(f"Temp {temp:.1f}°C abaixo da banda ({fase.temp_min:.0f}–{fase.temp_max:.0f}°C) "
                            f"— aquecedor a {aquecedor:.0f}%. Ventilação suspensa para não resfriar."))

        # ── CALOR / ITU ──────────────────────────────────────────
        #  A escala de ITU 74/78 vale para aves crescidas (zona
        #  termoneutra ~21 °C). NÃO se aplica a pintinhos, cujo alvo é
        #  ~32 °C (a fórmula daria ITU ~80 no conforto deles). Por isso
        #  o ITU só dispara resfriamento nas fases 2 e 3, e nunca abaixo
        #  do alvo térmico da fase.
        usa_itu = self.cfg.faixa != 1
        calor_por_temp = temp > fase.temp_max + g.clima_deadband
        calor_por_itu = usa_itu and itu >= lim.itu_conforto and temp >= fase.temp_alvo
        if calor_por_temp or calor_por_itu:
            base = max(temp - fase.temp_max, 0.0)
            extra_itu = 2.0 * max(itu - lim.itu_conforto, 0.0) if usa_itu else 0.0
            vent = _clamp(20.0 + g.clima_kp_calor * base + extra_itu, 0.0, 100.0)
            cortina = _clamp(vent * 0.8, 0.0, 100.0)
            if usa_itu and itu >= lim.itu_critico and temp >= fase.temp_alvo:
                return DemandaClima(
                    0.0, 100.0, 100.0, "calor_critico", True,
                    f"ITU {itu:.1f} CRÍTICO (≥ {lim.itu_critico:.0f}) — estresse térmico por calor. "
                    f"Ventilação e cortina ao máximo.")
            return DemandaClima(
                0.0, round(vent, 1), round(cortina, 1), "calor", False,
                f"Temp {temp:.1f}°C / ITU {itu:.1f} — resfriando: ventilação {vent:.0f}%, cortina {cortina:.0f}%.")

        # ── DENTRO DA BANDA ──────────────────────────────────────
        return DemandaClima(
            0.0, 0.0, 0.0, "ideal", False,
            f"Temp {temp:.1f}°C / ITU {itu:.1f} em conforto (banda {fase.temp_min:.0f}–{fase.temp_max:.0f}°C).")
