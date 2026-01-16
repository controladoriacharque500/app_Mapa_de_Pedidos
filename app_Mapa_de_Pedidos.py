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
        if fill: 
            pdf.set_fill_color(230, 230, 230)
            pdf.set_font("Arial", "B", 7)
        else: pdf.set_font("Arial", "", 7)
        pdf.cell(50, 6, label[:30], 1, 0, 'L', fill)
        for col in cols:
            val = row[col]
            txt = f"{val:.2f}" if "PESO" in str(index) else str(int(val))
            pdf.cell(col_width, 6, txt, 1, 0, 'C', fill)
        pdf.ln()
    return bytes(pdf.output())

# --- MÓDULO: GESTÃO DE USUÁRIOS ---
def tela_usuarios(user):
    st.header("👥 Gestão de Usuários e Permissões")
    gc = get_gc()
    sh = gc.open(PLANILHA_NOME)
    aba_user = sh.worksheet("usuarios")
    
    with st.expander("➕ Cadastrar / Editar Usuário"):
        with st.form("form_usuario"):
            novo_u = st.text_input("Usuário (Login)")
            nova_s = st.text_input("Senha", type="password")
            nivel = st.selectbox("Nível", ["total", "visualizacao"])
            st.write("**Módulos Permitidos:**")
            m1 = st.checkbox("Cadastro", True); m2 = st.checkbox("Produtos", True)
            m3 = st.checkbox("Pedidos", True); m4 = st.checkbox("Gestão de Rotas", True)
            m5 = st.checkbox("Gestão de Usuários", False); m6 = st.checkbox("Logs", True)
            
            if st.form_submit_button("Salvar"):
                mods = []
                if m1: mods.append("Cadastro"); 
                if m2: mods.append("Produtos");
                if m3: mods.append("Pedidos"); 
                if m4: mods.append("Gestão de Rotas");
                if m5: mods.append("Gestão de Usuários"); 
                if m6: mods.append("Logs");
                
                df_u = pd.DataFrame(aba_user.get_all_records())
                if novo_u in df_u['usuario'].values:
                    idx = df_u[df_u['usuario'] == novo_u].index[0] + 2
                    aba_user.delete_rows(int(idx))
                aba_user.append_row([novo_u, nova_s, nivel, ",".join(mods)])
                st.success("Usuário salvo!"); st.rerun()
    st.dataframe(pd.DataFrame(aba_user.get_all_records()), use_container_width=True)

# --- MÓDULO: PRODUTOS ---
def tela_produtos(user):
    st.header("📦 Cadastro de Produtos")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME); aba_prod = sh.worksheet("produtos")
    with st.expander("➕ Novo Produto"):
        with st.form("form_prod"):
            desc = st.text_input("Descrição")
            p_unit = st.number_input("Peso Unitário", min_value=0.0, step=0.01)
            tipo = st.selectbox("Tipo de Peso", ["padrão", "variável"])
            if st.form_submit_button("Cadastrar"):
                aba_prod.append_row([desc, p_unit, tipo])
                st.success("Cadastrado!"); st.rerun()
    st.dataframe(pd.DataFrame(aba_prod.get_all_records()), use_container_width=True)

