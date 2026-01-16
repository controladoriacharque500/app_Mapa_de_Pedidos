import streamlit as st
import pandas as pd
from datetime import datetime
import gspread
from fpdf import FPDF

# --- CONFIGURAÇÕES INICIAIS ---
PLANILHA_NOME = "Mapa_de_Pedidos" 
CREDENTIALS_PATH = "credentials.json"

def get_gc():
    try:
        if "gcp_service_account" in st.secrets:
            secrets_dict = dict(st.secrets["gcp_service_account"])
            pk = secrets_dict["private_key"].replace('\n', '\n')
            secrets_dict["private_key"] = pk
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
    
    df_reset = df_matriz.reset_index()
    cols = df_reset.columns.tolist()
    col_width = 270 / len(cols)
    
    pdf.set_font("Arial", "B", 8)
    for col in cols:
        pdf.cell(col_width, 8, str(col)[:15], 1, 0, 'C')
    pdf.ln()
    
    pdf.set_font("Arial", "", 8)
    for _, row in df_reset.iterrows():
        for val in row:
            pdf.cell(col_width, 7, str(val)[:20], 1, 0, 'C')
        pdf.ln()
    return bytes(pdf.output())

# --- MÓDULOS DE TELA ---

def tela_usuarios(user):
    st.header("👥 Gestão de Usuários")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME); aba_user = sh.worksheet("usuarios")
    with st.expander("➕ Cadastrar / Editar Usuário"):
        with st.form("form_usuario"):
            novo_u = st.text_input("Usuário (Login)")
            nova_s = st.text_input("Senha", type="password")
            nivel = st.selectbox("Nível", ["total", "visualizacao"])
            mods_list = ["Cadastro", "Produtos", "Pedidos", "Gestão de Rotas", "Relatórios", "Gestão de Usuários", "Logs"]
            selecionados = []
            for m in mods_list:
                if st.checkbox(m, value=True, key=f"check_{m}"): selecionados.append(m)
            
            if st.form_submit_button("Salvar Usuário"):
                aba_user.append_row([novo_u, nova_s, nivel, ",".join(selecionados)])
                st.success("Usuário salvo!"); st.rerun()
    st.dataframe(pd.DataFrame(aba_user.get_all_records()), use_container_width=True)

def tela_produtos(user):
    st.header("📦 Cadastro de Produtos")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME); aba_prod = sh.worksheet("produtos")
    with st.form("form_prod"):
        desc = st.text_input("Descrição")
        p_unit = st.number_input("Peso Unitário", min_value=0.0)
        tipo = st.selectbox("Tipo", ["padrão", "variável"])
        if st.form_submit_button("Cadastrar"):
            aba_prod.append_row([desc, p_unit, tipo])
            st.success("Cadastrado!"); st.rerun()
    st.dataframe(pd.DataFrame(aba_prod.get_all_records()), use_container_width=True)

def tela_cadastro(user):
    st.header("📝 Gestão de Pedidos")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME)
    aba_pedidos = sh.worksheet("pedidos")
    aba_produtos = sh.worksheet("produtos")
    
    df_ped = pd.DataFrame(aba_pedidos.get_all_records())
    df_prod = pd.DataFrame(aba_produtos.get_all_records())

    tab1, tab2 = st.tabs(["🚀 Novo Lançamento", "✏️ Editar/Excluir"])
    
    with tab1:
        with st.form("novo_pedido"):
            cliente = st.text_input("Cliente")
            uf = st.selectbox("UF", ["RJ", "SP", "MG", "ES", "PE", "AL", "BA", "SC", "PR", "RS"])
            prod_sel = st.selectbox("Produto", df_prod['descricao'].tolist() if not df_prod.empty else [])
            qtd = st.number_input("Caixas", min_value=1)
            
            if st.form_submit_button("Lançar Pedido"):
                proximo_id = int(df_ped['id'].max() + 1) if not df_ped.empty and 'id' in df_ped.columns else 1
                peso_u = df_prod[df_prod['descricao'] == prod_sel]['peso_unitario'].values[0]
                aba_pedidos.append_row([proximo_id, f"{cliente} ({uf})", prod_sel, qtd, qtd * peso_u, "pendente"])
                st.success("Pedido lançado!"); st.rerun()

