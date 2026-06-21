# Testes da arbitragem do supervisor — o coração do projeto.
# Validam que os atuadores compartilhados são resolvidos por uma
# hierarquia de bem-estar, sem prejudicar as aves.

from gemeo_digital.config import Config
from gemeo_digital.controllers import (ClimaController, GasController,
                                       LuzController)
from gemeo_digital.environment import calcular_itu
from gemeo_digital.sensors import LeituraClima, LeituraGas, LeituraLux
from gemeo_digital.supervisor import Supervisor


def _leituras(temp, umid, nh3, lux, cfg):
    itu = round(calcular_itu(temp, umid), 1)
    zona = "conforto" if itu < 74 else ("alerta" if itu < 78 else "critico")
    lc = LeituraClima(temp, umid, 0.0, itu, zona)
    lim = cfg.limiares
    if nh3 < lim.nh3_alvo: eg = "bom"
    elif nh3 < lim.nh3_atencao: eg = "elevado"
    elif nh3 < lim.nh3_critico: eg = "atencao"
    else: eg = "critico"
    gg = LeituraGas(nh3, eg)
    ll = LeituraLux(lux, lux, 0.0)
    return ll, lc, gg


def _decidir(cfg, temp, umid, nh3, lux):
    ll, lc, gg = _leituras(temp, umid, nh3, lux, cfg)
    dl = LuzController(cfg).passo(ll)
    dg = GasController(cfg).passo(gg)
    dc = ClimaController(cfg).passo(lc)
    return Supervisor(cfg).decidir(ll, dl, gg, dg, lc, dc), (dl, dg, dc)


# ═══════════════════════════════════════════════════════════════
#  CONFLITO CENTRAL: amônia tóxica × frio em pintinhos
# ═══════════════════════════════════════════════════════════════
def test_conflito_frio_amonia_limita_exaustor_ao_teto_seguro():
    cfg = Config().com_faixa(1)  # vent_max_seguro = 35 %
    # Pinto com frio (temp abaixo da banda 30-34) E NH3 tóxico (>25)
    dec, (dl, dg, dc) = _decidir(cfg, temp=27.0, umid=70.0, nh3=30.0, lux=20.0)

    # O eixo gases SOZINHO pediria 100 % de exaustor...
    assert dg.vent_pct == 100.0
    # ...mas o supervisor LIMITA ao teto seguro da fase para não congelar.
    assert dec.exaustor_pct <= cfg.fase.vent_max_seguro
    # E COMPENSA com aquecedor.
    assert dec.aquecedor_pct > dc.aquecedor_pct
    assert dec.modo_termico == "frio"
    assert any("CONFLITO" in c for c in dec.conflitos)
    assert dec.alerta_global


def test_frio_com_nh3_apenas_elevado_prioriza_calor():
    cfg = Config().com_faixa(1)
    dec, _ = _decidir(cfg, temp=27.0, umid=60.0, nh3=18.0, lux=20.0)
    # NH3 elevado (não tóxico) → mantém ventilação de renovação mínima.
    assert dec.exaustor_pct <= cfg.ganhos.gas_base_ventilacao
    assert dec.modo_termico == "frio"


# ═══════════════════════════════════════════════════════════════
#  SINERGIA: calor + amônia → ventilar resolve os dois
# ═══════════════════════════════════════════════════════════════
def test_calor_com_amonia_gera_sinergia_e_exaustor_alto():
    cfg = Config().com_faixa(2)  # banda 23-29
    dec, _ = _decidir(cfg, temp=33.0, umid=70.0, nh3=22.0, lux=10.0)
    assert dec.modo_termico == "calor"
    assert dec.aquecedor_pct == 0.0
    assert dec.exaustor_pct >= 80.0
    assert any("Sinergia" in s for s in dec.sinergias)


# ═══════════════════════════════════════════════════════════════
#  NEUTRO: térmico ok → exaustor segue os gases
# ═══════════════════════════════════════════════════════════════
def test_neutro_exaustor_segue_demanda_de_gases():
    cfg = Config().com_faixa(3)  # vent_max_seguro 100 %, banda 18-25
    dec, (dl, dg, dc) = _decidir(cfg, temp=21.0, umid=55.0, nh3=18.0, lux=20.0)
    assert dec.modo_termico == "neutro"
    assert dec.aquecedor_pct == 0.0
    assert dec.exaustor_pct == dg.vent_pct


def test_neutro_limita_exaustor_se_esfriaria_demais():
    # Fase 1 (teto 35 %), térmico dentro da banda mas perto do alvo:
    # NH3 alto pediria muito exaustor, mas isso esfriaria o galpão.
    cfg = Config().com_faixa(1)  # banda 30-34, alvo 32
    dec, (dl, dg, dc) = _decidir(cfg, temp=30.5, umid=60.0, nh3=19.0, lux=30.0)
    if dg.vent_pct > cfg.fase.vent_max_seguro:
        assert dec.exaustor_pct <= cfg.fase.vent_max_seguro


# ═══════════════════════════════════════════════════════════════
#  Garantia de segurança: NUNCA exceder o teto de frio quando há frio
# ═══════════════════════════════════════════════════════════════
def test_nunca_resfria_pintinho_alem_do_teto():
    cfg = Config().com_faixa(1)
    for nh3 in (12, 20, 26, 35, 50):
        dec, _ = _decidir(cfg, temp=26.0, umid=70.0, nh3=nh3, lux=20.0)
        assert dec.exaustor_pct <= cfg.fase.vent_max_seguro, f"falhou em nh3={nh3}"
