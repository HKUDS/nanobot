# Roadmap do nanobot

## ✅ Concluído

### Token Usage Tracking & Budget Monitoring
- ✅ Rastreamento completo de uso de tokens e monitoramento de custos
- ✅ Comando CLI `nanobot usage` com estatísticas diárias/mensais
- ✅ Monitoramento de orçamento mensal configurável com alertas
- ✅ Armazenamento de dados de uso em `~/.nanobot/usage/YYYY-MM-DD.json`
- ✅ Suporte a múltiplos provedores LLM (Anthropic, OpenAI, Gemini, Zhipu)
- ✅ Quebra de uso por modelo e canal de comunicação
- ✅ Ferramenta de auto-consciência `usage` para o agente
- ✅ Preços atualizados para APIs LLM (até final de 2024)
- ✅ Configuração de orçamento em `~/.nanobot/config.json`

### Ollama Local Model Support
- ✅ Provedor Ollama completo para modelos locais
- ✅ Comando CLI `nanobot ollama` para gerenciamento de modelos
- ✅ Integração com sistema de uso (custos zero para modelos locais)
- ✅ Configuração via `~/.nanobot/config.json`
- ✅ Suporte a modelos populares (Llama, Mistral, CodeLlama, etc.)
- ✅ Verificação automática de status e disponibilidade

### NVIDIA Provider Integration
- ✅ Provedor NVIDIA integrado ao sistema de provedores do agente
- ✅ Suporte ao modelo moonshotai/kimi-k2.5 via API NVIDIA
- ✅ Comunicação assíncrona com API OpenAI-compatible
- ✅ Configuração segura via config.json com apiKey
- ✅ Tratamento de erros e timeouts adequados

## 🚧 Em Desenvolvimento

### Melhorias Planejadas
- [ ] **Multi-modal** — Suporte a imagens, voz e vídeo
- [ ] **Memória de longo prazo** — Contexto persistente aprimorado
- [ ] **Raciocínio avançado** — Planejamento e reflexão multi-etapas
- [ ] **Mais integrações** — Discord, Slack, email, calendário
- [ ] **Auto-aperfeiçoamento** — Aprendizado com feedback

## 📋 Backlog

### Funcionalidades Futuras
- [ ] Sistema de plugins extensível
- [ ] Cache inteligente de respostas
- [ ] Análise de desempenho automatizada
- [ ] Suporte a múltiplos idiomas
- [ ] Integração com ferramentas de desenvolvimento
