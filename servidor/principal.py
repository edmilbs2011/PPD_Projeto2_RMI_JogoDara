from __future__ import annotations

import argparse

import Pyro5.api

from servidor.aplicacao.aplicacao_servidor import AplicacaoServidor


def executar() -> None:
    parser = argparse.ArgumentParser(description="Servidor Dara (RMI/Pyro5)")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=9000)
    args = parser.parse_args()

    with Pyro5.api.Daemon(host=args.host, port=args.port) as daemon:
        uri = daemon.register(AplicacaoServidor, objectId="jogo.dara")
        print(f"Servidor Dara RMI v2.0 iniciado")
        print(f"URI: {uri}")
        print(f"Clientes devem usar: PYRO:jogo.dara@{args.host}:{args.port}")
        daemon.requestLoop()


if __name__ == "__main__":
    executar()
