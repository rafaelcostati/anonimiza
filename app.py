from flask import Flask, request, send_file, Response
import fitz
import re
import os
import spacy
import io

# --- CARREGANDO O MODELO DE NLP ---
# Em um ambiente persistente como o Render, isso é feito uma vez quando a API inicia.
# O modelo é baixado durante a fase de build (instalação)
try:
    print("Carregando modelo de NLP...")
    nlp = spacy.load("pt_core_news_lg") # Podemos voltar para o modelo grande e mais preciso!
    print("Modelo de NLP carregado com sucesso!")
except OSError:
    print("Modelo 'pt_core_news_lg' não encontrado. Baixando...")
    # Este comando baixa e instala o modelo durante o build do Render
    from spacy.cli import download
    download("pt_core_news_lg")
    nlp = spacy.load("pt_core_news_lg")


app = Flask(__name__)

# --- Coloque aqui todas as suas funções de anonimização que já criamos ---
# encontrar_dados_sensiveis_regex()
# PALAVRAS_CHAVE_ENDERECO = [...]
# PALAVRAS_DE_EXCLUSAO = [...]
# eh_endereco_valido()
# encontrar_entidades_nlp()
# ... (copie e cole as funções do nosso último código funcional aqui)

# Exemplo de uma função, copie e cole as outras
def encontrar_dados_sensiveis_regex(texto):
    padroes = {
        'CPF': r'\b\d{3}\.\d{3}\.\d{3}-\d{2}\b', 'CNPJ': r'\b\d{2}\.\d{3}\.\d{3}\/\d{4}-\d{2}\b',
        'CPF_NUMEROS': r'\b(?<!\d)\d{11}(?!\d)\b', 'CNPJ_NUMEROS': r'\b(?<!\d)\d{14}(?!\d)\b',
        'EMAIL': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        'TELEFONE': r'\b(?:\(?\d{2}\)?\s?)?(?:9\d{4}|\d{4})[ -]?\d{4}\b',
        'CEP': r'\b\d{5}[-\s]?\d{3}\b',
    }
    resultados = []
    for tipo, padrao in padroes.items():
        for match in re.finditer(padrao, texto, re.IGNORECASE):
            resultados.append(type('obj', (object,), {'start': match.start(), 'end': match.end(), 'entity_type': tipo}))
    return resultados

# ... (cole as outras funções aqui) ...

def anonimizar_pdf_stream(pdf_stream):
    # Esta função não precisa do argumento nlp_model, pois ele agora é global
    # ... (lógica interna da função permanece a mesma) ...
    pass # Substitua este 'pass' pela sua função completa


# --- ENDPOINT DA API ---
@app.route('/anonymize', methods=['POST'])
def handle_anonymize():
    if 'pdf_file' not in request.files:
        return Response("Erro: Nenhum arquivo PDF enviado.", status=400)
    
    file = request.files['pdf_file']
    
    if file and file.mimetype == 'application/pdf':
        pdf_bytes = file.read()
        # Não precisa mais passar o 'nlp' como argumento
        pdf_anonimizado_bytes = anonimizar_pdf_stream(pdf_bytes)
        
        if pdf_anonimizado_bytes:
            return send_file(
                io.BytesIO(pdf_anonimizado_bytes),
                mimetype='application/pdf',
                as_attachment=True,
                download_name='documento-anonimizado.pdf'
            )
        else:
            return Response("Erro interno ao processar o PDF.", status=500)
            
    return Response("Erro: Formato de arquivo não suportado.", status=400)


@app.route('/', methods=['GET'])
def home():
    return "API de Anonimização de PDF com NLP está no ar!"