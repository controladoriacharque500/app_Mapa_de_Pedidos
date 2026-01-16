import streamlit as st
import pandas as pd
from datetime import datetime
import gspread

# --- CONFIGURAÇÕES INICIAIS ---
PLANILHA_NOME = "Mapa_de_Pedidos" 
CREDENTIALS_PATH = "credentials.json"

def get_gc():
    """Conecta ao Google Sheets usando a lógica de limpeza de chave."""
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
    except:
        pass

def login_usuario(usuario, senha):
    gc = get_gc()
    if gc:
        sh = gc.open(PLANILHA_NOME)
        wks = sh.worksheet("usuarios")
        df_users = pd.DataFrame(wks.get_all_records())
        user_match = df_users[(df_users['usuario'] == usuario) & (df_users['senha'].astype(str) == str(senha))]
        if not user_match.empty:
            return user_match.iloc[0].to_dict()
    return None

# --- MÓDULO 1: CADASTRO E EDIÇÃO ---
def tela_cadastro(user):
    st.header("📝 Gestão de Pedidos")
    gc = get_gc()
    sh = gc.open(PLANILHA_NOME)
    aba_pedidos = sh.worksheet("pedidos")

    # Inserção de Novo Pedido
    with st.expander("➕ Cadastrar Novo Pedido", expanded=False):
        if user['nivel'] == 'visualizacao':
            st.warning("Seu nível de acesso não permite cadastrar.")
        else:
            with st.form("novo_pedido", clear_on_submit=True):
                c1, c2 = st.columns(2)
                id_p = c1.text_input("ID Pedido")
                cli = c1.text_input("Cliente")
                prod = c2.text_input("Produto")
                cx = c2.number_input("Caixas", min_value=1)
                peso = st.number_input("Peso Total (kg)", min_value=0.0)
                if st.form_submit_button("Salvar Pedido"):
                    aba_pedidos.append_row([id_p, cli, prod, cx, peso, "pendente"])
                    registrar_log(user['usuario'], "CADASTRO", f"Inseriu ID {id_p}")
                    st.success("Pedido salvo!")
                    st.rerun()

    st.divider()
    st.subheader("✏️ Editar Pedidos Existentes")
    df_todos = pd.DataFrame(aba_pedidos.get_all_records())
    
    # O data_editor permite editar células diretamente
    df_edit = st.data_editor(df_todos, use_container_width=True, num_rows="dynamic", key="editor")

    if st.button("💾 Salvar Alterações na Planilha"):
        if user['nivel'] == 'visualizacao':
            st.error("Acesso negado.")
        else:
            aba_pedidos.clear()
            aba_pedidos.update([df_edit.columns.values.tolist()] + df_edit.values.tolist())
            registrar_log(user['usuario'], "EDIÇÃO", "Editou lista de pedidos")
            st.success("Planilha atualizada!")
            st.rerun()

# --- MÓDULO 2: CONTROLE DE CARGA ---
def tela_pedidos(user):
    st.header("🚚 Controle de Pedidos e Carga")
    gc = get_gc()
    planilha = gc.open(PLANILHA_NOME)
    aba_pedidos = planilha.worksheet("pedidos")
    df_p = pd.DataFrame(aba_pedidos.get_all_records())
    
    df_pendentes = df_p[df_p['status'] == 'pendente'].copy()

    if df_pendentes.empty:
        st.info("Nenhum pedido pendente para carregar.")
        return

    st.subheader("1. Selecione os itens para a Rota")
    selecao = st.dataframe(
        df_pendentes,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="multi-row"
    )

    rows = selecao.selection.rows
    if rows:
        df_rota = df_pendentes.iloc[rows]
        st.divider()
        st.subheader("2. Resumo do Mapa de Carregamento")
        st.table(df_rota[['cliente', 'produto', 'caixas', 'peso']])
        
        t_caixas = df_rota['caixas'].sum()
        t_peso = df_rota['peso'].sum()
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Qtd de Caixas", f"{t_caixas} un")
        c2.metric("Peso Total", f"{t_peso:.2f} kg")
        
        cap_max = st.number_input("Capacidade do Caminhão (kg)", value=1500.0)
        
        if t_peso > cap_max:
            st.error(f"🚨 CARGA EXCEDIDA! Reduza {t_peso - cap_max:.2f} kg")
        else:
            st.success("✅ Peso dentro do limite.")
            if user['nivel'] == 'visualizacao':
                st.warning("Apenas visualização.")
            else:
                if st.button("Confirmar Carregamento"):
                    # ATUALIZAÇÃO REAL NA PLANILHA
                    dados_completos = aba_pedidos.get_all_values()
                    ids_selecionados = df_rota['id'].astype(str).tolist()
                    
                    for i, linha in enumerate(dados_completos):
                        if str(linha[0]) in ids_selecionados:
                            aba_pedidos.update_cell(i + 1, 6, "em rota") # Coluna 6 = Status
                    
                    registrar_log(user['usuario'], "CARGA", f"Fechou carga de {t_peso}kg")
                    st.balloons()
                    st.success("Status atualizado para 'em rota'!")
                    st.rerun()

# --- INTERFACE PRINCIPAL ---
st.set_page_config(page_title="Sistema de Carga", layout="wide")

if 'usuario_logado' not in st.session_state:
    st.session_state.usuario_logado = None

if st.session_state.usuario_logado is None:
    st.title("Login do Sistema")
    with st.form("form_login"):
        u = st.text_input("Usuário")
        s = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            dados = login_usuario(u, s)
            if dados:
                st.session_state.usuario_logado = dados
                st.rerun()
            else:
                st.error("Credenciais inválidas")
else:
    user = st.session_state.usuario_logado
    st.sidebar.title(f"👤 {user['usuario']}")
    st.sidebar.write(f"Nível: **{user['nivel']}**")
    
    if user['modulos'] == 'todos':
        modulos_lista = ["Cadastro", "Pedidos", "Logs"]
    else:
        modulos_lista = user['modulos'].split(',')
    
    menu = st.sidebar.radio("Navegar para:", modulos_lista)

    if menu == "Cadastro":
        tela_cadastro(user)
    elif menu == "Pedidos":
        tela_pedidos(user)
    elif menu == "Logs":
        st.header("📜 Histórico de Operações")
        gc = get_gc()
        df_logs = pd.DataFrame(gc.open(PLANILHA_NOME).worksheet("log_operacoes").get_all_records())
        st.dataframe(df_logs.sort_index(ascending=False), use_container_width=True)

    if st.sidebar.button("Sair"):
        st.session_state.usuario_logado = None
        st.rerun()
