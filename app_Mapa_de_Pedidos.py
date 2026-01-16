import streamlit as st
import pandas as pd
from datetime import datetime
import gspread
from fpdf import FPDF

# --- CONFIGURAÇÕES ---
PLANILHA_NOME = "Mapa_de_Pedidos" 

def get_gc():
    try:
        if "gcp_service_account" in st.secrets:
            secrets_dict = dict(st.secrets["gcp_service_account"])
            pk = secrets_dict["private_key"].replace('\\n', '\n')
            secrets_dict["private_key"] = pk
            return gspread.service_account_from_dict(secrets_dict)
        return gspread.service_account(filename="credentials.json")
    except Exception as e:
        st.error(f"Erro de conexão: {e}")
        return None

def login_usuario(usuario, senha):
    gc = get_gc()
    if gc:
        try:
            sh = gc.open(PLANILHA_NOME)
            wks = sh.worksheet("usuarios")
            df_users = pd.DataFrame(wks.get_all_records())
            user_match = df_users[(df_users['usuario'] == usuario) & (df_users['senha'].astype(str) == str(senha))]
            return user_match.iloc[0].to_dict() if not user_match.empty else None
        except: return None
    return None

# --- TELAS ---

def tela_cadastro(user):
    st.header("📝 Gestão de Pedidos")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME)
    aba_pedidos = sh.worksheet("pedidos"); aba_prod = sh.worksheet("produtos")
    df_ped = pd.DataFrame(aba_pedidos.get_all_records())
    df_prod = pd.DataFrame(aba_prod.get_all_records())

    with st.form("novo_pedido"):
        c1, c2 = st.columns(2)
        cliente = c1.text_input("Cliente")
        uf = c2.selectbox("UF", ["RJ", "SP", "MG", "ES", "PR", "SC", "RS", "GO", "MT", "MS", "BA", "AL", "CE", "MA", "PB", "PE", "PI", "RN", "SE", "AC", "AM", "AP", "PA", "RO", "RR", "TO", "DF"])
        prod_sel = st.selectbox("Produto", df_prod['descricao'].tolist() if not df_prod.empty else [])
        qtd = st.number_input("Caixas", min_value=1, step=1)
        
        if st.form_submit_button("Lançar Pedido"):
            if cliente and prod_sel:
                novo_id = int(pd.to_numeric(df_ped['id'], errors='coerce').max() or 0) + 1
                p_unit = float(df_prod[df_prod['descricao'] == prod_sel]['peso_unitario'].values[0])
                aba_pedidos.append_row([novo_id, f"{cliente} ({uf})", prod_sel, qtd, round(qtd * p_unit, 2), "pendente"])
                st.success("Lançado!"); st.rerun()

def tela_pedidos(user):
    st.header("🚚 Montagem de Carga")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME); aba_pedidos = sh.worksheet("pedidos")
    df = pd.DataFrame(aba_pedidos.get_all_records())
    df_pend = df[df['status'] == 'pendente'].copy() if not df.empty else pd.DataFrame()

    if df_pend.empty:
        st.info("Nenhum pedido pendente.")
        return

    selecao = st.dataframe(df_pend, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row")
    
    if selecao.selection.rows:
        df_sel = df_pend.iloc[selecao.selection.rows]
        # Pivot table segura contra erros de conversão
        matriz = df_sel.assign(caixas=pd.to_numeric(df_sel['caixas'])).pivot_table(index='cliente', columns='produto', values='caixas', aggfunc='sum', fill_value=0)
        st.subheader("📊 Matriz de Carga")
        st.table(matriz)
        
        if st.button("🚀 Confirmar Saída em Rota"):
            ids = df_sel['id'].astype(str).tolist()
            for i, row in enumerate(aba_pedidos.get_all_values()):
                if str(row[0]) in ids: aba_pedidos.update_cell(i+1, 6, "em rota")
            st.success("Em rota!"); st.rerun()

def tela_gestao_rotas(user):
    st.header("🔄 Gestão de Rotas")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME)
    aba_pedidos = sh.worksheet("pedidos"); aba_hist = sh.worksheet("historico")
    df = pd.DataFrame(aba_pedidos.get_all_records())
    df_rota = df[df['status'] == 'em rota'].copy() if not df.empty else pd.DataFrame()

    if df_rota.empty:
        st.info("Nada em rota."); return

    selecao = st.dataframe(df_rota, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row")
    if selecao.selection.rows:
        df_sel = df_rota.iloc[selecao.selection.rows]
        for _, r in df_sel.iterrows():
            with st.expander(f"Baixa: {r['cliente']}"):
                qtd_e = st.number_input(f"Qtd Entregue", 0, int(r['caixas']), int(r['caixas']), key=f"b_{r['id']}")
                if st.button(f"Confirmar #{r['id']}"):
                    aba_hist.append_row([r['id'], r['cliente'], r['produto'], qtd_e, r['peso'], "entregue", datetime.now().strftime("%d/%m/%Y")])
                    aba_pedidos.delete_rows(int(df[df['id'] == r['id']].index[0]) + 2)
                    st.rerun()

# --- MAIN ---
st.set_page_config(page_title="Sistema Carga", layout="wide")

if 'user' not in st.session_state:
    st.session_state.user = None

if st.session_state.user is None:
    st.title("🔐 Login")
    with st.form("l"):
        u, s = st.text_input("Usuário"), st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            res = login_usuario(u, s)
            if res: st.session_state.user = res; st.rerun()
            else: st.error("Erro no login")
else:
    # CORREÇÃO DO MENU: Se for admin ou total, mostra tudo
    permissao = str(st.session_state.user.get('nivel', '')).lower()
    modulos_brutos = str(st.session_state.user.get('modulos', '')).lower()
    
    if permissao in ['total', 'admin'] or 'todos' in modulos_brutos:
        menus_disponiveis = ["Cadastro", "Pedidos", "Gestão de Rotas", "Relatórios"]
    else:
        menus_disponiveis = [m.strip() for m in st.session_state.user['modulos'].split(',')]

    st.sidebar.title(f"👋 Olá, {st.session_state.user['usuario']}!")
    escolha = st.sidebar.radio("Navegação:", menus_disponiveis)
    
    if st.sidebar.button("Sair"):
        st.session_state.user = None
        st.rerun()

    if escolha == "Cadastro": tela_cadastro(st.session_state.user)
    elif escolha == "Pedidos": tela_pedidos(st.session_state.user)
    elif escolha == "Gestão de Rotas": tela_gestao_rotas(st.session_state.user)
    elif escolha == "Relatórios": st.write("Tela de relatórios em desenvolvimento.")