# --- MÓDULO: CADASTRO (LANÇAMENTO) ---
def tela_cadastro(user):
    st.header("📝 Lançamento de Pedidos")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME)
    aba_pedidos = sh.worksheet("pedidos"); aba_produtos = sh.worksheet("produtos")
    df_atual = pd.DataFrame(aba_pedidos.get_all_records())
    proximo_id = int(pd.to_numeric(df_atual['id']).max()) + 1 if not df_atual.empty else 1
    df_p = pd.DataFrame(aba_produtos.get_all_records())

    with st.container(border=True):
        st.subheader(f"Novo Pedido: #{proximo_id}")
        c1, c2 = st.columns(2)
        cliente = c1.text_input("Cliente")
        uf = c2.selectbox("Estado", ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"])
        prod_sel = st.selectbox("Produto", [""] + df_p['descricao'].tolist())
        
        if prod_sel:
            dados_prod = df_p[df_p['descricao'] == prod_sel].iloc[0]
            col_a, col_b = st.columns(2)
            qtd = col_a.number_input("Caixas", min_value=1, step=1)
            # Lógica de Peso Padrão/Variável Recuperada
            if dados_prod['tipo'] == "padrão":
                peso_f = col_b.number_input("Peso (Calculado)", value=float(qtd * float(dados_prod['peso_unitario'])), disabled=True)
            else:
                peso_f = col_b.number_input("Informe o Peso Real", min_value=0.1)

            if st.button("Confirmar Lançamento"):
                if cliente:
                    aba_pedidos.append_row([proximo_id, f"{cliente} ({uf})", prod_sel, qtd, peso_f, "pendente"])
                    registrar_log(user['usuario'], "CADASTRO", f"ID {proximo_id}")
                    st.success("Lançado!"); st.rerun()

# --- MÓDULO: PEDIDOS (MONTAGEM DE CARGA) ---
def tela_pedidos(user):
    st.header("🚚 Montagem de Carga")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME); aba_pedidos = sh.worksheet("pedidos")
    df_p = pd.DataFrame(aba_pedidos.get_all_records())
    df_p['caixas'] = pd.to_numeric(df_p['caixas'], errors='coerce').fillna(0)
    df_p['peso'] = pd.to_numeric(df_p['peso'], errors='coerce').fillna(0)
    df_pendentes = df_p[df_p['status'] == 'pendente'].copy()

    if df_pendentes.empty:
        st.info("Sem pedidos pendentes."); return

    # Filtro por UF
    df_pendentes['uf_extraida'] = df_pendentes['cliente'].str.extract(r'\((.*?)\)')
    ufs = sorted(df_pendentes['uf_extraida'].dropna().unique().tolist())
    f_uf = st.sidebar.multiselect("Filtrar por UF", options=ufs, default=ufs)
    df_filtrado = df_pendentes[df_pendentes['uf_extraida'].isin(f_uf)]

    selecao = st.dataframe(df_filtrado.drop(columns=['uf_extraida']), use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row")
    
    if selecao.selection.rows:
        df_sel = df_filtrado.iloc[selecao.selection.rows]
        # Matriz de Carregamento detalhada Recuperada
        matriz = df_sel.pivot_table(index=['id', 'cliente'], columns='produto', values='caixas', aggfunc='sum', fill_value=0)
        matriz['TOTAL CX'] = matriz.sum(axis=1)
        totais_cx = matriz.sum().to_frame().T
        totais_cx.index = ['TOTAL CAIXAS']
        peso_resumo = df_sel.groupby('produto')['peso'].sum().to_frame().T
        peso_resumo = peso_resumo.reindex(columns=matriz.columns, fill_value=0)
        peso_resumo.index = ['TOTAL PESO (kg)']
        peso_resumo['TOTAL CX'] = df_sel['peso'].sum()
        df_final = pd.concat([matriz, totais_cx, peso_resumo])
        
        st.subheader("📊 Matriz de Carregamento")
        st.dataframe(df_final, use_container_width=True)
        
        c_pdf, c_conf = st.columns(2)
        # Geração de PDF Recuperada
        try:
            pdf_bytes = gerar_pdf_rota(df_final)
            c_pdf.download_button("📄 Baixar PDF do Mapa", data=pdf_bytes, file_name=f"mapa_{datetime.now().strftime('%d%m_%H%M')}.pdf", mime="application/pdf", use_container_width=True)
        except Exception as e: c_pdf.error(f"Erro PDF: {e}")
        
        if user['nivel'] != 'visualizacao' and c_conf.button("🚀 Confirmar Saída para Rota", use_container_width=True):
            ids = df_sel['id'].astype(str).tolist()
            data = aba_pedidos.get_all_values()
            for i, lin in enumerate(data):
                if str(lin[0]) in ids: aba_pedidos.update_cell(i + 1, 6, "em rota")
            registrar_log(user['usuario'], "ROTA", f"Carga confirmada")
            st.rerun()

# --- MÓDULO: GESTÃO DE ROTAS ---
def tela_gestao_rotas(user):
    st.header("🔄 Gestão de Pedidos em Rota")
    sh = get_gc().open(PLANILHA_NOME); aba = sh.worksheet("pedidos")
    df = pd.DataFrame(aba.get_all_records())
    df_rota = df[df['status'] == 'em rota'].copy()
    if df_rota.empty: st.info("Nada em rota."); return

    selecao = st.dataframe(df_rota, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row")
    if selecao.selection.rows:
        df_sel = df_rota.iloc[selecao.selection.rows]
        c1, c2 = st.columns(2)
        with c1.expander("❌ Cancelar Total"):
            if st.button("Confirmar Retorno"):
                ids = df_sel['id'].astype(str).tolist()
                for i, row in enumerate(aba.get_all_values()):
                    if str(row[0]) in ids: aba.update_cell(i + 1, 6, "pendente")
                st.rerun()
        with c2.expander("📉 Saída Parcial"):
            for _, r in df_sel.iterrows():
                qtd_s = st.number_input(f"Qtd saiu #{r['id']}", 0, int(r['caixas']), int(r['caixas']), key=f"s_{r['id']}")
                if st.button(f"Salvar Parcial {r['id']}"):
                    peso_u = float(r['peso']) / int(r['caixas'])
                    for i, lin in enumerate(aba.get_all_values()):
                        if str(lin[0]) == str(r['id']):
                            aba.update_cell(i + 1, 6, "entregue")
                            aba.update_cell(i + 1, 4, qtd_s)
                            aba.update_cell(i + 1, 5, qtd_s * peso_u)
                            sobra = int(r['caixas']) - qtd_s
                            if sobra > 0:
                                aba.append_row([r['id'], r['cliente'], r['produto'], sobra, sobra * peso_u, "pendente"])
                    st.rerun()

# --- MAIN ---
st.set_page_config(page_title="Sistema de Carga", layout="wide")
if 'usuario_logado' not in st.session_state: st.session_state.usuario_logado = None

if st.session_state.usuario_logado is None:
    st.title("Login")
    with st.form("l"):
        u, s = st.text_input("Usuário"), st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            d = login_usuario(u, s)
            if d: st.session_state.usuario_logado = d; st.rerun()
            else: st.error("Login inválido")
else:
    user = st.session_state.usuario_logado
    st.sidebar.title(f"👤 {user['usuario']}")
    opcoes_full = ["Cadastro", "Produtos", "Pedidos", "Gestão de Rotas", "Gestão de Usuários", "Logs"]
    opcoes = opcoes_full if user['modulos'] == 'todos' else user['modulos'].split(',')
    menu = st.sidebar.radio("Menu:", opcoes)

    if menu == "Cadastro": tela_cadastro(user)
    elif menu == "Produtos": tela_produtos(user)
    elif menu == "Pedidos": tela_pedidos(user)
    elif menu == "Gestão de Rotas": tela_gestao_rotas(user)
    elif menu == "Gestão de Usuários": tela_usuarios(user)
    elif menu == "Logs":
        df_l = pd.DataFrame(get_gc().open(PLANILHA_NOME).worksheet("log_operacoes").get_all_records())
        st.dataframe(df_l.sort_index(ascending=False), use_container_width=True)
    
    if st.sidebar.button("Sair"): st.session_state.usuario_logado = None; st.rerun()
