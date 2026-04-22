from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from typing import Dict, List, Optional, Set, Tuple

import Pyro5.api

from cliente.interface.tabuleiro_canvas import TabuleiroCanvas
from cliente.interface.prateleira_pecas import PrateleiraDePecas

Celula = Tuple[int, int]


class AplicacaoTk:
    """
    Janela principal do cliente Dara — comunicação por RMI com Pyro5.

    O cliente mantém um proxy Pyro5 que representa o objeto remoto no servidor.
    Chamar um método no proxy é equivalente a chamar o método diretamente no
    servidor, sem nenhuma codificação ou socket manual.

    ENVIO (clique → servidor):
        1. tabuleiro_canvas captura o clique do mouse e converte pixel → (linha, coluna).
        2. Entrega as coordenadas para _ao_clicar_tabuleiro() desta classe.
        3. aplicacao_tk chama o método correspondente no proxy:
               self._servidor.colocar(self._id_cliente, linha, coluna)
        4. Pyro5 serializa, transporta e executa o método no servidor.
        5. O retorno (STATE ou ERROR) é processado imediatamente por _processar_respostas().

    RECEBIMENTO (servidor → tela):
        1. _ciclo_rede() é chamado pelo Tkinter a cada 50 ms.
        2. Chama self._servidor.obter_estado(self._id_cliente).
        3. O servidor deriva o estado atual do jogo (sem fila) e retorna
           dicts de GAME_OVER, CHAT ou STATE/LOBBY quando algo mudou.
        4. aplicacao_tk interpreta cada dict e atualiza a interface.

    Os métodos de ação (colocar, mover, capturar, pronto, etc.) processam
    o retorno do servidor imediatamente via _processar_respostas(), sem
    esperar o próximo ciclo de polling. O ciclo obter_estado() permanece
    apenas para notificar o jogador que aguarda a vez do oponente.
    """

    def __init__(self, raiz: tk.Tk) -> None:
        self._raiz = raiz
        raiz.title("Dara — Cliente (RMI/Pyro5)")
        raiz.geometry("1100x720")
        raiz.configure(bg="#f5f0e8")

        # Proxy Pyro5 para o objeto remoto no servidor
        self._servidor: Optional[Pyro5.api.Proxy] = None
        self._id_cliente: str = ""

        # Estado local do jogo
        self._id_jogador: int = 0
        self._apelido: str = ""
        self._apelido_oponente: str = ""
        self._tabuleiro: List[List[int]] = [[0] * 6 for _ in range(5)]
        self._fase: str = ""
        self._vez_de: int = 0
        self._precisa_capturar: bool = False
        self._pecas_colocadas: int = 0
        self._pecas_capturadas: int = 0
        self._ultimo_movimento: Optional[Dict] = None
        self._partida_ativa: bool = False

        # Estado da interface (seleção para movimentação)
        self._celula_selecionada: Optional[Celula] = None
        self._destinos_validos: Set[Celula] = set()

        self._montar_interface()
        raiz.protocol("WM_DELETE_WINDOW", self._ao_fechar)
        self._abrir_dialogo_conexao()

    # ================================================================== #
    #  MONTAGEM DA INTERFACE                                              #
    # ================================================================== #

    def _montar_interface(self) -> None:
        # ---- Quadro superior ----
        topo = tk.Frame(self._raiz, bg="#e8ddd2", padx=10, pady=6)
        topo.pack(fill="x")

        self._var_status = tk.StringVar(value="Desconectado")
        tk.Label(topo, textvariable=self._var_status, bg="#e8ddd2", fg="#2c1a0e",
                 font=("Consolas", 10, "bold")).pack(side="left")

        self._btn_desistir = tk.Button(topo, text="Desistir", bg="#c0392b", fg="white",
                                       font=("Consolas", 9, "bold"), relief="flat",
                                       command=self._enviar_desistencia)
        self._btn_desistir.pack(side="right", padx=4)

        self._btn_nova = tk.Button(topo, text="Nova Partida", bg="#2471a3", fg="white",
                                    font=("Consolas", 9, "bold"), relief="flat",
                                    command=self._enviar_nova_partida)
        self._btn_nova.pack(side="right", padx=4)

        self._btn_pronto = tk.Button(topo, text="Pronto", bg="#27ae60", fg="white",
                                      font=("Consolas", 9, "bold"), relief="flat",
                                      command=self._enviar_pronto)
        self._btn_pronto.pack(side="right", padx=4)

        # ---- Corpo principal ----
        corpo = tk.Frame(self._raiz, bg="#f5f0e8")
        corpo.pack(fill="both", expand=True)

        # Coluna esquerda: prateleira + tabuleiro + capturas
        col_esq = tk.Frame(corpo, bg="#f5f0e8", padx=10, pady=8)
        col_esq.pack(side="left", fill="both", expand=True)

        self._prateleira = PrateleiraDePecas(
            col_esq, prefixo_titulo="Sua prateleira",
            quantidade_inicial=12, identificador_jogador=1,
        )
        self._prateleira.pack(fill="x", pady=(0, 6))

        self._canvas = TabuleiroCanvas(col_esq)
        self._canvas.pack()
        self._canvas.vincular_clique(self._ao_clicar_tabuleiro)

        self._capturas = PrateleiraDePecas(
            col_esq, prefixo_titulo="Peças capturadas do oponente",
            quantidade_inicial=0, identificador_jogador=2,
        )
        self._capturas.pack(fill="x", pady=(6, 0))

        # Coluna direita: log + chat
        col_dir = tk.Frame(corpo, bg="#f5f0e8", padx=10, pady=8)
        col_dir.pack(side="left", fill="both", expand=True)

        tk.Label(col_dir, text="Log", bg="#f5f0e8", fg="#2c1a0e",
                 font=("Consolas", 10, "bold")).pack(anchor="w")
        self._caixa_log = tk.Text(col_dir, width=40, height=12, state="disabled",
                                   bg="#ffffff", fg="#4a3828", font=("Consolas", 9),
                                   relief="flat")
        self._caixa_log.pack(fill="both", expand=True, pady=(2, 8))

        tk.Label(col_dir, text="Chat", bg="#f5f0e8", fg="#2c1a0e",
                 font=("Consolas", 10, "bold")).pack(anchor="w")
        self._caixa_chat = tk.Text(col_dir, width=40, height=12, state="disabled",
                                    bg="#ffffff", fg="#2c1a0e", font=("Consolas", 9),
                                    relief="flat")
        self._caixa_chat.pack(fill="both", expand=True, pady=(2, 4))

        linha_chat = tk.Frame(col_dir, bg="#f5f0e8")
        linha_chat.pack(fill="x")
        self._campo_chat = tk.Entry(linha_chat, bg="#ffffff", fg="#2c1a0e",
                                     font=("Consolas", 10), relief="flat",
                                     insertbackground="#2c1a0e")
        self._campo_chat.pack(side="left", fill="x", expand=True)
        self._campo_chat.bind("<Return>", lambda e: self._enviar_chat())
        tk.Button(linha_chat, text="Enviar", bg="#9a8878", fg="white",
                  font=("Consolas", 9, "bold"), relief="flat",
                  command=self._enviar_chat).pack(side="left", padx=(4, 0))

    # ================================================================== #
    #  DIÁLOGO DE CONEXÃO                                                 #
    # ================================================================== #

    def _abrir_dialogo_conexao(self) -> None:
        dlg = tk.Toplevel(self._raiz)
        dlg.title("Conectar ao Servidor")
        dlg.geometry("360x240")
        dlg.resizable(False, False)
        dlg.configure(bg="#f5f0e8")
        dlg.transient(self._raiz)
        dlg.grab_set()
        dlg.focus_force()

        dlg.update_idletasks()
        sx = dlg.winfo_screenwidth() // 2 - 180
        sy = dlg.winfo_screenheight() // 2 - 120
        dlg.geometry(f"360x240+{sx}+{sy}")

        lbl_cfg = dict(bg="#f5f0e8", fg="#2c1a0e", font=("Consolas", 10))
        ent_cfg = dict(bg="#ffffff", fg="#2c1a0e", font=("Consolas", 10),
                       relief="flat", insertbackground="#2c1a0e")

        var_nick = tk.StringVar(value="")
        var_host = tk.StringVar(value="localhost")
        var_port = tk.StringVar(value="9000")

        tk.Label(dlg, text="Nickname", **lbl_cfg).pack(anchor="w", padx=14, pady=(14, 0))
        campo_nick = tk.Entry(dlg, textvariable=var_nick, **ent_cfg)
        campo_nick.pack(fill="x", padx=14)

        tk.Label(dlg, text="Host / IP do servidor", **lbl_cfg).pack(anchor="w", padx=14, pady=(8, 0))
        tk.Entry(dlg, textvariable=var_host, **ent_cfg).pack(fill="x", padx=14)

        tk.Label(dlg, text="Porta", **lbl_cfg).pack(anchor="w", padx=14, pady=(8, 0))
        tk.Entry(dlg, textvariable=var_port, **ent_cfg).pack(fill="x", padx=14)

        def conectar():
            nick = var_nick.get().strip()
            host = var_host.get().strip()
            porta = int(var_port.get().strip() or "9000")
            if not nick:
                messagebox.showwarning("Aviso", "Informe um nickname.")
                return
            dlg.destroy()
            self._conectar(host, porta, nick)

        tk.Button(dlg, text="Conectar", bg="#27ae60", fg="white",
                  font=("Consolas", 10, "bold"), relief="flat",
                  pady=10,
                  command=conectar).pack(fill="x", padx=14, pady=12)

        campo_nick.focus_set()
        dlg.protocol("WM_DELETE_WINDOW", lambda: self._raiz.destroy())

    # ================================================================== #
    #  CONEXÃO — cria o proxy e chama hello() diretamente no servidor    #
    # ================================================================== #

    def _conectar(self, host: str, porta: int, apelido: str) -> None:
        """
        Cria o proxy Pyro5 e chama hello() no objeto remoto.

        Fluxo:
            1. Instancia Pyro5.api.Proxy com a URI do servidor.
            2. Chama proxy.hello(apelido) — executa remotamente no servidor.
            3. O retorno é o dict WELCOME com id_cliente, you, nickname.
            4. Armazena id_cliente e atualiza a interface.
            5. Inicia o ciclo de polling _ciclo_rede().
        """
        self._apelido = apelido
        self._var_status.set("Conectando...")
        self._log(f"Conectando em PYRO:jogo.dara@{host}:{porta}...")

        try:
            self._servidor = Pyro5.api.Proxy(f"PYRO:jogo.dara@{host}:{porta}")
            resultado = self._servidor.hello(apelido)
        except Exception as e:
            self._servidor = None
            self._var_status.set("Erro de conexão")
            self._log(f"ERRO: {e}")
            messagebox.showerror("Erro", f"Não foi possível conectar: {e}")
            return

        if resultado.get("type") == "ERROR":
            payload = resultado.get("payload", {})
            msg = payload.get("message", "Erro desconhecido")
            self._log(f"ERRO do servidor: {msg}")
            self._var_status.set("Erro")
            messagebox.showerror("Erro", msg)
            self._servidor._pyroRelease()
            self._servidor = None
            return

        payload = resultado.get("payload", {})
        self._id_cliente = payload.get("id_cliente", "")
        self._var_status.set("Conectado")
        self._log("Conexão RMI estabelecida.")
        self._ao_welcome(payload)
        self._raiz.after(50, self._ciclo_rede)

    # ================================================================== #
    #  CICLO DE REDE — polling via chamada remota a cada 50 ms           #
    # ================================================================== #

    def _ciclo_rede(self) -> None:
        """
        Polling chamado pelo Tkinter a cada 50ms.

        Fluxo:
            1. Chama self._servidor.obter_estado(self._id_cliente) — RMI.
            2. O servidor deriva o estado atual do jogo diretamente (sem fila) e
               retorna sempre STATE ou LOBBY, mais GAME_OVER e CHAT se houver pendentes.
            3. Para cada dict recebido, chama _tratar_mensagem().
            4. Reagenda o próximo ciclo.
        """
        if self._servidor is None:
            self._var_status.set("Desconectado")
            self._canvas.atualizar_status(status_conexao="Desconectado")
            self._redesenhar()
            return

        try:
            mensagens = self._servidor.obter_estado(self._id_cliente)
            for msg in mensagens:
                self._tratar_mensagem(msg)
        except Exception:
            self._servidor = None
            self._var_status.set("Desconectado")
            self._canvas.atualizar_status(status_conexao="Desconectado")
            self._redesenhar()
            return

        self._raiz.after(200, self._ciclo_rede)

    # ================================================================== #
    #  TRATAMENTO DE MENSAGENS RECEBIDAS                                  #
    # ================================================================== #

    def _tratar_mensagem(self, obj: Dict) -> None:
        tipo = obj.get("type", "")
        payload = obj.get("payload", {})
        self._log(f"RX ← {tipo}")

        if tipo == "LOBBY":
            self._ao_lobby(payload)
        elif tipo == "START":
            self._ao_start(payload)
        elif tipo == "STATE":
            self._ao_state(payload)
        elif tipo == "CHAT":
            self._ao_chat(payload)
        elif tipo == "ERROR":
            self._ao_error(payload)
        elif tipo == "GAME_OVER":
            self._ao_game_over(payload)

    def _ao_welcome(self, p: Dict) -> None:
        self._id_jogador = p.get("you", 0)
        self._apelido = p.get("nickname", self._apelido)
        self._log(f"WELCOME: jogador={self._id_jogador}, nick={self._apelido}")
        self._canvas.atualizar_status(
            status_conexao="Conectado",
            nome_jogador=self._apelido,
            id_jogador=self._id_jogador,
        )
        self._prateleira.definir_jogador(self._id_jogador)
        oponente_id = 2 if self._id_jogador == 1 else 1
        self._capturas.definir_jogador(oponente_id)
        self._redesenhar()

    def _ao_lobby(self, p: Dict) -> None:
        jogadores = p.get("players", [])
        nomes = ", ".join(
            f"J{j.get('id')}: {j.get('nick')} ({'pronto' if j.get('ready') else 'aguardando'})"
            for j in jogadores
        )
        self._log(f"LOBBY: {nomes}")
        self._var_status.set(f"Sala: {nomes}")

    def _ao_start(self, p: Dict) -> None:
        # O servidor não envia mais START; este método é mantido por
        # compatibilidade caso alguma extensão futura o utilize.
        fase = p.get("phase", "")
        self._fase = fase
        self._partida_ativa = True
        self._log(f"START: fase={fase}")
        self._var_status.set("Partida iniciada!")

    def _ao_state(self, p: Dict) -> None:
        novo_tabuleiro = p.get("board", self._tabuleiro)
        tabuleiro_mudou = novo_tabuleiro != self._tabuleiro

        self._tabuleiro = novo_tabuleiro
        self._vez_de = p.get("turn", 0)
        self._fase = p.get("phase", "")
        self._precisa_capturar = p.get("must_capture", False)
        self._ultimo_movimento = p.get("last_move", None)
        self._apelido_oponente = p.get("opponent_nick", "")
        self._pecas_colocadas = p.get("placed_you", 0)
        self._pecas_capturadas = p.get("captured_by_you", 0)
        self._partida_ativa = True

        if tabuleiro_mudou:
            self._celula_selecionada = None
            self._destinos_validos = set()

        self._canvas.atualizar_status(
            status_conexao="Conectado",
            nome_jogador=self._apelido,
            nome_oponente=self._apelido_oponente,
            id_jogador=self._id_jogador,
            vez_de=self._vez_de,
            fase=self._fase,
            precisa_capturar=self._precisa_capturar,
        )

        pecas_restantes = 12 - self._pecas_colocadas
        self._prateleira.definir_quantidade(pecas_restantes)
        self._capturas.definir_quantidade(self._pecas_capturadas)

        eh_minha_vez = (self._vez_de == self._id_jogador)
        if self._precisa_capturar and eh_minha_vez:
            self._var_status.set("Capture uma peça do oponente!")
        elif eh_minha_vez:
            self._var_status.set(f"Sua vez — Fase: {self._fase}")
        else:
            self._var_status.set(f"Aguardando {self._apelido_oponente}...")

        self._redesenhar()

    def _ao_chat(self, p: Dict) -> None:
        autor = p.get("from", "?")
        texto = p.get("text", "")
        self._chat(f"{autor} enviou: {texto}")

    def _ao_error(self, p: Dict) -> None:
        msg = p.get("message", "Erro desconhecido")
        codigo = p.get("code", "")
        self._log(f"ERRO [{codigo}]: {msg}")
        self._var_status.set(f"Erro: {msg}")

    def _ao_game_over(self, p: Dict) -> None:
        vencedor = p.get("winner", "?")
        motivo = p.get("reason", "")
        self._partida_ativa = False
        self._log(f"GAME_OVER: vencedor={vencedor} motivo={motivo}")
        self._var_status.set(f"Fim de jogo! Vencedor: {vencedor}")
        messagebox.showinfo("Fim de Jogo", f"Vencedor: {vencedor}\nMotivo: {motivo}")

    # ================================================================== #
    #  CLIQUE NO TABULEIRO — chama métodos diretamente no servidor       #
    # ================================================================== #

    def _ao_clicar_tabuleiro(self, linha: int, coluna: int) -> None:
        """
        Recebe coordenadas lógicas do tabuleiro_canvas e chama o método
        adequado diretamente no objeto remoto via proxy Pyro5.

        O retorno do servidor (STATE ou ERROR) é processado imediatamente
        por _processar_respostas(), sem aguardar o próximo ciclo de polling.
        """
        if not self._partida_ativa or self._servidor is None:
            return
        if self._vez_de != self._id_jogador:
            self._var_status.set("Não é sua vez.")
            return

        if self._precisa_capturar:
            msgs = self._servidor.capturar(self._id_cliente, linha, coluna)
            self._log(f"TX → capturar({linha},{coluna})")
            self._processar_respostas(msgs)
            return

        if self._fase == "colocação":
            msgs = self._servidor.colocar(self._id_cliente, linha, coluna)
            self._log(f"TX → colocar({linha},{coluna})")
            self._processar_respostas(msgs)
            return

        if self._fase == "movimentação":
            self._tratar_clique_movimentacao(linha, coluna)

    def _tratar_clique_movimentacao(self, linha: int, coluna: int) -> None:
        """
        Gerencia seleção de peça e destino na fase de movimentação.

        Primeiro clique: seleciona a peça (se for do jogador) e calcula destinos válidos.
        Segundo clique: se for destino válido, chama mover() no servidor e processa
        o retorno (STATE ou ERROR) imediatamente via _processar_respostas().
        Clique inválido: deseleciona e redesenha.
        """
        if self._celula_selecionada and (linha, coluna) in self._destinos_validos:
            sr, sc = self._celula_selecionada
            msgs = self._servidor.mover(self._id_cliente, sr, sc, linha, coluna)
            self._log(f"TX → mover({sr},{sc})→({linha},{coluna})")
            self._celula_selecionada = None
            self._destinos_validos = set()
            self._processar_respostas(msgs)
            return

        if self._tabuleiro[linha][coluna] == self._id_jogador:
            self._celula_selecionada = (linha, coluna)
            self._destinos_validos = self._calcular_destinos(linha, coluna)
            self._redesenhar()
            return

        self._celula_selecionada = None
        self._destinos_validos = set()
        self._redesenhar()

    def _calcular_destinos(self, linha: int, coluna: int) -> Set[Celula]:
        """Calcula casas adjacentes vazias para uma peça."""
        destinos = set()
        for dl, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = linha + dl, coluna + dc
            if 0 <= nr < 5 and 0 <= nc < 6 and self._tabuleiro[nr][nc] == 0:
                destinos.add((nr, nc))
        return destinos

    # ================================================================== #
    #  ENVIO DE COMANDOS — e processamento imediato do retorno           #
    # ================================================================== #

    def _processar_respostas(self, msgs: list) -> None:
        """Processa a lista de dicts retornada diretamente pelo servidor."""
        for msg in (msgs or []):
            self._tratar_mensagem(msg)

    def _enviar_pronto(self) -> None:
        if self._servidor:
            msgs = self._servidor.pronto(self._id_cliente)
            self._log("TX → pronto()")
            self._processar_respostas(msgs)

    def _enviar_desistencia(self) -> None:
        if self._servidor:
            msgs = self._servidor.desistir(self._id_cliente)
            self._log("TX → desistir()")
            self._processar_respostas(msgs)

    def _enviar_nova_partida(self) -> None:
        if self._servidor:
            msgs = self._servidor.nova_partida(self._id_cliente)
            self._log("TX → nova_partida()")
            self._processar_respostas(msgs)

    def _enviar_chat(self) -> None:
        texto = self._campo_chat.get().strip()
        if not texto or not self._servidor:
            return
        self._servidor.chat(self._id_cliente, texto)
        self._campo_chat.delete(0, "end")
        destinatario = self._apelido_oponente if self._apelido_oponente else "todos"
        self._chat(f"Você enviou para {destinatario}: {texto}")

    # ================================================================== #
    #  FECHAMENTO DA JANELA                                               #
    # ================================================================== #

    def _ao_fechar(self) -> None:
        """Notifica o servidor sobre a desconexão antes de encerrar a janela."""
        if self._servidor and self._id_cliente:
            try:
                self._servidor.desconectar(self._id_cliente)
            except Exception:
                pass
            self._servidor._pyroRelease()
        self._raiz.destroy()

    # ================================================================== #
    #  REDESENHO DO TABULEIRO                                             #
    # ================================================================== #

    def _redesenhar(self) -> None:
        ult = None
        if self._ultimo_movimento:
            um = self._ultimo_movimento
            orig = None
            dest = None
            if um.get("fr") is not None and um.get("fc") is not None:
                orig = (um["fr"], um["fc"])
            if um.get("tr") is not None and um.get("tc") is not None:
                dest = (um["tr"], um["tc"])
            ult = (orig, dest)

        self._canvas.renderizar(
            self._tabuleiro,
            celula_selecionada=self._celula_selecionada,
            destinos_validos=self._destinos_validos,
            ultimo_movimento=ult,
        )

    # ================================================================== #
    #  LOG E CHAT                                                         #
    # ================================================================== #

    def _log(self, texto: str) -> None:
        self._caixa_log.configure(state="normal")
        self._caixa_log.insert("end", texto + "\n")
        self._caixa_log.see("end")
        self._caixa_log.configure(state="disabled")

    def _chat(self, texto: str) -> None:
        self._caixa_chat.configure(state="normal")
        self._caixa_chat.insert("end", texto + "\n")
        self._caixa_chat.see("end")
        self._caixa_chat.configure(state="disabled")
