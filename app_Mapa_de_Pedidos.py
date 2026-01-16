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

# --- GESTÃO DE USUÁRIOS E ACESSOS ---
def tela_usuarios(user):
    st.header("👥 Gestão de Usuários e Permissões")
    gc = get_gc()
    sh = gc.open(PLANILHA_NOME)
    aba_user = sh.worksheet("usuarios")
    
    with st.expander("➕ Cadastrar / Editar Usuário"):
        with st.form("form_usuario"):
            novo_u = st.text_input("Nome de Usuário (Login)")
            nova_s = st.text_input("Senha", type="password")
            nivel = st.selectbox("Nível de Poder", ["total", "visualizacao"])
            
            st.write("---")
            st.write("**Módulos Permitidos:**")
            mod_cad = st.checkbox("Cadastro", value=True)
            mod_prod = st.checkbox("Produtos", value=True)
            mod_ped = st.checkbox("Pedidos", value=True)
            mod_gestao = st.checkbox("Gestão de Rotas", value=True)
            mod_user = st.checkbox("Gestão de Usuários", value=False)
            mod_logs = st.checkbox("Logs", value=True)
            
            if st.form_submit_button("Salvar Usuário"):
                # Monta a string de módulos selecionados
                lista_modulos = []
                if mod_cad: lista_modulos.append("Cadastro")
                if mod_prod: lista_modulos.append("Produtos")
                if mod_ped: lista_modulos.append("Pedidos")
                if mod_gestao: lista_modulos.append("Gestão de Rotas")
                if mod_user: lista_modulos.append("Gestão de Usuários")
                if mod_logs: lista_modulos.append("Logs")
                
                modulos_str = ",".join(lista_modulos)
                
                # Verifica se já existe para atualizar ou cria novo
                df_u = pd.DataFrame(aba_user.get_all_records())
                if novo_u in df_u['usuario'].values:
                    # Lógica de update simplificada (remove e adiciona)
                    idx = df_u[df_u['usuario'] == novo_u].index[0] + 2
                    aba_user.delete_rows(int(idx))
                
                aba_user.append_row([novo_u, nova_s, nivel, modulos_str])
                st.success(f"Usuário {novo_u} configurado com sucesso!")
                st.rerun()

    st.write("### Usuários Cadastrados")
    df_exibir = pd.DataFrame(aba_user.get_all_records())
    st.dataframe(df_exibir, use_container_width=True)

