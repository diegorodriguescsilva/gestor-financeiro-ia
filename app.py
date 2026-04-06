import os
import sys
import json
import csv
import io
import hashlib
from datetime import datetime

# Bibliotecas externas (Certifique-se de instalar: pip install flask flask-sqlalchemy google-generativeai python-dotenv)
import google.generativeai as genai
from flask import Flask, request, jsonify, render_template, Response
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

# --- CARREGAMENTO DE CONFIGURAÇÕES ---
# O método load_dotenv() lê o arquivo .env e disponibiliza as variáveis no sistema
load_dotenv()

VERSION = "1.0.0"

app = Flask(__name__)

# --- SUPORTE PARA PYINSTALLER (DIRETÓRIOS E RECURSOS) ---
def resource_path(relative_path):
    """ 
    Obtém o caminho absoluto para recursos. 
    Necessário para que o .exe encontre as pastas 'templates' e 'static'.
    """
    try:
        # O PyInstaller cria uma pasta temporária e armazena o caminho em _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# Configura o Flask para usar os caminhos compatíveis com o executável
app.template_folder = resource_path('templates')
app.static_folder = resource_path('static')

# --- CONFIGURAÇÃO DO BANCO DE DADOS ---
# Quando o app roda como .exe (frozen), salvamos o banco na pasta de documentos do usuário
# Isso evita que os dados sejam apagados em uma atualização do programa.
if getattr(sys, 'frozen', False):
    db_dir = os.path.join(os.path.expanduser("~"), "GestorFinanceiroIA")
    os.makedirs(db_dir, exist_ok=True)
    db_path = os.path.join(db_dir, 'comprovantes_final.db')
else:
    # Em modo de desenvolvimento, o banco fica na pasta do projeto
    db_path = 'comprovantes_final.db'

app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- CONFIGURAÇÃO DO GOOGLE GEMINI (SEGURA) ---
# A chave de API é lida do ambiente, protegendo contra vazamentos no GitHub
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("ERRO: Variável GEMINI_API_KEY não encontrada no arquivo .env!")
else:
    genai.configure(api_key=GEMINI_API_KEY)

# Usando o modelo Flash 1.5, ideal para extração rápida de dados
model = genai.GenerativeModel('models/gemini-1.5-flash-latest')

# --- MODELO DA TABELA COM TRAVA DE DUPLICADOS ---
class Comprovante(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
    
    # arquivo_hash: A 'impressão digital' única de cada arquivo enviado
    arquivo_hash = db.Column(db.String(64), unique=True, nullable=False)
    
    tipo = db.Column(db.String(50))
    valor = db.Column(db.String(50))
    data_pagamento = db.Column(db.String(50))
    destinatario_nome = db.Column(db.String(200))
    destinatario_banco = db.Column(db.String(100))
    remetente_nome = db.Column(db.String(200))

    def to_dict(self):
        return {c.name: getattr(self, c.name) or "" for c in self.__table__.columns}

def gerar_hash(conteudo_binario):
    """Cria um código SHA-256 único baseado no conteúdo do arquivo."""
    return hashlib.sha256(conteudo_binario).hexdigest()

# --- ROTAS ---

@app.route('/')
def index():
    # Passamos a versão para que ela apareça no rodapé do site
    return render_template('index.html', version=VERSION)

@app.route('/api/analisar', methods=['POST'])
def analisar():
    if not GEMINI_API_KEY:
        return jsonify({'erro': 'Configuração de API pendente no servidor.'}), 500

    if 'imagens' not in request.files:
        return jsonify({'erro': 'Nenhum ficheiro enviado'}), 400

    arquivos = request.files.getlist('imagens')
    resultados_finais = []

    for file in arquivos:
        try:
            mime_type = file.content_type
            nome_arquivo = file.filename
            conteudo = file.read()
            
            # 1. Gera o Hash (ID Único) do arquivo
            hash_atual = gerar_hash(conteudo)
            
            # 2. Verifica se o arquivo já foi processado anteriormente
            existente = Comprovante.query.filter_by(arquivo_hash=hash_atual).first()
            if existente:
                resultados_finais.append(existente.to_dict())
                continue

            # 3. Solicitação estruturada para a IA
            prompt = """Analise este documento financeiro e extraia os dados para este formato JSON:
            {
              "tipo": "NOTA FISCAL, PIX ou BOLETO",
              "valor": "R$ 0,00",
              "data_pagamento": "DD/MM/AAAA",
              "destinatario_nome": "Nome do receptor ou Razão Social",
              "destinatario_banco": "Banco ou CNPJ",
              "remetente_nome": "Nome de quem pagou ou Cliente"
            }
            Responda apenas o JSON puro, sem blocos de texto ou markdown."""

            response = model.generate_content([
                prompt,
                {'mime_type': mime_type, 'data': conteudo}
            ])
            
            texto_ia = response.text.strip()
            
            # Limpeza manual de tags markdown caso a IA as inclua por engano
            if "```json" in texto_ia:
                texto_ia = texto_ia.split("```json")[1].split("```")[0].strip()
            elif "```" in texto_ia:
                texto_ia = texto_ia.split("```")[1].split("```")[0].strip()

            dados = json.loads(texto_ia)

            # 4. Salva o novo registro no Banco de Dados
            novo_registro = Comprovante(
                arquivo_hash=hash_atual,
                tipo=dados.get('tipo'),
                valor=dados.get('valor'),
                data_pagamento=dados.get('data_pagamento'),
                destinatario_nome=dados.get('destinatario_nome'),
                destinatario_banco=dados.get('destinatario_banco'),
                remetente_nome=dados.get('remetente_nome')
            )
            
            db.session.add(novo_registro)
            db.session.commit()
            resultados_finais.append(novo_registro.to_dict())

        except Exception as e:
            print(f"Erro ao processar {file.filename}: {str(e)}")
            db.session.rollback()
            continue

    return jsonify(resultados_finais)

@app.route('/api/comprovantes', methods=['GET'])
def listar():
    itens = Comprovante.query.order_by(Comprovante.criado_em.desc()).all()
    return jsonify([i.to_dict() for i in itens])

@app.route('/api/exportar')
def exportar():
    """Gera um ficheiro CSV com todos os dados extraídos."""
    try:
        dados = Comprovante.query.all()
        si = io.StringIO()
        cw = csv.writer(si)
        cw.writerow(['ID', 'Tipo', 'Valor', 'Data', 'Destinatário', 'Banco/CNPJ', 'Remetente', 'Hash_Arquivo'])
        
        for c in dados:
            cw.writerow([c.id, c.tipo, c.valor, c.data_pagamento, c.destinatario_nome, c.destinatario_banco, c.remetente_nome, c.arquivo_hash])
        
        return Response(
            si.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": "attachment; filename=relatorio_financeiro.csv"}
        )
    except Exception as e:
        return jsonify({'erro': f'Erro ao exportar dados: {str(e)}'}), 500

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    
    # Rodando na porta 5001 para evitar conflitos com AirPlay ou outros serviços
    app.run(debug=True, host='0.0.0.0', port=5001)