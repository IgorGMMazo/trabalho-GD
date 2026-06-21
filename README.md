# 🐔 Gêmeo Digital — Granja Avícola (3 eixos + supervisor de bem-estar)

Gêmeo digital **reativo** de uma granja que monitora e atua sobre **três eixos
ambientais ao mesmo tempo**, sobre um **ambiente físico compartilhado**, com um
**supervisor que arbitra os conflitos entre os atuadores** segundo uma hierarquia
de **bem-estar animal**.

| Eixo | Sensor (Wokwi/ESP32) | Atuador | Limiares |
|------|----------------------|---------|----------|
| **Luz** | BH1750 (lux) | Lâmpada (dimmer) | alvo por fase de vida |
| **Clima** | DHT22 (temp/umid → ITU) | Aquecedor + cortina/ventilação | curva de aquecimento; ITU 74/78 |
| **Gases** | MQ-135 (NH₃ ppm) | Exaustor | 10 / 20 / 25 ppm |

> Roda **100% offline** — só com a biblioteca padrão do Python. Sem internet, sem
> broker MQTT, sem placa. O dashboard é um gêmeo digital animado servido por
> HTTP + SSE local.

```bash
python run_twin.py            # abre http://127.0.0.1:8000 no navegador
python run_twin.py --faixa 1  # fase de chegada (pintinhos)
```

---

## Por que isso não são três sistemas separados

Os três eixos **compartilham o mesmo ar do galpão**. Um atuador acionado para
resolver **um** problema afeta os **outros**:

| Atuador | Resolve | Efeito cruzado |
|---------|---------|----------------|
| **Exaustor** | ↓ NH₃ (gases) | ↓ temperatura e ↓ umidade → **gela pintinhos** |
| **Aquecedor** | frio (clima) | ↑ volatilização de NH₃ da cama → **piora os gases** |
| **Cortina/ventilação** | calor (clima) | = exaustor: resfria e limpa o ar |
| **Lâmpada** | luz | adiciona calor (relevante em incandescente) |

O **exaustor é um recurso ÚNICO** disputado pelos eixos gases e clima, e
**aquecedor × exaustor são fisicamente opostos**. Por isso existe o **supervisor**.

### Hierarquia de bem-estar do supervisor
1. **Risco térmico letal** (frio em pintinhos / calor extremo)
2. **Amônia tóxica** (NH₃ ≥ 25 ppm)
3. **Conforto lumínico**

**Regra de ouro:** nunca resfriar além do *teto seguro da fase* para combater
amônia — em vez disso, ventila o tolerável e **compensa com o aquecedor**,
registrando o conflito. No calor, ventilar **resolve dois eixos** (sinergia).

---

## Arquitetura

```
        ┌──────────── AMBIENTE FÍSICO COMPARTILHADO (galpão) ────────────┐
        │      temperatura · umidade · NH₃ · luz natural  (EDOs)         │
        └──────▲──────────────────────────────────────────────▲─────────┘
               │ lê                                    aplica  │
        ┌──────┴─────┐   ┌──────────────┐   ┌──────────────────┴─────────┐
        │  SENSORES  │ ─►│ CONTROLADORES│ ─►│        SUPERVISOR           │
        │ lux·clima  │   │  1 por eixo  │   │ arbitra conflitos por       │
        │   ·gás     │   │  (P + dead)  │   │ bem-estar → comanda tudo    │
        └────────────┘   └──────────────┘   └─────────────────────────────┘
```

```
gemeo_digital/
├── config.py       # fases de vida, limiares zootécnicos, física do galpão
├── environment.py  # ambiente físico compartilhado (acoplamentos) + ITU
├── sensors.py      # réplica do firmware: BH1750, DHT22, MQ-135 (com ruído)
├── controllers.py  # um controlador P por eixo (propõem demandas)
├── supervisor.py   # arbitragem de conflitos por hierarquia de bem-estar
├── twin.py         # orquestrador + motor de cenários cíclicos
└── server.py       # servidor HTTP + SSE (stdlib) que serve o dashboard
dashboard/index.html # interface do gêmeo digital (SVG/Canvas animados)
hardware_wokwi/      # firmware .ino e diagramas de referência (ESP32)
tests/               # 22 testes (física, controladores e conflitos)
slides/              # apresentação (.pptx) + gerador
run_twin.py          # ponto de entrada
```

---

## Cenários (cíclicos e automáticos)

O dashboard percorre — e você pode selecionar manualmente:

1. **Operação normal** — tudo em conforto.
2. **Acúmulo de amônia** — cama saturada; exaustor reage.
3. **Onda de calor** — ITU sobe; ventilação máxima + sinergia com gases.
4. **Noite fria** — aquecedor protege as aves.
5. **Conflito crítico: frio + amônia tóxica** — o supervisor arbitra para
   **não matar de frio** (exaustor limitado + aquecedor compensando).

Tudo isso para as 3 fases de vida (chegada / crescimento / final).

---

## Testes

```bash
pip install pytest        # opcional
python -m pytest          # 22 testes
```

Cobrem a física (ventilação resfria, aquecedor aquece e eleva NH₃…), os
controladores e — o mais importante — a **arbitragem de conflitos** do supervisor.

---

## Análise crítica — decisões e correções feitas no caminho

- **Conflito frio×amônia é um trade-off real, não mágica:** na fase 1 a
  ventilação sozinha **não** resolve a amônia sem congelar os pintinhos. O gêmeo
  evidencia que, na chegada, o controle de NH₃ depende de **manejo de cama**.
- **ITU não se aplica a pintinhos:** a 32 °C (conforto do pinto) a fórmula de
  Thom já daria “crítico”, o que faria o sistema **resfriar a temperatura que o
  pinto precisa**. Corrigido: na fase 1 o clima é guiado pela **banda térmica**, e
  o ITU 74/78 só vale para as fases 2–3 (aves crescidas).
- **Bug do projeto original corrigido:** a fase final tinha `lux_alvo = 90` com
  `min/max` invertidos no `control.py`. Frangos de corte são mantidos em luz baixa
  (5–20 lux) na fase final — corrigido para ~20 lux.
- **Limitação assumida:** o modelo físico é de 1ª ordem com constantes calibradas
  empiricamente, **não validadas com dados reais**.

---

## Slides

`slides/gemeo_digital_granja.pptx` (25 slides) cobre todos os tópicos exigidos,
com ênfase em **análise crítica**. Para regenerar:

```bash
pip install python-pptx
python slides/gerar_slides.py
```

---

## Sem banco de dados (por enquanto)

O gêmeo é **reativo** ao estado instantâneo — decide a cada ciclo a partir das
leituras atuais, sem histórico persistido. **Análise preditiva** (séries
temporais / ML, controle preditivo) é **trabalho futuro**.

---

## Hardware real (opcional)

Os firmwares `.ino` e diagramas em `hardware_wokwi/` são a referência ESP32/Wokwi.
Os payloads e tópicos MQTT (`granja/sensor/...`, `granja/atuador/...`) são os
mesmos do hardware, então um modo híbrido (Python ↔ Wokwi via MQTT) é uma extensão
direta — mantida como trabalho futuro.

---

### Projeto legado (vertentes originais)

Os arquivos `control.py`, `gas_control.py`, `gas_sim.py`, `dashboard.html` e
`wokwi/` são as **vertentes originais** (luz e gases, via MQTT) que serviram de
base. O gêmeo de 3 eixos descrito acima é a evolução integrada delas.
