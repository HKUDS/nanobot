# nanobot - Comandos Principais

## Gateway (Servidor Principal)

```bash
# Iniciar o gateway (modo foreground)
nanobot gateway

# Iniciar em background
nohup nanobot gateway > /tmp/nanobot-gateway.log 2>&1 &

# Ver logs
tail -f /tmp/nanobot-gateway.log

# Parar o gateway
pkill -f "nanobot gateway"
```

## Interação Direta com o Agente

```bash
# Mensagem única
nanobot agent -m "Sua mensagem aqui"

# Especificar sessão
nanobot agent -s minha-sessao -m "Mensagem"

# Modo interativo (REPL)
nanobot agent
```

## Context Compaction

```bash
# Listar sessões disponíveis
nanobot compact --list

# Compactar uma sessão específica
nanobot compact -s whatsapp:5512992247834

# Compactar TODAS as sessões
nanobot compact --all

# Compactar com resumo visível
nanobot compact -s cli:default --summary
```

## Status e Configuração

```bash
# Ver status geral
nanobot status

# Inicializar configuração (primeira vez)
nanobot onboard
```

## Canais

```bash
# Ver status dos canais
nanobot channels status

# Listar canais configurados
nanobot channels list
```

## Cron Jobs

```bash
# Listar jobs agendados
nanobot cron list

# Adicionar job
nanobot cron add --name "daily-check" --schedule "0 9 * * *" --message "Bom dia!"

# Remover job
nanobot cron remove --id <job-id>
```

## WhatsApp Bridge

```bash
# Iniciar bridge (necessário para WhatsApp)
cd bridge && npm start

# Ou via tmux (recomendado)
tmux new-session -d -s nanobot-bridge "cd bridge && npm start"

# Verificar se bridge está rodando
tmux ls | grep nanobot-bridge
```

## Logs e Debug

```bash
# Ver logs do gateway em tempo real
tail -f /tmp/nanobot-gateway.log

# Filtrar apenas erros
grep -i error /tmp/nanobot-gateway.log

# Ver últimas 50 linhas
tail -50 /tmp/nanobot-gateway.log
```

## Processos

```bash
# Ver processos do nanobot
ps aux | grep nanobot

# Ver processos da bridge
ps aux | grep "node.*bridge"

# Matar tudo
pkill -f nanobot
pkill -f "node.*bridge"
```
