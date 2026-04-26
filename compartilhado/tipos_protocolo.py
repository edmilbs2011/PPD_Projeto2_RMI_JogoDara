from __future__ import annotations

from typing import Literal

# Tipos de mensagem trocados via RMI entre cliente e servidor
TipoMensagem = Literal[
    "WELCOME", "LOBBY", "START", "STATE", "ERROR", "CHAT", "GAME_OVER"
]
