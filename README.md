# Gêmeo Digital — Granja (v2, ecossistema interno)

Recriação **100% em Python, dentro do VSCode**, de todo o ecossistema de
controle de iluminação de granja que antes dependia de hardware externo
(dois ESP32 no Wokwi) + `control.py`.

Agora o controlador, o **sensor** e o **atuador** rodam como código local,
ligados por um barramento de tópicos. Dá para rodar tudo offline (sem
internet, sem broker, sem placa) **ou** conectar no broker MQTT real e
conversar com o hardware Wokwi de verdade.

## Arquitetura

```
   SensorBH1750  ──lux──►  GranjaController  ──dimmer──►  AtuadorLED
        ▲                                          │
        └────────────── feedback de dimmer ────────┘
```

| Tópico                         | Quem publica   | Quem assina            |
|--------------------------------|----------------|------------------------|
| `granja/sensor/lux/{id}`       | Sensor         | Controlador            |
| `granja/atuador/dimmer/{id}`   | Controlador    | Atuador **e** Sensor   |
| `granja/status/{id}`           | Controlador    | (dashboard)            |

### Camada de transporte (`Bus`)
- **`LocalBus`** — mini-broker em memória, entrega síncrona, com curingas
  MQTT (`+`, `#`). Usado para rodar tudo interno e nos testes (determinístico).
- **`MqttBus`** — adaptador `paho-mqtt` (API v2) para o broker real
  (`broker.hivemq.com`). Mesmos tópicos e payloads do firmware → conversa
  com o hardware Wokwi sem alteração.

### Fidelidade ao original
- **Controlador** (`gemeo_digital/controller.py`): controle P com deadband,
  idêntico ao `referencia_control.py` (cópia do `control.py` original).
- **Sensor** (`gemeo_digital/sensor.py`): réplica do firmware do projeto
  Wokwi `466033186398196737` — `lux_total = lux_natural + lux_lampada +
  ruído gaussiano(σ=0.5)`, lâmpada ≤ 15 lux.
- **Atuador** (`gemeo_digital/atuador.py`): réplica do firmware do projeto
  Wokwi `466029783767796737` — `dimmer_pct → PWM 8-bit`, estados
  APAGADA/FRACA/MEDIA/FORTE/MAXIMA.
- Os sketches `.ino` originais ficam em `hardware_wokwi/` como referência.

## Como rodar

```powershell
# 1. Criar o ambiente e instalar dependências
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. Rodar o ecossistema interno (offline)
.\venv\Scripts\python.exe run_all.py --faixa 2 --natural 1 --segundos 15

# 3. Variar a luz natural (ciclo dia/noite senoidal)
.\venv\Scripts\python.exe run_all.py --faixa 1 --natural 40 --dia-noite

# 4. Conectar no broker MQTT real (e ao hardware Wokwi)
.\venv\Scripts\python.exe run_all.py --mqtt --faixa 2
```

Sem `--faixa`, o programa pergunta a fase de vida como o `control.py` original.

### Faixas de vida (alvo de iluminância)
| Fase | Descrição                         | Alvo (lux) |
|------|-----------------------------------|------------|
| 1    | Chegada (primeiros 7 dias)        | 35         |
| 2    | Crescimento (7 dias em diante)    | 10         |
| 3    | Fase final (perto do abate)       | 90         |

> Como a lâmpada entrega no máximo 15 lux, a fase 2 é totalmente controlável
> só pela lâmpada; as fases 1 e 3 dependem também de luz natural.

## Testes

```powershell
.\venv\Scripts\python.exe -m pytest
```

- `tests/test_logic.py` — lógica pura (curingas de tópico, controle P,
  PWM, estados, ruído, faixas).
- `tests/test_integration.py` — malha fechada completa sobre o `LocalBus`:
  convergência ao alvo, corte da lâmpada com excesso de luz natural,
  fluxo de mensagens nos três tópicos e robustez com ruído.

## Estrutura

```
trabaho-GD_v2/
├── gemeo_digital/        # pacote do ecossistema
│   ├── config.py         # parâmetros + faixas de vida
│   ├── bus.py            # LocalBus / MqttBus
│   ├── controller.py     # cérebro (P + deadband)
│   ├── sensor.py         # simulação ESP32 + BH1750
│   └── atuador.py        # simulação ESP32 + LED
├── hardware_wokwi/       # sketches .ino de referência
├── tests/                # pytest
├── run_all.py            # orquestrador do ecossistema
├── referencia_control.py # cópia do control.py original
└── requirements.txt
```
