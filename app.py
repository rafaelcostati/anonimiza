# --- 1. IMPORTAÇÕES ---
from flask import Flask, request, send_file, Response
import fitz  # PyMuPDF
import re
import os
import spacy
import io

# --- 2. CONFIGURAÇÃO INICIAL E CARREGAMENTO DO MODELO ---
# Esta parte é executada uma vez quando o servidor da API é iniciado.

# Inicializa a aplicação Flask
app = Flask(__name__)

# Tenta carregar o modelo de NLP. Se não estiver instalado, baixa automaticamente.
# No Render, isso acontece durante a fase de "build" ou na primeira inicialização.
try:
    print("Carregando modelo de NLP 'pt_core_news_lg'...")
    # Usamos o modelo grande e mais preciso, pois o Render suporta.
    nlp = spacy.load("pt_core_news_lg")
    print("Modelo de NLP carregado com sucesso!")
except OSError:
    print("Modelo não encontrado. Tentando baixar 'pt_core_news_lg'...")
    # Este comando executa o download e instalação do modelo.
    from spacy.cli import download
    download("pt_core_news_lg")
    nlp = spacy.load("pt_core_news_lg")
    print("Modelo baixado e carregado com sucesso!")

# Listas de palavras-chave e exclusão para a validação de endereços
PALAVRAS_CHAVE_ENDERECO = [
    'rua', 'av', 'av.', 'avenida', 'praça', 'travessa', 'tv', 'alameda', 
    'rodovia', 'rod', 'rodov', 'km', 'cep', 'bairro', 'nº', 'numero', 
    'apto', 'apartamento', 'bloco', 'andar', 's/n', 'sn', 'sala', 
    'conjunto', 'cj', 'edificio', 'edif', 'ed.'
]
PALAVRAS_DE_EXCLUSAO = [
    'centavo', 'centavos', 'real', 'reais', 'valor', 'total', 'pagamento',
    'saldo', 'taxa', 'juros', 'desconto', 'processo'
]


# --- 3. FUNÇÕES DE LÓGICA DE ANONIMIZAÇÃO ---
# (Exatamente as funções que desenvolvemos e refinamos)

def encontrar_dados_sensiveis_regex(texto):
    """Usa Regex para dados com formato fixo."""
    padroes = {
        'CPF': r'\b\d{3}\.\d{3}\.\d{3}-\d{2}\b',
        'CNPJ': r'\b\d{2}\.\d{3}\.\d{3}\/\d{4}-\d{2}\b',
        'CPF_NUMEROS': r'\b(?<!\d)\d{11}(?!\d)\b',
        'CNPJ_NUMEROS': r'\b(?<!\d)\d{14}(?!\d)\b',
        'EMAIL': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        'TELEFONE': r'\b(?:\(?\d{2}\)?\s?)?(?:9\d{4}|\d{4})[ -]?\d{4}\b',
        'CEP': r'\b\d{5}[-\s]?\d{3}\b',
    }
    resultados = []
    for tipo_entidade, padrao in padroes.items():
        for match in re.finditer(padrao, texto, re.IGNORECASE):
            resultado = type('obj', (object,), {
                'start': match.start(), 'end': match.end(), 'entity_type': tipo_entidade
            })
            resultados.append(resultado)
    return resultados

def eh_endereco_valido(texto_entidade):
    """Verifica se um texto se parece com um endereço real usando heurísticas."""
    texto_lower = texto_entidade.lower()
    if any(exclusao in texto_lower for exclusao in PALAVRAS_DE_EXCLUSAO):
        return False
    if any(palavra in texto_lower for palavra in PALAVRAS_CHAVE_ENDERECO):
        return True
    if any(char.isdigit() for char in texto_lower):
        return True
    return False

def encontrar_entidades_nlp(texto):
    """Usa spaCy para encontrar entidades e depois filtra com base nas heurísticas."""
    doc = nlp(texto)
    resultados = []
    for entidade in doc.ents:
        if entidade.label_ == "LOC" and eh_endereco_valido(entidade.text):
            resultado = type('obj', (object,), {
                'start': entidade.start_char, 'end': entidade.end_char, 'entity_type': 'ENDERECO_NLP'
            })
            resultados.append(resultado)
    return resultados

def anonimizar_pdf_stream(pdf_stream):
    """
    Lê um stream de PDF, anonimiza em memória e retorna os bytes do novo PDF.
    """
    try:
        doc = fitz.open(stream=pdf_stream, filetype="pdf")
        FATOR_AJUSTE_ALTURA = 0.15 

        for page in doc:
            texto_completo = page.get_text("text", sort=True)
            if not texto_completo:
                continue

            resultados_regex = encontrar_dados_sensiveis_regex(texto_completo)
            resultados_nlp = encontrar_entidades_nlp(texto_completo)
            resultados_analise = resultados_regex + resultados_nlp
            
            for res in resultados_analise:
                texto_sensivel = texto_completo[res.start:res.end]
                if len(texto_sensivel.strip()) < 8:
                    continue
                
                areas_para_redacao = page.search_for(texto_sensivel, quads=True)
                for quad in areas_para_redacao:
                    rect = quad.rect
                    ajuste = rect.height * FATOR_AJUSTE_ALTURA
                    rect.y0 += ajuste; rect.y1 -= ajuste
                    if rect.is_empty or rect.width == 0: continue
                    page.add_redact_annot(rect, fill=(0, 0, 0))
            
            page.apply_redactions()

        output_bytes = doc.save(garbage=4, deflate=True)
        doc.close()
        return output_bytes
    except Exception as e:
        print(f"Erro durante a anonimização: {e}")
        return None

# --- 4. ENDPOINTS DA API ---

@app.route('/anonymize', methods=['POST'])
def handle_anonymize():
    """Endpoint que recebe o PDF, anonimiza e retorna."""
    if 'pdf_file' not in request.files:
        return Response("Erro: Nenhum arquivo PDF enviado na chave 'pdf_file'.", status=400)
    
    file = request.files['pdf_file']
    
    if file.filename == '' or not file.mimetype == 'application/pdf':
        return Response("Erro: Arquivo inválido ou não é um PDF.", status=400)
    
    pdf_bytes = file.read()
    pdf_anonimizado_bytes = anonimizar_pdf_stream(pdf_bytes)

    if pdf_anonimizado_bytes:
        return send_file(
            io.BytesIO(pdf_anonimizado_bytes),
            mimetype='application/pdf',
            as_attachment=True,
            download_name='documento-anonimizado.pdf'
        )
    return Response("Erro interno ao processar o PDF.", status=500)


@app.route('/', methods=['GET'])
def home():
    """Rota principal para verificar se a API está online."""
    return "API de Anonimização de PDF com NLP (spaCy) está no ar!"