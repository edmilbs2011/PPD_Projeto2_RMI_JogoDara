from __future__ import annotations

import tkinter as tk

COR_JOGADOR_1 = "#c0392b"
COR_JOGADOR_2 = "#2471a3"


class PrateleiraDePecas(tk.Canvas):
    """Desenha visualmente a prateleira de peças disponíveis ou capturadas."""

    def __init__(
        self,
        mestre,
        largura: int = 600,
        altura: int = 90,
        prefixo_titulo: str = "Sua prateleira",
        quantidade_inicial: int = 12,
        identificador_jogador: int = 1,
        **kw,
    ):
        super().__init__(mestre, width=largura, height=altura, bg="#f5f0e8",
                         highlightthickness=0, **kw)
        self._largura = largura
        self._altura = altura
        self.prefixo_titulo = prefixo_titulo
        self.quantidade_pecas = quantidade_inicial
        self.id_jogador = 1 if identificador_jogador == 1 else 2
        self._desenhar()

    def definir_jogador(self, id_jogador: int) -> None:
        self.id_jogador = 1 if id_jogador == 1 else 2
        self._desenhar()

    def definir_quantidade(self, qtd: int) -> None:
        self.quantidade_pecas = max(0, min(12, qtd))
        self._desenhar()

    def _cor(self) -> str:
        return COR_JOGADOR_1 if self.id_jogador == 1 else COR_JOGADOR_2

    def _nome_cor(self) -> str:
        return "vermelhas" if self.id_jogador == 1 else "azuis"

    def _desenhar(self) -> None:
        self.delete("all")
        m = 12
        topo, base = 34, 72

        titulo = f"{self.prefixo_titulo}: {self.quantidade_pecas} peças {self._nome_cor()}"
        self.create_text(m, 14, anchor="w", text=titulo, fill="#2c1a0e",
                         font=("Consolas", 10, "bold"))

        self.create_rectangle(m, topo, self._largura - m, base,
                              fill="#d7c3a3", outline="#9a7b4f", width=2)
        self.create_rectangle(m + 10, base, self._largura - m - 10, base + 5,
                              fill="#9a7b4f", outline="#7b603b", width=1)

        if self.quantidade_pecas <= 0:
            return

        raio = 11
        cy = (topo + base) / 2
        cor = self._cor()

        if self.quantidade_pecas == 1:
            xs = [self._largura / 2]
        else:
            esq = m + 24
            dire = self._largura - m - 24
            esp = (dire - esq) / (self.quantidade_pecas - 1)
            xs = [esq + i * esp for i in range(self.quantidade_pecas)]

        for cx in xs:
            self.create_oval(cx - raio, cy - raio, cx + raio, cy + raio,
                             fill=cor, outline="#222", width=2)
