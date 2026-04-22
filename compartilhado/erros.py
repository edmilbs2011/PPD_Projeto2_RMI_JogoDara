class ErroDeProtocolo(Exception):
    """Exceção para erros ligados ao protocolo da aplicação."""
    pass


class ErroDeTransporte(Exception):
    """Exceção para falhas no transporte de rede."""
    pass
