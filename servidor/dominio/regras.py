from __future__ import annotations

from typing import List, Set, Tuple

QUANTIDADE_LINHAS = 5
QUANTIDADE_COLUNAS = 6


def esta_dentro_do_tabuleiro(linha: int, coluna: int) -> bool:
    """Verifica se a coordenada está dentro dos limites do tabuleiro."""
    return 0 <= linha < QUANTIDADE_LINHAS and 0 <= coluna < QUANTIDADE_COLUNAS


def sao_adjacentes(
    linha_origem: int, coluna_origem: int,
    linha_destino: int, coluna_destino: int,
) -> bool:
    """Verifica se duas casas são ortogonalmente adjacentes."""
    return abs(linha_origem - linha_destino) + abs(coluna_origem - coluna_destino) == 1


def contar_pecas_do_jogador(tabuleiro: List[List[int]], identificador_jogador: int) -> int:
    """Conta quantas peças de um jogador existem no tabuleiro."""
    return sum(
        1
        for linha in range(QUANTIDADE_LINHAS)
        for coluna in range(QUANTIDADE_COLUNAS)
        if tabuleiro[linha][coluna] == identificador_jogador
    )


def existe_movimento_legal(tabuleiro: List[List[int]], identificador_jogador: int) -> bool:
    """Verifica se o jogador ainda possui ao menos um movimento válido."""
    for linha in range(QUANTIDADE_LINHAS):
        for coluna in range(QUANTIDADE_COLUNAS):
            if tabuleiro[linha][coluna] != identificador_jogador:
                continue
            for dl, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nl, nc = linha + dl, coluna + dc
                if esta_dentro_do_tabuleiro(nl, nc) and tabuleiro[nl][nc] == 0:
                    return True
    return False


def _localizar_trincas(
    tabuleiro: List[List[int]], identificador_jogador: int,
) -> Set[Tuple[Tuple[int, int], ...]]:
    """Localiza todas as sequências de três peças do mesmo jogador."""
    trincas: Set[Tuple[Tuple[int, int], ...]] = set()

    # Horizontais
    for linha in range(QUANTIDADE_LINHAS):
        for coluna in range(QUANTIDADE_COLUNAS - 2):
            if (
                tabuleiro[linha][coluna] == identificador_jogador
                and tabuleiro[linha][coluna + 1] == identificador_jogador
                and tabuleiro[linha][coluna + 2] == identificador_jogador
            ):
                trincas.add(((linha, coluna), (linha, coluna + 1), (linha, coluna + 2)))

    # Verticais
    for linha in range(QUANTIDADE_LINHAS - 2):
        for coluna in range(QUANTIDADE_COLUNAS):
            if (
                tabuleiro[linha][coluna] == identificador_jogador
                and tabuleiro[linha + 1][coluna] == identificador_jogador
                and tabuleiro[linha + 2][coluna] == identificador_jogador
            ):
                trincas.add(((linha, coluna), (linha + 1, coluna), (linha + 2, coluna)))

    return trincas


def forma_trinca(tabuleiro: List[List[int]], identificador_jogador: int) -> bool:
    """Informa se o tabuleiro contém ao menos uma trinca para o jogador."""
    return len(_localizar_trincas(tabuleiro, identificador_jogador)) > 0
