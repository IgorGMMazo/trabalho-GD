"""Testes de integração: ecossistema completo sobre o LocalBus.

Fecha a malha sensor → controlador → atuador → (feedback) sensor e
verifica que o controle estabiliza a iluminância perto do alvo.
"""

from gemeo_digital import (
    Config, LocalBus, GranjaController, SensorBH1750, AtuadorLED,
)


def montar(faixa: int, lux_natural: float, noise_sigma: float = 0.0):
    cfg = Config().com_faixa(faixa)
    bus = LocalBus()
    atuador = AtuadorLED(bus, cfg, "1")
    controlador = GranjaController(bus, cfg)
    sensor = SensorBH1750(bus, cfg, "1", lux_natural=lux_natural,
                          noise_sigma=noise_sigma, seed=42)
    atuador.start()
    controlador.start()
    sensor.start()
    return cfg, bus, sensor, controlador, atuador


def test_convergencia_fase_crescimento():
    """Fase 2 (alvo=10), sem luz natural: a lâmpada (≤15 lux) deve
    levar a leitura para dentro do deadband do alvo."""
    cfg, bus, sensor, ctrl, atuador = montar(faixa=2, lux_natural=0.0)
    for _ in range(40):
        sensor.tick()

    est = ctrl.estados["1"]
    assert abs(est.lux - cfg.lux_alvo) <= cfg.deadband, \
        f"lux={est.lux} fora do deadband do alvo {cfg.lux_alvo}"
    assert est.status == "ESTAVEL"
    # alvo 10 com lâmpada de 15 lux → dimmer de equilíbrio em ~57-77%
    # (faixa que mantém a leitura dentro do deadband)
    assert 55.0 <= est.dimmer_pct <= 80.0
    assert atuador.estado.estado in ("MEDIA", "FORTE")


def test_excesso_de_luz_natural_apaga_lampada():
    """Se a luz natural já passa do alvo, o controle deve cortar o dimmer."""
    cfg, bus, sensor, ctrl, atuador = montar(faixa=2, lux_natural=30.0)
    for _ in range(40):
        sensor.tick()

    est = ctrl.estados["1"]
    assert est.dimmer_pct == 0.0
    assert atuador.estado.estado == "APAGADA"


def test_fluxo_de_mensagens_e_topicos():
    """O controlador publica dimmer e status; o atuador reage."""
    cfg, bus, sensor, ctrl, atuador = montar(faixa=2, lux_natural=0.0)

    vistos = {}
    bus.subscribe("granja/#", lambda t, p: vistos.setdefault(t, p))

    sensor.tick()
    assert "granja/sensor/lux/1" in vistos
    assert "granja/atuador/dimmer/1" in vistos
    assert "granja/status/1" in vistos
    assert ctrl.estados["1"].total_mensagens >= 1


def test_convergencia_com_ruido_realista():
    """Mesmo com ruído gaussiano (σ=0.5), a média final fica próxima do alvo."""
    cfg, bus, sensor, ctrl, atuador = montar(faixa=2, lux_natural=1.0,
                                             noise_sigma=0.5)
    for _ in range(60):
        sensor.tick()
    est = ctrl.estados["1"]
    # tolerância = deadband + alguns desvios de ruído
    assert abs(est.lux - cfg.lux_alvo) <= cfg.deadband + 2.0
