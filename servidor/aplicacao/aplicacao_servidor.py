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
from compartilhado.interfaces import InterfaceServidor

VERSAO_DO_SERVIDOR = "3.0"


@Pyro5.api.expose
@Pyro5.api.behavior(instance_mode="single")
class AplicacaoServidor(InterfaceServidor):
    """
    Servidor do Jogo Dara exposto via RMI com Pyro5.

    Toda comunicação ocorre por chamada remota direta — não há polling nem
    broadcast via buffer. O servidor resolve o contrato em duas direções:

    Cliente → Servidor (InterfaceServidor):
        O cliente chama métodos neste objeto para enviar ações de jogo.
        Cada método retorna a resposta diretamente ao chamador.

    Servidor → Cliente (InterfaceClienteCallback):
        Para notificar o outro jogador (que não fez a chamada atual), o servidor
        resolve o nome 'dara.cliente.<uuid>' no servidor de nomes e chama
        receber() no objeto de callback registrado pelo cliente.
        Cada chamada de callback é disparada em thread separada para não
        bloquear o lock enquanto a rede responde.

    Não há obter_estado(), _resultados ou _chats — todos os eventos chegam
    ao destino por chamada RMI direta no momento em que ocorrem.
    """

    def __init__(self, ns_host: str = "localhost", ns_porta: int = 9090) -> None:
        self._lock = threading.Lock()
        self._ns_host = ns_host
        self._ns_porta = ns_porta
        self.jogadores_por_cliente: Dict[str, JogadorConectado] = {}
        self.partida_atual: Optional[Partida] = None
        self._versao: int = 0
        # Armazena URI (string) do callback de cada cliente, resolvida no hello().
        # Usamos URI em vez de proxy porque proxies Pyro5 não são thread-safe;
        # cada notificação cria seu próprio proxy efêmero na thread dedicada.
        self._callbacks: Dict[str, str] = {}

    # ------------------------------------------------------------------ #
    #  Métodos expostos — retornam a resposta diretamente ao chamador    #
    # ------------------------------------------------------------------ #

    def hello(self, apelido: str, nome_callback: str) -> dict:
        """
        Registra o jogador e resolve o callback pelo servidor de nomes.

        Fluxo:
            1. Valida apelido e verifica slot disponível (1 ou 2).
            2. Resolve 'nome_callback' no NS → obtém URI do objeto callback.
            3. Armazena a URI para uso em notificações futuras.
            4. Notifica jogadores já conectados sobre atualização do lobby.
            5. Retorna WELCOME ao chamador.
        """
        with self._lock:
            apelido = str(apelido).strip()
            nome_callback = str(nome_callback).strip()
            if not apelido:
                return {"type": "ERROR", "payload": {"code": "BAD_NICK", "message": "Nickname obrigatório"}}

            ids_usados = {j.identificador_jogador for j in self.jogadores_por_cliente.values()}
            if 1 not in ids_usados:
                id_jogador = 1
            elif 2 not in ids_usados:
                id_jogador = 2
            else:
                return {"type": "ERROR", "payload": {"code": "FULL", "message": "Servidor cheio (2 jogadores)."}}

            # Resolve URI do callback no servidor de nomes
            try:
                ns = Pyro5.api.locate_ns(host=self._ns_host, port=self._ns_porta)
                uri_callback = str(ns.lookup(nome_callback))
                ns._pyroRelease()
            except Exception as e:
                return {"type": "ERROR", "payload": {
                    "code": "CALLBACK_FAIL",
                    "message": f"Não foi possível resolver callback '{nome_callback}': {e}",
                }}

            id_cliente = str(uuid.uuid4())
            self.jogadores_por_cliente[id_cliente] = JogadorConectado(
                identificador_cliente=id_cliente,
                apelido=apelido,
                identificador_jogador=id_jogador,
            )
            self._callbacks[id_cliente] = uri_callback
            self._versao += 1
            self._tentar_criar_partida()

            # Notifica todos os jogadores já conectados sobre o lobby atualizado.
            # Inclui o próprio novo jogador para que ele veja o estado inicial.
            lobby = self._msg_lobby()
            for uri in self._callbacks.values():
                self._notificar(uri, [lobby])

            return {
                "type": "WELCOME",
                "payload": {
                    "id_cliente": id_cliente,
                    "you": id_jogador,
                    "nickname": apelido,
                    "server_version": VERSAO_DO_SERVIDOR,
                },
            }

    def pronto(self, id_cliente: str) -> List[dict]:
        """
        Marca jogador como pronto.
        Notifica o oponente via callback com STATE (ambos prontos) ou LOBBY.
        Retorna STATE ou LOBBY ao chamador.
        """
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
                    self._notificar_oponente_state(jogador)
                    return [self._msg_state(jogador)]
            # Ainda aguardando — notifica oponente sobre atualização do lobby
            self._notificar_todos_exceto(id_cliente, [self._msg_lobby()])
            return [self._msg_lobby()]

    def colocar(self, id_cliente: str, linha: int, coluna: int) -> List[dict]:
        """Coloca uma peça. Retorna STATE ou ERROR."""
        with self._lock:
            jogador = self.jogadores_por_cliente.get(id_cliente)
            if not self.partida_atual or not jogador:
                return [self._msg_erro("NO_MATCH", "Aguardando partida iniciar.")]
            return self._tratar_colocacao(jogador, linha, coluna)

    def mover(self, id_cliente: str, fr: int, fc: int, tr: int, tc: int) -> List[dict]:
        """Move uma peça. Retorna STATE ou ERROR."""
        with self._lock:
            jogador = self.jogadores_por_cliente.get(id_cliente)
            if not self.partida_atual or not jogador:
                return [self._msg_erro("NO_MATCH", "Aguardando partida iniciar.")]
            return self._tratar_movimentacao(jogador, fr, fc, tr, tc)

    def capturar(self, id_cliente: str, linha: int, coluna: int) -> List[dict]:
        """Captura uma peça. Retorna STATE, ERROR ou [STATE, GAME_OVER, LOBBY]."""
        with self._lock:
            jogador = self.jogadores_por_cliente.get(id_cliente)
            if not self.partida_atual or not jogador:
                return [self._msg_erro("NO_MATCH", "Aguardando partida iniciar.")]
            return self._tratar_captura(jogador, linha, coluna)

    def desistir(self, id_cliente: str) -> List[dict]:
        """Declara desistência. Retorna [GAME_OVER, LOBBY] ao chamador."""
        with self._lock:
            jogador = self.jogadores_por_cliente.get(id_cliente)
            if not self.partida_atual or not jogador:
                return [self._msg_erro("NO_MATCH", "Sem partida.")]
            oponente_id = 2 if jogador.identificador_jogador == 1 else 1
            vencedor = self.partida_atual.jogadores_por_identificador[oponente_id].apelido
            return self._encerrar_partida(vencedor, "desistência", id_cliente)

    def nova_partida(self, id_cliente: str) -> List[dict]:
        """Reinicia o jogo. Notifica o oponente via callback. Retorna STATE."""
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
            self._notificar_oponente_state(jogador)
            return [self._msg_state(jogador)]

    def chat(self, id_cliente: str, texto: str) -> None:
        """
        Envia mensagem de chat.
        Chama receber() no callback do outro jogador via RMI — sem buffer.
        """
        with self._lock:
            jogador = self.jogadores_por_cliente.get(id_cliente)
            if not jogador:
                return
            msg = {"type": "CHAT", "payload": {"from": jogador.apelido, "text": str(texto)}}
            self._notificar_todos_exceto(id_cliente, [msg])

    def desconectar(self, id_cliente: str) -> None:
        """
        Remove o jogador e notifica o oponente via callback com GAME_OVER.
        Remove também a entrada de callback armazenada.
        """
        with self._lock:
            jogador = self.jogadores_por_cliente.pop(id_cliente, None)
            self._callbacks.pop(id_cliente, None)
            if self.partida_atual and jogador:
                outro_id = 2 if jogador.identificador_jogador == 1 else 1
                outro = self.partida_atual.jogadores_por_identificador.get(outro_id)
                if outro:
                    uri_outro = self._callbacks.get(outro.identificador_cliente)
                    if uri_outro:
                        self._notificar(uri_outro, [
                            {"type": "GAME_OVER", "payload": {
                                "winner": outro.apelido,
                                "reason": "desconexão",
                            }},
                            self._msg_lobby(),
                        ])
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

        self._notificar_oponente_state(jogador)
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

        self._notificar_oponente_state(jogador)
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
            jogador_oponente = p.jogadores_por_identificador[id_oponente]
            # STATE final com tabuleiro atualizado (peça removida) deve chegar
            # ao oponente antes do GAME_OVER — passado como msgs_extras.
            estado_caller = self._msg_state(jogador)
            estado_oponente = self._msg_state(jogador_oponente)
            return [estado_caller] + self._encerrar_partida(
                vencedor, "oponente com duas peças", jogador.identificador_cliente,
                msgs_extras_oponente=[estado_oponente],
            )

        fim = self._verificar_sem_movimentos(jogador)
        if fim is not None:
            return fim

        self._notificar_oponente_state(jogador)
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
            # Oponente (prox) recebe STATE final antes do GAME_OVER
            jogador_prox = p.jogadores_por_identificador[prox]
            estado_oponente = self._msg_state(jogador_prox)
            return self._encerrar_partida(
                vencedor, "oponente sem movimentos", jogador.identificador_cliente,
                msgs_extras_oponente=[estado_oponente],
            )
        return None

    def _encerrar_partida(
        self,
        vencedor: str,
        motivo: str,
        id_caller: str,
        msgs_extras_oponente: Optional[List[dict]] = None,
    ) -> List[dict]:
        """
        Encerra a partida e notifica o outro jogador via callback RMI direto.

        O oponente recebe: msgs_extras_oponente (ex: STATE final) + GAME_OVER + LOBBY.
        O chamador recebe como retorno: GAME_OVER + LOBBY.
        Não há buffer — a notificação ao oponente é uma chamada remota imediata.
        """
        game_over_payload = {"winner": vencedor, "reason": motivo}
        game_over_msg = {"type": "GAME_OVER", "payload": game_over_payload}
        lobby_msg = self._msg_lobby()

        for id_c in self._ids_da_partida():
            if id_c != id_caller:
                uri = self._callbacks.get(id_c)
                if uri:
                    notif = (msgs_extras_oponente or []) + [game_over_msg, lobby_msg]
                    self._notificar(uri, notif)

        self.partida_atual = None
        for j in self.jogadores_por_cliente.values():
            j.esta_pronto = True
        self._versao += 1

        return [game_over_msg, lobby_msg]

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
    #  Notificação via callback — servidor → cliente (RMI inverso)       #
    # ------------------------------------------------------------------ #

    def _notificar(self, uri: str, msgs: List[dict]) -> None:
        """
        Dispara chamada RMI ao callback do cliente em thread separada.
        Thread separada evita bloquear o _lock durante a chamada de rede.
        Proxy criado localmente na thread — proxies Pyro5 não são thread-safe.
        """
        threading.Thread(
            target=self._chamar_callback,
            args=(uri, msgs),
            daemon=True,
        ).start()

    def _chamar_callback(self, uri: str, msgs: List[dict]) -> None:
        try:
            with Pyro5.api.Proxy(uri) as cb:
                cb.receber(msgs)
        except Exception:
            pass

    def _notificar_oponente_state(self, jogador: JogadorConectado) -> None:
        """Empurra STATE atualizado ao oponente via callback RMI."""
        p = self.partida_atual
        if not p:
            return
        id_oponente = 2 if jogador.identificador_jogador == 1 else 1
        jogador_oponente = p.jogadores_por_identificador.get(id_oponente)
        if not jogador_oponente:
            return
        uri = self._callbacks.get(jogador_oponente.identificador_cliente)
        if uri:
            self._notificar(uri, [self._msg_state(jogador_oponente)])

    def _notificar_todos_exceto(self, id_caller: str, msgs: List[dict]) -> None:
        """Notifica todos os jogadores conectados, exceto o chamador."""
        for id_c, uri in self._callbacks.items():
            if id_c != id_caller:
                self._notificar(uri, msgs)

    # ------------------------------------------------------------------ #
    #  Construtores de mensagem — derivados ao vivo do estado atual       #
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
