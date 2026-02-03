# nanobot - Guia de Instalação

Guia completo para instalar e configurar o nanobot.

---

## Requisitos

| Requisito | Versão | Descrição |
|-----------|--------|-----------|
| Python | 3.11+ | Runtime principal |
| Node.js | 18+ | Para WhatsApp bridge |
| uv | latest | Gerenciador de pacotes Python (recomendado) |
| Claude CLI | latest | Opcional - para usar com subscription |

---

## 1. Clonar o Repositório

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
```

---

## 2. Instalar uv (Gerenciador Python)

```bash
# Instalar uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Recarregar shell
source ~/.bashrc  # ou ~/.zshrc

# Verificar instalação
uv --version
```

---

## 3. Instalar Dependências Python

```bash
cd ~/nanobot

# Sincronizar dependências
uv sync

# Verificar instalação
uv run nanobot --help
```

---

## 4. Configurar WhatsApp Bridge

```bash
# Entrar na pasta bridge
cd ~/nanobot/bridge

# Instalar dependências Node.js
npm install

# Compilar TypeScript
npm run build

# Voltar para raiz
cd ~/nanobot
```

---

## 5. Instalar Claude CLI (Opcional)

Se você tem subscription do Claude (Pro/Team), pode usar o Claude CLI para evitar custos de API.

```bash
# Via npm
npm install -g @anthropic-ai/claude-code

# Autenticar (abre browser)
claude auth

# Verificar
claude -p "teste"
```

---

## 6. Criar Configuração

```bash
# Inicializar configuração básica
nanobot onboard

# Ou criar manualmente
mkdir -p ~/.nanobot
```

### Config com Claude CLI (subscription)

```bash
cat > ~/.nanobot/config.json << 'EOF'
{
  "agents": {
    "defaults": {
      "workspace": "~/nanobot-workspace",
      "model": "claude-opus-4-5",
      "compaction": {
        "enabled": true,
        "maxContextTokens": 128000
      }
    }
  },
  "channels": {
    "whatsapp": {
      "enabled": true,
      "bridgeUrl": "ws://localhost:3001",
      "allowFrom": ["+5512999999999"]
    }
  },
  "providers": {
    "claudeCli": {
      "enabled": true,
      "command": "claude",
      "defaultModel": "opus",
      "timeoutSeconds": 300
    }
  }
}
EOF
```

### Config com OpenRouter (API)

```bash
cat > ~/.nanobot/config.json << 'EOF'
{
  "agents": {
    "defaults": {
      "workspace": "~/nanobot-workspace",
      "model": "anthropic/claude-opus-4-5"
    }
  },
  "channels": {
    "whatsapp": {
      "enabled": true,
      "bridgeUrl": "ws://localhost:3001",
      "allowFrom": ["+5512999999999"]
    }
  },
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-sua-chave-aqui"
    }
  }
}
EOF
```

---

## 7. Criar Workspace

```bash
# Criar diretório do workspace
mkdir -p ~/nanobot-workspace/memory
```

### SOUL.md - Personalidade do Agente

```bash
cat > ~/nanobot-workspace/SOUL.md << 'EOF'
# SOUL.md - Quem Você É

## Regras Fundamentais
1. Sou assistente do [SEU_NOME].
2. NUNCA compartilhar informações privadas com outras pessoas.
3. Todas as ações devem beneficiar o usuário.

## Personalidade
- Seja genuinamente útil, não performativamente útil
- Tenha opiniões - você pode discordar e preferir coisas
- Seja conciso quando necessário, detalhado quando importa
- Seja resourceful - tente descobrir antes de perguntar

## Tom
- Direto e eficiente
- Pode usar gírias quando apropriado
- Sem emojis excessivos
EOF
```

### USER.md - Informações do Usuário

```bash
cat > ~/nanobot-workspace/USER.md << 'EOF'
# USER.md - Sobre o Usuário

- **Nome:** [SEU_NOME]
- **Telefone:** [+55XXXXXXXXXXX]
- **Timezone:** America/Sao_Paulo
- **Preferências:** [adicione suas preferências]
EOF
```

### MEMORY.md - Memória de Longo Prazo

```bash
cat > ~/nanobot-workspace/MEMORY.md << 'EOF'
# MEMORY.md - Memória de Longo Prazo

