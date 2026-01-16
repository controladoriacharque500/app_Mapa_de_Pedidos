import streamlit as st
import pandas as pd
from datetime import datetime
import gspread
from fpdf import FPDF
import io

# --- CONFIGURAÇÕES INICIAIS ---
PLANILHA_NOME = "Mapa_de_Pedidos" 
CREDENTIALS_PATH = "credentials.json"

def get_gc():
    try:
        if "gcp_service_account" in st.secrets:
            secrets_dict = dict(st.secrets["gcp_service_account"])
            pk = secrets_dict["private_key"].replace('\n', '').replace(' ', '')
            pk = pk.replace('-----BEGINPRIVATEKEY-----', '').replace('-----ENDPRIVATEKEY-----', '')
            padding = len(pk) % 4
            if padding != 0: pk += '=' * (4 - padding)
            secrets_dict["private_key"] = f"-----BEGIN PRIVATE KEY-----\n{pk}\n-----END PRIVATE KEY-----\n"
            return gspread.service_account_from_dict(secrets_dict)
        else:
            return gspread.service_account(filename=CREDENTIALS_PATH)
    except Exception as e:
        st.error(f"Erro na conexão: {e}")
        return None

# --- FUNÇÕES DE APOIO ---
def registrar_log(usuario, acao, detalhes):
    try:
        gc = get_gc()
        aba_log = gc.open(PLANILHA_NOME).worksheet("log_operacoes")
        aba_log.append_row([datetime.now().strftime("%d/%m/%Y %H:%M:%S"), usuario, acao, detalhes])
    except: pass

def login_usuario(usuario, senha):
    gc = get_gc()
    if gc:
        sh = gc.open(PLANILHA_NOME)
        wks = sh.worksheet("usuarios")
        df_users = pd.DataFrame(wks.get_all_records())
        user_match = df_users[(df_users['usuario'] == usuario) & (df_users['senha'].astype(str) == str(senha))]
        return user_match.iloc[0].to_dict() if not user_match.empty else None
    return None

# --- GERAÇÃO DE PDF ---
def gerar_pdf_rota(df_matriz):
    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, f"MAPA DE CARREGAMENTO - {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True, align='C')
    pdf.ln(5)
    
    pdf.set_font("Arial", "B", 7)
    cols = df_matriz.columns.tolist()
    col_width = 240 / (len(cols) + 1)
    
    pdf.cell(50, 7, "Cliente", 1, 0, 'C')
    for col in cols:
        pdf.cell(col_width, 7, str(col)[:10], 1, 0, 'C')
    pdf.ln()
    
    pdf.set_font("Arial", "", 7)
    for index, row in df_matriz.iterrows():
        label = str(index[1]) if isinstance(index, tuple) else str(index)
        fill = index in ['TOTAL CAIXAS', 'TOTAL PESO (kg)']
        if fill: pdf.set_fill_color(230, 230, 230)
        
        pdf.cell(50, 6, label[:30], 1, 0, 'L', fill)
        for col in cols:
            val = row[col]
            txt = f"{val:.2f}" if "PESO" in str(index) else str(int(val))
            pdf.cell(col_width, 6, txt, 1, 0, 'C', fill)
        pdf.ln()
    return pdf.output()

# --- MÓDULOS DE TELA ---
def tela_produtos(user):
    st.header("📦 Cadastro de Produtos")
    gc = get_gc()
    sh = gc.open(PLANILHA_NOME)
    aba_prod = sh.worksheet("produtos")
    with st.expander("➕ Adicionar Novo Produto"):
        with st.form("form_prod"):
            desc = st.text_input("Descrição do Produto")
            p_unit = st.number_input("Peso Unitário (se for padrão)", min_value=0.0, step=0.01)
            tipo = st.selectbox("Tipo de Peso", ["padrão", "variável"])
            if st.form_submit_button("Cadastrar Produto"):
                aba_prod.append_row([desc, p_unit, tipo])
                st.success("Produto cadastrado!")
                st.rerun()
    st.dataframe(pd.DataFrame(aba_prod.get_all_records()), use_container_width=True)

