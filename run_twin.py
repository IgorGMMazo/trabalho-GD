#!/usr/bin/env python3
# ================================================================
#  GÊMEO DIGITAL — GRANJA AVÍCOLA · PONTO DE ENTRADA
#
#  Sobe o gêmeo digital (offline, só com a biblioteca padrão do
#  Python) e abre o dashboard no navegador. Tudo roda na sua máquina:
#  sem internet, sem broker MQTT, sem placa.
#
#  Uso:
#     python run_twin.py                 # fase 2 (crescimento), abre o navegador
#     python run_twin.py --faixa 1       # fase de chegada (pintinhos)
#     python run_twin.py --porta 8080    # outra porta
#     python run_twin.py --sem-navegador # não abre o navegador sozinho
# ================================================================

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser

from gemeo_digital.config import Config
from gemeo_digital.server import iniciar_servidor

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description="Gêmeo Digital — Granja Avícola (offline)")
    ap.add_argument("--faixa", type=int, choices=[1, 2, 3], default=2,
                    help="fase de vida das aves (1=chegada, 2=crescimento, 3=final)")
    ap.add_argument("--porta", type=int, default=8000, help="porta HTTP do dashboard")
    ap.add_argument("--host", default="127.0.0.1", help="host de bind")
    ap.add_argument("--sem-navegador", action="store_true", help="não abrir o navegador")
    args = ap.parse_args()

    cfg = Config().com_faixa(args.faixa)
    servidor, hub = iniciar_servidor(cfg, args.host, args.porta)
    url = f"http://{args.host}:{args.porta}/"

    print("=" * 60)
    print("  GÊMEO DIGITAL — GRANJA AVÍCOLA")
    print(f"  Fase inicial : {cfg.fase.nome}")
    print(f"  Dashboard    : {url}")
    print("  Modo         : offline (sem internet / sem MQTT)")
    print("  Ctrl+C para encerrar.")
    print("=" * 60)

    if not args.sem_navegador:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando...")
    finally:
        hub.parar()
        servidor.shutdown()


if __name__ == "__main__":
    main()