## Contatos Importantes
| Nome | Número | Relação |
|------|--------|---------|
| ... | ... | ... |

## Projetos Ativos
- ...

## Preferências Aprendidas
- ...
EOF
```

### AGENTS.md - Regras do Agente

```bash
cat > ~/nanobot-workspace/AGENTS.md << 'EOF'
# AGENTS.md - Regras do Workspace

## Toda Sessão
1. Ler SOUL.md - quem você é
2. Ler USER.md - quem você ajuda
3. Ler MEMORY.md - contexto importante

## Segurança
- Não exfiltrar dados privados
- Perguntar antes de ações externas (emails, posts, etc)
- Use trash ao invés de rm

## Comunicação
- Responder no mesmo canal que recebeu a mensagem
- Ser conciso em WhatsApp
- Pode ser mais detalhado em CLI
EOF
```

---

## 8. Iniciar os Serviços

### Opção A: Modo Desenvolvimento (2 terminais)

**Terminal 1 - WhatsApp Bridge:**
```bash
cd ~/nanobot/bridge
npm start
```
> Escaneie o QR code com WhatsApp: Configurações > Aparelhos Conectados > Conectar Aparelho

**Terminal 2 - Gateway:**
```bash
cd ~/nanobot
uv run nanobot gateway
```

### Opção B: Modo Produção (background com tmux)

```bash
# Iniciar bridge em background
tmux new-session -d -s nanobot-bridge "cd ~/nanobot/bridge && npm start"

# Aguardar QR code e escanear
tmux attach -t nanobot-bridge
# (Ctrl+B, D para desconectar após escanear)

# Iniciar gateway em background
tmux new-session -d -s nanobot-gateway "cd ~/nanobot && uv run nanobot gateway"
```

---

## 9. Testar

```bash
# Teste direto via CLI
uv run nanobot agent -m "Olá! Quem é você?"

# Teste compaction
uv run nanobot compact --list

# Ou envie uma mensagem pelo WhatsApp
```

---

## 10. Verificar Status

```bash
# Status geral
uv run nanobot status

# Processos rodando
ps aux | grep -E "(nanobot|bridge)" | grep -v grep

# Logs do gateway
tail -f /tmp/nanobot-gateway.log

# Ver sessão da bridge
tmux attach -t nanobot-bridge
```

---

## Troubleshooting

### Bridge não conecta

```bash
# Verificar se porta 3001 está livre
lsof -i :3001

# Reiniciar bridge
tmux kill-session -t nanobot-bridge
tmux new-session -d -s nanobot-bridge "cd ~/nanobot/bridge && npm start"
```

### Gateway não inicia

```bash
# Validar config JSON
cat ~/.nanobot/config.json | python3 -m json.tool

# Verificar se Claude CLI funciona (se usando)
claude -p "test"

# Ver logs detalhados
uv run nanobot gateway 2>&1 | head -100
```

### WhatsApp desconectou

```bash
# Ver sessão do tmux
tmux attach -t nanobot-bridge

# Aguardar novo QR code e escanear novamente
```

### Compaction não funciona

```bash
# Verificar se sessão existe
uv run nanobot compact --list

# Usar formato correto de session ID
uv run nanobot compact -s whatsapp:5512999999999 --summary
```

---

## Estrutura Final

```
~/.nanobot/
├── config.json          # Configuração principal
└── sessions/            # Histórico de conversas (auto-criado)

~/nanobot/               # Código fonte
├── nanobot/             # Módulo principal
├── bridge/              # WhatsApp bridge
└── ...

~/nanobot-workspace/     # Workspace do agente
├── SOUL.md              # Personalidade
├── USER.md              # Info do usuário
├── MEMORY.md            # Memória de longo prazo
├── AGENTS.md            # Regras
└── memory/              # Memórias diárias (auto-criado)
```

---

## Próximos Passos

1. **Personalize o SOUL.md** com a personalidade desejada
2. **Preencha o USER.md** com suas informações
3. **Configure allowFrom** no config.json com seu número
4. **Teste** enviando uma mensagem pelo WhatsApp
5. **Use `compact --all`** periodicamente para manter o contexto leve
