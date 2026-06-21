# ================================================================
#  GÊMEO DIGITAL — CAMADA DE TRANSPORTE (BUS)
#
#  Abstrai a comunicação por tópicos para que o mesmo código de
#  controlador / sensor / atuador rode em dois modos:
#
#    LocalBus → pub/sub MQTT-style 100% em processo (offline,
#               determinístico) — usado para rodar o ecossistema
#               interno no VSCode e nos testes.
#
#    MqttBus  → paho-mqtt conectando num broker real (HiveMQ ou
#               mosquitto local) para conversar com o hardware
#               Wokwi de verdade.
#
#  Ambos respeitam os curingas MQTT '+' (um nível) e '#' (resto).
# ================================================================

from __future__ import annotations

import threading
import time
from typing import Callable, List, Tuple

Callback = Callable[[str, str], None]  # (topic, payload_str) -> None


def topic_matches(filtro: str, topic: str) -> bool:
    """Implementa o casamento de curingas MQTT ('+' e '#')."""
    f = filtro.split("/")
    t = topic.split("/")
    for i, parte in enumerate(f):
        if parte == "#":
            return True
        if i >= len(t):
            return False
        if parte == "+":
            continue
        if parte != t[i]:
            return False
    return len(f) == len(t)


class Bus:
    """Interface comum dos transportes."""

    def publish(self, topic: str, payload: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def subscribe(self, topic_filter: str, callback: Callback) -> None:  # pragma: no cover
        raise NotImplementedError

    def start(self) -> None:  # pragma: no cover
        pass

    def stop(self) -> None:  # pragma: no cover
        pass


# ────────────────────────────────────────────────────────────────
#  LOCALBUS — broker em processo
# ────────────────────────────────────────────────────────────────
class LocalBus(Bus):
    """
    Mini-broker em memória. Entrega as mensagens de forma síncrona
    no mesmo thread de quem publica — o que torna o fluxo
    sensor→controlador→atuador totalmente determinístico nos testes.
    """

    def __init__(self) -> None:
        self._subs: List[Tuple[str, Callback]] = []
        self._lock = threading.RLock()

    def publish(self, topic: str, payload: str) -> None:
        with self._lock:
            alvos = [cb for filtro, cb in self._subs if topic_matches(filtro, topic)]
        for cb in alvos:
            cb(topic, payload)

    def subscribe(self, topic_filter: str, callback: Callback) -> None:
        with self._lock:
            self._subs.append((topic_filter, callback))


# ────────────────────────────────────────────────────────────────
#  MQTTBUS — broker real via paho-mqtt
# ────────────────────────────────────────────────────────────────
class MqttBus(Bus):
    """Adaptador paho-mqtt (callback API v2). Conecta no broker real."""

    def __init__(self, broker: str, port: int = 1883, keepalive: int = 60,
                 client_id: str | None = None) -> None:
        import paho.mqtt.client as mqtt  # import tardio: só quando usado

        self._mqtt = mqtt
        self._broker = broker
        self._port = port
        self._keepalive = keepalive
        self._subs: List[Tuple[str, Callback]] = []
        self._connected = threading.Event()

        self._client = mqtt.Client(
            client_id=client_id or f"gd-bus-{int(time.time())}",
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code == 0:
            self._connected.set()
            for filtro, _ in self._subs:
                client.subscribe(filtro, qos=1)

    def _on_message(self, client, userdata, msg) -> None:
        payload = msg.payload.decode("utf-8", errors="replace")
        for filtro, cb in self._subs:
            if topic_matches(filtro, msg.topic):
                cb(msg.topic, payload)

    def publish(self, topic: str, payload: str) -> None:
        self._client.publish(topic, payload, qos=1)

    def subscribe(self, topic_filter: str, callback: Callback) -> None:
        self._subs.append((topic_filter, callback))
        if self._connected.is_set():
            self._client.subscribe(topic_filter, qos=1)

    def start(self) -> None:
        self._client.connect_async(self._broker, self._port, keepalive=self._keepalive)
        self._client.loop_start()

    def stop(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def wait_connected(self, timeout: float = 10.0) -> bool:
        return self._connected.wait(timeout)
