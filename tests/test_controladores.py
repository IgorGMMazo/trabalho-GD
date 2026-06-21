# Testes dos controladores isolados (cada eixo no seu próprio mundo).
from gemeo_digital.config import Config
from gemeo_digital.controllers import (ClimaController, GasController,
                                       LuzController)
from gemeo_digital.sensors import LeituraClima, LeituraGas, LeituraLux


# ── LUZ ─────────────────────────────────────────────────────────
def test_luz_aumenta_dimmer_quando_escuro():
    cfg = Config().com_faixa(2)  # alvo 10 lux
    ctrl = LuzController(cfg)
    ctrl.dimmer_pct = 50.0
    dem = ctrl.passo(LeituraLux(lux=2.0, lux_natural=2.0, lux_lampada=0.0))
    assert dem.dimmer_pct > 50.0
    assert dem.status in ("muito_baixo", "abaixo")


def test_luz_estavel_no_deadband():
    cfg = Config().com_faixa(2)
    ctrl = LuzController(cfg)
    ctrl.dimmer_pct = 40.0
    dem = ctrl.passo(LeituraLux(lux=10.0, lux_natural=10.0, lux_lampada=0.0))
    assert dem.dimmer_pct == 40.0
    assert dem.status == "ideal"


# ── GASES ───────────────────────────────────────────────────────
def test_gas_so_ventilacao_base_quando_saudavel():
    cfg = Config()
    dem = GasController(cfg).passo(LeituraGas(ppm=6.0, estado="bom"))
    assert dem.vent_pct == cfg.ganhos.gas_base_ventilacao
    assert not dem.alerta


def test_gas_critico_exaustor_maximo_e_alerta():
    cfg = Config()
    dem = GasController(cfg).passo(LeituraGas(ppm=27.0, estado="critico"))
    assert dem.vent_pct == 100.0
    assert dem.alerta
    assert dem.status == "critico"


def test_gas_proporcional_na_faixa_intermediaria():
    cfg = Config()
    dem = GasController(cfg).passo(LeituraGas(ppm=18.0, estado="elevado"))
    assert cfg.ganhos.gas_base_ventilacao < dem.vent_pct < 100.0


# ── CLIMA ───────────────────────────────────────────────────────
def _clima(temp, umid, cfg):
    from gemeo_digital.environment import calcular_itu
    itu = calcular_itu(temp, umid)
    zona = "conforto" if itu < 74 else ("alerta" if itu < 78 else "critico")
    return LeituraClima(temp_C=temp, umid_pct=umid, tpo_C=0.0, itu=round(itu, 1), zona=zona)


def test_clima_frio_aciona_aquecedor_e_zera_ventilacao():
    cfg = Config().com_faixa(2)  # banda 23-29
    dem = ClimaController(cfg).passo(_clima(18.0, 55.0, cfg))
    assert dem.status == "frio"
    assert dem.aquecedor_pct > 0
    assert dem.vent_pct == 0.0


def test_clima_calor_aciona_ventilacao_sem_aquecedor():
    cfg = Config().com_faixa(2)
    dem = ClimaController(cfg).passo(_clima(33.0, 70.0, cfg))
    assert dem.status in ("calor", "calor_critico")
    assert dem.vent_pct > 0
    assert dem.aquecedor_pct == 0.0


def test_pintinho_no_alvo_nao_dispara_resfriamento_por_itu():
    # FASE 1: 32 °C é o conforto do pinto, embora o ITU dê ~80.
    # A escala de ITU 74/78 NÃO se aplica a pintinhos → não pode resfriar.
    cfg = Config().com_faixa(1)  # banda 30-34, alvo 32
    leitura = _clima(32.0, 60.0, cfg)
    assert leitura.itu > 78  # o ITU bruto seria "crítico"...
    dem = ClimaController(cfg).passo(leitura)
    assert dem.status == "ideal"          # ...mas o controlador NÃO resfria
    assert dem.vent_pct == 0.0
