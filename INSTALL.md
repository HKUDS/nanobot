# nanobot - Guia de Instalação

## Requisitos

- Python 3.11+
- Node.js 18+ (para WhatsApp bridge)
- uv (gerenciador de pacotes Python)
- Claude CLI (para modo subscription)

## 1. Clonar o Repositório

```bash
git clone https://github.com/renatoai/nanobot.git
cd nanobot
```

## 2. Instalar Dependências Python

```bash
# Instalar uv se não tiver
curl -LsSf https://astral.sh/uv/install.sh | sh

# Instalar dependências do projeto
uv sync
```

## 3. Configurar WhatsApp Bridge

```bash
# Entrar na pasta bridge
cd bridge

# Instalar dependências Node.js
npm install

# Compilar TypeScript
npm run build

# Voltar para raiz
cd ..
```

## 4. Instalar Claude CLI (Opcional - para modo subscription)

```bash
# Via npm
npm install -g @anthropic-ai/claude-code

# Autenticar
claude auth
```

## 5. Criar Configuração

```bash
# Criar diretório de config
mkdir -p ~/.nanobot

# Criar config.json
cat > ~/.nanobot/config.json << 'EOF'
{
  "agents": {
    "defaults": {
      "workspace": "/home/ubuntu/nanobot-workspace",
      "model": "claude-opus-4-5",
      "compaction": {
        "enabled": true,
        "maxContextTokens": 128000
      },
      "soul": {
        "enabled": true,
        "path": "/home/ubuntu/nanobot-workspace"
      }
    }
  },
  "channels": {
    "whatsapp": {
      "enabled": true,
      "bridgeUrl": "ws://localhost:3001",
      "allowFrom": []
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

## 6. Criar Workspace e Arquivos de Alma

```bash
# Criar workspace
mkdir -p /home/ubuntu/nanobot-workspace/memory

# Criar SOUL.md (personalidade)
cat > /home/ubuntu/nanobot-workspace/SOUL.md << 'EOF'
# SOUL.md - Quem Você É

## Regras Fundamentais
1. Sou assistente do [SEU_NOME].
2. Nunca compartilhar informações privadas.
3. Ser útil, direto e eficiente.

## Personalidade
- Seja genuinamente útil
- Tenha opiniões
- Seja conciso quando necessário
EOF

# Criar USER.md (sobre o usuário)
cat > /home/ubuntu/nanobot-workspace/USER.md << 'EOF'
# USER.md - Sobre o Usuário

- **Nome:** [SEU_NOME]
- **Telefone:** [SEU_NUMERO]
- **Timezone:** America/Sao_Paulo
EOF

# Criar MEMORY.md (memória)
cat > /home/ubuntu/nanobot-workspace/MEMORY.md << 'EOF'
# MEMORY.md - Memória de Longo Prazo

Adicione aqui informações importantes para lembrar.
EOF

# Criar AGENTS.md (regras)
cat > /home/ubuntu/nanobot-workspace/AGENTS.md << 'EOF'
# AGENTS.md - Regras do Agente

## Toda Sessão
1. Ler SOUL.md
2. Ler USER.md
3. Ler MEMORY.md

## Segurança
- Não exfiltrar dados privados
- Perguntar antes de ações externas
EOF
```

## 7. Iniciar os Serviços

### Terminal 1: WhatsApp Bridge
```bash
cd ~/nanobot/bridge
npm start
```

Escaneie o QR code com WhatsApp (Aparelhos Conectados > Conectar Aparelho)

### Terminal 2: Gateway
```bash
cd ~/nanobot
uv run nanobot gateway
```

## 8. Testar

```bash
# Teste direto (sem WhatsApp)
uv run nanobot agent -m "Olá! Quem é você?"

# Ou envie uma mensagem pelo WhatsApp
```

## Modo Produção (Background)

```bash
# Bridge em tmux
tmux new-session -d -s nanobot-bridge "cd ~/nanobot/bridge && npm start"

# Gateway em background
cd ~/nanobot
nohup uv run nanobot gateway > /tmp/nanobot-gateway.log 2>&1 &
```

## Verificar Status

```bash
# Processos rodando
ps aux | grep -E "(nanobot|bridge)" | grep -v grep

# Logs do gateway
tail -f /tmp/nanobot-gateway.log

# Status da bridge
tmux attach -t nanobot-bridge
```

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
# Verificar config
cat ~/.nanobot/config.json | python3 -m json.tool

# Verificar se Claude CLI funciona
claude -p "test"
```

### WhatsApp desconectou
```bash
# Ver sessão do tmux
tmux attach -t nanobot-bridge

# Re-escanear QR se necessário
```