# --- GESTÃO DE ROTAS ---
def tela_gestao_rotas(user):
    st.header("🔄 Gestão de Pedidos em Rota")
    gc = get_gc()
    sh = gc.open(PLANILHA_NOME)
    aba = sh.worksheet("pedidos")
    df = pd.DataFrame(aba.get_all_records())
    df_rota = df[df['status'] == 'em rota'].copy()

    if df_rota.empty:
        st.info("Não há pedidos em rota.")
        return

    selecao = st.dataframe(df_rota, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row")
    
    if selecao.selection.rows:
        df_sel = df_rota.iloc[selecao.selection.rows]
        c1, c2 = st.columns(2)
        
        with c1:
            if st.button("❌ Cancelar Total (Voltar Pendente)", use_container_width=True):
                ids = df_sel['id'].astype(str).tolist()
                data = aba.get_all_values()
                for i, row in enumerate(data):
                    if str(row[0]) in ids: aba.update_cell(i + 1, 6, "pendente")
                st.success("Cancelado!")
                st.rerun()
        
        with c2:
            for _, r in df_sel.iterrows():
                with st.expander(f"Parcial Pedido #{r['id']}"):
                    qtd_saiu = st.number_input(f"Qtd que saiu", 0, int(r['caixas']), int(r['caixas']), key=f"s_{r['id']}")
                    if st.button(f"Confirmar Parcial #{r['id']}"):
                        peso_u = float(r['peso']) / int(r['caixas'])
                        data = aba.get_all_values()
                        for i, lin in enumerate(data):
                            if str(lin[0]) == str(r['id']):
                                aba.update_cell(i + 1, 6, "entregue")
                                aba.update_cell(i + 1, 4, qtd_saiu)
                                aba.update_cell(i + 1, 5, qtd_saiu * peso_u)
                                sobra = int(r['caixas']) - qtd_saiu
                                if sobra > 0:
                                    aba.append_row([r['id'], r['cliente'], r['produto'], sobra, sobra * peso_u, "pendente"])
                        st.rerun()

# --- TELAS DE APOIO (CÓDIGO RESUMIDO PARA MANUTENÇÃO) ---
def tela_produtos(user):
    st.header("📦 Produtos")
    sh = get_gc().open(PLANILHA_NOME).worksheet("produtos")
    with st.expander("Novo Produto"):
        with st.form("p"):
            d = st.text_input("Descrição")
            w = st.number_input("Peso", 0.0)
            t = st.selectbox("Tipo", ["padrão", "variável"])
            if st.form_submit_button("OK"): sh.append_row([d, w, t]); st.rerun()
    st.dataframe(pd.DataFrame(sh.get_all_records()), use_container_width=True)

def tela_cadastro(user):
    st.header("📝 Lançamento")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME)
    aba_p = sh.worksheet("pedidos"); df_p = pd.DataFrame(aba_p.get_all_records())
    df_prod = pd.DataFrame(sh.worksheet("produtos").get_all_records())
    prox_id = int(df_p['id'].max() + 1) if not df_p.empty else 1
    with st.form("cad"):
        cli = st.text_input("Cliente")
        uf = st.selectbox("UF", ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"])
        prod = st.selectbox("Produto", df_prod['descricao'].tolist())
        qtd = st.number_input("Qtd", 1)
        if st.form_submit_button("Gravar"):
            p_unit = float(df_prod[df_prod['descricao']==prod]['peso_unitario'].values[0])
            aba_p.append_row([prox_id, f"{cli} ({uf})", prod, qtd, qtd*p_unit, "pendente"])
            st.rerun()

def tela_pedidos(user):
    st.header("🚚 Montagem de Carga")
    sh = get_gc().open(PLANILHA_NOME).worksheet("pedidos")
    df = pd.DataFrame(sh.get_all_records())
    df_pend = df[df['status']=='pendente'].copy()
    if df_pend.empty: st.info("Nada pendente."); return
    sel = st.dataframe(df_pend, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row")
    if sel.selection.rows:
        df_sel = df_pend.iloc[sel.selection.rows]
        if st.button("🚀 Confirmar Saída"):
            ids = df_sel['id'].astype(str).tolist()
            data = sh.get_all_values()
            for i, r in enumerate(data):
                if str(r[0]) in ids: sh.update_cell(i+1, 6, "em rota")
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
    
    # DINÂMICO: O menu agora é baseado no que está escrito na coluna 'modulos' da planilha
    if user['modulos'] == 'todos':
        opcoes = ["Cadastro", "Produtos", "Pedidos", "Gestão de Rotas", "Gestão de Usuários", "Logs"]
    else:
        opcoes = user['modulos'].split(',')
    
    menu = st.sidebar.radio("Menu:", opcoes)

    if menu == "Cadastro": tela_cadastro(user)
    elif menu == "Produtos": tela_produtos(user)
    elif menu == "Pedidos": tela_pedidos(user)
    elif menu == "Gestão de Rotas": tela_gestao_rotas(user)
    elif menu == "Gestão de Usuários": tela_usuarios(user)
    elif menu == "Logs":
        df_l = pd.DataFrame(get_gc().open(PLANILHA_NOME).worksheet("log_operacoes").get_all_records())
        st.dataframe(df_l.sort_index(ascending=False), use_container_width=True)
    
    if st.sidebar.button("Sair"):
        st.session_state.usuario_logado = None
        st.rerun()
