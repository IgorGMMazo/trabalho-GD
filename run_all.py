# ================================================================
#  GÊMEO DIGITAL — ORQUESTRADOR DO ECOSSISTEMA INTERNO
#
#  Sobe, dentro de um único processo Python (VSCode), os três
#  elementos do gêmeo digital ligados pelo mesmo barramento:
#
#       SensorBH1750  ──lux──►  GranjaController  ──dimmer──►  AtuadorLED
#            ▲                                          │
#            └────────────── feedback de dimmer ────────┘
#
#  Modos:
#    (padrão)  LocalBus  → tudo interno, offline, sem hardware.
#    --mqtt    MqttBus   → conecta no broker.hivemq.com e conversa
#                          com o hardware Wokwi de verdade.
#
#  Exemplos:
#    python run_all.py                  # interativo (escolhe a faixa)
#    python run_all.py --faixa 2        # fase de crescimento
#    python run_all.py --faixa 2 --natural 6 --segundos 20
#    python run_all.py --mqtt --faixa 2 # usa o broker MQTT real
# ================================================================

from __future__ import annotations

import argparse
import logging
import math
import sys
import time

# Console do Windows costuma ser cp1252; força UTF-8 para os acentos/ícones.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from gemeo_digital import (
    Config, FAIXAS, LocalBus, MqttBus,
    GranjaController, SensorBH1750, AtuadorLED,
)


def escolher_faixa() -> int:
    while True:
        print("Qual fase de vida os animais (Galinhas/Pintos) estão?")
        for k, f in FAIXAS.items():
            print(f"  {k} - {f.nome}  (alvo {f.alvo:.0f} lux)")
        try:
            faixa = int(input("> "))
        except ValueError:
            faixa = -1
        if faixa in FAIXAS:
            return faixa
        print("Coloque um dos valores válidos (1, 2 ou 3)\n")


def construir_ambiente(natural: float, dia_noite: bool):
    """Retorna lux_natural como valor fixo ou curva senoidal dia/noite."""
    if not dia_noite:
        return natural
    # Curva suave variando de ~0 (noite) a `natural` (pico), período 20 s
    return lambda t: max(0.0, natural * (0.5 + 0.5 * math.sin(2 * math.pi * t / 20.0)))


def main() -> None:
    ap = argparse.ArgumentParser(description="Gêmeo Digital — ecossistema interno")
    ap.add_argument("--faixa", type=int, choices=[1, 2, 3], help="fase de vida (senão pergunta)")
    ap.add_argument("--natural", type=float, default=2.0, help="lux de luz natural ambiente")
    ap.add_argument("--dia-noite", action="store_true", help="varia a luz natural (senoidal)")
    ap.add_argument("--segundos", type=float, default=15.0, help="duração da simulação")
    ap.add_argument("--intervalo", type=float, default=1.0, help="intervalo de leitura do sensor")
    ap.add_argument("--mqtt", action="store_true", help="usa broker MQTT real (HiveMQ)")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    faixa = args.faixa or escolher_faixa()
    cfg = Config().com_faixa(faixa)
    f = FAIXAS[faixa]
    print(f"\n► Faixa: {f.nome} | alvo={cfg.lux_alvo:.0f} lux "
          f"(min={cfg.lux_min:.0f}/max={cfg.lux_max:.0f}) | lâmpada≤{cfg.lux_max_lampada:.0f} lux\n")

    # Transporte
    if args.mqtt:
        bus = MqttBus(cfg.broker, cfg.port, cfg.keepalive)
        bus.start()
        if not bus.wait_connected(10):
            print("Não foi possível conectar ao broker MQTT.")
            return
    else:
        bus = LocalBus()

    # Componentes
    atuador = AtuadorLED(bus, cfg, atuador_id="1")
    controlador = GranjaController(bus, cfg)
    sensor = SensorBH1750(
        bus, cfg, sensor_id="1",
        lux_natural=construir_ambiente(args.natural, args.dia_noite),
    )

    atuador.start()
    controlador.start()
    sensor.start()

    # Laço de simulação
    t_fim = time.monotonic() + args.segundos
    try:
        while time.monotonic() < t_fim:
            sensor.tick()
            est = controlador.estados.get("1")
            lamp = atuador.estado
            if est:
                print(f"   lux={est.lux:5.1f}  alvo={cfg.lux_alvo:4.0f}  "
                      f"dimmer={est.dimmer_pct:5.1f}%  {lamp.estado:7s}  "
                      f"status={est.status}")
            time.sleep(args.intervalo)
    except KeyboardInterrupt:
        print("\nEncerrando...")
    finally:
        bus.stop()

    est = controlador.estados.get("1")
    if est:
        print(f"\n✓ Estado final: lux={est.lux:.1f} (alvo {cfg.lux_alvo:.0f}), "
              f"dimmer={est.dimmer_pct:.1f}%, lâmpada={atuador.estado.estado}, "
              f"mensagens processadas={est.total_mensagens}")


if __name__ == "__main__":
    main()
