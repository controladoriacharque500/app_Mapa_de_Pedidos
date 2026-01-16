import streamlit as st
import pandas as pd
from datetime import datetime
import gspread

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

# --- NOVO MÓDULO: GESTÃO DE PRODUTOS ---
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

    df_prod = pd.DataFrame(aba_prod.get_all_records())
    st.dataframe(df_prod, use_container_width=True)

# --- MÓDULO CADASTRO (ATUALIZADO) ---
def tela_cadastro(user):
    st.header("📝 Lançamento de Pedidos")
    gc = get_gc()
    sh = gc.open(PLANILHA_NOME)
    aba_pedidos = sh.worksheet("pedidos")
    aba_produtos = sh.worksheet("produtos")
    
    # 1. Gerar ID Automático
    df_atual = pd.DataFrame(aba_pedidos.get_all_records())
    if not df_atual.empty:
        proximo_id = int(pd.to_numeric(df_atual['id']).max()) + 1
    else:
        proximo_id = 1

    # 2. Carregar Lista de Produtos
    df_p = pd.DataFrame(aba_produtos.get_all_records())
    lista_produtos = df_p['descricao'].tolist()

    with st.container(border=True):
        st.subheader(f"Novo Pedido: #{proximo_id}")
        
        col1, col2 = st.columns(2)
        cliente = col1.text_input("Cliente")
        uf = col2.selectbox("Estado", ["SP", "RJ", "MG", "ES", "PR", "SC", "RS", "GO", "MT", "MS", "BA"])
        
        prod_selecionado = st.selectbox("Selecione o Produto", [""] + lista_produtos)
        
        if prod_selecionado:
            dados_prod = df_p[df_p['descricao'] == prod_selecionado].iloc[0]
            tipo_peso = dados_prod['tipo']
            
            c1, c2 = st.columns(2)
            qtd = c1.number_input("Quantidade de Caixas", min_value=1, step=1)
            
            if tipo_peso == "padrão":
                peso_calc = qtd * float(dados_prod['peso_unitario'])
                peso_final = c2.number_input("Peso Total (Calculado)", value=peso_calc, disabled=True)
                st.caption(f"ℹ️ Produto de peso padrão ({dados_prod['peso_unitario']}kg/un)")
            else:
                peso_final = c2.number_input("Informe o Peso Real (Variável)", min_value=0.1)

            if st.button("Confirmar Lançamento"):
                if cliente:
                    aba_pedidos.append_row([proximo_id, f"{cliente} ({uf})", prod_selecionado, qtd, peso_final, "pendente"])
                    registrar_log(user['usuario'], "CADASTRO", f"ID {proximo_id} - {cliente}")
                    st.success("Pedido lançado!")
                    st.rerun()
                else:
                    st.error("Informe o nome do cliente.")

    st.divider()
    st.subheader("Pedidos Pendentes")
    st.dataframe(df_atual[df_atual['status'] == 'pendente'], use_container_width=True)

# --- TELA DE PEDIDOS (MAPA DE CARGA) ---
def tela_pedidos(user):
    st.header("🚚 Montagem de Carga")
    gc = get_gc()
    sh = gc.open(PLANILHA_NOME)
    aba_pedidos = sh.worksheet("pedidos")
    df_p = pd.DataFrame(aba_pedidos.get_all_records())
    df_pendentes = df_p[df_p['status'] == 'pendente'].copy()

    if df_pendentes.empty:
        st.info("Nenhum pedido pendente.")
        return

    selecao = st.dataframe(df_pendentes, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row")
    
    rows = selecao.selection.rows
    if rows:
        df_rota = df_pendentes.iloc[rows]
        st.table(df_rota[['cliente', 'produto', 'caixas', 'peso']])
        t_peso = df_rota['peso'].sum()
        
        st.metric("Peso Total Selecionado", f"{t_peso:.2f} kg")
        cap_max = st.number_input("Limite do Caminhão", value=1500.0)
        
        if t_peso > cap_max:
            st.error("EXCESSO DE CARGA!")
        elif user['nivel'] != 'visualizacao':
            if st.button("Confirmar Saída para Rota"):
                ids_sel = df_rota['id'].astype(str).tolist()
                dados_brutos = aba_pedidos.get_all_values()
                for i, linha in enumerate(dados_brutos):
                    if str(linha[0]) in ids_sel:
                        aba_pedidos.update_cell(i + 1, 6, "em rota")
                registrar_log(user['usuario'], "SAIDA", f"Carga {t_peso}kg")
                st.rerun()

# --- LOGIN E NAVEGAÇÃO ---
st.set_page_config(page_title="Logística Dinâmica", layout="wide")

if 'usuario_logado' not in st.session_state:
    st.session_state.usuario_logado = None

if st.session_state.usuario_logado is None:
    st.title("Login")
    with st.form("login"):
        u = st.text_input("Usuário")
        s = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            dados = login_usuario(u, s)
            if dados:
                st.session_state.usuario_logado = dados
                st.rerun()
            else: st.error("Erro!")
else:
    user = st.session_state.usuario_logado
    st.sidebar.title(f"👤 {user['usuario']}")
    
    if user['modulos'] == 'todos':
        opcoes = ["Cadastro", "Produtos", "Pedidos", "Logs"]
    else:
        opcoes = user['modulos'].split(',')
    
    menu = st.sidebar.radio("Ir para:", opcoes)

    if menu == "Cadastro": tela_cadastro(user)
    elif menu == "Produtos": tela_produtos(user)
    elif menu == "Pedidos": tela_pedidos(user)
    elif menu == "Logs":
        df_logs = pd.DataFrame(get_gc().open(PLANILHA_NOME).worksheet("log_operacoes").get_all_records())
        st.dataframe(df_logs.sort_index(ascending=False))

    if st.sidebar.button("Sair"):
        st.session_state.usuario_logado = None
        st.rerun()
