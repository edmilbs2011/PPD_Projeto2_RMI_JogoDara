from __future__ import annotations

from typing import Literal

# Tipos de mensagem que o servidor enfileira para os clientes
TipoMensagem = Literal[
    "WELCOME", "LOBBY", "START", "STATE", "ERROR", "CHAT", "GAME_OVER"
]
