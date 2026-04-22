# Projeto2 — Jogo Dara (RMI com Pyro5) — Programação Paralela e Distribuída

Implementação do Jogo de Tabuleiro **Dara** (origem africana — Nigéria) com
comunicação **Cliente/Servidor via RMI (Remote Method Invocation)** usando a
biblioteca **Pyro5**, sem socket manual, sem JSONL e sem fila de mensagens.
UI gráfica em **Tkinter (Canvas)**.

Disciplina: **Programação Paralela e Distribuída** — Engenharia da Computação — IFCE.

---

## Arquitetura — RMI com Pyro5 (sem fila, sem barramento de eventos)

O servidor expõe um único objeto Python (`AplicacaoServidor`) via Pyro5.
O cliente obtém um **proxy** desse objeto e chama seus métodos diretamente,
como se fossem chamadas locais. O Pyro5 cuida de toda a serialização e transporte.

### Fluxo de ENVIO (clique do mouse → servidor)

```
1. tabuleiro_canvas captura o clique do mouse (<Button-1>)
2. _pixel_para_celula() converte pixels em (linha, coluna)
3. aplicacao_tk chama o método no proxy Pyro5:
       self._servidor.colocar(id_cliente, linha, coluna)
4. Pyro5 serializa, transporta e executa o método no servidor
5. O retorno (lista de dicts) é processado imediatamente por _processar_respostas()
```

### Fluxo de RECEBIMENTO — jogador que aguarda a vez do oponente

```
1. _ciclo_rede() é chamado pelo Tkinter a cada 50 ms
2. Chama self._servidor.obter_estado(id_cliente)
3. O servidor deriva o estado atual do jogo diretamente (sem fila) e retorna
   STATE ou LOBBY; se houver pendentes, inclui GAME_OVER e/ou CHAT
4. aplicacao_tk chama _tratar_mensagem() para cada dict e atualiza a tela
```

### Por que dois mini-buffers ainda existem no servidor

| Buffer | Motivo |
|---|---|
| `_resultados` (GAME_OVER) | Quando a partida encerra, `partida_atual = None` e o estado não pode mais ser derivado. O GAME_OVER fica guardado até o outro jogador fazer polling. |
| `_chats` (mensagens de chat) | Chat é broadcast e não pode ser reconstruído a partir do estado do jogo.|

### Diagrama

