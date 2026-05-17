import os
import sys
import json
import csv
import io
import hashlib
import time
import re
from datetime import datetime

# Bibliotecas externas (Configuradas no novo venv)
from google import genai
from google.genai import types
from flask import Flask, request, jsonify, render_template, Response
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

# --- CARREGAMENTO DE CONFIGURAÇÕES ---
load_dotenv()

VERSION = "1.2.1" # Versão: SDK Oficial Estável com Otimização de Lote

app = Flask(__name__)

# --- SUPORTE PARA PYINSTALLER E DIRETÓRIOS ---
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

app.template_folder = resource_path('templates')
app.static_folder = resource_path('static')

# --- CONFIGURAÇÃO DO BANCO DE DADOS ---
if getattr(sys, 'frozen', False):
    db_dir = os.path.join(os.path.expanduser("~"), "GestorFinanceiroIA")
    os.makedirs(db_dir, exist_ok=True)
    db_path = os.path.join(db_dir, 'comprovantes_final.db')
else:
    db_path = os.path.abspath('comprovantes_final.db')

print(f"SISTEMA: Banco de dados localizado em: {db_path}")

app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- CONFIGURAÇÃO DO GOOGLE GEMINI (SDK MODERNO) ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = None

if GEMINI_API_KEY:
    try:
        # Inicialização do cliente utilizando a API oficial v1 da Google
        client = genai.Client(api_key=GEMINI_API_KEY)
        print("SISTEMA: Conexão com Google GenAI (Novo SDK) configurada com sucesso!")
    except Exception as e:
        print(f"ERRO ao configurar Gemini: {e}")
else:
    print("ERRO CRÍTICO: GEMINI_API_KEY não configurada no arquivo .env")

# --- MODELO DA TABELA ---
class Comprovante(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
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
    return hashlib.sha256(conteudo_binario).hexdigest()

# --- ROTAS ---

@app.route('/')
def index():
    return render_template('index.html', version=VERSION)

@app.route('/api/analisar', methods=['POST'])
def analisar():
    if not GEMINI_API_KEY or client is None:
        return jsonify({'erro': 'IA não configurada. Verifique se a sua chave API é válida.'}), 500

    if 'imagens' not in request.files:
        return jsonify({'erro': 'Nenhum ficheiro enviado'}), 400

    arquivos = request.files.getlist('imagens')
    total_arquivos = len(arquivos)
    print(f"\n=== INICIANDO LOTE DE {total_arquivos} FICHEIROS ===")
    
    resultados_finais = []
    
    for idx, file in enumerate(arquivos):
        nome_arquivo = file.filename
        if not nome_arquivo: continue

        try:
            file.seek(0)
            conteudo = file.read()
            mime_type = file.content_type
            
            if not conteudo: continue

            hash_atual = gerar_hash(conteudo)
            
            # Verificação de duplicados
            existente = Comprovante.query.filter_by(arquivo_hash=hash_atual).first()
            if existente:
                print(f"[{idx+1}/{total_arquivos}] JÁ EXISTE NO BANCO: '{nome_arquivo}'")
                resultados_finais.append(existente.to_dict())
                continue

            print(f"[{idx+1}/{total_arquivos}] IA ANALISANDO: '{nome_arquivo}'...")

            prompt = """Extraia os dados deste comprovante financeiro. 
            Retorne APENAS um objeto JSON válido no formato: 
            {"tipo": "tipo do documento", "valor": "valor com R$", "data_pagamento": "data", "destinatario_nome": "nome", "destinatario_banco": "banco", "remetente_nome": "remetente"}"""

            # Lógica resiliente para evitar limitações de limite por minuto (Erro 429)
            max_retries = 3
            raw_text = ""
            for attempt in range(max_retries):
                try:
                    # Chamada com a API oficial moderna e o novo modelo Gemini 2.5 Flash
                    response = client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=[
                            types.Part.from_bytes(data=conteudo, mime_type=mime_type),
                            prompt
                        ]
                    )
                    raw_text = response.text.strip()
                    break 
                except Exception as e:
                    if ("429" in str(e) or "quota" in str(e).lower()) and attempt < max_retries - 1:
                        wait_time = 20 + (attempt * 10)
                        print(f"   > Limite de chamadas atingido. Aguardando {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        raise e 

            # Limpeza rápida de possíveis blocos de Markdown que a IA envie
            if "```json" in raw_text:
                raw_text = raw_text.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_text:
                raw_text = raw_text.split("```")[1].split("```")[0].strip()

            match = re.search(r'\{.*\}', raw_text, re.DOTALL)
            if not match: raise Exception("Não foi possível processar a resposta JSON da IA")
            
            dados = json.loads(match.group(0))

            novo = Comprovante(
                arquivo_hash=hash_atual,
                tipo=str(dados.get('tipo', 'Desconhecido')),
                valor=str(dados.get('valor', 'R$ 0,00')),
                data_pagamento=str(dados.get('data_pagamento', '')),
                destinatario_nome=str(dados.get('destinatario_nome', '')),
                destinatario_banco=str(dados.get('destinatario_banco', '')),
                remetente_nome=str(dados.get('remetente_nome', ''))
            )
            
            db.session.add(novo)
            db.session.commit()
            resultados_finais.append(novo.to_dict())
            print(f"[{idx+1}/{total_arquivos}] SUCESSO: '{nome_arquivo}'")

            # Pequena pausa regulatória entre arquivos
            time.sleep(1.5)

        except Exception as e:
            print(f"[{idx+1}/{total_arquivos}] ERRO ao analisar '{nome_arquivo}': {str(e)}")
            db.session.rollback()
            continue

    print(f"=== FIM DO PROCESSAMENTO: {len(resultados_finais)} FICHEIROS ===\n")
    return jsonify(resultados_finais)

@app.route('/api/comprovantes', methods=['GET'])
def listar():
    itens = Comprovante.query.order_by(Comprovante.criado_em.desc()).all()
    return jsonify([i.to_dict() for i in itens])

@app.route('/api/exportar', methods=['GET'])
def exportar():
    try:
        dados = Comprovante.query.order_by(Comprovante.criado_em.desc()).all()
        si = io.StringIO()
        cw = csv.writer(si)
        cw.writerow(['ID', 'Data Criação', 'Tipo', 'Valor', 'Data Pagamento', 'Destinatário', 'Banco/CNPJ', 'Remetente'])
        for c in dados:
            cw.writerow([c.id, c.criado_em.strftime('%d/%m/%Y %H:%M'), c.tipo, c.valor, c.data_pagamento, c.destinatario_nome, c.destinatario_banco, c.remetente_nome])
        output = si.getvalue()
        return Response(output, mimetype="text/csv", headers={"Content-disposition": "attachment; filename=relatorio.csv"})
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/api/limpar', methods=['POST'])
def limpar_banco():
    try:
        db.session.query(Comprovante).delete()
        db.session.commit()
        return jsonify({'mensagem': 'Banco limpo.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'erro': str(e)}), 500

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=5001)