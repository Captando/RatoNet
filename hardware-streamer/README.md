# Pasta para hardware do streamer

Este diretório contém apenas o necessário para rodar o **Field Agent** no hardware de campo.

## O que está incluso

- `ratonet/field/` (agente, setup, telemetria, encoder, bonding)
- `ratonet/common/` (logger e protocolo)
- `ratonet/config.py`
- `requirements.txt`
- `.env.example`

## Instalação no hardware

```bash
cd hardware-streamer
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Configuração guiada (recomendado)

```bash
python -m ratonet.field.setup
```

## Execução

Modo telemetria:

```bash
python -m ratonet.field.main --id SEU_UUID --key SUA_API_KEY
```

Modo telemetria + vídeo:

```bash
python -m ratonet.field.main --id SEU_UUID --key SUA_API_KEY --video
```

## Dependências de sistema (fora do pip)

- `ping` (normalmente já disponível)
- `ffmpeg` (se usar `--video`)
- `gpsd` (se usar GPS USB)
- `srtla_send` (opcional, se usar SRTLA)
