import streamlit as st
import pandas as pd
from datetime import datetime
import gspread
from fpdf import FPDF

# --- CONFIGURAÇÕES E CONEXÃO ---
PLANILHA_NOME = "Mapa_de_Pedidos" 

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
        return gspread.service_account(filename="credentials.json")
    except Exception as e:
        st.error(f"Erro de Conexão: {e}")
        return None

# --- FUNÇÕES DE APOIO ---
def limpar_dados(df):
    """Proteção contra o erro de conversão int64 (Strings vazias)"""
    df['id'] = pd.to_numeric(df['id'], errors='coerce').fillna(0).astype(int)
    df['caixas'] = pd.to_numeric(df['caixas'], errors='coerce').fillna(0).astype(int)
    df['peso'] = pd.to_numeric(df['peso'], errors='coerce').fillna(0.0)
    return df[df['id'] > 0] # Remove linhas fantasmas

def gerar_pdf_rota(df_matriz):
    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, f"MAPA DE CARREGAMENTO - {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True, align='C')
    pdf.ln(5)
    
    cols = [c for c in df_matriz.columns.tolist() if c != 'TOTAL CX']
    cols.append('TOTAL CX')
    col_width = 230 / (len(cols) + 1)
    
    pdf.set_font("Arial", "B", 8)
    pdf.cell(50, 7, "Cliente", 1, 0, 'C')
    for col in cols:
        pdf.cell(col_width, 7, str(col)[:12], 1, 0, 'C')
    pdf.ln()
    
    pdf.set_font("Arial", "", 8)
    for index, row in df_matriz.iterrows():
        label = str(index[1]) if isinstance(index, tuple) else str(index)
        is_total = "TOTAL" in label.upper()
        if is_total: pdf.set_fill_color(230, 230, 230)
        
        pdf.cell(50, 6, label[:30], 1, 0, 'L', is_total)
        for col in cols:
            val = row[col]
            txt = f"{val:.1f}" if "PESO" in label.upper() else str(int(val))
            pdf.cell(col_width, 6, txt, 1, 0, 'C', is_total)
        pdf.ln()
    return bytes(pdf.output())

# --- TELAS ---

def tela_cadastro(user):
    st.header("📝 Gestão de Pedidos")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME)
    aba_ped = sh.worksheet("pedidos"); aba_prod = sh.worksheet("produtos")
    
    df_ped = limpar_dados(pd.DataFrame(aba_ped.get_all_records()))
    df_prod = pd.DataFrame(aba_prod.get_all_records())

    t1, t2 = st.tabs(["🚀 Novo Lançamento", "✏️ Editar/Excluir"])
    
    with t1:
        with st.form("form_novo_pedido", clear_on_submit=True):
            prox_id = int(df_ped['id'].max() + 1) if not df_ped.empty else 1
            st.subheader(f"Pedido #{prox_id}")
            cliente = st.text_input("Nome do Cliente")
            uf = st.selectbox("UF", ["RJ", "SP", "MG", "ES", "PR", "SC", "RS", "MT", "MS", "GO", "DF", "BA", "PE", "CE", "AL"])
            produto = st.selectbox("Produto", df_prod['descricao'].tolist())
            qtd = st.number_input("Quantidade de Caixas", min_value=1, step=1)
            
            if st.form_submit_button("✅ Salvar Pedido"):
                if cliente:
                    p_info = df_prod[df_prod['descricao'] == produto].iloc[0]
                    peso_total = qtd * float(p_info['peso_unitario'])
                    aba_ped.append_row([prox_id, f"{cliente} ({uf})", produto, qtd, peso_total, "pendente"])
                    st.success("Pedido Salvo!"); st.rerun()

