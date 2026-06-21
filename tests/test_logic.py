"""Testes unitários da lógica pura (sem broker, determinísticos)."""

from gemeo_digital import (
    Config, FAIXAS, topic_matches,
    calcular_dimmer, calcular_watts,
    dimmer_para_pwm, estado_lampada,
    LocalBus, SensorBH1750,
)

CFG = Config().com_faixa(2)  # alvo=10, deadband=1.5


# ── Bus: casamento de curingas MQTT ──────────────────────────────
def test_topic_matches_exato():
    assert topic_matches("granja/sensor/lux/1", "granja/sensor/lux/1")
    assert not topic_matches("granja/sensor/lux/1", "granja/sensor/lux/2")


def test_topic_matches_curingas():
    assert topic_matches("granja/sensor/lux/+", "granja/sensor/lux/9")
    assert not topic_matches("granja/sensor/lux/+", "granja/sensor/lux/9/extra")
    assert topic_matches("granja/#", "granja/sensor/lux/9/extra")
    assert not topic_matches("granja/atuador/#", "granja/sensor/lux/1")


# ── Controlador P com deadband ───────────────────────────────────
def test_deadband_mantem_dimmer():
    novo, status = calcular_dimmer(lux_medido=10.0, dimmer_atual=60.0, cfg=CFG)
    assert novo == 60.0
    assert status == "ESTAVEL"


def test_abaixo_do_alvo_aumenta():
    novo, status = calcular_dimmer(lux_medido=4.0, dimmer_atual=50.0, cfg=CFG)
    # erro = 10-4 = 6 ; ajuste = 2.5*6 = 15 → 65
    assert novo == 65.0
    assert status in ("abaixo_do_esperado", "bem_abaixo_do_esperado")


def test_acima_do_alvo_reduz():
    novo, status = calcular_dimmer(lux_medido=20.0, dimmer_atual=50.0, cfg=CFG)
    # erro = 10-20 = -10 ; ajuste = -25 → 25
    assert novo == 25.0
    assert status in ("acima_do_esperado", "bem_acima_do_esperado")


def test_clamp_min_max():
    alto, _ = calcular_dimmer(lux_medido=0.0, dimmer_atual=95.0, cfg=CFG)
    assert alto == 100.0
    baixo, _ = calcular_dimmer(lux_medido=100.0, dimmer_atual=5.0, cfg=CFG)
    assert baixo == 0.0


def test_watts():
    assert calcular_watts(50.0, CFG) == 10.0     # 50% de 20W
    assert calcular_watts(100.0, CFG) == 20.0


# ── Atuador ──────────────────────────────────────────────────────
def test_dimmer_para_pwm():
    assert dimmer_para_pwm(0.0) == 0
    assert dimmer_para_pwm(100.0) == 255
    assert dimmer_para_pwm(50.0) == 127


def test_estado_lampada():
    assert estado_lampada(0.0) == "APAGADA"
    assert estado_lampada(10.0) == "FRACA"
    assert estado_lampada(50.0) == "MEDIA"
    assert estado_lampada(85.0) == "FORTE"
    assert estado_lampada(100.0) == "MAXIMA"


# ── Faixas de vida ───────────────────────────────────────────────
def test_faixas_alvos():
    assert Config().com_faixa(1).lux_alvo == 35.0
    assert Config().com_faixa(2).lux_alvo == 10.0
    assert Config().com_faixa(3).lux_alvo == 90.0


# ── Sensor: feedback da lâmpada e ruído ──────────────────────────
def test_sensor_feedback_dimmer():
    sensor = SensorBH1750(LocalBus(), CFG, lux_natural=0.0, noise_sigma=0.0)
    sensor._on_dimmer("granja/atuador/dimmer/1", '{"dimmer_pct": 50.0}')
    assert sensor.lux_lampada == 7.5   # 50% de 15 lux


def test_sensor_sem_ruido_eh_deterministico():
    sensor = SensorBH1750(LocalBus(), CFG, lux_natural=5.0, noise_sigma=0.0)
    p = sensor.tick()
    assert p["lux"] == 5.0
    assert p["lux_natural"] == 5.0
