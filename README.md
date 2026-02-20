# RatoNet

Plataforma open-source para **streaming IRL** (In Real Life) com foco em estabilidade de conexão, monitoramento em tempo real e operação resiliente em campo.

Projetada para streamers que transmitem de ambientes externos — estradas, expedições, regiões remotas — onde a conectividade é instável e múltiplos links de rede são essenciais.

---

## Arquitetura

```
┌─────────────────┐     WebSocket/REST      ┌─────────────────────────┐
│   Field Agent    │ ◄─────────────────────► │      VPS Server         │
│  (hardware IRL)  │     telemetria + GPS    │  (FastAPI + Dashboard)  │
└────────┬────────┘                          └────────┬──────┬────────┘
         │                                            │      │
   SRT + SRTLA bonding                          RTMP relay   │
         │                                            │      │
         └──────────────────────────┐    ┌────────────┘      │
                                    │    │              WebSocket
                                    ▼    ▼                   │
                              ┌──────────────┐    ┌──────────▼────────┐
                              │ Twitch/YouTube│    │  Dashboard Web    │
                              │  (via RTMP)   │    │  + Overlays OBS   │
                              └──────────────┘    │  + PWA GPS Tracker │
                                                   └───────────────────┘
```

O sistema é dividido em três componentes independentes:

| Componente | Função | Onde roda |
|---|---|---|
| **Field Agent** | Coleta GPS, hardware, rede; faz bonding SRT | No hardware de campo (Raspberry Pi, laptop, etc.) |
| **VPS Server** | Recebe streams, relay RTMP, health monitor, OBS control | Servidor VPS na nuvem |
| **Dashboard** | API REST, WebSocket em tempo real, mapa ao vivo, overlays | Mesmo servidor (FastAPI) |

---

## Funcionalidades

### Telemetria em Tempo Real
- **GPS** — Posição, velocidade, altitude, heading, satélites (via gpsd)
- **Hardware** — CPU, temperatura, RAM, disco, bateria (via psutil)
- **Rede** — RTT, jitter, packet loss, bandwidth por interface
- **Starlink** — Latência, velocidade, obstrução (via gRPC)
- **Reverse geocoding** — Nome do bairro/cidade via OpenStreetMap Nominatim

### Bonding de Rede
- **SRTLA** — Protocolo real de bonding do BELABOX (srtla_send + srtla_rec)
- **Bonding nativo** — Fallback multi-link SRT (1 stream por interface)
- **Auto-fallback** — Se binário SRTLA não encontrado, usa bonding nativo automaticamente

### Health Monitor + OBS
- Score de saúde 0-100 calculado em tempo real
- Estados: HEALTHY → DEGRADED → CRITICAL → DOWN
- Troca automática de cena OBS (LIVE ↔ BRB) via OBS WebSocket
- Delay configurável para evitar flapping

### RTMP Relay
- Relay automático do stream SRT para destinos RTMP
- Suporte a múltiplos destinos simultâneos (Twitch + YouTube)
- FFmpeg como backend

### Dashboard Web
- Mapa full-screen com Leaflet (camada dark CartoDB)
- Marcadores com avatar e trilha de deslocamento
- Sidebar com streamers ao vivo e métricas
- Atualização em tempo real via WebSocket
- API REST completa para integração

### Overlays OBS (estilo RealtimeIRL)
- **Mapa** — Mini-mapa Leaflet com posição e trilha
- **Velocidade** — Velocímetro digital com altitude e heading
- **Localização** — Nome do bairro/cidade (reverse geocoding)
- **Saúde** — Score e barras de qualidade de conexão

Cada overlay é um HTML autocontido, adicionado no OBS como Browser Source.

### PWA GPS Tracker
- App web instalável para celular do streamer
- Rastreamento GPS em background (`watchPosition` + Wake Lock API)
- Envio via WebSocket com fallback REST
- Fila offline com sync automático ao reconectar
- Service Worker para cache e operação sem rede

### Plataforma Multi-Streamer
- Registro de streamers com API key e pull key (read-only)
- Painel admin para aprovação e gerenciamento
- Suporte a múltiplos streamers simultâneos no mapa
- Cada streamer tem suas credenciais e configuração independente

---

## Setup Rápido

### Requisitos
- Python 3.9+
- FFmpeg (para pipeline de vídeo)
- srtla_send / srtla_rec (opcional, para bonding BELABOX)
- gpsd (opcional, para GPS real)

### Instalação

```bash
git clone git@github.com:Captando/RatoNet.git
cd RatoNet
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configuração

Copie e edite o `.env`:

```bash
cp .env.example .env
```

Variáveis principais:

```env
# Dashboard
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=8000
DASHBOARD_STATIC_DIR=.