def tela_pedidos(user):
    st.header("🚚 Montagem de Carga")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME); aba_pedidos = sh.worksheet("pedidos")
    df_p = pd.DataFrame(aba_pedidos.get_all_records())
    
    if df_p.empty:
        st.info("Nenhum pedido pendente."); return

    df_pendentes = df_p[df_p['status'] == 'pendente'].copy()
    if df_pendentes.empty:
        st.info("Todos os pedidos já foram processados."); return

    selecao = st.dataframe(df_pendentes, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row")
    
    if selecao.selection.rows:
        df_sel = df_pendentes.iloc[selecao.selection.rows]
        st.subheader("📊 Matriz de Carregamento")
        matriz = df_sel.pivot_table(index=['id', 'cliente'], columns='produto', values='caixas', aggfunc='sum', fill_value=0)
        st.dataframe(matriz, use_container_width=True)
        
        if st.button("Confirmar Saída (Em Rota)"):
            ids = df_sel['id'].astype(str).tolist()
            todas_linhas = aba_pedidos.get_all_values()
            for i, linha in enumerate(todas_linhas):
                if str(linha[0]) in ids:
                    aba_pedidos.update_cell(i + 1, 6, "em rota")
            st.success("Pedidos em rota!"); st.rerun()

def tela_gestao_rotas(user):
    st.header("🔄 Baixa de Entregas")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME)
    aba_pedidos = sh.worksheet("pedidos")
    aba_hist = sh.worksheet("historico")
    
    df_ped = pd.DataFrame(aba_pedidos.get_all_records())
    df_rota = df_ped[df_ped['status'] == 'em rota'].copy()
    
    if df_rota.empty:
        st.info("Nenhum pedido em rota."); return
        
    for _, r in df_rota.iterrows():
        with st.expander(f"ID {r['id']} - {r['cliente']} ({r['produto']})"):
            entregue = st.number_input(f"Qtd entregue", 0, int(r['caixas']), int(r['caixas']), key=f"baixa_{r['id']}")
            if st.button(f"Confirmar Baixa #{r['id']}", key=f"btn_{r['id']}"):
                # Calcular pesos
                peso_u = float(r['peso']) / int(r['caixas'])
                sobra = int(r['caixas']) - entregue
                
                # 1. Atualizar histórico (Soma se já existir ID + Produto)
                df_h = pd.DataFrame(aba_hist.get_all_records())
                match = df_h[(df_h['id'].astype(str) == str(r['id'])) & (df_h['produto'] == r['produto'])]
                
                if not match.empty:
                    idx_h = match.index[0] + 2
                    aba_hist.update_cell(idx_h, 4, int(match.iloc[0]['caixas']) + entregue)
                    aba_hist.update_cell(idx_h, 5, float(match.iloc[0]['peso']) + (entregue * peso_u))
                else:
                    aba_hist.append_row([r['id'], r['cliente'], r['produto'], entregue, entregue * peso_u, "entregue"])
                
                # 2. Atualizar Pedido Original
                data_ped = aba_pedidos.get_all_values()
                for i, lin in enumerate(data_ped):
                    if str(lin[0]) == str(r['id']) and lin[2] == r['produto']:
                        if sobra > 0:
                            aba_pedidos.update_cell(i+1, 4, sobra)
                            aba_pedidos.update_cell(i+1, 5, sobra * peso_u)
                            aba_pedidos.update_cell(i+1, 6, "pendente")
                        else:
                            aba_pedidos.delete_rows(i+1)
                        break
                st.rerun()

def tela_relatorios(user):
    st.header("📊 Relatórios de Vendas")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME)
    aba_hist = sh.worksheet("historico")
    df_h = pd.DataFrame(aba_hist.get_all_records())
    
    if df_h.empty:
        st.warning("Nenhum dado no histórico."); return
        
    df_h['caixas'] = pd.to_numeric(df_h['caixas'])
    df_h['peso'] = pd.to_numeric(df_h['peso'])
    
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Total por Produto")
        venda_prod = df_h.groupby('produto')[['caixas', 'peso']].sum()
        st.bar_chart(venda_prod['caixas'])
        st.table(venda_prod)
        
    with c2:
        st.subheader("Total por Cliente")
        venda_cli = df_h.groupby('cliente')[['caixas', 'peso']].sum()
        st.table(venda_cli)

# --- MAIN ---
st.set_page_config(page_title="Sistema Carga", layout="wide")
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
    st.sidebar.title(f"Olá, {user['usuario']}")
    
    op_full = ["Cadastro", "Produtos", "Pedidos", "Gestão de Rotas", "Relatórios", "Gestão de Usuários", "Logs"]
    modulos_usuario = user['modulos'].split(',') if user['modulos'] != 'todos' else op_full
    
    menu = st.sidebar.radio("Navegação", modulos_usuario)
    
    if menu == "Cadastro": tela_cadastro(user)
    elif menu == "Produtos": tela_produtos(user)
    elif menu == "Pedidos": tela_pedidos(user)
    elif menu == "Gestão de Rotas": tela_gestao_rotas(user)
    elif menu == "Relatórios": tela_relatorios(user)
    elif menu == "Gestão de Usuários": tela_usuarios(user)
    elif menu == "Logs":
        df_l = pd.DataFrame(get_gc().open(PLANILHA_NOME).worksheet("log_operacoes").get_all_records())
        st.dataframe(df_l.sort_index(ascending=False), use_container_width=True)
    
    if st.sidebar.button("Sair"):
        st.session_state.usuario_logado = None
        st.rerun()
