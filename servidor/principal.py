from __future__ import annotations

import argparse

import Pyro5.api

from servidor.aplicacao.aplicacao_servidor import AplicacaoServidor


def executar() -> None:
    parser = argparse.ArgumentParser(description="Servidor Dara (RMI/Pyro5)")
    parser.add_argument("--host", default="localhost",
                        help="Host/IP em que o daemon do jogo vai escutar")
    parser.add_argument("--port", type=int, default=9000,
                        help="Porta do daemon do jogo")
    parser.add_argument("--ns-host", default="localhost",
                        help="Host/IP do servidor de nomes Pyro5")
    parser.add_argument("--ns-port", type=int, default=9090,
                        help="Porta do servidor de nomes Pyro5")
    args = parser.parse_args()

    # Instancia o servidor passando as coordenadas do NS para que ele possa
    # resolver os callbacks dos clientes (registrados como 'dara.cliente.<uuid>').
    servidor = AplicacaoServidor(ns_host=args.ns_host, ns_porta=args.ns_port)

    with Pyro5.api.Daemon(host=args.host, port=args.port) as daemon:
        uri = daemon.register(servidor, objectId="jogo.dara")

        print(f"Servidor Dara RMI v3.0 iniciado")
        print(f"URI do daemon: {uri}")

        try:
            ns = Pyro5.api.locate_ns(host=args.ns_host, port=args.ns_port)
            ns.register("jogo.dara", uri)
            ns._pyroRelease()
            print(f"Registrado no servidor de nomes ({args.ns_host}:{args.ns_port}) como 'jogo.dara'")
        except Exception as e:
            print(f"AVISO: não foi possível registrar no servidor de nomes: {e}")
            print(f"Clientes podem usar a URI direta: {uri}")

        try:
            daemon.requestLoop()
        finally:
            try:
                ns = Pyro5.api.locate_ns(host=args.ns_host, port=args.ns_port)
                ns.remove("jogo.dara")
                ns._pyroRelease()
                print("\nRemovido do servidor de nomes.")
            except Exception:
                pass


if __name__ == "__main__":
    executar()