# Banco de Dados
DB_PATH=ratonet.db
DB_AUTO_APPROVE=false

# Admin
ADMIN_TOKEN=seu_token_seguro_aqui

# SRT
SRT_BASE_PORT=9000
SRT_LATENCY_MS=500
SRT_MAX_LINKS=4

# SRTLA (opcional — desabilitado por padrão)
SRTLA_ENABLED=false
SRTLA_SEND_PORT=5000
SRTLA_REC_PORT=5001

# RTMP Relay
RTMP_PRIMARY_URL=rtmp://live.twitch.tv/app/SUA_STREAM_KEY
RTMP_SECONDARY_URL=

# OBS WebSocket
OBS_HOST=localhost
OBS_PORT=4455
OBS_PASSWORD=
OBS_SCENE_LIVE=LIVE
OBS_SCENE_BRB=BRB

# Field Agent
FIELD_SERVER_WS_URL=ws://seu-servidor:8000/ws/field
FIELD_TELEMETRY_INTERVAL_S=1.0
FIELD_GPS_DEVICE=localhost:2947
FIELD_STARLINK_ADDR=192.168.100.1:9200

# Health
HEALTH_THRESHOLD_DEGRADED=70
HEALTH_THRESHOLD_CRITICAL=40
HEALTH_THRESHOLD_DOWN=10
```

### Rodando

**Dashboard (desenvolvimento):**
```bash
source venv/bin/activate
python -m ratonet.dashboard.main
# Acesse http://localhost:8000
```

**VPS Server completo (SRT + relay + OBS + dashboard):**
```bash
python -m ratonet.server.main
```

**Field Agent:**
```bash
# Setup interativo
python -m ratonet.field.setup

# Ou direto
python -m ratonet.field.main --id SEU_UUID --key SUA_API_KEY
```

---

## API

### Registro

```bash
# Cadastrar novo streamer
curl -X POST http://localhost:8000/api/register \
  -H "Content-Type: application/json" \
  -d '{"name": "Meu Nome", "email": "email@exemplo.com"}'
