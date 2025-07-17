import fitz
import re
import os
import spacy
import io
import requests
import tarfile
from flask import Flask, request, send_file, Response

# --- CONFIGURAÇÃO DO MODELO E CACHE ---
# Usaremos o modelo PEQUENO, muito mais adequado para a Vercel
MODEL_NAME = "pt_core_news_sm"
# URL direta para o download do modelo (versão compatível com spacy 3.7.x)
MODEL_URL = f"https://github.com/explosion/spacy-models/releases/download/{MODEL_NAME}-3.7.0/{MODEL_NAME}-3.7.0.tar.gz"
# Diretório temporário da Vercel onde o modelo será salvo
MODEL_PATH = f"/tmp/{MODEL_NAME}"

nlp = None # Variável global para carregar o modelo apenas uma vez

def load_spacy_model():
    """
    Verifica se o modelo está em cache. Se não, baixa e extrai para /tmp.
    Retorna a instância do modelo carregada.
    """
    global nlp
    if nlp is not None:
        return nlp

    if os.path.exists(MODEL_PATH):
        print(f"Carregando modelo do cache: {MODEL_PATH}")
        nlp = spacy.load(MODEL_PATH)
        return nlp
    
    print(f"Modelo não encontrado em cache. Baixando de {MODEL_URL}...")
    
    try:
        # Baixa o arquivo .tar.gz
        response = requests.get(MODEL_URL, stream=True)
        response.raise_for_status() # Lança erro se o download falhar

        # Salva o arquivo baixado no diretório /tmp
        tmp_tar_path = "/tmp/model.tar.gz"
        with open(tmp_tar_path, "wb") as f:
            f.write(response.content)
        
        print("Download completo. Extraindo...")

        # Extrai o conteúdo para a pasta final
        with tarfile.open(tmp_tar_path, "r:gz") as tar:
            # O conteúdo está numa subpasta, precisamos extrair para o caminho correto
            # Ex: pt_core_news_sm-3.7.0/pt_core_news_sm/pt_core_news_sm-3.7.0
            # Vamos encontrar o caminho certo dentro do tar
            main_folder_in_tar = ""
            for member in tar.getmembers():
                if "meta.json" in member.name:
                    main_folder_in_tar = os.path.dirname(member.name)
                    break
            
            if main_folder_in_tar:
                tar.extractall(path="/tmp")
                # Renomeia a pasta extraída para nosso caminho fixo
                os.rename(f"/tmp/{main_folder_in_tar}", MODEL_PATH)
                print(f"Modelo extraído e salvo em {MODEL_PATH}")
            else:
                 raise Exception("Não foi possível encontrar a pasta principal do modelo no arquivo tar.")

        # Remove o arquivo .tar.gz para limpar o espaço
        os.remove(tmp_tar_path)
        
        print(f"Carregando modelo a partir de {MODEL_PATH}")
        nlp = spacy.load(MODEL_PATH)
        return nlp
        
    except Exception as e:
        print(f"Falha ao baixar ou carregar o modelo: {e}")
        return None

# --- Nossas funções de anonimização (exatamente como antes) ---

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

PALAVRAS_CHAVE_ENDERECO = ['rua','av','av.','avenida','praça','travessa','tv','alameda','rodovia','rod','rodov','km','cep','bairro','nº','numero','apto','apartamento','bloco','andar','s/n','sn','sala','conjunto','cj','edificio','edif','ed.']
PALAVRAS_DE_EXCLUSAO = ['centavo','centavos','real','reais','valor','total','pagamento','saldo','taxa','juros','desconto','processo']

def eh_endereco_valido(texto_entidade):
    texto_lower = texto_entidade.lower()
    if any(exclusao in texto_lower for exclusao in PALAVRAS_DE_EXCLUSAO): return False
    if any(palavra in texto_lower for palavra in PALAVRAS_CHAVE_ENDERECO): return True
    if any(char.isdigit() for char in texto_lower): return True
    return False

def encontrar_entidades_nlp(texto, nlp_model):
    if not nlp_model: return []
    doc = nlp_model(texto)
    resultados = []
    for entidade in doc.ents:
        if entidade.label_ == "LOC" and eh_endereco_valido(entidade.text):
            resultados.append(type('obj', (object,), {'start': entidade.start_char, 'end': entidade.end_char, 'entity_type': 'ENDERECO_NLP'}))
    return resultados

def anonimizar_pdf_stream(pdf_stream, nlp_model):
    try:
        doc = fitz.open(stream=pdf_stream, filetype="pdf")
        total_redacoes = 0
        FATOR_AJUSTE_ALTURA = 0.15 
        for page in doc:
            texto_completo = page.get_text("text", sort=True)
            if not texto_completo: continue
            resultados_regex = encontrar_dados_sensiveis_regex(texto_completo)
            resultados_nlp = encontrar_entidades_nlp(texto_completo, nlp_model)
            resultados_analise = resultados_regex + resultados_nlp
            for res in resultados_analise:
                if len(res.end - res.start) < 8: continue
                areas_para_redacao = page.search_for(texto_completo[res.start:res.end], quads=True)
                for quad in areas_para_redacao:
                    rect = quad.rect
                    ajuste = rect.height * FATOR_AJUSTE_ALTURA
                    rect.y0 += ajuste; rect.y1 -= ajuste
                    if rect.is_empty or rect.width == 0: continue
                    page.add_redact_annot(rect, fill=(0, 0, 0))
                    total_redacoes += 1
            page.apply_redactions()
        output_bytes = doc.save(garbage=4, deflate=True)
        doc.close()
        return output_bytes
    except Exception as e:
        print(f"Erro na anonimização: {e}")
        return None

# --- INICIALIZAÇÃO DA APLICAÇÃO E ENDPOINTS ---
app = Flask(__name__)

@app.route('/api/anonymize', methods=['POST'])
def handle_anonymize():
    nlp_model = load_spacy_model() # Garante que o modelo está carregado
    if not nlp_model:
        return Response("Erro crítico: Modelo de NLP não pôde ser carregado.", status=500)
    
    if 'pdf_file' not in request.files:
        return Response("Erro: Nenhum arquivo PDF enviado.", status=400)
    file = request.files['pdf_file']
    if file.filename == '' or not file.mimetype == 'application/pdf':
        return Response("Erro: Arquivo inválido ou não é PDF.", status=400)
    
    pdf_bytes = file.read()
    pdf_anonimizado_bytes = anonimizar_pdf_stream(pdf_bytes, nlp_model)

    if pdf_anonimizado_bytes:
        return send_file(
            io.BytesIO(pdf_anonimizado_bytes),
            mimetype='application/pdf',
            as_attachment=True,
            download_name='documento-anonimizado.pdf'
        )
    return Response("Erro interno ao processar o PDF.", status=500)

@app.route('/api', methods=['GET'])
def home():
    return "API de Anonimização de PDF com NLP está no ar!"