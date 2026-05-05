from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class JogadorConectado:
    """Representa um jogador conectado ao servidor."""
    identificador_cliente: str
    apelido: str
    identificador_jogador: int
    esta_pronto: bool = False
    vitorias: int = 0


@dataclass
class Partida:
    """Representa o estado completo de uma partida no servidor."""
    jogadores_por_identificador: Dict[int, JogadorConectado]
    tabuleiro: List[List[int]]
    jogador_da_vez: int
    fase: str
    precisa_capturar: bool
    jogador_que_deve_capturar: Optional[int]
    pecas_colocadas_por_jogador: Dict[int, int]
    pecas_capturadas_por_jogador: Dict[int, int]
    ultimo_movimento: Optional[dict] = None


def criar_nova_partida(
    jogador_um: JogadorConectado,
    jogador_dois: JogadorConectado,
) -> Partida:
    """Cria uma nova partida com tabuleiro limpo e contadores zerados."""
    return Partida(
        jogadores_por_identificador={1: jogador_um, 2: jogador_dois},
        tabuleiro=[[0] * 6 for _ in range(5)],
        jogador_da_vez=1,
        fase="colocação",
        precisa_capturar=False,
        jogador_que_deve_capturar=None,
        pecas_colocadas_por_jogador={1: 0, 2: 0},
        pecas_capturadas_por_jogador={1: 0, 2: 0},
        ultimo_movimento=None,
    )
