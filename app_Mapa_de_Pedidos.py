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

# --- MÓDULOS ---

def tela_usuarios(user):
    st.header("👥 Gestão de Usuários")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME); aba_user = sh.worksheet("usuarios")
    with st.expander("➕ Configurar Usuário"):
        with st.form("form_u"):
            n_u = st.text_input("Login"); n_s = st.text_input("Senha"); n_l = st.selectbox("Nível", ["total", "visualizacao"])
            mods = ["Cadastro", "Produtos", "Pedidos", "Gestão de Rotas", "Gestão de Usuários", "Logs"]
            sel = [m for m in mods if st.checkbox(m, value=True)]
            if st.form_submit_button("Salvar"):
                df = pd.DataFrame(aba_user.get_all_records())
                if n_u in df['usuario'].values: aba_user.delete_rows(int(df[df['usuario']==n_u].index[0]+2))
                aba_user.append_row([n_u, n_s, n_l, ",".join(sel)])
                st.success("Salvo!"); st.rerun()
    st.dataframe(pd.DataFrame(aba_user.get_all_records()))

def tela_produtos(user):
    st.header("📦 Produtos")
    sh = get_gc().open(PLANILHA_NOME).worksheet("produtos")
    with st.expander("Novo Produto"):
        with st.form("f_p"):
            d = st.text_input("Desc"); p = st.number_input("Peso", 0.0); t = st.selectbox("Tipo", ["padrão", "variável"])
            if st.form_submit_button("Ok"): sh.append_row([d, p, t]); st.rerun()
    st.dataframe(pd.DataFrame(sh.get_all_records()))

