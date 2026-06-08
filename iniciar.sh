#!/usr/bin/env bash
# ================================================================
#  GÊMEO DIGITAL — INICIAR.SH
#  Sobe tudo da vertente de GASES de uma vez:
#    1) garante o paho-mqtt
#    2) abre o dashboard no navegador
#    3) inicia o cérebro (gas_control.py)
#    4) inicia o simulador de NH3 (gas_sim.py) como fonte de dados
#
#  Uso:
#    ./iniciar.sh          # cérebro + simulador + dashboard (demo completo)
#    ./iniciar.sh wokwi    # cérebro + dashboard (os dados vêm do Wokwi)
#
#  Para parar tudo: feche este terminal ou aperte Ctrl+C.
# ================================================================
set -e
cd "$(dirname "$0")"

echo "==> Verificando paho-mqtt..."
python3 -c "import paho.mqtt" 2>/dev/null || \
  pip3 install --user --break-system-packages -q paho-mqtt

echo "==> Abrindo dashboard.html no navegador..."
xdg-open "dashboard.html" >/dev/null 2>&1 || true
sleep 1

# Mata processos antigos do projeto (evita duplicar)
pkill -f gas_control.py 2>/dev/null || true
pkill -f gas_sim.py 2>/dev/null || true
sleep 1

echo "==> Iniciando o cérebro (gas_control.py)..."
python3 gas_control.py &
PID_CTRL=$!
sleep 2

# Encerra o cérebro quando este script for fechado
trap "echo; echo '==> Encerrando...'; kill $PID_CTRL 2>/dev/null; pkill -f gas_sim.py 2>/dev/null; exit 0" INT TERM

if [ "$1" == "wokwi" ]; then
  echo
  echo "============================================================"
  echo "  Cérebro + dashboard no ar. Agora dê PLAY no Wokwi."
  echo "  (gire o potenciômetro para simular a amônia)"
  echo "  Ctrl+C aqui para encerrar tudo."
  echo "============================================================"
  wait $PID_CTRL
else
  echo "==> Iniciando o simulador de NH3 (gas_sim.py)..."
  echo
  echo "============================================================"
  echo "  Tudo no ar! Veja o gráfico subir no dashboard."
  echo "  Ctrl+C aqui para encerrar tudo."
  echo "============================================================"
  python3 gas_sim.py
fi
