# Projeto2 — Jogo Dara (RMI com Pyro5) — Programação Paralela e Distribuída

Implementação do Jogo de Tabuleiro **Dara** (origem africana — Nigéria) com
comunicação **Cliente/Servidor via RMI (Remote Method Invocation)** usando a
biblioteca **Pyro5**, com **RMI bidirecional** e resolução de endereços via
**Servidor de Nomes Pyro5**. UI gráfica em **Tkinter (Canvas)**.

Disciplina: **Programação Paralela e Distribuída** — Engenharia da Computação — IFCE.

---

## Arquitetura — RMI Bidirecional via Servidor de Nomes

Toda comunicação ocorre por chamada remota direta, sem polling e sem buffer.
O servidor de nomes é o ponto central de descoberta para **ambos os lados**:

- O **servidor do jogo** registra `"jogo.dara"` → URI do daemon do jogo.
- Cada **cliente** registra `"dara.cliente.<uuid>"` → URI do seu objeto de callback.

O servidor resolve os contratos em duas direções:

| Direção | Quem chama | O quê chama | Como descobre |
|---|---|---|---|
| Cliente → Servidor | `aplicacao_tk` | métodos de `InterfaceServidor` | `ns.lookup("jogo.dara")` |
| Servidor → Cliente | `AplicacaoServidor` | `InterfaceClienteCallback.receber()` | `ns.lookup("dara.cliente.<uuid>")` |

### Fluxo de CONEXÃO (diálogo → NS → proxy bidirecional)

```
1. Usuário informa nickname, host e porta do servidor de nomes
2. Cliente cria _ClienteCallback e o registra no Daemon Pyro5 local
3. ns.register("dara.cliente.<uuid>", uri_callback) publica o callback no NS
4. Daemon local sobe em thread de background para receber chamadas do servidor
5. ns.lookup("jogo.dara") retorna a URI do daemon do jogo
6. proxy.hello(apelido, "dara.cliente.<uuid>") registra o jogador no servidor
7. Servidor faz ns.lookup("dara.cliente.<uuid>") e armazena o proxy do callback
```

### Fluxo de ENVIO (clique → servidor, cliente → servidor)

```
1. tabuleiro_canvas captura o clique do mouse (<Button-1>)
2. _pixel_para_celula() converte pixels em (linha, coluna)
3. aplicacao_tk chama o método no proxy Pyro5:
       self._servidor.colocar(id_cliente, linha, coluna)
4. Pyro5 serializa, transporta e executa o método no servidor
5. O retorno (lista de dicts) é processado imediatamente por _processar_respostas()
```

### Fluxo de RECEBIMENTO (servidor → cliente, RMI inverso)

```
1. Servidor conclui uma ação (colocar, mover, capturar, chat, game_over...)
2. Resolve a URI do callback do outro jogador (já armazenada desde o hello())
3. Chama proxy_callback.receber([msgs]) — chamada RMI direta ao cliente
4. Daemon local do cliente recebe a chamada na thread de background
5. _ClienteCallback.receber() agenda _processar_respostas() via after(0, ...)
6. Thread principal do Tkinter processa as mensagens e atualiza a interface
```

Não há polling, não há buffer. Cada evento chega ao destino no momento em que ocorre.

### Diagrama

