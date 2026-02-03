# Changelog do nanobot

## [Unreleased]

### Adicionado
- **Token Usage Tracking & Budget Monitoring**: Sistema abrangente para rastreamento de uso de tokens e monitoramento de custos
  - Comando CLI `nanobot usage` com estatísticas diárias/mensais
  - Monitoramento de orçamento mensal configurável com alertas
  - Armazenamento de dados de uso em `~/.nanobot/usage/YYYY-MM-DD.json`
  - Suporte a múltiplos provedores LLM (Anthropic, OpenAI, Gemini, Zhipu)
  - Quebra de uso por modelo e canal de comunicação
  - Ferramenta de auto-consciência `usage` para o agente
  - Preços atualizados para APIs LLM (até final de 2024)
  - Configuração de orçamento em `~/.nanobot/config.json`

### Mudanças
- Integração de rastreamento de uso automático em todas as chamadas LLM
- Adição de módulo `nanobot.usage` com classes de dados e ferramentas
- Extensão do esquema de configuração com seção `usage`
- Registro automático de custos por provedor e modelo

### Documentação
- Atualização do README.md com nova funcionalidade
- Criação do ROADMAP.md com funcionalidades concluídas e planejadas
- Documentação da ferramenta `usage` em workspace/TOOLS.md
- Atualização de workspace/AGENTS.md com capacidades de auto-consciência

## [2025-02-01] - Lançamento Inicial

### Adicionado
- Arquitetura ultra-leve com ~4.000 linhas de código
- Suporte a múltiplos provedores LLM (OpenRouter, Anthropic, OpenAI, Gemini)
- Canais de comunicação: CLI, Telegram, WhatsApp
- Sistema de ferramentas extensível
- Gerenciamento de tarefas cron
- Sistema de heartbeat para tarefas periódicas
- Interface web gateway
- Configuração baseada em Pydantic
