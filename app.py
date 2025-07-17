# app.py

import streamlit as st
import fitz  # PyMuPDF
import re
import os
import spacy
import io

# --- CONFIGURAÇÃO DA PÁGINA E TÍTULO ---
st.set_page_config(page_title="Anonimizador de PDF", layout="wide")
st.title("Ferramenta de Anonimização de PDF 📄➡️⬛")
st.markdown("Faça o upload de um arquivo PDF para anonimizar dados sensíveis como CPF, CNPJ, e-mails, telefones e endereços.")

# --- LÓGICA DE CACHE E CARREGAMENTO DO MODELO NLP ---
@st.cache_resource
def carregar_modelo_nlp():
    """Baixa e carrega o modelo spaCy, mantendo-o em cache."""
    modelo = "pt_core_news_lg"
    try:
        print(f"Tentando carregar o modelo '{modelo}'...")
        nlp = spacy.load(modelo)
        print("Modelo carregado com sucesso!")
    except OSError:
        print(f"Modelo '{modelo}' não encontrado localmente. Tentando baixar...")
        from spacy.cli import download
        download(modelo)
        nlp = spacy.load(modelo)
        print("Modelo baixado e carregado com sucesso!")
    return nlp

nlp = carregar_modelo_nlp()


PALAVRAS_CHAVE_ENDERECO = ['rua','av','av.','avenida','praça','travessa','tv','alameda','rodovia','rod','rodov','km','cep','bairro','nº','numero','apto','apartamento','bloco','andar','s/n','sn','sala','conjunto','cj','edificio','edif','ed.']
PALAVRAS_DE_EXCLUSAO = ['centavo','centavos','real','reais','valor','total','pagamento','saldo','taxa','juros','desconto','processo']

def encontrar_dados_sensiveis_regex(texto):
    padroes = {
        'CPF': r'\b\d{3}\.\d{3}\.\d{3}-\d{2}\b', 'CNPJ': r'\b\d{2}\.\d{3}\.\d{3}\/\d{4}-\d{2}\b',
        'CPF_NUMEROS': r'\b(?<!\d)\d{11}(?!\d)\b', 'CNPJ_NUMEROS': r'\b(?<!\d)\d{14}(?!\d)\b',
        'EMAIL': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        'TELEFONE': r'\b(?:\(?\d{2}\)?\s?)?(?:9\d{4}|\d{4})[ -]?\d{4}\b', 'CEP': r'\b\d{5}[-\s]?\d{3}\b'
    }
    resultados = []
    for tipo, padrao in padroes.items():
        for match in re.finditer(padrao, texto, re.IGNORECASE):
            resultados.append(type('obj', (object,), {'start': match.start(), 'end': match.end(), 'entity_type': tipo}))
    return resultados

def eh_endereco_valido(texto_entidade):
    texto_lower = texto_entidade.lower()
    if any(exclusao in texto_lower for exclusao in PALAVRAS_DE_EXCLUSAO): return False
    if any(palavra in texto_lower for palavra in PALAVRAS_CHAVE_ENDERECO): return True
    if any(char.isdigit() for char in texto_lower): return True
    return False

def encontrar_entidades_nlp(texto):
    doc = nlp(texto)
    resultados = []
    for entidade in doc.ents:
        if entidade.label_ == "LOC" and eh_endereco_valido(entidade.text):
            resultados.append(type('obj', (object,), {'start': entidade.start_char, 'end': entidade.end_char, 'entity_type': 'ENDERECO_NLP'}))
    return resultados

def anonimizar_pdf_bytes(pdf_bytes):
    """Função principal que recebe e retorna os bytes de um PDF."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        FATOR_AJUSTE_ALTURA = 0.15
        total_entidades_encontradas = 0
        for page in doc:
            texto_completo = page.get_text("text", sort=True)
            if not texto_completo: continue
            
            resultados_regex = encontrar_dados_sensiveis_regex(texto_completo)
            resultados_nlp = encontrar_entidades_nlp(texto_completo)
            resultados_analise = resultados_regex + resultados_nlp
            total_entidades_encontradas += len(resultados_analise)

            for res in resultados_analise:
                if (res.end - res.start) < 8: continue
                
                areas_para_redacao = page.search_for(texto_completo[res.start:res.end], quads=True)
                for quad in areas_para_redacao:
                    rect = quad.rect
                    ajuste = rect.height * FATOR_AJUSTE_ALTURA
                    rect.y0 += ajuste; rect.y1 -= ajuste
                    if not rect.is_empty:
                        page.add_redact_annot(rect, fill=(0, 0, 0))
            page.apply_redactions()
        
        if total_entidades_encontradas > 0:
            # --- AQUI ESTÁ A CORREÇÃO ---
            # Trocamos doc.save() por doc.tobytes() para salvar em memória
            return doc.tobytes(garbage=4, deflate=True)
        else:
            return None
    except Exception as e:
        st.error(f"Ocorreu um erro ao processar o PDF: {e}")
        return None

# --- INTERFACE DA APLICAÇÃO STREAMLIT ---
uploaded_file = st.file_uploader("Escolha um arquivo PDF", type="pdf")

if uploaded_file is not None:
    with st.spinner('Anonimizando seu PDF, por favor aguarde...'):
        pdf_bytes = uploaded_file.getvalue()
        resultado_bytes = anonimizar_pdf_bytes(pdf_bytes)

    st.success("Processo de anonimização concluído!")

    if resultado_bytes:
        st.download_button(
            label="Clique para baixar o PDF Anonimizado",
            data=resultado_bytes,
            file_name=f"anonimizado_{uploaded_file.name}",
            mime="application/pdf"
        )
    else:
        st.warning("Nenhum dado sensível foi encontrado no documento para anonimizar.")
        st.download_button(
            label="Baixar o arquivo original (nada foi alterado)",
            data=pdf_bytes,
            file_name=uploaded_file.name,
            mime="application/pdf"
        )