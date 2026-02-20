"""Wizard interativo de setup do Field Agent.

Guia o streamer pelo processo de configuração:
1. Servidor URL + API key (ou cadastro via email)
2. Auto-detecção de interfaces de rede
3. Teste de conectividade
4. Geração de .env pronto para uso
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

from ratonet.common.logger import get_logger

log = get_logger("setup")

# Diretório onde o .env será salvo
ENV_FILE = Path(".env")


def _input_required(prompt: str) -> str:
    """Pede input obrigatório ao usuário."""
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("  [!] Este campo é obrigatório.")


def _input_optional(prompt: str, default: str = "") -> str:
    """Pede input opcional com valor padrão."""
    value = input(prompt).strip()
    return value if value else default


def _yes_no(prompt: str, default: bool = True) -> bool:
    """Pergunta sim/não."""
    suffix = " [S/n]: " if default else " [s/N]: "
    answer = input(prompt + suffix).strip().lower()
    if not answer:
        return default
    return answer in ("s", "sim", "y", "yes")


def step_server_config() -> Dict[str, str]:
    """Passo 1: Configuração do servidor."""
    print("\n" + "=" * 50)
    print("  PASSO 1: Configuração do Servidor")
    print("=" * 50)
    print()

    server_url = _input_required(
        "  URL do servidor RatoNet\n"
        "  (ex: ws://seu-servidor:8000/ws/field)\n"
        "  > "
    )

    # Normaliza URL
    if not server_url.startswith(("ws://", "wss://")):
        server_url = "ws://" + server_url
    if not server_url.endswith("/ws/field"):
        server_url = server_url.rstrip("/") + "/ws/field"

    print()
    print("  Você já tem um cadastro na RatoNet?")
    has_account = _yes_no("  Já possuo ID e API key", default=True)

    if has_account:
        streamer_id = _input_required("  Seu Streamer ID: ")
        api_key = _input_required("  Sua API Key: ")
    else:
        # Cadastro via API
        print()
        print("  Vamos cadastrar você! Preencha os dados:")
        name = _input_required("  Seu nome: ")
        email = _input_required("  Seu email: ")
        avatar_url = _input_optional("  URL do avatar (opcional): ")
        color = _input_optional("  Cor do marcador (hex, ex: #ff6600): ", "#ff6600")

        streamer_id, api_key = _register_streamer(
            server_url, name, email, avatar_url, color
        )

    return {
        "server_url": server_url,
        "streamer_id": streamer_id,
        "api_key": api_key,
    }


def _register_streamer(
    server_url: str,
    name: str,
    email: str,
    avatar_url: str,
    color: str,
) -> tuple:
    """Registra streamer via API REST."""
    import urllib.request
    import urllib.error

    # Converte ws:// para http:// para a API REST
    api_base = server_url.replace("ws://", "http://").replace("wss://", "https://")
    api_base = api_base.split("/ws/")[0]
    register_url = f"{api_base}/api/register"

    payload = json.dumps({
        "name": name,
        "email": email,
        "avatar_url": avatar_url,
        "color": color,
    }).encode("utf-8")

    req = urllib.request.Request(
        register_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            streamer_id = data["id"]
            api_key = data["api_key"]
            approved = data.get("approved", False)

            print()
            print("  Cadastro realizado com sucesso!")
            print(f"  ID: {streamer_id}")
            print(f"  API Key: {api_key}")
            if not approved:
                print("  [!] Seu cadastro precisa ser aprovado pelo admin.")
                print("      Você já pode configurar o agent, mas só conectará após aprovação.")
            print()
            return streamer_id, api_key
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"\n  [ERRO] Falha no cadastro: {e.code} — {body}")
        sys.exit(1)
    except Exception as e:
        print(f"\n  [ERRO] Não foi possível conectar ao servidor: {e}")
        sys.exit(1)


def step_network_scan() -> List[Dict[str, str]]:
    """Passo 2: Auto-detecção de interfaces de rede."""
    print("\n" + "=" * 50)
    print("  PASSO 2: Detecção de Interfaces de Rede")
    print("=" * 50)
    print()

    try:
        from ratonet.field.network_monitor import detect_interfaces
        interfaces = detect_interfaces()
    except ImportError:
        print("  [!] psutil não instalado — detecção automática indisponível.")
        interfaces = []

    if not interfaces:
        print("  Nenhuma interface de rede detectada automaticamente.")
        print("  Você pode configurar manualmente no .env depois.")
        return []

    print(f"  {len(interfaces)} interface(s) detectada(s):\n")
    for i, iface in enumerate(interfaces):
        print(f"    [{i + 1}] {iface['interface']} ({iface['type']}) — IP: {iface['ip']}")

    print()
    return interfaces


def step_network_test(interfaces: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Passo 3: Teste de conectividade."""
    if not interfaces:
        return []

    print("\n" + "=" * 50)
    print("  PASSO 3: Teste de Conectividade")
    print("=" * 50)
    print()

    test = _yes_no("  Testar conectividade de cada interface?", default=True)
    if not test:
        return interfaces

    import asyncio
    from ratonet.field.network_monitor import ping_interface, calculate_link_score

    async def _test_all():
        results = []
        for iface in interfaces:
            name = iface["interface"]
            itype = iface["type"]
            print(f"  Testando {name} ({itype})...", end=" ", flush=True)

            ping = await ping_interface(name)
            score = calculate_link_score(
                ping["rtt_ms"], ping["jitter_ms"], ping["packet_loss_pct"]
            )

            if ping["packet_loss_pct"] >= 100:
                status = "FALHOU"
                color = ""
            elif score >= 70:
                status = "OK"
                color = ""
            else:
                status = "DEGRADADO"
                color = ""

            print(f"{status} — RTT: {ping['rtt_ms']:.0f}ms, "
                  f"Loss: {ping['packet_loss_pct']:.0f}%, Score: {score}")

            iface["rtt_ms"] = ping["rtt_ms"]
            iface["score"] = score
            iface["connected"] = ping["packet_loss_pct"] < 100
            results.append(iface)
        return results

    results = asyncio.run(_test_all())

    connected = [r for r in results if r.get("connected")]
    print(f"\n  {len(connected)}/{len(results)} interface(s) com conectividade.")

    return results


