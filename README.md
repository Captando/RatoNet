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

### RTMP Relay (Multi-Streamer)
- **Cada streamer configura suas próprias stream keys** (Twitch, YouTube, Kick, custom)
- Relay individual por streamer — quando conecta, sobe FFmpeg; quando desconecta, mata
- Suporte a múltiplos destinos simultâneos por streamer (multistream)
- URLs RTMP mascaradas na API (segurança das stream keys)
- Alocação dinâmica de portas SRT por streamer

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
- **LivePix** — Alertas de doação animados (integração LivePix)

Cada overlay é um HTML autocontido, adicionado no OBS como Browser Source.

### Painel do Streamer (`/panel/`)
- Login com API key — responsivo (mobile + desktop)
- **Dashboard** — Status ao vivo, GPS, health score
- **Perfil** — Editar nome, avatar, cor, redes sociais
- **Stream Keys** — Gerenciar destinos RTMP (Twitch, YouTube, Kick)
- **Overlays** — URLs copiáveis para OBS + config do field agent
- **LivePix** — Configurar token para alertas de doação

### Painel Admin (`/admin/`)
- Login com ADMIN_TOKEN
- **Dashboard** — Contadores do sistema (registrados, aprovados, online)
- **Streamers** — Tabela com aprovação, crown, remoção, filtros
- **Monitor** — Telemetria em tempo real via WebSocket (GPS, health, hardware, rede)

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

## Hardware Recomendado

Guia completo para o streamer montar seu setup IRL solo:

### Encoder (computador de campo)

| Dispositivo | Uso | Observações |
|---|---|---|
| **Raspberry Pi 5 (8GB)** | Encoder + telemetria | Leve, barato, roda srtla_send + field agent. Melhor custo-benefício. |
| **Intel NUC / Mini PC** | Encoding pesado (1080p60) | Mais potência para encoding por hardware (Intel QuickSync) |
| **Laptop velho** | Alternativa zero custo | Qualquer laptop com Linux funciona |

### Modems / Conectividade

| Dispositivo | Tipo | Observações |
|---|---|---|
| **Huawei E3372h** | Modem USB 4G | Barato, plug-and-play no Linux. Use 2-4 unidades com chips de operadoras diferentes. |
| **Quectel RM520N** | Modem 5G M.2 | Alta performance, precisa de adaptador USB |
| **GL.iNet Mudi V2 (GL-E750V2)** | Roteador 4G portátil | Tem bateria própria, OpenWrt, bom para setup compacto |
| **Starlink Mini** | Internet satelital | Backup para áreas sem 4G. ~1kg, alimenta via USB-C PD. |
| **Peplink MAX BR1** | Roteador bonding | Bonding nativo por hardware (alternativa cara ao SRTLA) |

> **Dica:** Para bonding, use **2-4 chips de operadoras diferentes** (ex: Claro + Vivo + Tim + Oi). O SRTLA distribui pacotes entre todos os links automaticamente.

### GPS

| Dispositivo | Uso | Observações |
|---|---|---|
| **u-blox 7/8/9 USB** | GPS dedicado | ~R$30, plug-and-play com gpsd. Precisão de 2-3m. |
| **Celular com PWA** | GPS via browser | Alternativa sem hardware extra — use a PWA em `/pwa/` |

### Camera / Captura

| Dispositivo | Uso | Observações |
|---|---|---|
| **GoPro Hero** | Camera de ação | Saída HDMI limpa (sem OSD), resistente a chuva |
| **Sony ZV-1 / ZV-E10** | Camera dedicada | Melhor qualidade de imagem, autofoco excelente |
| **Elgato Cam Link 4K** | Placa de captura USB | HDMI → USB, funciona como webcam no Linux |
| **Captura genérica USB** | Alternativa barata | ~R$50 no AliExpress, funciona com v4l2 |
| **Webcam USB** | Alternativa simples | Logitech C920/C922 — sem placa de captura |

### Energia

| Dispositivo | Uso | Observações |
|---|---|---|
| **Powerbank 20.000+ mAh** | Alimentação principal | USB-C PD (65W+) para Raspberry Pi + modems |
| **Powerbank 50.000 mAh** | Longa duração | Para lives de 8+ horas |
| **Bateria V-Mount** | Setup profissional | 14.4V, mais capacidade, mais pesada |

### Montagem

