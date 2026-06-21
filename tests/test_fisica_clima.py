# Testes da física do ambiente e das fórmulas de clima.
import math

import pytest

from gemeo_digital.config import Config
from gemeo_digital.environment import (Ambiente, ComandosAtuadores,
                                       CondicoesExternas, calcular_itu,
                                       ponto_de_orvalho)

CFG = Config()


# ── Fórmulas de clima (devem bater com o firmware) ──────────────
def test_ponto_orvalho_monotonico_com_umidade():
    # Mais umidade → ponto de orvalho mais alto, à mesma temperatura.
    assert ponto_de_orvalho(25, 80) > ponto_de_orvalho(25, 40)


def test_itu_cresce_com_temp_e_umidade():
    assert calcular_itu(30, 60) > calcular_itu(25, 60)
    assert calcular_itu(28, 80) > calcular_itu(28, 50)


def test_itu_formula_thom():
    # ITU = T + 0.36*Tpo + 41.5
    t, u = 26.0, 60.0
    esperado = t + 0.36 * ponto_de_orvalho(t, u) + 41.5
    assert calcular_itu(t, u) == pytest.approx(esperado)


# ── Dinâmica do ambiente ────────────────────────────────────────
def _regime(amb, cmd, ext, passos=4000, dt=0.5):
    for _ in range(passos):
        amb.step(cmd, ext, dt)
    return amb


def test_ventilacao_resfria_em_direcao_ao_exterior():
    ext = CondicoesExternas(temp_ext=15.0, umid_ext=50.0, sujeira_cama=1.0)
    quente = _regime(Ambiente(CFG.fisica, temp_C=30), ComandosAtuadores(exaustor=1.0), ext)
    fechado = _regime(Ambiente(CFG.fisica, temp_C=30), ComandosAtuadores(exaustor=0.0), ext)
    # Com exaustor ligado, o galpão fica MAIS FRIO (mais perto do exterior).
    assert quente.temp_C < fechado.temp_C
    assert quente.temp_C < 30


def test_aquecedor_eleva_temperatura():
    ext = CondicoesExternas(temp_ext=10.0, umid_ext=55.0, sujeira_cama=1.0)
    com = _regime(Ambiente(CFG.fisica, temp_C=15), ComandosAtuadores(aquecedor=1.0), ext)
    sem = _regime(Ambiente(CFG.fisica, temp_C=15), ComandosAtuadores(aquecedor=0.0), ext)
    assert com.temp_C > sem.temp_C


def test_cross_effect_aquecedor_aumenta_nh3():
    # Efeito cruzado clima→gases: mais calor → mais volatilização de amônia.
    ext = CondicoesExternas(temp_ext=20.0, umid_ext=60.0, sujeira_cama=1.5)
    quente = _regime(Ambiente(CFG.fisica, temp_C=20, nh3_ppm=10),
                     ComandosAtuadores(exaustor=0.15, aquecedor=1.0), ext, passos=600)
    frio = _regime(Ambiente(CFG.fisica, temp_C=20, nh3_ppm=10),
                   ComandosAtuadores(exaustor=0.15, aquecedor=0.0), ext, passos=600)
    assert quente.nh3_ppm > frio.nh3_ppm


def test_ventilacao_remove_amonia():
    ext = CondicoesExternas(temp_ext=22.0, umid_ext=60.0, sujeira_cama=2.0)
    ventilado = _regime(Ambiente(CFG.fisica, nh3_ppm=20), ComandosAtuadores(exaustor=1.0), ext, passos=400)
    parado = _regime(Ambiente(CFG.fisica, nh3_ppm=20), ComandosAtuadores(exaustor=0.0), ext, passos=400)
    assert ventilado.nh3_ppm < parado.nh3_ppm


def test_lampada_adiciona_calor():
    # Efeito cruzado luz→clima (lâmpada incandescente esquenta um pouco).
    ext = CondicoesExternas(temp_ext=20.0, umid_ext=55.0, sujeira_cama=0.5)
    com = _regime(Ambiente(CFG.fisica, temp_C=20), ComandosAtuadores(lampada=1.0), ext)
    sem = _regime(Ambiente(CFG.fisica, temp_C=20), ComandosAtuadores(lampada=0.0), ext)
    assert com.temp_C > sem.temp_C
