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
    
    cols = [c for c in df_matriz.columns.tolist() if c != 'TOTAL CX']
    cols.append('TOTAL CX')
    col_width = 240 / (len(cols) + 1)
    
    pdf.cell(50, 7, "Cliente", 1, 0, 'C')
    for col in cols:
        pdf.cell(col_width, 7, str(col)[:10], 1, 0, 'C')
    pdf.ln()
    
    pdf.set_font("Arial", "", 7)
    for index, row in df_matriz.iterrows():
        label = str(index[1]) if isinstance(index, tuple) else str(index)
        is_total = "TOTAL" in label.upper()
        if is_total:
            pdf.set_fill_color(230, 230, 230)
            pdf.set_font("Arial", "B", 7)
        else:
            pdf.set_font("Arial", "", 7)
            
        pdf.cell(50, 6, label[:30], 1, 0, 'L', is_total)
        for col in cols:
            val = row[col]
            txt = f"{val:.2f}" if "PESO" in label.upper() else str(int(val))
            pdf.cell(col_width, 6, txt, 1, 0, 'C', is_total)
        pdf.ln()
    return bytes(pdf.output())

# --- TELAS ---

def tela_usuarios(user):
    st.header("👥 Gestão de Usuários")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME); aba_user = sh.worksheet("usuarios")
    with st.expander("➕ Configurar Usuário"):
        with st.form("form_usuarios"):
            n_u = st.text_input("Login")
            n_s = st.text_input("Senha", type="password")
            n_l = st.selectbox("Nível", ["total", "visualizacao"])
            mods = ["Cadastro", "Produtos", "Pedidos", "Gestão de Rotas", "Gestão de Usuários", "Logs"]
            sel = [m for m in mods if st.checkbox(m, value=True)]
            if st.form_submit_button("Salvar"):
                df = pd.DataFrame(aba_user.get_all_records())
                if n_u in df['usuario'].values:
                    idx = df[df['usuario'] == n_u].index[0] + 2
                    aba_user.delete_rows(int(idx))
                aba_user.append_row([n_u, n_s, n_l, ",".join(sel)])
                st.success("Usuário salvo!"); st.rerun()
    st.dataframe(pd.DataFrame(aba_user.get_all_records()), use_container_width=True)

def tela_produtos(user):
    st.header("📦 Cadastro de Produtos")
    sh = get_gc().open(PLANILHA_NOME).worksheet("produtos")
    with st.expander("➕ Novo Produto"):
        with st.form("form_produtos"):
            d = st.text_input("Descrição")
            p = st.number_input("Peso Unitário", 0.0, step=0.01)
            t = st.selectbox("Tipo", ["padrão", "variável"])
            if st.form_submit_button("Cadastrar"):
                sh.append_row([d, p, t])
                st.success("Produto cadastrado!"); st.rerun()
    st.dataframe(pd.DataFrame(sh.get_all_records()), use_container_width=True)

