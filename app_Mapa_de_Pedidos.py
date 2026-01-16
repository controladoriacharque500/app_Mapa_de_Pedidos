import streamlit as st
import pandas as pd
from datetime import datetime
import gspread
from fpdf import FPDF
import io

# --- CONFIGURAÇÕES E CONEXÃO ---
PLANILHA_NOME = "Mapa_de_Pedidos" 

def get_gc():
    try:
        if "gcp_service_account" in st.secrets:
            secrets_dict = dict(st.secrets["gcp_service_account"])
            # Limpeza da chave privada para evitar erros de formatação
            pk = secrets_dict["private_key"].replace('\\n', '\n')
            if not pk.startswith("-----BEGIN"):
                pk = f"-----BEGIN PRIVATE KEY-----\n{pk}\n-----END PRIVATE KEY-----\n"
            secrets_dict["private_key"] = pk
            return gspread.service_account_from_dict(secrets_dict)
        return gspread.service_account(filename="credentials.json")
    except Exception as e:
        st.error(f"Erro de conexão com o Google Sheets: {e}")
        return None

# --- FUNÇÕES DE APOIO ---
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

def gerar_pdf_rota(df_matriz):
    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, f"MAPA DE CARREGAMENTO - {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True, align='C')
    pdf.ln(5)
    
    pdf.set_font("Arial", "B", 8)
    cols = df_matriz.columns.tolist()
    # Largura das colunas
    pdf.cell(60, 8, "Cliente", 1, 0, 'C')
    for col in cols:
        pdf.cell(25, 8, str(col)[:10], 1, 0, 'C')
    pdf.ln()
    
    pdf.set_font("Arial", "", 8)
    for index, row in df_matriz.iterrows():
        pdf.cell(60, 7, str(index)[:35], 1, 0, 'L')
        for col in cols:
            pdf.cell(25, 7, str(row[col]), 1, 0, 'C')
        pdf.ln()
    return bytes(pdf.output())

# --- TELAS DO SISTEMA ---

def tela_cadastro(user):
    st.header("📝 Gestão de Pedidos")
    gc = get_gc()
    sh = gc.open(PLANILHA_NOME)
    aba_pedidos = sh.worksheet("pedidos")
    aba_produtos = sh.worksheet("produtos")
    
    df_ped = pd.DataFrame(aba_pedidos.get_all_records())
    df_prod = pd.DataFrame(aba_produtos.get_all_records())

    tab1, tab2 = st.tabs(["🚀 Novo Lançamento", "✏️ Editar / Excluir"])
    
    with tab1:
        with st.form("form_novo_pedido"):
            c1, c2 = st.columns(2)
            cliente = c1.text_input("Nome do Cliente")
            uf = c2.selectbox("UF", ["RJ", "SP", "MG", "ES", "BA", "PR", "SC", "RS", "GO", "MT", "MS", "AL", "CE", "MA", "PB", "PE", "PI", "RN", "SE", "AC", "AM", "AP", "PA", "RO", "RR", "TO", "DF"])
            
            lista_prods = df_prod['descricao'].tolist() if not df_prod.empty else []
            prod_sel = st.selectbox("Selecione o Produto", lista_prods)
            qtd = st.number_input("Quantidade de Caixas", min_value=1, step=1)
            
            if st.form_submit_button("Confirmar Lançamento"):
                if cliente and prod_sel:
                    # Cálculo de ID robusto
                    if df_ped.empty or 'id' not in df_ped.columns: novo_id = 1
                    else: novo_id = int(pd.to_numeric(df_ped['id'], errors='coerce').max() or 0) + 1
                    
                    peso_u = float(df_prod[df_prod['descricao'] == prod_sel]['peso_unitario'].values[0])
                    aba_pedidos.append_row([novo_id, f"{cliente} ({uf})", prod_sel, qtd, round(qtd * peso_u, 2), "pendente"])
                    st.success(f"Pedido #{novo_id} registrado com sucesso!")
                    st.rerun()
                else:
                    st.warning("Preencha todos os campos.")

