import streamlit as st
import pandas as pd
from datetime import datetime
import gspread

# --- CONFIGURAÇÕES INICIAIS ---
PLANILHA_NOME = "Mapa_de_Pedidos" # Nome exato da sua planilha
CREDENTIALS_PATH = "credentials.json"  # Para rodar localmente

def get_gc():
    """Conecta ao Google Sheets usando a lógica de limpeza de chave do projeto anterior."""
    try:
        if "gcp_service_account" in st.secrets:
            secrets_dict = dict(st.secrets["gcp_service_account"])
            # Limpeza da chave privada (Sua lógica anterior)
            pk = secrets_dict["private_key"].replace('\n', '').replace(' ', '')
            pk = pk.replace('-----BEGINPRIVATEKEY-----', '').replace('-----ENDPRIVATEKEY-----', '')
            padding = len(pk) % 4
            if padding != 0: pk += '=' * (4 - padding)
            secrets_dict["private_key"] = f"-----BEGIN PRIVATE KEY-----\n{pk}\n-----END PRIVATE KEY-----\n"
            
            # Autenticação usando gspread padrão
            return gspread.service_account_from_dict(secrets_dict)
        else:
            return gspread.service_account(filename=CREDENTIALS_PATH)
    except Exception as e:
        st.error(f"Erro na conexão: {e}")
        return None

# --- FUNÇÕES DE DADOS ---
def login_usuario(usuario, senha):
    gc = get_gc()
    if gc:
        # Abre a aba 'usuarios'
        sh = gc.open(PLANILHA_NOME)
        wks = sh.worksheet("usuarios")
        df_users = pd.DataFrame(wks.get_all_records())
        
        # Filtra usuário e senha (convertendo senha para string para evitar erro de tipo)
        user_match = df_users[(df_users['usuario'] == usuario) & (df_users['senha'].astype(str) == str(senha))]
        
        if not user_match.empty:
            return user_match.iloc[0].to_dict()
    return None

def registrar_log(usuario, acao, detalhes):
    gc = get_gc()
    aba_log = gc.open(PLANILHA_NOME).worksheet("log_operacoes")
    aba_log.append_row([datetime.now().strftime("%d/%m/%Y %H:%M:%S"), usuario, acao, detalhes])

# --- INTERFACE ---
st.set_page_config(page_title="Sistema de Carga", layout="wide")

if 'usuario_logado' not in st.session_state:
    st.session_state.usuario_logado = None

# TELA DE LOGIN
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
    st.sidebar.title(f"Olá, {user['usuario']}")
    st.sidebar.info(f"Nível: {user['nivel']}")
    
    # Controle de Módulos (Separados por vírgula na planilha)
    if user['modulos'] == 'todos':
        modulos_lista = ["Pedidos", "Dashboard", "Logs"]
    else:
        modulos_lista = user['modulos'].split(',')
    
    menu = st.sidebar.radio("Navegar para:", modulos_lista)

    if menu == "Pedidos":
        st.header("🚚 Controle de Pedidos e Carga")
        
        # Carregar Pedidos
        gc = get_gc()
        planilha = gc.open(PLANILHA_NOME)
        aba_pedidos = planilha.worksheet("pedidos")
        df_p = pd.DataFrame(aba_pedidos.get_all_records())
        
        # Filtro de pendentes
        df_pendentes = df_p[df_p['status'] == 'pendente'].copy()

        # Interface de Seleção
        st.subheader("1. Selecione os itens para a Rota")
        
        # Usando a nova funcionalidade de seleção do Streamlit
        selecao = st.dataframe(
            df_pendentes,
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="multi-row"
        )

        rows_selecionadas = selecao.selection.rows
        
        if rows_selecionadas:
            df_rota = df_pendentes.iloc[rows_selecionadas]
            
            st.divider()
            st.subheader("2. Resumo do Mapa de Carregamento")
            st.table(df_rota[['cliente', 'produto', 'caixas', 'peso']])
            
            # Totais
            total_caixas = df_rota['caixas'].sum()
            total_peso = df_rota['peso'].sum()
            
            c1, c2, c3 = st.columns(3)
            c1.metric("Qtd de Caixas", f"{total_caixas} un")
            c2.metric("Peso Total", f"{total_peso:.2f} kg")
            
            cap_max = st.number_input("Capacidade do Caminhão (kg)", value=1500.0)
            
            if total_peso > cap_max:
                st.error(f"🚨 CARGA EXCEDIDA! Reduza {total_peso - cap_max:.2f} kg")
            else:
                st.success("✅ Peso dentro do limite operacional.")
                
                # Bloqueio de edição para nível 'visualizacao'
                if user['nivel'] == 'visualizacao':
                    st.warning("Seu nível de acesso permite apenas visualizar o mapa.")
                else:
                    if st.button("Confirmar Carregamento"):
                        # Aqui você implementaria a atualização na planilha
                        # Ex: mudar status para 'em rota' e salvar o log
                        registrar_log(user['usuario'], "Criou Mapa de Carga", f"Total: {total_peso}kg")
                        st.balloons()
                        st.success("Mapa salvo e log registrado!")

    if st.sidebar.button("Sair"):
        st.session_state.usuario_logado = None
        st.rerun()
