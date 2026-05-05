from __future__ import annotations

import tkinter as tk
from typing import Callable, List, Optional, Set, Tuple

Celula = Tuple[int, int]

COR_JOGADOR_1 = "#c0392b"
COR_JOGADOR_2 = "#2471a3"
COR_FUNDO = "#ffffff"
COR_GRADE = "#b0a090"
COR_BORDA = "#9a8878"
COR_SELECAO = "#f39c12"
COR_DESTINO = "#27ae60"
COR_ULTIMO_ORIG = "#7f8c8d"
COR_ULTIMO_DEST = "#2c3e50"

# Cores do tema claro
COR_BARRA_STATUS_FUNDO = "#e8ddd2"
COR_BARRA_STATUS_TEXTO = "#2c1a0e"
COR_BARRA_STATUS_TEXTO2 = "#5a4232"
COR_TABULEIRO_FUNDO = "#f0e8d8"


class TabuleiroCanvas(tk.Canvas):
    """
    Desenha o tabuleiro do Dara e converte cliques em coordenadas lógicas.

    Fluxo de um clique:
        1. Tkinter dispara <Button-1> → _ao_clicar()
        2. _pixel_para_celula() converte (x, y) em (linha, coluna)
        3. Se válida, chama o callback registrado por aplicacao_tk
        4. aplicacao_tk chama o método correspondente diretamente no proxy Pyro5
           (ex.: self._servidor.colocar(id_cliente, linha, coluna)) e processa
           o retorno imediatamente via _processar_respostas()
    """

    LINHAS = 5
    COLUNAS = 6

    def __init__(self, mestre, largura: int = 600, altura: int = 500, **kw):
        super().__init__(mestre, width=largura, height=altura, bg=COR_FUNDO,
                         highlightthickness=0, **kw)
        self._largura = largura
        self._altura = altura
        self._margem_topo = 70       # reserva para barra de status
        self._margem_lateral = 20
        self._margem_inferior = 20

        area_x = self._largura - 2 * self._margem_lateral
        area_y = self._altura - self._margem_topo - self._margem_inferior
        self._cel_w = area_x / self.COLUNAS
        self._cel_h = area_y / self.LINHAS

        self._callback_clique: Optional[Callable[[int, int], None]] = None

        # Info de status pintada no canvas
        self._status_conexao = "Desconectado"
        self._nome_jogador = ""
        self._nome_oponente = ""
        self._id_jogador = 0
        self._vez_de = 0
        self._fase = ""
        self._precisa_capturar = False

        self.bind("<Button-1>", self._ao_clicar)

    # ------------------------------------------------------------------ #
    #  API pública                                                        #
    # ------------------------------------------------------------------ #

    def vincular_clique(self, callback: Callable[[int, int], None]) -> None:
        """Registra o callback que receberá (linha, coluna) a cada clique."""
        self._callback_clique = callback

    def atualizar_status(
        self,
        status_conexao: str = "",
        nome_jogador: str = "",
        nome_oponente: str = "",
        id_jogador: int = 0,
        vez_de: int = 0,
        fase: str = "",
        precisa_capturar: bool = False,
    ) -> None:
        """Atualiza as informações de status exibidas no topo do canvas."""
        if status_conexao:
            self._status_conexao = status_conexao
        if nome_jogador:
            self._nome_jogador = nome_jogador
        if nome_oponente:
            self._nome_oponente = nome_oponente
        if id_jogador:
            self._id_jogador = id_jogador
        if vez_de:
            self._vez_de = vez_de
        if fase:
            self._fase = fase
        self._precisa_capturar = precisa_capturar

    def renderizar(
        self,
        tabuleiro: List[List[int]],
        celula_selecionada: Optional[Celula] = None,
        destinos_validos: Optional[Set[Celula]] = None,
        ultimo_movimento: Optional[Tuple[Optional[Celula], Optional[Celula]]] = None,
    ) -> None:
        """Redesenha o tabuleiro completo: status, grade, peças e destaques."""
        if destinos_validos is None:
            destinos_validos = set()

        self.delete("all")
        self._desenhar_barra_status()
        self._desenhar_grade()

        # Último movimento
        if ultimo_movimento:
            orig, dest = ultimo_movimento
            if orig:
                self._anel(orig[0], orig[1], COR_ULTIMO_ORIG, 2)
            if dest:
                self._anel(dest[0], dest[1], COR_ULTIMO_DEST, 3)

        # Seleção
        if celula_selecionada:
            self._anel(celula_selecionada[0], celula_selecionada[1], COR_SELECAO, 4)

        # Destinos
        for r, c in destinos_validos:
            cx, cy = self._centro(r, c)
            raio = min(self._cel_w, self._cel_h) * 0.12
            self.create_oval(cx - raio, cy - raio, cx + raio, cy + raio,
                             outline=COR_DESTINO, width=3, tags="jogo")

        # Peças
        for r in range(self.LINHAS):
            for c in range(self.COLUNAS):
                v = tabuleiro[r][c]
                if v == 0:
                    continue
                cx, cy = self._centro(r, c)
                raio = min(self._cel_w, self._cel_h) * 0.35
                cor = COR_JOGADOR_1 if v == 1 else COR_JOGADOR_2
                self.create_oval(cx - raio, cy - raio, cx + raio, cy + raio,
                                 fill=cor, outline="#222", width=2, tags="jogo")

    # ------------------------------------------------------------------ #
    #  Barra de status no topo do canvas                                  #
    # ------------------------------------------------------------------ #

    def _desenhar_barra_status(self) -> None:
        """Desenha a barra com conexão, nomes, vez e fase."""
        self.create_rectangle(0, 0, self._largura, self._margem_topo - 4,
                              fill=COR_BARRA_STATUS_FUNDO, outline="")

        # Linha 1: conexão e nomes
        cor_conexao = "#27ae60" if self._status_conexao == "Conectado" else "#e74c3c"
        # Indicador redondo
        self.create_oval(10, 8, 22, 20, fill=cor_conexao, outline="")
        self.create_text(28, 14, anchor="w", fill=COR_BARRA_STATUS_TEXTO,
                         font=("Consolas", 10, "bold"),
                         text=self._status_conexao)

        if self._nome_jogador:
            cor_jog = COR_JOGADOR_1 if self._id_jogador == 1 else COR_JOGADOR_2
            self.create_text(180, 14, anchor="w", fill=cor_jog,
                             font=("Consolas", 10, "bold"), text=f"Você: {self._nome_jogador}")

        if self._nome_oponente:
            cor_op = COR_JOGADOR_2 if self._id_jogador == 1 else COR_JOGADOR_1
            self.create_text(380, 14, anchor="w", fill=cor_op,
                             font=("Consolas", 10, "bold"), text=f"vs {self._nome_oponente}")

        # Linha 2: fase e turno
        if self._fase:
            txt_fase = f"Fase: {self._fase}"
            self.create_text(10, 38, anchor="w", fill=COR_BARRA_STATUS_TEXTO2,
                             font=("Consolas", 9), text=txt_fase)

        if self._vez_de:
            eh_minha_vez = (self._vez_de == self._id_jogador)
            if self._precisa_capturar and eh_minha_vez:
                txt_vez = "⚔ CAPTURE uma peça do oponente!"
                cor_vez = "#d4860a"
            elif eh_minha_vez:
                txt_vez = "► SUA VEZ"
                cor_vez = "#1a8a45"
            else:
                txt_vez = "◇ Aguardando oponente..."
                cor_vez = "#7f8c8d"
            self.create_text(180, 38, anchor="w", fill=cor_vez,
                             font=("Consolas", 10, "bold"), text=txt_vez)

        # Linha separadora
        self.create_line(0, self._margem_topo - 5, self._largura, self._margem_topo - 5,
                         fill=COR_BORDA, width=2)

    # ------------------------------------------------------------------ #
    #  Grade do tabuleiro                                                 #
    # ------------------------------------------------------------------ #

    def _desenhar_grade(self) -> None:
        x0, y0 = self._margem_lateral, self._margem_topo
        x1 = self._largura - self._margem_lateral
        y1 = self._altura - self._margem_inferior

        # Fundo da área de jogo
        self.create_rectangle(x0, y0, x1, y1, fill=COR_TABULEIRO_FUNDO, outline=COR_BORDA, width=2)

        for col in range(1, self.COLUNAS):
            x = x0 + col * self._cel_w
            self.create_line(x, y0, x, y1, fill=COR_GRADE, width=1)
        for lin in range(1, self.LINHAS):
            y = y0 + lin * self._cel_h
            self.create_line(x0, y, x1, y, fill=COR_GRADE, width=1)

        # Rótulos de colunas e linhas
        for col in range(self.COLUNAS):
            cx = x0 + col * self._cel_w + self._cel_w / 2
            self.create_text(cx, y1 + 10, text=str(col), fill=COR_BARRA_STATUS_TEXTO2,
                             font=("Consolas", 8))
        for lin in range(self.LINHAS):
            cy = y0 + lin * self._cel_h + self._cel_h / 2
            self.create_text(x0 - 10, cy, text=str(lin), fill=COR_BARRA_STATUS_TEXTO2,
                             font=("Consolas", 8))

    # ------------------------------------------------------------------ #
    #  Utilitários de geometria                                           #
    # ------------------------------------------------------------------ #

    def _centro(self, linha: int, coluna: int) -> Tuple[float, float]:
        cx = self._margem_lateral + coluna * self._cel_w + self._cel_w / 2
        cy = self._margem_topo + linha * self._cel_h + self._cel_h / 2
        return cx, cy

    def _anel(self, linha: int, coluna: int, cor: str, espessura: int) -> None:
        cx, cy = self._centro(linha, coluna)
        raio = min(self._cel_w, self._cel_h) * 0.42
        self.create_oval(cx - raio, cy - raio, cx + raio, cy + raio,
                         outline=cor, width=espessura, fill="", tags="jogo")

    def _pixel_para_celula(self, x: int, y: int) -> Tuple[Optional[int], Optional[int]]:
        """Converte coordenadas de pixel em (linha, coluna) lógica."""
        x0 = self._margem_lateral
        y0 = self._margem_topo
        x1 = self._largura - self._margem_lateral
        y1 = self._altura - self._margem_inferior

        if x < x0 or x >= x1 or y < y0 or y >= y1:
            return None, None

        coluna = int((x - x0) / self._cel_w)
        linha = int((y - y0) / self._cel_h)

        if 0 <= linha < self.LINHAS and 0 <= coluna < self.COLUNAS:
            return linha, coluna
        return None, None

    # ------------------------------------------------------------------ #
    #  Captura de clique                                                  #
    # ------------------------------------------------------------------ #

    def _ao_clicar(self, evento) -> None:
        """
        Converte o clique do mouse em coordenadas lógicas.

        Fluxo:
            pixel (x,y) → _pixel_para_celula() → (linha, coluna)
            → callback registrado por aplicacao_tk
        """
        if not self._callback_clique:
            return
        linha, coluna = self._pixel_para_celula(evento.x, evento.y)
        if linha is not None and coluna is not None:
            self._callback_clique(linha, coluna)
