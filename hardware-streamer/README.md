# Pasta para hardware do streamer

O código do Field Agent tem uma única fonte em `ratonet/field/`. Este diretório contém a configuração e a lista de dependências para gerar uma distribuição leve.

## O que está incluso

- `ratonet/field/` (agente, setup, telemetria, encoder, bonding)
- `ratonet/common/` (logger e protocolo)
- `ratonet/config.py`
- `requirements.txt`
- `.env.example`

## Gerar o pacote para o hardware

Na raiz do repositório:

```bash
python3 scripts/build_field_bundle.py
```

Copie `dist/ratonet-field.tar.gz` para o equipamento. O pacote contém somente o agente, os módulos compartilhados e sua configuração, sem copiar segredos ou ambientes virtuais.

## Instalação do pacote no hardware

```bash
tar -xzf ratonet-field.tar.gz
cd ratonet-field
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Em um clone completo, instale com `pip install -e .` na raiz e execute o mesmo módulo. Não é necessário gerar o pacote nesse caso.

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
