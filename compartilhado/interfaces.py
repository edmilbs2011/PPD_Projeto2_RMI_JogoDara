from __future__ import annotations

from typing import List


class InterfaceServidor:
    """
    Contrato do servidor do jogo Dara.
    Registrado no servidor de nomes Pyro5 como 'jogo.dara'.
    Toda chamada cliente → servidor passa por este contrato.
    """

    def hello(self, apelido: str, nome_callback: str) -> dict:
        """
        Registra o jogador e armazena o nome do seu callback no NS.
        Retorna WELCOME ou ERROR.
        """
        ...

    def pronto(self, id_cliente: str) -> List[dict]:
        """Marca o jogador como pronto. Retorna STATE ou LOBBY."""
        ...

    def colocar(self, id_cliente: str, linha: int, coluna: int) -> List[dict]:
        """Coloca uma peça na fase de colocação. Retorna STATE ou ERROR."""
        ...

    def mover(self, id_cliente: str, fr: int, fc: int, tr: int, tc: int) -> List[dict]:
        """Move uma peça na fase de movimentação. Retorna STATE ou ERROR."""
        ...

    def capturar(self, id_cliente: str, linha: int, coluna: int) -> List[dict]:
        """Captura uma peça do oponente. Retorna STATE, ERROR ou GAME_OVER."""
        ...

    def desistir(self, id_cliente: str) -> List[dict]:
        """Declara desistência. Retorna GAME_OVER."""
        ...

    def nova_partida(self, id_cliente: str) -> List[dict]:
        """Reinicia o jogo. Retorna STATE ou ERROR."""
        ...

    def chat(self, id_cliente: str, texto: str) -> None:
        """Envia mensagem de chat. O servidor chama receber() no outro jogador."""
        ...

    def desconectar(self, id_cliente: str) -> None:
        """Remove o jogador e notifica o oponente via callback."""
        ...


class InterfaceClienteCallback:
    """
    Contrato do callback do cliente.
    Registrado no servidor de nomes Pyro5 como 'dara.cliente.<uuid>'.
    O servidor chama receber() para empurrar notificações diretamente ao cliente
    sem polling — esta é a direção servidor → cliente do RMI bidirecional.
    """

    def receber(self, msgs: List[dict]) -> None:
        """
        Recebe lista de mensagens empurradas pelo servidor.
        Tipos possíveis: STATE, LOBBY, CHAT, GAME_OVER.
        """
        ...