def tela_cadastro(user):
    st.header("📝 Gestão de Pedidos")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME)
    aba_ped = sh.worksheet("pedidos"); aba_prod = sh.worksheet("produtos")
    df_ped = pd.DataFrame(aba_ped.get_all_records())
    df_prod = pd.DataFrame(aba_prod.get_all_records())

    t1, t2 = st.tabs(["🚀 Novo Lançamento", "✏️ Editar/Excluir"])
    
    with t1:
        prox_id = int(pd.to_numeric(df_ped['id']).max()) + 1 if not df_ped.empty else 1
        st.subheader(f"Pedido #{prox_id}")
        cliente = st.text_input("Nome do Cliente")
        uf = st.selectbox("Estado", ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"])
        prod_sel = st.selectbox("Selecione o Produto", [""] + df_prod['descricao'].tolist())
        
        if prod_sel:
            dados_p = df_prod[df_prod['descricao'] == prod_sel].iloc[0]
            c1, c2 = st.columns(2)
            qtd = c1.number_input("Caixas", 1, step=1)
            
            if dados_p['tipo'] == "padrão":
                peso_calc = float(qtd * float(dados_p['peso_unitario']))
                peso_f = c2.number_input("Peso (Calculado)", value=peso_calc, disabled=True)
            else:
                peso_f = c2.number_input("Informe o Peso Real", min_value=0.1, step=0.1)
            
            if st.button("✅ Confirmar Lançamento"):
                if cliente:
                    aba_ped.append_row([prox_id, f"{cliente} ({uf})", prod_sel, qtd, peso_f, "pendente"])
                    st.success("Pedido registrado!"); st.rerun()

    with t2:
        df_pend = df_ped[df_ped['status'] == 'pendente']
        if not df_pend.empty:
            sel_idx = st.selectbox("Pedido para alterar", df_pend.index, format_func=lambda x: f"ID {df_pend.loc[x,'id']} - {df_pend.loc[x,'cliente']}")
            ped_atual = df_pend.loc[sel_idx]
            
            with st.form("form_edicao"):
                novo_nome = st.text_input("Editar Cliente/UF", ped_atual['cliente'])
                nova_qtd = st.number_input("Editar Caixas", value=int(ped_atual['caixas']), min_value=1)
                
                c_edit, c_del = st.columns(2)
                if c_edit.form_submit_button("Salvar Alteração"):
                    all_v = aba_ped.get_all_values()
                    for i, r in enumerate(all_v):
                        if str(r[0]) == str(ped_atual['id']) and r[5] == 'pendente':
                            aba_ped.update_cell(i+1, 2, novo_nome)
                            aba_ped.update_cell(i+1, 4, nova_qtd)
                            # Ajusta peso proporcional
                            p_unit = float(ped_atual['peso'])/int(ped_atual['caixas'])
                            aba_ped.update_cell(i+1, 5, nova_qtd * p_unit)
                    st.rerun()
                
                if c_del.form_submit_button("🗑️ EXCLUIR PEDIDO"):
                    all_v = aba_ped.get_all_values()
                    for i, r in enumerate(all_v):
                        if str(r[0]) == str(ped_atual['id']) and r[5] == 'pendente':
                            aba_ped.delete_rows(i+1)
                            st.warning("Pedido removido!"); break
                    st.rerun()

def tela_pedidos(user):
    st.header("🚚 Montagem de Carga")
    sh = get_gc().open(PLANILHA_NOME).worksheet("pedidos")
    df = pd.DataFrame(sh.get_all_records())
    df['caixas'] = pd.to_numeric(df['caixas'], errors='coerce').fillna(0)
    df['peso'] = pd.to_numeric(df['peso'], errors='coerce').fillna(0)
    
    df_pendentes = df[df['status'] == 'pendente'].copy()
    if df_pendentes.empty:
        st.info("Nenhum pedido pendente."); return

    # --- LÓGICA DE FILTRO POR UF RESTAURADA ---
    df_pendentes['uf_extraida'] = df_pendentes['cliente'].str.extract(r'\((.*?)\)')
    ufs_disponiveis = sorted(df_pendentes['uf_extraida'].dropna().unique().tolist())
    
    st.sidebar.subheader("Filtros de Rota")
    f_uf = st.sidebar.multiselect("Filtrar por UF", options=ufs_disponiveis, default=ufs_disponiveis)
    df_filtrado = df_pendentes[df_pendentes['uf_extraida'].isin(f_uf)]

    # Seleção de linhas
    selecao = st.dataframe(df_filtrado.drop(columns=['uf_extraida']), use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row")
    
    if selecao.selection.rows:
        df_sel = df_filtrado.iloc[selecao.selection.rows]
        
        # --- MATRIZ DE CARREGAMENTO RESTAURADA ---
        matriz = df_sel.pivot_table(index=['id', 'cliente'], columns='produto', values='caixas', aggfunc='sum', fill_value=0)
        matriz['TOTAL CX'] = matriz.sum(axis=1)
        
        # Totais
        totais_cx = matriz.sum().to_frame().T
        totais_cx.index = [('', 'TOTAL CAIXAS')]
        
        peso_resumo = df_sel.groupby('produto')['peso'].sum().to_frame().T
        peso_resumo = peso_resumo.reindex(columns=matriz.columns, fill_value=0)
        peso_resumo['TOTAL CX'] = df_sel['peso'].sum()
        peso_resumo.index = [('', 'TOTAL PESO (kg)')]
        
        df_final = pd.concat([matriz, totais_cx, peso_resumo])
        
        st.subheader("📊 Matriz de Carregamento")
        st.dataframe(df_final, use_container_width=True)
        
        c_pdf, c_conf = st.columns(2)
        
        # --- GERAÇÃO DE PDF RESTAURADA ---
        try:
            pdf_bytes = gerar_pdf_rota(df_final)
            c_pdf.download_button("📄 Gerar PDF do Mapa", data=pdf_bytes, file_name=f"mapa_{datetime.now().strftime('%d%m_%H%M')}.pdf", mime="application/pdf", use_container_width=True)
        except Exception as e:
            c_pdf.error(f"Erro no PDF: {e}")

        # Botão de Saída
        if (user['nivel'] == 'total' or user['usuario'] == 'admin') and c_conf.button("🚀 Confirmar Saída de Carga", use_container_width=True):
            ids_v = df_sel['id'].astype(str).tolist()
            all_data = sh.get_all_values()
            for i, lin in enumerate(all_data):
                if str(lin[0]) in ids_v and lin[5] == 'pendente':
                    sh.update_cell(i + 1, 6, "em rota")
            st.success("Carga em rota!"); st.rerun()

def tela_gestao_rotas(user):
    st.header("🔄 Pedidos em Rota")
    sh = get_gc().open(PLANILHA_NOME).worksheet("pedidos")
    df = pd.DataFrame(sh.get_all_records())
    df_rota = df[df['status'] == 'em rota'].copy()
    
    if df_rota.empty:
        st.info("Nenhuma carga em rota."); return
        
    selecao = st.dataframe(df_rota, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row")
    
    if selecao.selection.rows:
        df_sel = df_rota.iloc[selecao.selection.rows]
        c1, c2 = st.columns(2)
        
        with c1.expander("❌ Retornar ao Pátio"):
            if st.button("Confirmar Retorno"):
                all_v = sh.get_all_values()
                ids_sel = df_sel['id'].astype(str).tolist()
                for i, r in enumerate(all_v):
                    if str(r[0]) in ids_sel and r[5] == 'em rota':
                        sh.update_cell(i+1, 6, "pendente")
                st.rerun()
                
        with c2.expander("📉 Saída Parcial"):
            for _, r in df_sel.iterrows():
                q_saiu = st.number_input(f"Qtd Entregue #{r['id']}", 0, int(r['caixas']), int(r['caixas']), key=f"p_{r['id']}")
                if st.button(f"Baixa Parcial #{r['id']}"):
                    p_unit = float(r['peso'])/int(r['caixas'])
                    all_v = sh.get_all_values()
                    for i, lin in enumerate(all_v):
                        if str(lin[0]) == str(r['id']) and lin[5] == 'em rota':
                            sh.update_cell(i+1, 6, "entregue")
                            sh.update_cell(i+1, 4, q_saiu)
                            sh.update_cell(i+1, 5, q_saiu * p_unit)
                            sobra = int(r['caixas']) - q_saiu
                            if sobra > 0:
                                sh.append_row([r['id'], r['cliente'], r['produto'], sobra, sobra * p_unit, "pendente"])
                    st.rerun()

# --- MAIN ---
st.set_page_config(page_title="Gestão de Carga", layout="wide")
if 'usuario_logado' not in st.session_state: st.session_state.usuario_logado = None

if st.session_state.usuario_logado is None:
    st.title("Acesso ao Sistema")
    with st.form("login"):
        u = st.text_input("Usuário")
        s = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            d = login_usuario(u, s)
            if d: st.session_state.usuario_logado = d; st.rerun()
            else: st.error("Acesso negado")
else:
    user = st.session_state.usuario_logado
    st.sidebar.title(f"👤 {user['usuario']}")
    opcoes = ["Cadastro", "Produtos", "Pedidos", "Gestão de Rotas", "Gestão de Usuários", "Logs"]
    menu = st.sidebar.radio("Navegação", opcoes if user['modulos'] == 'todos' else user['modulos'].split(','))
    
    if menu == "Cadastro": tela_cadastro(user)
    elif menu == "Produtos": tela_produtos(user)
    elif menu == "Pedidos": tela_pedidos(user)
    elif menu == "Gestão de Rotas": tela_gestao_rotas(user)
    elif menu == "Gestão de Usuários": tela_usuarios(user)
    elif menu == "Logs":
        log_data = get_gc().open(PLANILHA_NOME).worksheet("log_operacoes").get_all_records()
        st.dataframe(pd.DataFrame(log_data).sort_index(ascending=False), use_container_width=True)
    
    if st.sidebar.button("Sair"):
        st.session_state.usuario_logado = None
        st.rerun()
