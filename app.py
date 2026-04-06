import os
import json
import csv
import io
import hashlib
import google.generativeai as genai
from datetime import datetime
from flask import Flask, request, jsonify, render_template, Response
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

# --- CONFIGURAÇÃO DO BANCO DE DADOS ---
# Alterado para 'final' para forçar a criação da coluna de Hash (Anti-duplicidade)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///comprovantes_final.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- CONFIGURAÇÃO DO GOOGLE GEMINI ---
GEMINI_API_KEY = "AIzaSyBXQ9i5E6cZDGOPnqOsAHyPtHCnUBy9W7w"
genai.configure(api_key=GEMINI_API_KEY)

# Modelo estável para leitura de documentos e imagens
MODEL_NAME = 'models/gemini-flash-latest'
model = genai.GenerativeModel(MODEL_NAME)

# --- MODELO DA TABELA COM TRAVA DE DUPLICADOS ---
class Comprovante(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Esta coluna guarda a 'Impressão Digital' do arquivo. 
    # unique=True impede que o mesmo arquivo entre duas vezes.
    arquivo_hash = db.Column(db.String(64), unique=True, nullable=False)
    
    tipo = db.Column(db.String(50))
    valor = db.Column(db.String(50))
    data_pagamento = db.Column(db.String(50))
    destinatario_nome = db.Column(db.String(200))
    destinatario_banco = db.Column(db.String(100))
    remetente_nome = db.Column(db.String(200))

    def to_dict(self):
        return {c.name: getattr(self, c.name) or "" for c in self.__table__.columns}

# --- FUNÇÃO PARA GERAR A DIGITAL DO ARQUIVO ---
def gerar_hash(conteudo_binario):
    """Cria um código SHA-256 único baseado nos bytes do arquivo."""
    return hashlib.sha256(conteudo_binario).hexdigest()

# --- ROTAS ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/analisar', methods=['POST'])
def analisar():
    """Analisa arquivos e ignora automaticamente os que já foram processados."""
    if 'imagens' not in request.files:
        return jsonify({'erro': 'Nenhum arquivo enviado'}), 400

    arquivos = request.files.getlist('imagens')
    resultados_finais = []

    for file in arquivos:
        try:
            mime_type = file.content_type
            nome_arquivo = file.filename
            conteudo = file.read()
            
            # 1. Gerar a digital (Hash) do arquivo
            hash_atual = gerar_hash(conteudo)
            
            # 2. Verificar se este arquivo já existe no Banco de Dados
            existente = Comprovante.query.filter_by(arquivo_hash=hash_atual).first()
            
            if existente:
                print(f"SISTEMA: O arquivo '{nome_arquivo}' já foi processado. Ignorando...")
                # Retorna os dados que já estão no banco para não deixar a tela vazia
                resultados_finais.append(existente.to_dict())
                continue

            print(f"SISTEMA: Analisando novo arquivo: {nome_arquivo}")
            
            # Prompt para extração de dados de Comprovantes e Notas Fiscais
            prompt = """Analise este documento e extraia os dados para este formato JSON:
            {
              "tipo": "NOTA FISCAL, PIX ou BOLETO",
              "valor": "R$ 0,00",
              "data_pagamento": "DD/MM/AAAA",
              "destinatario_nome": "Nome do receptor ou Razão Social do Emitente",
              "destinatario_banco": "Banco ou CNPJ se for NF",
              "remetente_nome": "Nome de quem pagou ou Cliente"
            }
            Responda apenas o JSON puro."""

            # Chamada ao Gemini
            response = model.generate_content([
                prompt,
                {'mime_type': mime_type, 'data': conteudo}
            ])
            
            texto_ia = response.text.strip()
            
            # Limpeza do JSON
            if "{" in texto_ia:
                json_str = texto_ia[texto_ia.find("{"):texto_ia.rfind("}")+1]
                dados = json.loads(json_str)
            else:
                continue

            # 3. Salvar no banco com o Hash exclusivo
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
            print(f"ERRO ao processar {nome_arquivo}: {str(e)}")
            db.session.rollback()
            continue

    return jsonify(resultados_finais)

@app.route('/api/comprovantes', methods=['GET'])
def listar():
    """Lista o histórico para o frontend."""
    itens = Comprovante.query.order_by(Comprovante.criado_em.desc()).all()
    return jsonify([i.to_dict() for i in itens])

@app.route('/api/exportar')
def exportar():
    """Exporta todos os registros únicos para CSV."""
    try:
        dados = Comprovante.query.all()
        si = io.StringIO()
        cw = csv.writer(si)
        cw.writerow(['ID', 'Tipo', 'Valor', 'Data', 'Entidade', 'Banco/CNPJ', 'Origem', 'Hash_Digital'])
        
        for c in dados:
            cw.writerow([c.id, c.tipo, c.valor, c.data_pagamento, c.destinatario_nome, c.destinatario_banco, c.remetente_nome, c.arquivo_hash])
        
        return Response(
            si.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": "attachment; filename=relatorio_financeiro.csv"}
        )
    except Exception as e:
        return jsonify({'erro': f'Erro ao exportar: {str(e)}'}), 500

if __name__ == '__main__':
    # Cria o banco de dados e as tabelas
    with app.app_context():
        db.create_all()
    
    # Porta 5001 para evitar conflitos
    app.run(debug=True, host='0.0.0.0', port=5001)