def tela_pedidos(user):
    st.header("🚚 Montagem de Carga")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME); aba_pedidos = sh.worksheet("pedidos")
    df = pd.DataFrame(aba_pedidos.get_all_records())
    
    df_pend = df[df['status'] == 'pendente'].copy() if not df.empty else pd.DataFrame()
    
    if df_pend.empty:
        st.info("Não há pedidos pendentes para montagem de carga.")
        return

    # Extração de UF para filtro
    df_pend['uf_label'] = df_pend['cliente'].str.extract(r'\((.*?)\)')
    ufs = sorted(df_pend['uf_label'].dropna().unique())
    filtro_uf = st.multiselect("Filtrar Carga por Estado (UF):", ufs, default=ufs)
    df_filtrado = df_pend[df_pend['uf_label'].isin(filtro_uf)]

    st.write("Selecione os pedidos que sairão no caminhão:")
    selecao = st.dataframe(
        df_filtrado.drop(columns=['uf_label']), 
        use_container_width=True, 
        hide_index=True, 
        on_select="rerun", 
        selection_mode="multi-row"
    )
    
    if selecao.selection.rows:
        df_sel = df_filtrado.iloc[selecao.selection.rows]
        
        # Gerar Matriz de Carregamento (Pivot Table)
        try:
            matriz = df_sel.pivot_table(index='cliente', columns='produto', values='caixas', aggfunc='sum', fill_value=0)
            matriz.loc['TOTAL GERAL'] = matriz.sum()
            
            st.subheader("📊 Matriz de Carregamento")
            st.table(matriz) # st.table evita erros de formatação do st.dataframe
            
            c1, c2 = st.columns(2)
            if c1.button("🚀 Confirmar Saída em Rota", use_container_width=True):
                ids_em_rota = df_sel['id'].astype(str).tolist()
                all_vals = aba_pedidos.get_all_values()
                for i, row in enumerate(all_vals):
                    if str(row[0]) in ids_em_rota:
                        aba_pedidos.update_cell(i + 1, 6, "em rota")
                st.success("Status atualizado para 'em rota'!")
                st.rerun()
                
            pdf_b = gerar_pdf_rota(matriz)
            c2.download_button("📄 Baixar Mapa (PDF)", pdf_b, "mapa_carga.pdf", use_container_width=True)
        except Exception as e:
            st.error(f"Erro ao gerar matriz: {e}")

def tela_gestao_rotas(user):
    st.header("🔄 Gestão de Pedidos em Rota")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME)
    aba_pedidos = sh.worksheet("pedidos"); aba_hist = sh.worksheet("historico")
    
    df = pd.DataFrame(aba_pedidos.get_all_records())
    df_rota = df[df['status'] == 'em rota'].copy() if not df.empty else pd.DataFrame()
    
    if df_rota.empty:
        st.info("Nenhum caminhão em rota no momento.")
        return

    st.write("Selecione o pedido para confirmar a entrega:")
    selecao = st.dataframe(df_rota, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row")
    
    if selecao.selection.rows:
        df_sel = df_rota.iloc[selecao.selection.rows]
        
        for _, r in df_sel.iterrows():
            with st.expander(f"📦 Confirmar Baixa: {r['cliente']} - {r['produto']}", expanded=True):
                qtd_entregue = st.number_input(f"Qtd Entregue (Pedido #{r['id']})", 0, int(r['caixas']), int(r['caixas']), key=f"ent_{r['id']}_{r['produto']}")
                
                if st.button(f"Confirmar Entrega #{r['id']}", key=f"btn_{r['id']}_{r['produto']}"):
                    # 1. Registrar no Histórico
                    aba_hist.append_row([
                        r['id'], r['cliente'], r['produto'], qtd_entregue, 
                        round(float(r['peso']) * (qtd_entregue / r['caixas']), 2), 
                        "entregue", datetime.now().strftime("%d/%m/%Y")
                    ])
                    
                    # 2. Atualizar ou Remover da aba Pedidos
                    sobra = int(r['caixas']) - qtd_entregue
                    data_atual = aba_pedidos.get_all_values()
                    
                    for i, linha in enumerate(data_atual):
                        # Validação dupla: ID e Produto (para não errar em pedidos com múltiplos itens)
                        if str(linha[0]) == str(r['id']) and linha[2] == r['produto']:
                            if sobra > 0:
                                p_unit = float(linha[4]) / int(linha[3])
                                aba_pedidos.update_cell(i+1, 4, sobra)
                                aba_pedidos.update_cell(i+1, 5, round(sobra * p_unit, 2))
                                aba_pedidos.update_cell(i+1, 6, "pendente")
                            else:
                                aba_pedidos.delete_rows(i+1)
                            break
                    st.success("Baixa realizada!")
                    st.rerun()

# --- NAVEGAÇÃO PRINCIPAL ---
st.set_page_config(page_title="Sistema de Carga", layout="wide")

if 'user' not in st.session_state:
    st.session_state.user = None

if st.session_state.user is None:
    st.title("🔐 Login de Acesso")
    with st.form("login_form"):
        u = st.text_input("Usuário")
        s = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            dados = login_usuario(u, s)
            if dados:
                st.session_state.user = dados
                st.rerun()
            else: st.error("Usuário ou senha incorretos.")
else:
    # --- BARRA LATERAL (RESTAURADA) ---
    st.sidebar.title(f"👋 Olá, {st.session_state.user['usuario']}!")
    
    # Define módulos por permissão
    modulos_str = st.session_state.user.get('modulos', "Cadastro,Pedidos,Gestão de Rotas")
    lista_modulos = [m.strip() for m in modulos_str.split(',')]
    
    escolha = st.sidebar.radio("Navegação:", lista_modulos)
    
    if st.sidebar.button("Sair / Logout"):
        st.session_state.user = None
        st.rerun()

    # --- ROTEAMENTO ---
    if escolha == "Cadastro": tela_cadastro(st.session_state.user)
    elif escolha == "Pedidos": tela_pedidos(st.session_state.user)
    elif escolha == "Gestão de Rotas": tela_gestao_rotas(st.session_state.user)
    elif escolha == "Relatórios":
        st.header("📊 Relatório de Entregas")
        df_h = pd.DataFrame(get_gc().open(PLANILHA_NOME).worksheet("historico").get_all_records())
        st.dataframe(df_h, use_container_width=True)
