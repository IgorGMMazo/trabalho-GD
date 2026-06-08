# Gêmeo Digital — Granja Avícola 🐔

Sistema de **gêmeo digital** que monitora o ambiente de uma granja e atua para
mantê-lo no equilíbrio homeostático ideal para as aves. Duas vertentes:

| Vertente | Sensor | Atuador | Cérebro |
|----------|--------|---------|---------|
| **Luminosidade** | LDR / BH1750 (lux) | Dimmer da lâmpada | [`control.py`](control.py) |
| **Gases (NH₃)** | MQ-135 / MQ-137 (ppm) | Exaustor | [`gas_control.py`](gas_control.py) |

Todos os componentes conversam por **MQTT** (broker `broker.hivemq.com`),
fechando o ciclo **sensor → cérebro → atuador → dashboard**.

```
  ┌──────────────┐   granja/sensor/gas/1   ┌────────────────┐
  │ ESP32 (Wokwi)│ ──────────────────────► │  gas_control.py │
  │  MQ-135 sim  │                          │  (controlador)  │
  └──────────────┘ ◄────────────────────── └────────────────┘
        ▲           granja/atuador/exaustor/1        │
        │ LED exaustor + LED alerta                  │ granja/status/gas/1
        │                                            ▼
        └───────────── feedback loop ──────► dashboard.html (tempo real)
```

---

## Vertente de GASES — passo a passo da apresentação

### 0. Instalar dependências (uma vez)
```bash
pip install -r requirements.txt
```

### 1. Subir o cérebro (controlador do exaustor)
```bash
python gas_control.py
```
Calcula a potência do exaustor a partir do NH₃ e publica os comandos/estado.

### 2. Abrir o dashboard
Abra **`dashboard.html`** no navegador (duplo clique). Ele assina o broker
por WebSocket e mostra ppm, potência do exaustor, estado e gráfico ao vivo.
*(Não precisa de servidor — é HTML puro.)*

### 3. Gerar leituras de NH₃ — escolha **A** ou **B**

**A) Wokwi (principal):** abra o projeto em `wokwi/` (veja
[`wokwi/README.md`](wokwi/README.md)), dê Play e **gire o potenciômetro**
para simular o acúmulo de amônia.

**B) Fallback sintético (se a rede do Wokwi falhar ao vivo):**
```bash
python gas_sim.py            # ciclo automático 5↔30 ppm
python gas_sim.py --manual   # você digita o ppm no teclado
```

### Roteiro sugerido para a banca
1. NH₃ baixo (~8 ppm) → estado 🟢 **bom**, exaustor em ventilação base (15%).
2. Subir para ~18 ppm → 🔵 **elevado**, exaustor sobe proporcionalmente.
3. Passar de **25 ppm** → 🔴 **crítico**: banner de ALERTA, exaustor 100%,
   LED vermelho do ESP32 acende. **Aqui se mostra o feedback loop.**
4. Baixar de novo → o sistema relaxa o exaustor sozinho.

---

## Limiares de amônia (base zootécnica)

| NH₃ (ppm) | Estado | Ação |
|-----------|--------|------|
| < 10 | 🟢 bom | ventilação base (15%) |
| 10–20 | 🔵 elevado | exaustor proporcional |
| 20–25 | 🟡 atenção | exaustor alto |
| ≥ 25 | 🔴 crítico | exaustor 100% + ALERTA (lesão respiratória) |

Ajuste os limiares e ganhos em `Config` no topo de
[`gas_control.py`](gas_control.py).

## Tópicos MQTT

| Tópico | Direção | Conteúdo |
|--------|---------|----------|
| `granja/sensor/gas/{id}`   | ESP32/sim → cérebro | `{"ppm": 18.4}` |
| `granja/atuador/exaustor/{id}` | cérebro → ESP32 | `{"exaustor_pct": 72, "alerta": false}` |
| `granja/status/gas/{id}`   | cérebro → dashboard | estado completo |
