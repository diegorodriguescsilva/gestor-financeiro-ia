# 📄 Leitor de Comprovantes com IA

Aplicação web que usa a API da Anthropic para ler, categorizar e armazenar comprovantes de pagamento (PIX, Boleto, TED, DOC), com exportação para Excel.

---

## 🚀 Opção 1 — Rodar localmente (sem Docker)

### Pré-requisitos
- Python 3.10+
- Chave de API da Anthropic

### Passos

```bash
# 1. Entre na pasta do projeto
cd comprovante-reader

# 2. Crie o ambiente virtual
python -m venv venv

# No Windows:
venv\Scripts\activate

# No Mac/Linux:
source venv/bin/activate

# 3. Instale as dependências
pip install -r requirements.txt

# 4. Configure a chave de API
# Copie o arquivo de exemplo e preencha sua chave:
cp .env.example .env
# Edite o .env e coloque sua chave ANTHROPIC_API_KEY

# 5. Rode o servidor
python app.py
```

Acesse: **http://localhost:5000**

---

## 🐳 Opção 2 — Docker (local ou nuvem)

### Pré-requisitos
- Docker e Docker Compose instalados

### Passos

```bash
# 1. Configure a chave
cp .env.example .env
# Edite o .env com sua chave ANTHROPIC_API_KEY

# 2. Suba o container
docker-compose up -d

# Para ver os logs:
docker-compose logs -f

# Para parar:
docker-compose down
```

Acesse: **http://localhost:5000**

---

## ☁️ Opção 3 — Deploy na nuvem

### Railway (mais fácil — gratuito no plano starter)

1. Crie conta em https://railway.app
2. Crie um novo projeto → "Deploy from GitHub"
3. Faça upload ou conecte o repositório
4. Em **Variables**, adicione: `ANTHROPIC_API_KEY=sua_chave_aqui`
5. O Railway detecta o Dockerfile automaticamente e faz o deploy

### Render

1. Crie conta em https://render.com
2. Novo serviço → **Web Service** → conecte o repo
3. Runtime: **Docker**
4. Em **Environment Variables**: `ANTHROPIC_API_KEY=sua_chave`
5. Clique em **Create Web Service**

### Fly.io

```bash
# Instale o flyctl: https://fly.io/docs/hands-on/install-flyctl/
fly launch
fly secrets set ANTHROPIC_API_KEY=sua_chave_aqui
fly deploy
```

---

## 📊 Exportação para Excel

Clique no botão **↓ Excel** na barra de histórico.

O arquivo gerado contém:
- **Aba "Comprovantes"**: todos os dados extraídos, com cores por tipo (verde=PIX, amarelo=Boleto, azul=TED, roxo=DOC)
- **Aba "Resumo"**: contagem por tipo de transação

---

## 📁 Estrutura do Projeto

```
comprovante-reader/
├── app.py              # Servidor Flask + API + banco de dados
├── templates/
│   └── index.html      # Interface web completa
├── requirements.txt    # Dependências Python
├── Dockerfile          # Container Docker
├── docker-compose.yml  # Orquestração
├── .env.example        # Modelo de configuração
└── README.md
```

---

## 🔑 Onde obter a chave de API

1. Acesse https://console.anthropic.com
2. Vá em **API Keys** → **Create Key**
3. Copie a chave e cole no arquivo `.env`