```

Retorna `id`, `api_key` (escrita) e `pull_key` (leitura para overlays).

### Endpoints Principais

| Método | Endpoint | Auth | Descrição |
|---|---|---|---|
| POST | `/api/register` | — | Cadastro de streamer |
| GET | `/api/me` | api_key | Dados do próprio perfil |
| PUT | `/api/me` | api_key | Atualizar perfil |
| GET | `/api/me/config` | api_key | Config pronta para field agent |
| GET | `/api/streamers` | — | Lista streamers ao vivo |
| GET | `/api/streamers/{id}` | — | Dados de um streamer |
| GET | `/api/overlay/data/{id}` | pull_key | Dados para overlays OBS |
| POST | `/api/location` | api_key | Push GPS (fallback REST) |
| GET | `/api/health` | — | Health de todos os streamers |
| GET | `/api/status` | — | Status geral do sistema |

### Admin

| Método | Endpoint | Auth | Descrição |
|---|---|---|---|
| GET | `/api/admin/streamers` | admin_token | Lista todos os streamers |
| POST | `/api/admin/streamers/{id}/approve` | admin_token | Aprovar streamer |
| DELETE | `/api/admin/streamers/{id}` | admin_token | Remover streamer |

### WebSocket

| Endpoint | Direção | Descrição |
|---|---|---|
| `/ws/dashboard` | Server → Client | Atualizações de telemetria para browsers |
| `/ws/field/{id}?key=API_KEY` | Client → Server | Telemetria do field agent |

---

## Overlays OBS

Adicione como **Browser Source** no OBS:

```
http://seu-servidor:8000/static/overlays/speed.html?streamer_id=UUID&pull_key=pk_XXX
http://seu-servidor:8000/static/overlays/map.html?streamer_id=UUID&pull_key=pk_XXX
http://seu-servidor:8000/static/overlays/location.html?streamer_id=UUID&pull_key=pk_XXX
http://seu-servidor:8000/static/overlays/health.html?streamer_id=UUID&pull_key=pk_XXX
```

Tamanhos recomendados:
- **Mapa**: 400x300
- **Velocidade**: 300x120
- **Localização**: 500x60
- **Saúde**: 250x130

---

## PWA GPS Tracker

Acesse `/pwa/` no celular do streamer:

1. Faça login com Streamer ID e API Key
2. Toque "Iniciar Tracking"
3. Para melhor experiência, use "Adicionar na tela inicial"

O tracker usa `watchPosition` com alta precisão e mantém a tela ligada via Wake Lock API. Se a conexão cair, os pontos GPS são enfileirados e enviados automaticamente ao reconectar.

> **Nota:** No iOS, o tracking em background é limitado pelo sistema. Para uso contínuo, mantenha o app em primeiro plano. No Android, funciona em background normalmente.

---

## Estrutura do Projeto

```
RatoNet/
├── index.html                    # Dashboard frontend (mapa + sidebar)
├── requirements.txt              # Dependências Python
├── LICENSE                       # MIT
│
├── ratonet/                      # Backend Python
│   ├── config.py                 # Configuração centralizada (env vars)
│   │
│   ├── common/                   # Módulos compartilhados
│   │   ├── logger.py             # Logger colorido estruturado
│   │   └── protocol.py           # Protocolo WebSocket (MessageType)
│   │
│   ├── dashboard/                # FastAPI — API + WebSocket + admin
│   │   ├── main.py               # App FastAPI (lifespan, rotas, static)
│   │   ├── routes.py             # Endpoints REST (/api/*)
│   │   ├── admin.py              # Endpoints admin (/api/admin/*)
│   │   ├── ws_handler.py         # WebSocket manager (field + dashboard)
│   │   ├── models.py             # Pydantic models (GPS, Health, Streamer...)
│   │   ├── db.py                 # SQLite async (aiosqlite)
│   │   └── geocoder.py           # Reverse geocoding (Nominatim)
│   │
│   ├── field/                    # Field Agent — roda no hardware de campo
│   │   ├── main.py               # Agent principal (WebSocket client)
│   │   ├── setup.py              # Wizard interativo de configuração
│   │   ├── telemetry.py          # Coleta GPS + hardware + Starlink
│   │   ├── network_monitor.py    # Monitor de interfaces de rede
│   │   ├── bonding.py            # Bonding SRT (nativo + SRTLA)
│   │   └── encoder.py            # FFmpeg SRT encoder
│   │
│   └── server/                   # VPS Server — recebe streams
│       ├── main.py               # Orquestrador (SRT + relay + OBS + dashboard)
│       ├── srt_receiver.py       # SRT receiver (nativo + SRTLA)
│       ├── relay.py              # RTMP relay (FFmpeg)
│       ├── health.py             # Health monitor (score 0-100)
│       └── obs_controller.py     # OBS WebSocket (troca de cena)
│
├── static/                       # Arquivos estáticos
│   ├── overlays/                 # Overlays para OBS Browser Source
│   │   ├── map.html              # Mini-mapa Leaflet
│   │   ├── speed.html            # Velocímetro digital
│   │   ├── location.html         # Nome do local (geocoding)
│   │   └── health.html           # Score de saúde da conexão
│   │
│   └── pwa/                      # PWA GPS Tracker (celular)
│       ├── index.html            # Login
│       ├── tracker.html          # Tracker GPS principal
│       ├── manifest.json         # PWA manifest
│       ├── sw.js                 # Service Worker
│       ├── icon-192.svg          # Ícone app
│       └── icon-512.svg          # Ícone app (grande)
│
└── tests/                        # Testes
```

---

## APIs Externas Consumidas

| API | Uso | Auth |
|---|---|---|
| **Nominatim (OpenStreetMap)** | Reverse geocoding (coordenadas → nome do local) | Nenhuma (rate limit: 1 req/s) |
| **gpsd** | Dados GPS do receptor (via socket local) | Local |
| **Starlink gRPC** | Telemetria do dish Starlink | Local (rede 192.168.100.x) |
| **OBS WebSocket** | Controle de cenas (fallback automático) | Password local |

O sistema pode ser estendido para consumir qualquer API REST/WebSocket. A arquitetura modular permite adicionar novos coletores de telemetria em `ratonet/field/telemetry.py` ou novos endpoints em `ratonet/dashboard/routes.py`.

---

## Stack Técnica

| Camada | Tecnologia |
|---|---|
| Backend | Python 3.9+, FastAPI, aiosqlite, Pydantic v2, websockets |
| Frontend | HTML5, JavaScript vanilla, Tailwind CSS (CDN), Leaflet.js |
| Streaming | FFmpeg, SRT, SRTLA (BELABOX), RTMP |
| Banco | SQLite (async via aiosqlite) |
| GPS | gpsd, Geolocation Web API (PWA) |
| Overlays | HTML autocontido (OBS Browser Source) |
| PWA | Service Worker, Wake Lock API, Background Sync |

---

## Licença

MIT — veja [LICENSE](LICENSE).
