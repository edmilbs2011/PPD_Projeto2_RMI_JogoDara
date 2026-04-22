from __future__ import annotations

import tkinter as tk

from cliente.interface.aplicacao_tk import AplicacaoTk


def executar() -> None:
    raiz = tk.Tk()
    _app = AplicacaoTk(raiz)
    raiz.mainloop()


if __name__ == "__main__":
    executar()
