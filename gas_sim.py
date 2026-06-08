# ================================================================
#  GÊMEO DIGITAL — GAS_SIM.PY  (PLANO B / DEMO)
#  Publicador sintético de NH3 — substitui o Wokwi se a rede falhar
#  na apresentação. Publica no MESMO tópico do ESP32.
#
#  Modelagem (cf. fluxo): valor base + ruído gaussiano + tendência
#  controlável pelo teclado, simulando acúmulo de amônia.
#
#  Tópico:  granja/sensor/gas/1
#
#  Uso:
#     python gas_sim.py            # sobe de 5 ppm até ~30 e desce (ciclo)
#     python gas_sim.py --manual   # você controla com +/- no teclado
# ================================================================

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from datetime import datetime

import paho.mqtt.client as mqtt

BROKER = "broker.hivemq.com"
PORT   = 1883
TOPIC  = "granja/sensor/gas/1"
SIGMA  = 0.5     # desvio-padrão do ruído gaussiano do sensor (ppm)


def publicar(client: mqtt.Client, ppm: float) -> None:
    ppm = max(0.0, ppm + random.gauss(0, SIGMA))   # ruído do sensor real
    payload = json.dumps({
        "sensor_id": "1",
        "ppm": round(ppm, 2),
        "unidade": "ppm_NH3",
        "fonte": "sim",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    })
    client.publish(TOPIC, payload, qos=1)
    print(f"{datetime.now():%H:%M:%S}  ->  NH3 = {ppm:5.1f} ppm  ({TOPIC})")


def modo_ciclo(client: mqtt.Client) -> None:
    """Onda senoidal 5→30 ppm: cruza o limiar crítico (25) e volta."""
    print("Modo CICLO — NH3 oscilando 5↔30 ppm (Ctrl+C para sair)")
    t = 0.0
    while True:
        # senoide entre 5 e 30 ppm, período ~40s
        ppm = 17.5 + 12.5 * math.sin(t)
        publicar(client, ppm)
        t += 0.32
        time.sleep(2)


def modo_manual(client: mqtt.Client) -> None:
    """Você digita o nível de NH3 e ele mantém publicando com ruído."""
    print("Modo MANUAL — digite um valor de ppm e Enter (ex: 27). Ctrl+C p/ sair")
    ppm = 8.0
    last = time.time()
    while True:
        # publica a cada 2s
        if time.time() - last >= 2:
            publicar(client, ppm)
            last = time.time()
        # leitura não-bloqueante simples
        try:
            import select
            if select.select([sys.stdin], [], [], 0.2)[0]:
                linha = sys.stdin.readline().strip()
                if linha:
                    ppm = float(linha)
                    print(f"  >> alvo ajustado para {ppm} ppm")
        except (ValueError, OSError):
            pass


def main() -> None:
    ap = argparse.ArgumentParser(description="Simulador sintético de NH3 (fallback do Wokwi)")
    ap.add_argument("--manual", action="store_true", help="controle manual via teclado")
    args = ap.parse_args()

    client = mqtt.Client(
        client_id=f"gas-sim-{int(time.time())}",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    print(f"Conectando ao broker {BROKER}:{PORT} ...")
    client.connect(BROKER, PORT, 60)
    client.loop_start()

    try:
        if args.manual:
            modo_manual(client)
        else:
            modo_ciclo(client)
    except KeyboardInterrupt:
        print("\nEncerrando simulador...")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