| Item | Uso |
|---|---|
| **Mochila com abertura lateral** | Acomoda encoder + modems + powerbank |
| **Gimbal DJI RS / Zhiyun** | Estabilização (opcional) |
| **Tripod de selfie** | Alternativa leve |

### Setup Mínimo (baixo custo)

```
Raspberry Pi 5 (8GB)       ~R$ 500
2x Huawei E3372h (4G)      ~R$ 200
GPS USB u-blox              ~R$  30
Webcam Logitech C920        ~R$ 300
Powerbank 20.000mAh PD      ~R$ 150
Mochila                     ~R$  80
                     Total: ~R$ 1.260
```

---

## VPS Recomendada

O servidor VPS precisa de:
- **IP público** com portas UDP abertas (SRT/SRTLA)
- **2+ vCPU, 4+ GB RAM** (SRT receiver + FFmpeg relay)
- **Localização próxima** ao streamer (latência menor = stream mais estável)

Recomendamos a [**Hostinger VPS**](https://hostinger.com.br?REFERRALCODE=BY1GDEV2DDXO) — planos KVM com IP dedicado, bom custo-benefício para IRL streaming:

| Plano | Specs | Uso |
|---|---|---|
| **KVM 1** | 1 vCPU, 4GB RAM | 1 streamer, relay simples |
| **KVM 2** | 2 vCPU, 8GB RAM | Recomendado — múltiplos streamers + SRTLA + relay |
| **KVM 4** | 4 vCPU, 16GB RAM | Setup profissional com vários destinos RTMP |

### Setup Rápido na VPS

```bash
# 1. Na VPS (Ubuntu/Debian)
sudo apt update && sudo apt install -y docker.io docker-compose-plugin git

# 2. Clone o projeto
git clone https://github.com/Captando/RatoNet.git
cd RatoNet

# 3. Configure
cp .env.example .env
nano .env  # ajuste ADMIN_TOKEN, RTMP_PRIMARY_URL, etc.

# 4. Suba
docker compose up -d

# 5. Abra as portas no firewall
sudo ufw allow 8000/tcp   # Dashboard
sudo ufw allow 9000:9003/udp  # SRT
sudo ufw allow 5001/udp   # SRTLA
```

Acesse `http://SEU-IP:8000` para ver o dashboard.

---

## Setup Rápido (Desenvolvimento Local)

### Requisitos
- Python 3.9+
- FFmpeg (para pipeline de vídeo)
- srtla_send / srtla_rec (opcional, para bonding BELABOX)
- gpsd (opcional, para GPS real)

### Instalação

```bash
git clone https://github.com/Captando/RatoNet.git
cd RatoNet
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
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

# RTMP Relay (legado — agora cada streamer configura via API)
# RTMP_PRIMARY_URL e RTMP_SECONDARY_URL são usados apenas como fallback global
RTMP_PRIMARY_URL=
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

**Com Docker (recomendado para produção):**
```bash
cp .env.example .env
# edite .env com suas configurações
docker compose up -d
```

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

**Testes:**
```bash
pytest
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

### Configurar Stream Keys

Cada streamer configura seus próprios destinos de stream (Twitch, YouTube, Kick, etc.):

```bash
# Configurar destinos RTMP
curl -X PUT "http://localhost:8000/api/me/destinations?api_key=SUA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '[
    {"platform": "twitch", "rtmp_url": "rtmp://live.twitch.tv/app/live_SUA_KEY", "enabled": true},
    {"platform": "youtube", "rtmp_url": "rtmp://a.rtmp.youtube.com/live2/SUA_KEY", "enabled": true}
  ]'

# Verificar destinos configurados (URLs mascaradas)
curl "http://localhost:8000/api/me/destinations?api_key=SUA_API_KEY"
```

Quando o field agent conectar, o servidor sobe automaticamente os relays FFmpeg para cada destino habilitado. Ao desconectar, os relays são encerrados.

### Endpoints Principais

| Método | Endpoint | Auth | Descrição |
|---|---|---|---|
| POST | `/api/register` | — | Cadastro de streamer |
| GET | `/api/me` | api_key | Dados do próprio perfil |
| PUT | `/api/me` | api_key | Atualizar perfil |
| GET | `/api/me/config` | api_key | Config pronta para field agent |
| GET | `/api/me/destinations` | api_key | Lista destinos de stream (URLs mascaradas) |
| GET | `/api/me/destinations/full` | api_key | Lista destinos com URLs completas (para painel) |
| PUT | `/api/me/destinations` | api_key | Configura destinos RTMP (Twitch, YouTube, etc.) |
| GET | `/api/me/livepix` | api_key | Token LivePix configurado |
| PUT | `/api/me/livepix` | api_key | Salvar token LivePix |
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
| GET | `/api/admin/stats` | admin_token | Contadores e streamers online |
| POST | `/api/admin/streamers/{id}/approve` | admin_token | Aprovar streamer |
| POST | `/api/admin/streamers/{id}/crown` | admin_token | Toggle crown (destaque) |
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
http://seu-servidor:8000/static/overlays/livepix.html?streamer_id=UUID&pull_key=pk_XXX
```

> **LivePix:** Configure o token no painel do streamer (`/panel/` → aba LivePix). O overlay conecta direto ao WebSocket da LivePix e exibe alertas de doação animados. Para testar, adicione `&test=1` na URL.

Tamanhos recomendados:
- **Mapa**: 400x300
- **Velocidade**: 300x120
- **Localização**: 500x60
- **Saúde**: 250x130
- **LivePix**: 450x200

---

## PWA GPS Tracker

Acesse `/pwa/` no celular do streamer:

1. Faça login com Streamer ID e API Key
2. Toque "Iniciar Tracking"
3. Para melhor experiência, use "Adicionar na tela inicial"

O tracker usa `watchPosition` com alta precisão e mantém a tela ligada via Wake Lock API. Se a conexão cair, os pontos GPS são enfileirados e enviados automaticamente ao reconectar.

> **Nota:** No iOS, o tracking em background é limitado pelo sistema. Para uso contínuo, mantenha o app em primeiro plano. No Android, funciona em background normalmente.

---

## Painéis Web

### Painel do Streamer (`/panel/`)

Acesse `http://seu-servidor:8000/panel/` e faça login com sua **API key**.

**Tabs disponíveis:**
- **Dashboard** — Status ao vivo, GPS, health score, uptime
- **Perfil** — Editar nome, avatar, cor, redes sociais
- **Stream Keys** — Gerenciar destinos RTMP (Twitch, YouTube, Kick) com toggle liga/desliga
- **Overlays** — URLs copiáveis para cada overlay OBS + config do field agent
- **LivePix** — Configurar token para alertas de doação no overlay

### Painel Admin (`/admin/`)

Acesse `http://seu-servidor:8000/admin/` e faça login com o **ADMIN_TOKEN**.

**Tabs disponíveis:**
- **Dashboard** — Contadores: registrados, aprovados, online, field agents, dashboards
- **Streamers** — Tabela completa com ações (aprovar, crown, remover) e filtros (todos/pendentes/aprovados/online)
- **Monitor** — Telemetria em tempo real via WebSocket (GPS, health bar, hardware, rede)

---

## Estrutura do Projeto

```
RatoNet/
├── index.html                    # Dashboard frontend (mapa + sidebar)
├── pyproject.toml                # Packaging + entry points CLI
├── requirements.txt              # Dependências Python
├── Dockerfile                    # Container para VPS
├── docker-compose.yml            # Deploy com Docker Compose
├── .env.example                  # Template de configuração
├── LICENSE                       # MIT
├── CONTRIBUTING.md               # Guia de contribuição
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
│   │   ├── health.html           # Score de saúde da conexão
│   │   └── livepix.html          # Alertas de doação LivePix
│   │
│   ├── panel/                    # Painel do Streamer (SPA)
│   │   └── index.html            # Login + 5 tabs (perfil, keys, overlays, livepix)
│   │
│   ├── admin/                    # Painel Admin (SPA)
│   │   └── index.html            # Login + 3 tabs (dashboard, streamers, monitor)
│   │
│   └── pwa/                      # PWA GPS Tracker (celular)
│       ├── index.html            # Login
│       ├── tracker.html          # Tracker GPS principal
│       ├── manifest.json         # PWA manifest
│       ├── sw.js                 # Service Worker
│       ├── icon-192.svg          # Ícone app
│       └── icon-512.svg          # Ícone app (grande)
│
└── tests/                        # Testes (pytest)
    ├── test_config.py            # Configuração
    ├── test_models.py            # Pydantic models
    ├── test_geocoder.py          # Geocoder + haversine
    ├── test_db.py                # CRUD SQLite
    ├── test_routes.py            # Endpoints REST
    └── test_relay.py             # Relay + PortAllocator
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
