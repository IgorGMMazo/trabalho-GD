# ================================================================
#  GÊMEO DIGITAL — SERVIDOR LOCAL (HTTP + SSE, só stdlib)
#
#  Sobe o gêmeo digital num thread de simulação e transmite o estado
#  para o dashboard via Server-Sent Events (SSE) — sem dependências
#  externas, sem internet, sem broker. O navegador recebe o estado
#  por `EventSource` e envia comandos por `fetch` simples.
#
#  Rotas:
#     GET /                → dashboard (dashboard/index.html)
#     GET /stream          → fluxo SSE com o snapshot do gêmeo (JSON)
#     GET /cmd?acao=...    → comandos (faixa, cenário, auto, próximo)
# ================================================================

from __future__ import annotations

import json
import os
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .config import Config
from .twin import CENARIOS, GemeoDigital

DT = 0.5  # passo de simulação (s, tempo real)

_DASHBOARD = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dashboard", "index.html")


class Hub:
    """Mantém o gêmeo, o laço de simulação e os assinantes SSE."""

    def __init__(self, cfg: Config) -> None:
        self.gemeo = GemeoDigital(cfg)
        self._lock = threading.Lock()
        self._subs: list[queue.Queue] = []
        self._ultimo_snapshot: dict | None = None
        self._parar = threading.Event()

    # ── Assinantes SSE ───────────────────────────────────────────
    def assinar(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=4)
        with self._lock:
            self._subs.append(q)
            if self._ultimo_snapshot is not None:
                q.put_nowait(self._ultimo_snapshot)
        return q

    def desassinar(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def _broadcast(self, snap: dict) -> None:
        with self._lock:
            self._ultimo_snapshot = snap
            mortos = []
            for q in self._subs:
                try:
                    q.put_nowait(snap)
                except queue.Full:
                    # consumidor lento: descarta o frame mais antigo
                    try:
                        q.get_nowait()
                        q.put_nowait(snap)
                    except queue.Empty:
                        mortos.append(q)
            for q in mortos:
                self._subs.remove(q)

    # ── Comandos vindos do dashboard ─────────────────────────────
    def comando(self, params: dict) -> None:
        acao = (params.get("acao", [""])[0])
        with self._lock:
            if acao == "faixa":
                self.gemeo.mudar_faixa(int(params.get("valor", ["2"])[0]))
            elif acao == "cenario":
                self.gemeo.motor.modo_auto = False
                self.gemeo.motor.selecionar(int(params.get("valor", ["0"])[0]))
            elif acao == "auto":
                self.gemeo.motor.modo_auto = True
            elif acao == "proximo":
                self.gemeo.motor.modo_auto = False
                self.gemeo.motor.proximo()

    # ── Laço de simulação ────────────────────────────────────────
    def rodar(self) -> None:
        while not self._parar.is_set():
            inicio = time.monotonic()
            with self._lock:
                snap = self.gemeo.tick(DT)
            self._broadcast(snap)
            dormir = DT - (time.monotonic() - inicio)
            if dormir > 0:
                self._parar.wait(dormir)

    def parar(self) -> None:
        self._parar.set()


def criar_handler(hub: Hub):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # silencia o log padrão
            pass

        def _html(self, body: bytes, status: int = 200, ctype: str = "text/html; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)

            if url.path in ("/", "/index.html"):
                try:
                    with open(_DASHBOARD, "rb") as fh:
                        self._html(fh.read())
                except FileNotFoundError:
                    self._html(b"<h1>dashboard/index.html nao encontrado</h1>", 404)
                return

            if url.path == "/cenarios":
                body = json.dumps([
                    {"indice": i, "nome": c.nome, "descricao": c.descricao}
                    for i, c in enumerate(CENARIOS)
                ]).encode("utf-8")
                self._html(body, ctype="application/json")
                return

            if url.path == "/cmd":
                hub.comando(parse_qs(url.query))
                self._html(b'{"ok":true}', ctype="application/json")
                return

            if url.path == "/stream":
                self._stream()
                return

            self._html(b"not found", 404, "text/plain")

        # ── SSE ──────────────────────────────────────────────────
        def _stream(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            q = hub.assinar()
            try:
                while True:
                    snap = q.get()
                    dados = json.dumps(snap, ensure_ascii=False)
                    self.wfile.write(f"data: {dados}\n\n".encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ValueError):
                pass
            finally:
                hub.desassinar(q)

    return Handler


def iniciar_servidor(cfg: Config, host: str = "127.0.0.1", porta: int = 8000):
    hub = Hub(cfg)
    sim = threading.Thread(target=hub.rodar, daemon=True)
    sim.start()
    servidor = ThreadingHTTPServer((host, porta), criar_handler(hub))
    return servidor, hub