def tela_cadastro(user):
    st.header("📝 Lançamento de Pedidos")
    gc = get_gc()
    sh = gc.open(PLANILHA_NOME)
    aba_pedidos = sh.worksheet("pedidos")
    aba_produtos = sh.worksheet("produtos")
    
    df_atual = pd.DataFrame(aba_pedidos.get_all_records())
    proximo_id = int(pd.to_numeric(df_atual['id']).max()) + 1 if not df_atual.empty else 1
    df_p = pd.DataFrame(aba_produtos.get_all_records())
    lista_produtos = df_p['descricao'].tolist()

    with st.container(border=True):
        st.subheader(f"Novo Pedido: #{proximo_id}")
        c1, c2 = st.columns(2)
        cliente = c1.text_input("Cliente")
        uf = c2.selectbox("Estado", ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"])
        prod_sel = st.selectbox("Produto", [""] + lista_produtos)
        
        if prod_sel:
            dados_prod = df_p[df_p['descricao'] == prod_sel].iloc[0]
            col_a, col_b = st.columns(2)
            qtd = col_a.number_input("Caixas", min_value=1, step=1)
            if dados_prod['tipo'] == "padrão":
                peso_f = col_b.number_input("Peso (Calculado)", value=qtd * float(dados_prod['peso_unitario']), disabled=True)
            else:
                peso_f = col_b.number_input("Informe o Peso Real", min_value=0.1)

            if st.button("Confirmar Lançamento"):
                if cliente:
                    aba_pedidos.append_row([proximo_id, f"{cliente} ({uf})", prod_sel, qtd, peso_f, "pendente"])
                    registrar_log(user['usuario'], "CADASTRO", f"ID {proximo_id}")
                    st.success("Lançado!")
                    st.rerun()

def tela_pedidos(user):
    st.header("🚚 Montagem de Carga")
    gc = get_gc()
    sh = gc.open(PLANILHA_NOME)
    aba_pedidos = sh.worksheet("pedidos")
    df_p = pd.DataFrame(aba_pedidos.get_all_records())
    df_p['caixas'] = pd.to_numeric(df_p['caixas'], errors='coerce').fillna(0)
    df_p['peso'] = pd.to_numeric(df_p['peso'], errors='coerce').fillna(0)
    df_pendentes = df_p[df_p['status'] == 'pendente'].copy()

    if df_pendentes.empty:
        st.info("Sem pedidos pendentes.")
        return

    # --- FILTRO POR ESTADO (UF) ---
    st.sidebar.subheader("Filtros de Rota")
    df_pendentes['uf_extraida'] = df_pendentes['cliente'].str.extract(r'\((.*?)\)')
    ufs_disponiveis = sorted(df_pendentes['uf_extraida'].dropna().unique().tolist())
    filtro_uf = st.sidebar.multiselect("Filtrar por UF", options=ufs_disponiveis, default=ufs_disponiveis)
    
    df_filtrado = df_pendentes[df_pendentes['uf_extraida'].isin(filtro_uf)]

    selecao = st.dataframe(
        df_filtrado.drop(columns=['uf_extraida']), 
        use_container_width=True, 
        hide_index=True, 
        on_select="rerun", 
        selection_mode="multi-row"
    )
    
    rows = selecao.selection.rows
    if rows:
        df_sel = df_filtrado.iloc[rows]
        
        # MATRIZ DINÂMICA (Resolução do ValueError de alinhamento)
        matriz = df_sel.pivot_table(index=['id', 'cliente'], columns='produto', values='caixas', aggfunc='sum', fill_value=0)
        matriz['TOTAL CX'] = matriz.sum(axis=1)
        
        totais_cx = matriz.sum().to_frame().T
        totais_cx.index = ['TOTAL CAIXAS']
        
        # Cálculo de Peso por Produto alinhado às colunas da matriz
        peso_resumo = df_sel.groupby('produto')['peso'].sum().to_frame().T
        peso_resumo = peso_resumo.reindex(columns=matriz.columns, fill_value=0)
        peso_resumo.index = ['TOTAL PESO (kg)']
        peso_resumo['TOTAL CX'] = df_sel['peso'].sum()
        
        df_final = pd.concat([matriz, totais_cx, peso_resumo])
        
        st.subheader("📊 Matriz de Carregamento")
        st.dataframe(df_final, use_container_width=True)
        
        col_pdf, col_conf = st.columns(2)
        
        # Botão PDF
        pdf_bytes = gerar_pdf_rota(df_final)
        col_pdf.download_button("📄 Baixar PDF para Impressão", data=pdf_bytes, file_name="mapa_carga.pdf", mime="application/pdf", use_container_width=True)
        
        # Botão Confirmar
        if user['nivel'] != 'visualizacao' and col_conf.button("🚀 Confirmar Saída para Rota", use_container_width=True):
            ids_sel = df_sel['id'].astype(str).tolist()
            dados_planilha = aba_pedidos.get_all_values()
            for i, linha in enumerate(dados_planilha):
                if str(linha[0]) in ids_sel:
                    aba_pedidos.update_cell(i + 1, 6, "em rota")
            registrar_log(user['usuario'], "ROTA", f"Carga: {df_sel['peso'].sum()}kg")
            st.rerun()

# --- MAIN ---
st.set_page_config(page_title="Logística Dinâmica", layout="wide")

if 'usuario_logado' not in st.session_state:
    st.session_state.usuario_logado = None

if st.session_state.usuario_logado is None:
    st.title("Login do Sistema")
    with st.form("login"):
        u = st.text_input("Usuário")
        s = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            dados = login_usuario(u, s)
            if dados:
                st.session_state.usuario_logado = dados
                st.rerun()
            else: st.error("Usuário ou senha incorretos.")
else:
    user = st.session_state.usuario_logado
    st.sidebar.title(f"👤 {user['usuario']}")
    opcoes = ["Cadastro", "Produtos", "Pedidos", "Logs"] if user['modulos'] == 'todos' else user['modulos'].split(',')
    menu = st.sidebar.radio("Menu:", opcoes)

    if menu == "Cadastro": tela_cadastro(user)
    elif menu == "Produtos": tela_produtos(user)
    elif menu == "Pedidos": tela_pedidos(user)
    elif menu == "Logs":
        gc = get_gc()
        df_logs = pd.DataFrame(gc.open(PLANILHA_NOME).worksheet("log_operacoes").get_all_records())
        st.dataframe(df_logs.sort_index(ascending=False), use_container_width=True)

    if st.sidebar.button("Sair"):
        st.session_state.usuario_logado = None
        st.rerun()