def tela_pedidos(user):
    st.header("🚚 Montagem de Carga")
    sh = get_gc().open(PLANILHA_NOME).worksheet("pedidos")
    df = limpar_dados(pd.DataFrame(sh.get_all_records()))
    df_pend = df[df['status'] == 'pendente'].copy()
    
    if df_pend.empty:
        st.info("Não há pedidos pendentes."); return

    # Filtro de UF
    df_pend['uf_filt'] = df_pend['cliente'].str.extract(r'\((.*?)\)')
    lista_ufs = sorted(df_pend['uf_filt'].dropna().unique().tolist())
    filtro = st.sidebar.multiselect("Filtrar por UF", lista_ufs, default=lista_ufs)
    df_filtrado = df_pend[df_pend['uf_filt'].isin(filtro)]

    sel = st.dataframe(df_filtrado.drop(columns=['uf_filt']), use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row")
    
    if sel.selection.rows:
        df_sel = df_filtrado.iloc[sel.selection.rows].copy()
        try:
            # Matriz Segura: ID + Cliente como index para evitar o erro de duplicidade
            matriz = df_sel.pivot_table(index=['id', 'cliente'], columns='produto', values='caixas', aggfunc='sum', fill_value=0)
            matriz['TOTAL CX'] = matriz.sum(axis=1)
            
            # Totais inferiores
            t_cx = matriz.sum().to_frame().T
            t_cx.index = [('', 'TOTAL CAIXAS')]
            t_peso = df_sel.groupby('produto')['peso'].sum().to_frame().T
            t_peso = t_peso.reindex(columns=matriz.columns, fill_value=0)
            t_peso['TOTAL CX'] = df_sel['peso'].sum()
            t_peso.index = [('', 'TOTAL PESO (kg)')]
            
            df_final = pd.concat([matriz, t_cx, t_peso])
            st.subheader("📊 Matriz de Carregamento")
            st.dataframe(df_final, use_container_width=True)
            
            col1, col2 = st.columns(2)
            col1.download_button("📄 Baixar PDF", gerar_pdf_rota(df_final), f"mapa_{datetime.now().strftime('%d%m_%H%M')}.pdf")
            
            if col2.button("🚀 Enviar para Rota"):
                all_v = sh.get_all_values()
                ids_confirmar = df_sel['id'].astype(str).tolist()
                for i, row in enumerate(all_v):
                    if str(row[0]) in ids_confirmar and row[5] == 'pendente':
                        sh.update_cell(i+1, 6, "em rota")
                st.success("Carga em Rota!"); st.rerun()
        except Exception as e:
            st.error(f"Erro ao processar matriz: {e}")

def tela_gestao_rotas(user):
    st.header("🔄 Pedidos em Rota")
    sh = get_gc().open(PLANILHA_NOME).worksheet("pedidos")
    df = limpar_dados(pd.DataFrame(sh.get_all_records()))
    df_rota = df[df['status'] == 'em rota'].copy()
    
    if df_rota.empty:
        st.info("Nenhuma carga em rota."); return
        
    sel = st.dataframe(df_rota, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row")
    
    if sel.selection.rows:
        df_sel = df_rota.iloc[sel.selection.rows]
        with st.expander("📉 Realizar Baixa Parcial/Total"):
            for _, r in df_sel.iterrows():
                with st.form(key=f"baixa_{_}_{r['id']}"):
                    st.write(f"**ID {r['id']} - {r['cliente']}** ({r['produto']})")
                    qtd_entregue = st.number_input("Qtd Entregue", 0, int(r['caixas']), int(r['caixas']))
                    if st.form_submit_button("Confirmar Entrega"):
                        p_u = float(r['peso'])/int(r['caixas'])
                        all_v = sh.get_all_values()
                        for i, lin in enumerate(all_v):
                            if str(lin[0]) == str(r['id']) and lin[2] == r['produto'] and lin[5] == 'em rota':
                                # Atualiza para Entregue
                                sh.update_cell(i+1, 6, "entregue")
                                sh.update_cell(i+1, 4, qtd_entregue)
                                sh.update_cell(i+1, 5, qtd_entregue * p_u)
                                # Se sobrou, gera novo pendente
                                sobra = int(r['caixas']) - qtd_entregue
                                if sobra > 0:
                                    sh.append_row([r['id'], r['cliente'], r['produto'], sobra, sobra * p_u, "pendente"])
                                break
                        st.rerun()

# --- LOGIN E MENU ---
st.set_page_config(page_title="Sistema Carga", layout="wide")
if 'logado' not in st.session_state: st.session_state.logado = False

if not st.session_state.logado:
    with st.form("login"):
        u = st.text_input("Usuário"); s = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            if u == "admin" and s == "123": # Altere aqui
                st.session_state.logado = True; st.rerun()
            else: st.error("Incorreto")
else:
    menu = st.sidebar.radio("Menu", ["Pedidos", "Cadastro", "Gestão de Rotas"])
    if menu == "Pedidos": tela_pedidos(None)
    elif menu == "Cadastro": tela_cadastro(None)
    elif menu == "Gestão de Rotas": tela_gestao_rotas(None)
    
    if st.sidebar.button("Sair"):
        st.session_state.logado = False; st.rerun()