def tela_cadastro(user):
    st.header("📝 Gestão de Pedidos")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME)
    aba_ped = sh.worksheet("pedidos"); aba_prod = sh.worksheet("produtos")
    df_ped = pd.DataFrame(aba_ped.get_all_records())
    df_prod = pd.DataFrame(aba_prod.get_all_records())

    t1, t2 = st.tabs(["Lançar", "Editar/Excluir"])
    with t1:
        prox_id = int(pd.to_numeric(df_ped['id']).max()) + 1 if not df_ped.empty else 1
        with st.form("f_n"):
            cli = st.text_input("Cliente")
            uf = st.selectbox("UF", ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"])
            prod = st.selectbox("Produto", [""] + df_prod['descricao'].tolist())
            if prod:
                dp = df_prod[df_prod['descricao']==prod].iloc[0]
                q = st.number_input("Caixas", 1)
                p = st.number_input("Peso", value=float(q*dp['peso_unitario'])) if dp['tipo']=="padrão" else st.number_input("Peso Real", 0.1)
                if st.form_submit_button("Lançar"):
                    aba_ped.append_row([prox_id, f"{cli} ({uf})", prod, q, p, "pendente"])
                    st.rerun()
    with t2:
        df_pend = df_ped[df_ped['status']=='pendente']
        if not df_pend.empty:
            s_idx = st.selectbox("Pedido", df_pend.index, format_func=lambda x: f"#{df_pend.loc[x,'id']} {df_pend.loc[x,'cliente']}")
            with st.form("f_e"):
                n_c = st.text_input("Cliente", df_pend.loc[s_idx, 'cliente'])
                n_q = st.number_input("Qtd", value=int(df_pend.loc[s_idx, 'caixas']))
                c_e, c_d = st.columns(2)
                if c_e.form_submit_button("Salvar"):
                    all_v = aba_ped.get_all_values()
                    for i, r in enumerate(all_v):
                        if str(r[0]) == str(df_pend.loc[s_idx, 'id']) and r[5] == 'pendente':
                            aba_ped.update_cell(i+1, 2, n_c); aba_ped.update_cell(i+1, 4, n_q)
                            aba_ped.update_cell(i+1, 5, n_q * (float(df_pend.loc[s_idx,'peso'])/int(df_pend.loc[s_idx,'caixas'])))
                            st.rerun()
                if c_d.form_submit_button("Excluir"):
                    all_v = aba_ped.get_all_values()
                    for i, r in enumerate(all_v):
                        if str(r[0]) == str(df_pend.loc[s_idx, 'id']) and r[5] == 'pendente':
                            aba_ped.delete_rows(i+1); st.rerun()

def tela_pedidos(user):
    st.header("🚚 Montagem de Carga")
    sh = get_gc().open(PLANILHA_NOME).worksheet("pedidos")
    df = pd.DataFrame(sh.get_all_records())
    df_p = df[df['status']=='pendente'].copy()
    if df_p.empty: st.info("Nada pendente."); return
    
    sel = st.dataframe(df_p, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row")
    if sel.selection.rows:
        df_sel = df_p.iloc[sel.selection.rows]
        matriz = df_sel.pivot_table(index=['id', 'cliente'], columns='produto', values='caixas', aggfunc='sum', fill_value=0)
        st.dataframe(matriz)
        
        c1, c2 = st.columns(2)
        try: c1.download_button("📄 PDF", gerar_pdf_rota(matriz), "mapa.pdf")
        except: pass
        
        if (user['nivel'] == 'total' or user['usuario'] == 'admin') and c2.button("🚀 Confirmar Saída"):
            ids_selecionados = df_sel['id'].astype(str).tolist()
            # PEGA TODOS OS DADOS DA PLANILHA PARA LOCALIZAR A LINHA EXATA
            all_rows = sh.get_all_values()
            
            for i, row in enumerate(all_rows):
                # SÓ ATUALIZA SE: ID bater E o status for 'pendente'
                # Isso impede que ele mude a linha que já está 'entregue' (mesmo ID)
                if str(row[0]) in ids_selecionados and row[5] == 'pendente':
                    sh.update_cell(i + 1, 6, "em rota")
            st.success("Carga em rota!"); st.rerun()

def tela_gestao_rotas(user):
    st.header("🔄 Gestão de Rotas")
    sh = get_gc().open(PLANILHA_NOME).worksheet("pedidos")
    df = pd.DataFrame(sh.get_all_records())
    df_r = df[df['status']=='em rota'].copy()
    if df_r.empty: st.info("Nada em rota."); return
    
    sel = st.dataframe(df_r, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row")
    if sel.selection.rows:
        df_sel = df_r.iloc[sel.selection.rows]
        c1, c2 = st.columns(2)
        with c1.expander("❌ Retornar"):
            if st.button("Confirmar Retorno"):
                all_v = sh.get_all_values()
                for i, r in enumerate(all_v):
                    if str(r[0]) in df_sel['id'].astype(str).tolist() and r[5] == 'em rota':
                        sh.update_cell(i+1, 6, "pendente")
                st.rerun()
        with c2.expander("📉 Parcial"):
            for _, r in df_sel.iterrows():
                qtd_s = st.number_input(f"Qtd saiu #{r['id']}", 0, int(r['caixas']), int(r['caixas']), key=f"r_{r['id']}")
                if st.button(f"Salvar #{r['id']}"):
                    peso_u = float(r['peso'])/int(r['caixas'])
                    all_v = sh.get_all_values()
                    for i, lin in enumerate(all_v):
                        # LOCALIZAÇÃO SEGURA: ID + Status 'em rota'
                        if str(lin[0]) == str(r['id']) and lin[5] == 'em rota':
                            sh.update_cell(i+1, 6, "entregue")
                            sh.update_cell(i+1, 4, qtd_s)
                            sh.update_cell(i+1, 5, qtd_s * peso_u)
                            if int(r['caixas']) - qtd_s > 0:
                                sob = int(r['caixas']) - qtd_s
                                sh.append_row([r['id'], r['cliente'], r['produto'], sob, sob*peso_u, "pendente"])
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
    ops = ["Cadastro", "Produtos", "Pedidos", "Gestão de Rotas", "Gestão de Usuários", "Logs"]
    menu = st.sidebar.radio("Menu:", ops if user['modulos'] == 'todos' else user['modulos'].split(','))
    
    if menu == "Cadastro": tela_cadastro(user)
    elif menu == "Produtos": tela_produtos(user)
    elif menu == "Pedidos": tela_pedidos(user)
    elif menu == "Gestão de Rotas": tela_gestao_rotas(user)
    elif menu == "Gestão de Usuários": tela_usuarios(user)
    elif menu == "Logs":
        st.dataframe(pd.DataFrame(get_gc().open(PLANILHA_NOME).worksheet("log_operacoes").get_all_records()).sort_index(ascending=False))
    if st.sidebar.button("Sair"): st.session_state.usuario_logado = None; st.rerun()
