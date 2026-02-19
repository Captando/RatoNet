# RatoNet Open Source

Interface web de acompanhamento de transmissões IRL (In Real Life), com foco em visualização de equipe ao vivo, mapa interativo e base para integração com infraestrutura de live resiliente.

## Sobre o projeto

A proposta da RatoNet é servir como camada de visualização e operação para lives em campo, incluindo cenários de estrada, viagens e regiões com conectividade instável.

No contexto de transmissões IRL, o objetivo é reduzir quedas e travamentos usando arquitetura de rede com múltiplos links (bonding), normalmente combinando diferentes operadoras 4G/5G e outras opções de backhaul quando disponível.

Este repositório contém, no momento, uma **versão demo** da interface, com dados mockados para layout, fluxo de navegação e validação visual.

## Status atual

- `Modo`: Demo / Mock data
- `Funcionalidade`: Interface visual pronta para evolução
- `Integrações reais`: Ainda não conectadas neste repositório

## O que já existe

- Mapa full-screen com Leaflet
- Rotas simuladas de expedição (SP -> PB -> PA -> AM)
- Marcadores customizados com avatar e status
- Sidebar com lista de streamers e metadados de live
- Sistema de toasts para itens ainda não implementados
- Layout responsivo com Tailwind via CDN

## Stack atual

- HTML5
- CSS (custom + utilitários Tailwind CSS via CDN)
- JavaScript vanilla
- Leaflet.js (mapa)
- Font Awesome (ícones)
- Google Fonts

## Estrutura do projeto

```txt
.
├── index.html
├── LICENSE
└── README.md
```

## Como executar localmente

Como é um projeto estático, existem duas formas simples:

1. Abrir `index.html` diretamente no navegador.
2. Servir com um servidor local (recomendado para desenvolvimento):

```bash
# opção com Python
python3 -m http.server 8080

# depois acesse
http://localhost:8080
```

## Componentes visuais e de interação

- **Mapa principal**: camada escura CartoDB em tela cheia.
- **Navegação superior**: abas `Mapa`, `eyeRat` e `Split` (as duas últimas em demo).
- **Card de expedição**: resumo de distância, dia e audiência.
- **Sidebar de operação**: streamers ativos, status "Live" e atalhos sociais.
- **Controles de zoom**: botões customizados no canto inferior.
- **Toasts de demo**: feedback visual para recursos em construção.

## Roadmap sugerido

- Integração com API real de streamers, posições e estado de conexão
- Atualização de localização em tempo real (WebSocket/SSE)
- Camadas de observabilidade da live (latência, bitrate, perda, uptime)
- Integração de múltiplos players/feeds (switch operacional)
- Gestão de fila, permissões e roles de operação
- Histórico de rota e playback de deslocamento
- Organização em frontend modular (ex.: React/Vue + build tool)

## Boas práticas para evolução

- Separar dados mockados em arquivo próprio
- Criar camada de serviços para API (fetch centralizado)
- Introduzir controle de ambiente (`dev`, `staging`, `prod`)
- Adicionar lint/format e testes básicos de interface
- Definir contrato de dados (tipagem/interface) antes da API final

## Contribuição

Contribuições são bem-vindas via issue e pull request.

Fluxo recomendado:

1. Faça um fork do projeto.
2. Crie uma branch de feature/correção.
3. Commit com mensagem clara.
4. Abra um PR descrevendo contexto, mudança e validação.

## Aviso importante

Este repositório pode conter dados, rotas e estados simulados para fins de interface. Não trate os dados atuais como telemetria real de operação.

## Licença

Este projeto está sob a licença MIT. Consulte o arquivo `LICENSE`.