```
┌────────────────────────── CLIENTE A ──────────────────────────┐
│                                                               │
│  [ Diálogo de Conexão ]                                       │
│      registra "dara.cliente.uuid-A" no NS                     │
│      resolve "jogo.dara" no NS → proxy do servidor            │
│      hello(apelido, "dara.cliente.uuid-A")                    │
│                                                               │
│  [ tabuleiro_canvas ]                                         │
│      clique → _pixel_para_celula() → (linha, coluna)          │
│      ▼                                                        │
│  [ aplicacao_tk ]                          [ _ClienteCallback ]
│      │  proxy.colocar(id, linha, coluna)       ▲  receber()  │
│      │  ──── RMI: cliente → servidor ────      │  RMI inverso│
│      ▼  retorno imediato (STATE/ERROR)          │             │
│  _processar_respostas() → atualiza UI          │             │
│                                                │             │
│  [ Daemon Pyro5 local — thread background ] ───┘             │
│                                                               │
└───────────────────────────────────────────────────────────────┘
                          │  ▲
        RMI cliente→server │  │ RMI server→cliente (callback)
                          ▼  │
┌─────────────────── SERVIDOR DE NOMES ─────────────────────────┐
│  [ Pyro5 Name Server ]                                        │
│      "jogo.dara"             → URI do daemon do jogo          │
│      "dara.cliente.uuid-A"   → URI do callback do cliente A   │
│      "dara.cliente.uuid-B"   → URI do callback do cliente B   │
└───────────────────────────────────────────────────────────────┘
                          │  ▲
                          ▼  │
┌────────────────────────── SERVIDOR ───────────────────────────┐
│                                                               │
│  [ AplicacaoServidor ] — instância única                      │
│      registra "jogo.dara" no NS ao iniciar                    │
│      recebe chamada RMI → adquire _lock → valida e executa    │
│      retorna List[dict] ao chamador (retorno direto)          │
│      chama receber() no callback do outro jogador (RMI inv.)  │
│                                                               │
│  Sem obter_estado(), sem _resultados, sem _chats              │
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

### Protocolo de mensagens

| Tipo | Quando | Como chega ao destino |
|---|---|---|
| `WELCOME` | Retorno de `hello()` | Valor de retorno direto (chamador) |
| `LOBBY` | Conexão, `pronto()`, `desconectar()` | Retorno direto (chamador) + `receber()` (outros) |
| `STATE` | Qualquer ação de jogo bem-sucedida | Retorno direto (chamador) + `receber()` (oponente) |
| `ERROR` | Ação inválida (vez errada, casa ocupada, etc.) | Valor de retorno direto (chamador) |
| `GAME_OVER` | Fim de partida | Retorno direto (chamador) + `receber()` (oponente) |
| `CHAT` | `chat()` | `receber()` no callback do oponente (RMI direto) |

### Contratos RMI (`compartilhado/interfaces.py`)

```python
class InterfaceServidor:          # registrado como "jogo.dara"
    def hello(apelido, nome_callback) -> dict
    def colocar(id_cliente, linha, coluna) -> List[dict]
    def mover(id_cliente, fr, fc, tr, tc) -> List[dict]
    def capturar(id_cliente, linha, coluna) -> List[dict]
    def pronto(id_cliente) -> List[dict]
    def desistir(id_cliente) -> List[dict]
    def nova_partida(id_cliente) -> List[dict]
    def chat(id_cliente, texto) -> None
    def desconectar(id_cliente) -> None

class InterfaceClienteCallback:   # registrado como "dara.cliente.<uuid>"
    def receber(msgs: List[dict]) -> None
```

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

### 1. Servidor de Nomes

Deve ser iniciado **antes** do servidor do jogo e dos clientes.
Por padrão escuta na porta `9090`.

```bash
python -m Pyro5.nameserver
```

Para escutar em um IP específico (útil em rede local):

```bash
python -m Pyro5.nameserver -n 0.0.0.0
```

### 2. Servidor do Jogo

```bash
python -m servidor.principal
```

Argumentos disponíveis:

| Argumento | Padrão | Descrição |
|---|---|---|
| `--host` | `localhost` | IP em que o daemon do jogo vai escutar |
| `--port` | `9000` | Porta do daemon do jogo |
| `--ns-host` | `localhost` | IP do servidor de nomes |
| `--ns-port` | `9090` | Porta do servidor de nomes |

Exemplo em rede local:

```bash
python -m servidor.principal --host 0.0.0.0 --ns-host 192.168.1.10
```

O servidor imprime no terminal:

```
Servidor Dara RMI v3.0 iniciado
URI do daemon: PYRO:jogo.dara@0.0.0.0:9000
Registrado no servidor de nomes (localhost:9090) como 'jogo.dara'
```

### 3. Cliente (em cada máquina)

```bash
python -m cliente.principal
```

No diálogo de conexão, informe:
- **Nickname** — seu nome no jogo
- **Host / IP do servidor de nomes** — endereço da máquina onde o servidor de nomes está rodando
- **Porta do servidor de nomes** — padrão `9090`

Clique em **Conectar**. O cliente registra seu callback no servidor de nomes, resolve
o endereço do jogo e estabelece a conexão RMI bidirecional. Em seguida, clique em
**Pronto** para sinalizar que está pronto para jogar.

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
PPD_Projeto2_RMI_JogoDara/
├── compartilhado/
│   ├── interfaces.py           # Contratos RMI: InterfaceServidor e InterfaceClienteCallback
│   ├── tipos_protocolo.py      # TipoMensagem (Literal type)
│   └── erros.py                # Exceções do domínio
├── servidor/
│   ├── dominio/
│   │   ├── regras.py           # Regras do Dara (trinca, adjacência, movimentos legais)
│   │   └── estado_partida.py   # Dataclasses JogadorConectado e Partida
│   ├── aplicacao/
│   │   └── aplicacao_servidor.py  # Objeto RMI exposto via Pyro5 (InterfaceServidor)
│   └── principal.py            # Daemon do jogo + registro no servidor de nomes
├── cliente/
│   ├── interface/
│   │   ├── aplicacao_tk.py     # UI + _ClienteCallback (InterfaceClienteCallback) + proxy
│   │   ├── tabuleiro_canvas.py # Canvas do tabuleiro + barra de status
│   │   └── prateleira_pecas.py # Prateleira visual de peças
│   └── principal.py            # Ponto de entrada do cliente
└── README.md
```