def step_generate_env(config: Dict[str, str], interfaces: List[Dict[str, str]]) -> None:
    """Passo 4: Gera arquivo .env."""
    print("\n" + "=" * 50)
    print("  PASSO 4: Gerando Configuração")
    print("=" * 50)
    print()

    # Monta lista de interfaces para o .env
    iface_names = ",".join(i["interface"] for i in interfaces if i.get("connected", True))

    env_content = f"""# RatoNet Field Agent — Configuração gerada pelo setup wizard
# Gerado automaticamente. Edite conforme necessário.

# Servidor
FIELD_SERVER_WS_URL={config['server_url']}
FIELD_STREAMER_ID={config['streamer_id']}
FIELD_API_KEY={config['api_key']}

# Interfaces de rede (separadas por vírgula)
FIELD_NETWORK_INTERFACES={iface_names}

# Telemetria
FIELD_TELEMETRY_INTERVAL_S=1.0

# GPS (host:port do gpsd)
FIELD_GPS_DEVICE=localhost:2947

# Starlink (endereço gRPC do dish)
FIELD_STARLINK_ADDR=192.168.100.1:9200

# Video (descomente para habilitar)
# FIELD_VIDEO_DEVICE=/dev/video0
# FIELD_VIDEO_BITRATE=4000k
# FIELD_VIDEO_RESOLUTION=1920x1080
# FIELD_VIDEO_CODEC=h264

# SRT
# SRT_BASE_PORT=9000
# SRT_LATENCY_MS=500
# SRT_PASSPHRASE=
"""

    # Verifica se já existe .env
    if ENV_FILE.exists():
        print(f"  [!] Arquivo {ENV_FILE} já existe.")
        overwrite = _yes_no("  Sobrescrever?", default=False)
        if not overwrite:
            alt_path = Path(".env.ratonet")
            alt_path.write_text(env_content)
            print(f"  Configuração salva em: {alt_path.resolve()}")
            print(f"  Copie para .env quando quiser usar: cp {alt_path} .env")
            return

    ENV_FILE.write_text(env_content)
    print(f"  Configuração salva em: {ENV_FILE.resolve()}")


def step_summary(config: Dict[str, str]) -> None:
    """Resumo final com instruções."""
    print("\n" + "=" * 50)
    print("  SETUP COMPLETO!")
    print("=" * 50)
    print()
    print("  Para iniciar o field agent:")
    print()
    print(f"    python -m ratonet.field.main \\")
    print(f"      --id {config['streamer_id']} \\")
    print(f"      --key {config['api_key']} \\")
    print(f"      --server {config['server_url']}")
    print()
    print("  Ou simplesmente (lê do .env):")
    print()
    print("    python -m ratonet.field.main --id $FIELD_STREAMER_ID --key $FIELD_API_KEY")
    print()
    print("  Dica: para habilitar vídeo, adicione --video")
    print()


def main() -> None:
    """Entry point do wizard de setup."""
    print()
    print("  ╔══════════════════════════════════════╗")
    print("  ║   RatoNet Field Agent — Setup Wizard  ║")
    print("  ╚══════════════════════════════════════╝")
    print()
    print("  Este wizard vai configurar seu field agent")
    print("  para conectar à rede RatoNet.")

    try:
        # Passo 1: Servidor + credenciais
        config = step_server_config()

        # Passo 2: Detecta interfaces
        interfaces = step_network_scan()

        # Passo 3: Testa conectividade
        tested = step_network_test(interfaces)

        # Passo 4: Gera .env
        step_generate_env(config, tested)

        # Resumo
        step_summary(config)

    except KeyboardInterrupt:
        print("\n\n  Setup cancelado pelo usuário.")
        sys.exit(0)


if __name__ == "__main__":
    main()
