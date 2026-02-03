# nanobot - Comandos Principais

Referência rápida de todos os comandos do nanobot.

---

## Primeiros Passos

```bash
# Inicializar configuração (primeira vez)
nanobot onboard

# Ver status geral
nanobot status
```

---

## Gateway (Servidor Principal)

O gateway é o servidor que recebe mensagens do WhatsApp/Telegram e processa com o agente.

```bash
# Iniciar o gateway (modo foreground)
nanobot gateway

# Iniciar em background com nohup
nohup nanobot gateway > /tmp/nanobot-gateway.log 2>&1 &

# Ou via tmux (recomendado)
tmux new-session -d -s nanobot-gateway "cd ~/nanobot && uv run nanobot gateway"

# Parar o gateway
pkill -f "nanobot gateway"
```

---

## Chat Direto com o Agente

```bash
# Mensagem única
nanobot agent -m "Sua mensagem aqui"

# Modo interativo (REPL)
nanobot agent

# Especificar sessão
nanobot agent -s minha-sessao -m "Mensagem"

# Especificar modelo
nanobot agent --model anthropic/claude-sonnet-4 -m "Olá"

# Especificar workspace
nanobot agent -w /caminho/workspace -m "Teste"
```

---

## Context Compaction

Compacta o histórico de conversas para economizar tokens.

```bash
# Listar todas as sessões disponíveis
nanobot compact --list
nanobot compact -l

# Compactar uma sessão específica (formato simples)
nanobot compact -s whatsapp:5512992247834

# Compactar com resumo visível
nanobot compact -s whatsapp:5512992247834 --summary

# Compactar sem mostrar o resumo
nanobot compact -s whatsapp:5512992247834 --no-summary

# Compactar TODAS as sessões de uma vez
nanobot compact --all

# Compactar todas sem mostrar resumos
nanobot compact --all --no-summary
```

### Formatos de Session ID

```bash
# Formato simples (recomendado)
nanobot compact -s whatsapp:5512992247834
nanobot compact -s telegram:123456789
nanobot compact -s cli:direct

# Formato completo também funciona
nanobot compact -s "whatsapp_5512992247834@s.whatsapp.net"
```

---

## Canais de Comunicação

### WhatsApp

```bash
# Fazer login (escanear QR code)
nanobot channels login

# Ver status dos canais
nanobot channels status
```

### WhatsApp Bridge (Node.js)

```bash
# Iniciar bridge (necessário para WhatsApp)
cd ~/nanobot/bridge && npm start

# Via tmux (recomendado - persiste após desconexão)
tmux new-session -d -s nanobot-bridge "cd ~/nanobot/bridge && npm start"

# Verificar se bridge está rodando
tmux ls | grep nanobot-bridge

# Reconectar ao tmux da bridge
tmux attach -t nanobot-bridge
```

---

## Tarefas Agendadas (Cron)

```bash
# Listar jobs agendados
nanobot cron list

# Adicionar job com expressão cron
nanobot cron add --name "bom-dia" --message "Bom dia!" --cron "0 9 * * *"

# Adicionar job por intervalo (segundos)
nanobot cron add --name "check" --message "Verificar status" --every 3600

# Remover job
nanobot cron remove <job_id>
```

---

## Logs e Debug

```bash
# Ver logs do gateway em tempo real
tail -f /tmp/nanobot-gateway.log

# Filtrar apenas erros
grep -i error /tmp/nanobot-gateway.log

# Ver últimas 50 linhas
tail -50 /tmp/nanobot-gateway.log

# Ver logs da bridge
tmux attach -t nanobot-bridge
```

---

## Gerenciamento de Processos

```bash
# Ver processos do nanobot
ps aux | grep nanobot

# Ver processos da bridge
ps aux | grep "node.*bridge"

# Matar gateway
pkill -f "nanobot gateway"

# Matar bridge
pkill -f "node.*bridge"

# Matar tudo
pkill -f nanobot && pkill -f "node.*bridge"
```

### Com systemd (produção)

```bash
# Status do serviço
sudo systemctl status nanobot-gateway

# Reiniciar
sudo systemctl restart nanobot-gateway

# Ver logs
journalctl -u nanobot-gateway -f
```

---

## Arquivos Importantes

| Arquivo | Descrição |
|---------|-----------|
| `~/.nanobot/config.json` | Configuração principal |
| `~/.nanobot/sessions/` | Histórico de conversas |
| `~/nanobot-workspace/` | Workspace do agente |
| `~/nanobot-workspace/SOUL.md` | Personalidade do agente |
| `~/nanobot-workspace/USER.md` | Informações do usuário |
| `~/nanobot-workspace/MEMORY.md` | Memória de longo prazo |
| `~/nanobot-workspace/memory/` | Memórias diárias |

---

## Desenvolvimento

```bash
# Rodar do source com uv
cd ~/nanobot
uv run nanobot agent -m "teste"

# Instalar em modo editável
pip install -e .

# Sincronizar dependências
uv sync
```

---

## Dicas

1. **Sempre rode o gateway** para receber mensagens de WhatsApp/Telegram
2. **Use `compact --all`** periodicamente para manter o contexto leve
3. **Use tmux** para manter processos rodando após desconexão SSH
4. **Verifique `status`** se algo não estiver funcionando
5. **Logs do gateway** mostram mensagens recebidas em tempo real
