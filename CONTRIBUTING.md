# Contribuindo com o RatoNet

Contribuições são bem-vindas! Este guia explica como configurar o ambiente e enviar mudanças.

## Setup de Desenvolvimento

```bash
git clone https://github.com/Captando/RatoNet.git
cd RatoNet
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

## Rodando

```bash
# Dashboard (desenvolvimento com reload)
python -m ratonet.dashboard.main

# Acesse http://localhost:8000
```

## Testes

```bash
pytest
```

## Estrutura

```
ratonet/
├── common/      # Logger, protocolo WebSocket
├── config.py    # Configuração via env vars
├── dashboard/   # FastAPI (API + WebSocket + admin)
├── field/       # Field agent (telemetria + bonding)
└── server/      # VPS server (SRT + relay + OBS)
```

## Convenções

- **Python 3.9+** — use `Optional[X]`, `List[X]`, `Dict[K, V]` do `typing` (não `X | None`)
- **Commits** — mensagens em inglês, concisas, no imperativo ("add feature", não "added feature")
- **Testes** — adicione testes para funcionalidades novas em `tests/`
- **Sem build frontend** — o `index.html` é vanilla JS, sem framework ou bundler

## Fluxo de PR

1. Fork o repositório
2. Crie uma branch (`git checkout -b feat/minha-feature`)
3. Commit suas mudanças
4. Push para o fork
5. Abra um Pull Request descrevendo o que mudou e por quê