```
┌────────────────────────── CLIENTE ────────────────────────────┐
│                                                               │
│  [ tabuleiro_canvas ]                                         │
│      │  clique (pixel)                                        │
│      │  _pixel_para_celula() → (linha, coluna)                │
│      ▼  callback registrado em vincular_clique()              │
│  [ aplicacao_tk ]                                             │
│      │  self._servidor.colocar(id_cliente, linha, coluna)     │
│      │         ──── chamada direta via proxy Pyro5 ────       │
│      ▼                                                        │
│  RMI retorna List[dict] imediatamente                         │
│      │                                                        │
│      ▼  _processar_respostas()                                │
│  [ aplicacao_tk._tratar_mensagem() ]                          │
│      atualiza estado local e chama tabuleiro_canvas.renderizar│
│                                                               │
│  [ _ciclo_rede() — a cada 50 ms ]                             │
│      self._servidor.obter_estado(id_cliente)                  │
│      ─── notifica o jogador que aguarda a vez do oponente ─── │
│                                                               │
└───────────────────────────────────────────────────────────────┘

┌────────────────────────── SERVIDOR ───────────────────────────┐
│                                                               │
│  [ AplicacaoServidor ] — objeto único (instance_mode=single)  │
│      │  recebe chamada RMI (thread Pyro5)                     │
│      │  adquire _lock (threading.Lock)                        │
│      │  valida e executa regras do domínio                    │
│      │  incrementa _versao a cada mudança de estado           │
│      │  retorna List[dict] diretamente ao chamador            │
│      ▼                                                        │
│  obter_estado(id_cliente, versao_cliente=-1)                  │
│      só inclui STATE/LOBBY quando _versao > versao_cliente    │
│      esvazia _resultados e _chats pendentes se houver         │
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

### Protocolo de mensagens (tipos de retorno)

| Tipo | Quando | Quem recebe |
|---|---|---|
| `WELCOME` | Retorno de `hello()` | Chamador |
| `LOBBY` | `pronto()`, `obter_estado()` sem partida | Chamador |
| `STATE` | Qualquer ação de jogo bem-sucedida | Chamador (imediato) e outro jogador (via polling) |
| `ERROR` | Ação inválida (vez errada, casa ocupada, etc.) | Chamador |
| `GAME_OVER` | Fim de partida | Chamador (imediato) + outro jogador (via `_resultados`) |
| `CHAT` | `obter_estado()` quando há mensagens pendentes | Cada jogador (via `_chats`) |

---

## Informações exibidas no Canvas

O `tabuleiro_canvas` exibe diretamente no canvas (sem widgets Tkinter extras):

- **Status da conexão** — indicador visual verde/vermelho
- **Nome do jogador** e **nome do oponente** com cores dos jogadores
- **De quem é a vez** — "► SUA VEZ" / "◇ Aguardando oponente..."
- **Fase da partida** — colocação / movimentação
- **Indicação de captura** — "⚔ CAPTURE uma peça do oponente!"

---

## Requisitos

- Python 3.10+
- [Pyro5](https://pyro5.readthedocs.io/) — `pip install Pyro5`

```bash
pip install Pyro5
```

---

## Como rodar

### 1. Servidor

```bash
python -m servidor.principal --host 0.0.0.0 --port 9000
```

O servidor imprime a URI no formato:

```
Servidor Dara RMI v2.0 iniciado
URI: PYRO:jogo.dara@0.0.0.0:9000
Clientes devem usar: PYRO:jogo.dara@<ip>:9000
```

### 2. Cliente (em cada máquina)

```bash
python -m cliente.principal
```

No diálogo de conexão, informe:
- **Nickname** — seu nome no jogo
- **Host / IP do servidor** — endereço da máquina do servidor
- **Porta** — padrão `9000`

Clique em **Pronto** para sinalizar que está pronto para jogar.

---

## Regras do Dara

- **Tabuleiro**: 5 linhas × 6 colunas
- **Peças**: 12 por jogador (vermelho — Jogador 1 / azul — Jogador 2)
- **Fase de colocação**: jogadores alternam colocando 1 peça por vez; não é permitido formar trinca ao colocar
- **Fase de movimentação**: move 1 peça para casa adjacente (cima/baixo/esquerda/direita)
- **Captura**: ao formar trinca (3 em linha horizontal ou vertical), o jogador deve remover 1 peça do oponente antes de continuar
- **Vitória**:
  - Oponente com ≤ 2 peças
  - Oponente sem movimentos legais
  - Desistência (`Desistir`)
  - Desconexão do oponente

---

## Estrutura do Projeto

```
PPD_Ptojeto2_RMI_JogoDara/
├── compartilhado/
│   ├── tipos_protocolo.py      # TipoMensagem (Literal type)
│   └── erros.py                # Exceções do domínio
├── servidor/
│   ├── dominio/
│   │   ├── regras.py           # Regras do Dara (trinca, adjacência, movimentos legais)
│   │   └── estado_partida.py   # Dataclasses JogadorConectado e Partida
│   ├── aplicacao/
│   │   └── aplicacao_servidor.py  # Objeto RMI exposto via Pyro5
│   └── principal.py            # Ponto de entrada do servidor (Pyro5 Daemon)
├── cliente/
│   ├── interface/
│   │   ├── aplicacao_tk.py     # Janela principal — proxy Pyro5 + lógica de UI
│   │   ├── tabuleiro_canvas.py # Canvas do tabuleiro + barra de status
│   │   └── prateleira_pecas.py # Prateleira visual de peças
│   └── principal.py            # Ponto de entrada do cliente
└── README.md
```
