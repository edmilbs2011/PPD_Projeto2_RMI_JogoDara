from __future__ import annotations

import threading
import uuid
from typing import Dict, List, Optional

import Pyro5.api

from servidor.dominio.estado_partida import (
    JogadorConectado,
    Partida,
    criar_nova_partida,
)
from servidor.dominio import regras

VERSAO_DO_SERVIDOR = "2.0"


@Pyro5.api.expose
@Pyro5.api.behavior(instance_mode="single")
class AplicacaoServidor:
    """
    Servidor do Jogo Dara exposto via RMI com Pyro5.

    Cada método exposto retorna a resposta diretamente ao chamador como
    valor de retorno Python. Não há fila de mensagens por cliente.

    O cliente que fez a chamada recebe a resposta pelo retorno da função.
    O outro jogador (não chamador) usa polling via obter_estado(), que
    deriva o estado atual diretamente do jogo sem nenhuma fila.

    Dois mini-buffers são mantidos:
      _resultados : GAME_OVER por cliente — necessário porque partida_atual
                    é zerado ao encerrar o jogo, tornando-o irrecuperável.
      _chats      : mensagens de chat por cliente — necessário porque chat é
                    broadcast; não há como derivá-lo do estado atual do jogo.

    Para evitar redesenhos desnecessários a cada 50 ms, o servidor mantém
    um contador _versao que é incrementado a cada mudança de estado.
    obter_estado() só inclui STATE/LOBBY quando _versao > versao_cliente.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.jogadores_por_cliente: Dict[str, JogadorConectado] = {}
        self.partida_atual: Optional[Partida] = None
        self._versao: int = 0
        self._resultados: Dict[str, Optional[dict]] = {}   # GAME_OVER pendente
        self._chats: Dict[str, List[dict]] = {}            # chat pendente

    # ------------------------------------------------------------------ #
    #  Métodos expostos — retornam a resposta diretamente ao chamador    #
    # ------------------------------------------------------------------ #

    def hello(self, apelido: str) -> dict:
        """
        Registra o jogador. Retorna WELCOME ou ERROR diretamente.
        O id_cliente do payload deve ser usado em todas as chamadas seguintes.
        """
        with self._lock:
            apelido = str(apelido).strip()
            if not apelido:
                return {"type": "ERROR", "payload": {"code": "BAD_NICK", "message": "Nickname obrigatório"}}

            ids_usados = {j.identificador_jogador for j in self.jogadores_por_cliente.values()}
            if 1 not in ids_usados:
                id_jogador = 1
            elif 2 not in ids_usados:
                id_jogador = 2
            else:
                return {"type": "ERROR", "payload": {"code": "FULL", "message": "Servidor cheio (2 jogadores)."}}

            id_cliente = str(uuid.uuid4())
            self.jogadores_por_cliente[id_cliente] = JogadorConectado(
                identificador_cliente=id_cliente,
                apelido=apelido,
                identificador_jogador=id_jogador,
            )
            self._resultados[id_cliente] = None
            self._chats[id_cliente] = []

            self._versao += 1
            self._tentar_criar_partida()

            return {
                "type": "WELCOME",
                "payload": {
                    "id_cliente": id_cliente,
                    "you": id_jogador,
                    "nickname": apelido,
                    "server_version": VERSAO_DO_SERVIDOR,
                },
            }

    def obter_estado(self, id_cliente: str, versao_cliente: int = -1) -> List[dict]:
        """
        Polling do outro jogador — deriva o estado atual sem usar fila.

        Retorna apenas quando algo mudou (_versao > versao_cliente),
        mais quaisquer GAME_OVER ou CHAT pendentes (inevitavelmente buffered).
        """
        with self._lock:
            msgs: List[dict] = []

            # Buffer de mensagens pendentes (chat e STATE final de fim de partida).
            # Processado antes de GAME_OVER para garantir que o tabuleiro seja
            # atualizado no cliente antes da notificação de fim de jogo.
            chats = self._chats.get(id_cliente, [])
            if chats:
                msgs.extend(chats)
                self._chats[id_cliente] = []

            # GAME_OVER é transitório: após partida_atual = None o estado
            # não pode mais ser derivado, por isso é guardado até ser lido.
            resultado = self._resultados.get(id_cliente)
            if resultado is not None:
                msgs.append({"type": "GAME_OVER", "payload": resultado})
                self._resultados[id_cliente] = None

            # STATE ou LOBBY: derivados ao vivo do estado atual.
            # Só enviados quando algo mudou desde o último poll do cliente.
            if self._versao > versao_cliente:
                if self.partida_atual:
                    jogador = self.jogadores_por_cliente.get(id_cliente)
                    if jogador:
                        msgs.append(self._msg_state(jogador))
                else:
                    msgs.append(self._msg_lobby())

            return msgs

    def pronto(self, id_cliente: str) -> List[dict]:
        """Marca jogador como pronto. Retorna STATE (se partida iniciou) ou LOBBY."""
        with self._lock:
            jogador = self.jogadores_por_cliente.get(id_cliente)
            if not jogador:
                return [self._msg_erro("NOT_AUTH", "Não autenticado (HELLO).")]
            jogador.esta_pronto = True
            if self.partida_atual:
                j1 = self.partida_atual.jogadores_por_identificador[1]
                j2 = self.partida_atual.jogadores_por_identificador[2]
                if j1.esta_pronto and j2.esta_pronto:
                    self._versao += 1
                    return [self._msg_state(jogador)]
            return [self._msg_lobby()]

    def colocar(self, id_cliente: str, linha: int, coluna: int) -> List[dict]:
        """Coloca uma peça. Retorna STATE, ERROR ou [GAME_OVER, LOBBY]."""
        with self._lock:
            jogador = self.jogadores_por_cliente.get(id_cliente)
            if not self.partida_atual or not jogador:
                return [self._msg_erro("NO_MATCH", "Aguardando partida iniciar.")]
            return self._tratar_colocacao(jogador, linha, coluna)

    def mover(self, id_cliente: str, fr: int, fc: int, tr: int, tc: int) -> List[dict]:
        """Move uma peça. Retorna STATE, ERROR ou [GAME_OVER, LOBBY]."""
        with self._lock:
            jogador = self.jogadores_por_cliente.get(id_cliente)
            if not self.partida_atual or not jogador:
                return [self._msg_erro("NO_MATCH", "Aguardando partida iniciar.")]
            return self._tratar_movimentacao(jogador, fr, fc, tr, tc)

    def capturar(self, id_cliente: str, linha: int, coluna: int) -> List[dict]:
        """Captura uma peça. Retorna STATE, ERROR ou [GAME_OVER, LOBBY]."""
        with self._lock:
            jogador = self.jogadores_por_cliente.get(id_cliente)
            if not self.partida_atual or not jogador:
                return [self._msg_erro("NO_MATCH", "Aguardando partida iniciar.")]
            return self._tratar_captura(jogador, linha, coluna)

    def desistir(self, id_cliente: str) -> List[dict]:
        """Declara desistência. Retorna [GAME_OVER, LOBBY] ou ERROR."""
        with self._lock:
            jogador = self.jogadores_por_cliente.get(id_cliente)
            if not self.partida_atual or not jogador:
                return [self._msg_erro("NO_MATCH", "Sem partida.")]
            oponente_id = 2 if jogador.identificador_jogador == 1 else 1
            vencedor = self.partida_atual.jogadores_por_identificador[oponente_id].apelido
            return self._encerrar_partida(vencedor, "desistência", id_cliente)

    def nova_partida(self, id_cliente: str) -> List[dict]:
        """Reinicia o jogo com os jogadores conectados. Retorna STATE ou ERROR."""
        with self._lock:
            j1 = next((j for j in self.jogadores_por_cliente.values() if j.identificador_jogador == 1), None)
            j2 = next((j for j in self.jogadores_por_cliente.values() if j.identificador_jogador == 2), None)
            if not j1 or not j2:
                return [self._msg_erro("NO_PLAYERS", "São necessários dois jogadores conectados.")]
            self.partida_atual = criar_nova_partida(j1, j2)
            j1.esta_pronto = True
            j2.esta_pronto = True
            self._versao += 1
            jogador = self.jogadores_por_cliente[id_cliente]
            return [self._msg_state(jogador)]

    def chat(self, id_cliente: str, texto: str) -> None:
        """
        Distribui mensagem de chat. Não retorna nada.
        Chat é o único caso de broadcast inevitável: não pode ser derivado
        do estado atual, então é buffered em _chats por cliente.
        Funciona sempre que o remetente estiver conectado, independente de
        haver partida ativa.
        """
        with self._lock:
            jogador = self.jogadores_por_cliente.get(id_cliente)
            if not jogador:
                return
            msg = {"type": "CHAT", "payload": {"from": jogador.apelido, "text": str(texto)}}
            for id_c in self.jogadores_por_cliente:
                if id_c != id_cliente:
                    self._chats.setdefault(id_c, []).append(msg)

    def desconectar(self, id_cliente: str) -> None:
        """Remove o jogador. Define GAME_OVER no _resultados do outro jogador."""
        with self._lock:
            jogador = self.jogadores_por_cliente.pop(id_cliente, None)
            self._resultados.pop(id_cliente, None)
            self._chats.pop(id_cliente, None)
            if self.partida_atual and jogador:
                outro_id = 2 if jogador.identificador_jogador == 1 else 1
                outro = self.partida_atual.jogadores_por_identificador.get(outro_id)
                if outro:
                    self._resultados[outro.identificador_cliente] = {
                        "winner": outro.apelido,
                        "reason": "desconexão",
                    }
                    self.partida_atual = None
                    for j in self.jogadores_por_cliente.values():
                        j.esta_pronto = True
                    self._versao += 1

    # ------------------------------------------------------------------ #
    #  Lógica de jogadas — retornam List[dict] para o chamador           #
    # ------------------------------------------------------------------ #

    def _tratar_colocacao(self, jogador: JogadorConectado, linha: int, coluna: int) -> List[dict]:
        p = self.partida_atual
        assert p is not None

        if p.fase != "colocação":
            return [self._msg_erro("BAD_PHASE", "Fase atual não é de colocação.")]
        if p.jogador_da_vez != jogador.identificador_jogador:
            return [self._msg_erro("NOT_YOUR_TURN", "Não é sua vez.")]
        if not regras.esta_dentro_do_tabuleiro(linha, coluna):
            return [self._msg_erro("OUT_OF_BOUNDS", "Coordenadas fora do tabuleiro.")]
        if p.tabuleiro[linha][coluna] != 0:
            return [self._msg_erro("OCCUPIED", "Casa já ocupada.")]
        if p.precisa_capturar:
            return [self._msg_erro("MUST_CAPTURE", "Você precisa capturar antes de jogar.")]

        p.tabuleiro[linha][coluna] = jogador.identificador_jogador
        if regras.forma_trinca(p.tabuleiro, jogador.identificador_jogador):
            p.tabuleiro[linha][coluna] = 0
            return [self._msg_erro("PLACE_FORBIDDEN_TRIPLE",
                                   "Não é permitido formar trinca na fase de colocação.")]

        p.pecas_colocadas_por_jogador[jogador.identificador_jogador] += 1
        p.ultimo_movimento = {"fr": None, "fc": None, "tr": linha, "tc": coluna}
        p.jogador_da_vez = 2 if p.jogador_da_vez == 1 else 1

        if p.pecas_colocadas_por_jogador[1] + p.pecas_colocadas_por_jogador[2] == 24:
            p.fase = "movimentação"

        self._versao += 1

        if p.fase == "movimentação" and not p.precisa_capturar:
            fim = self._verificar_sem_movimentos(jogador)
            if fim is not None:
                return fim

        return [self._msg_state(jogador)]

    def _tratar_movimentacao(
        self, jogador: JogadorConectado, lr: int, lc: int, dr: int, dc: int
    ) -> List[dict]:
        p = self.partida_atual
        assert p is not None

        if p.fase != "movimentação":
            return [self._msg_erro("BAD_PHASE", "Fase atual não é de movimentação.")]
        if p.jogador_da_vez != jogador.identificador_jogador:
            return [self._msg_erro("NOT_YOUR_TURN", "Não é sua vez.")]
        if p.precisa_capturar:
            return [self._msg_erro("MUST_CAPTURE", "Você precisa capturar antes de jogar.")]
        if not (regras.esta_dentro_do_tabuleiro(lr, lc) and regras.esta_dentro_do_tabuleiro(dr, dc)):
            return [self._msg_erro("OUT_OF_BOUNDS", "Coordenadas fora do tabuleiro.")]
        if p.tabuleiro[lr][lc] != jogador.identificador_jogador:
            return [self._msg_erro("NOT_YOURS", "A peça de origem não é sua.")]
        if p.tabuleiro[dr][dc] != 0:
            return [self._msg_erro("DEST_OCCUPIED", "Destino já ocupado.")]
        if not regras.sao_adjacentes(lr, lc, dr, dc):
            return [self._msg_erro("NOT_ADJACENT", "Movimento deve ser para casa adjacente.")]

        p.tabuleiro[lr][lc] = 0
        p.tabuleiro[dr][dc] = jogador.identificador_jogador
        p.ultimo_movimento = {"fr": lr, "fc": lc, "tr": dr, "tc": dc}

        if regras.forma_trinca(p.tabuleiro, jogador.identificador_jogador):
            p.precisa_capturar = True
            p.jogador_que_deve_capturar = jogador.identificador_jogador
        else:
            p.jogador_da_vez = 2 if p.jogador_da_vez == 1 else 1

        self._versao += 1

        if not p.precisa_capturar:
            fim = self._verificar_sem_movimentos(jogador)
            if fim is not None:
                return fim

        return [self._msg_state(jogador)]

    def _tratar_captura(self, jogador: JogadorConectado, linha: int, coluna: int) -> List[dict]:
        p = self.partida_atual
        assert p is not None

        if not p.precisa_capturar or p.jogador_que_deve_capturar != jogador.identificador_jogador:
            return [self._msg_erro("CAPTURE_NOT_ALLOWED", "Captura não permitida agora.")]
        if p.jogador_da_vez != jogador.identificador_jogador:
            return [self._msg_erro("NOT_YOUR_TURN", "Não é sua vez.")]
        if not regras.esta_dentro_do_tabuleiro(linha, coluna):
            return [self._msg_erro("OUT_OF_BOUNDS", "Coordenadas fora do tabuleiro.")]

        id_oponente = 2 if jogador.identificador_jogador == 1 else 1
        if p.tabuleiro[linha][coluna] != id_oponente:
            return [self._msg_erro("BAD_TARGET", "Selecione uma peça do adversário para capturar.")]

        p.tabuleiro[linha][coluna] = 0
        p.pecas_capturadas_por_jogador[jogador.identificador_jogador] += 1
        p.precisa_capturar = False
        p.jogador_que_deve_capturar = None
        p.jogador_da_vez = id_oponente

        self._versao += 1

        if regras.contar_pecas_do_jogador(p.tabuleiro, id_oponente) <= 2:
            vencedor = p.jogadores_por_identificador[jogador.identificador_jogador].apelido
            # Constrói STATE final com o tabuleiro já atualizado (peça removida)
            # antes de encerrar a partida (que anula partida_atual).
            estado_caller = self._msg_state(jogador)
            jogador_oponente = p.jogadores_por_identificador[id_oponente]
            estado_oponente = self._msg_state(jogador_oponente)
            # Entrega STATE final ao oponente via buffer antes do GAME_OVER
            self._chats.setdefault(jogador_oponente.identificador_cliente, []).append(estado_oponente)
            return [estado_caller] + self._encerrar_partida(
                vencedor, "oponente com duas peças", jogador.identificador_cliente
            )

        fim = self._verificar_sem_movimentos(jogador)
        if fim is not None:
            return fim

        return [self._msg_state(jogador)]

    # ------------------------------------------------------------------ #
    #  Fim de jogo e encerramento                                        #
    # ------------------------------------------------------------------ #

    def _verificar_sem_movimentos(self, jogador: JogadorConectado) -> Optional[List[dict]]:
        """Verifica se o próximo jogador tem movimentos. Retorna GAME_OVER ou None."""
        p = self.partida_atual
        if not p or p.fase != "movimentação" or p.precisa_capturar:
            return None
        prox = p.jogador_da_vez
        if not regras.existe_movimento_legal(p.tabuleiro, prox):
            vencedor_id = 2 if prox == 1 else 1
            vencedor = p.jogadores_por_identificador[vencedor_id].apelido
            return self._encerrar_partida(vencedor, "oponente sem movimentos", jogador.identificador_cliente)
        return None

    def _encerrar_partida(self, vencedor: str, motivo: str, id_caller: str) -> List[dict]:
        """
        Encerra a partida.
        Retorna [GAME_OVER, LOBBY] para o chamador.
        Registra GAME_OVER em _resultados para o outro jogador ser notificado
        via obter_estado() no próximo poll.
        """
        game_over_payload = {"winner": vencedor, "reason": motivo}

        for id_c in self._ids_da_partida():
            if id_c != id_caller:
                self._resultados[id_c] = game_over_payload

        self.partida_atual = None
        for j in self.jogadores_por_cliente.values():
            j.esta_pronto = True
        self._versao += 1

        return [
            {"type": "GAME_OVER", "payload": game_over_payload},
            self._msg_lobby(),
        ]

    # ------------------------------------------------------------------ #
    #  Inicialização de partida                                          #
    # ------------------------------------------------------------------ #

    def _tentar_criar_partida(self) -> None:
        if self.partida_atual:
            return
        j1 = next((j for j in self.jogadores_por_cliente.values() if j.identificador_jogador == 1), None)
        j2 = next((j for j in self.jogadores_por_cliente.values() if j.identificador_jogador == 2), None)
        if j1 and j2:
            self.partida_atual = criar_nova_partida(j1, j2)

    # ------------------------------------------------------------------ #
    #  Construtores de mensagem — embutem _versao para sync do cliente   #
    # ------------------------------------------------------------------ #

    def _msg_state(self, jogador: JogadorConectado) -> dict:
        """Constrói STATE ao vivo a partir do estado atual da partida."""
        p = self.partida_atual
        assert p is not None
        id_jog = jogador.identificador_jogador
        outro_id = 2 if id_jog == 1 else 1
        oponente_nick = p.jogadores_por_identificador[outro_id].apelido
        return {"type": "STATE", "payload": {
            "board": p.tabuleiro,
            "turn": p.jogador_da_vez,
            "phase": p.fase,
            "must_capture": p.precisa_capturar,
            "last_move": p.ultimo_movimento,
            "you": id_jog,
            "your_nick": jogador.apelido,
            "opponent_nick": oponente_nick,
            "placed_you": p.pecas_colocadas_por_jogador[id_jog],
            "captured_by_you": p.pecas_capturadas_por_jogador[id_jog],
            "versao": self._versao,
        }}

    def _msg_lobby(self) -> dict:
        """Constrói LOBBY ao vivo a partir dos jogadores conectados."""
        jogadores = [
            {"id": j.identificador_jogador, "nick": j.apelido, "ready": j.esta_pronto}
            for j in sorted(self.jogadores_por_cliente.values(), key=lambda x: x.identificador_jogador)
        ]
        return {"type": "LOBBY", "payload": {
            "players": jogadores,
            "can_start": len(jogadores) == 2,
            "versao": self._versao,
        }}

    def _msg_erro(self, codigo: str, texto: str) -> dict:
        return {"type": "ERROR", "payload": {"code": codigo, "message": texto}}

    # ------------------------------------------------------------------ #
    #  Utilitários                                                       #
    # ------------------------------------------------------------------ #

    def _ids_da_partida(self) -> List[str]:
        if not self.partida_atual:
            return []
        return [
            self.partida_atual.jogadores_por_identificador[1].identificador_cliente,
            self.partida_atual.jogadores_por_identificador[2].identificador_cliente,
        ]
