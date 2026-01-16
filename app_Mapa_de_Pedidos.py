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
    
    # Organização das colunas para o PDF
    cols = [c for c in df_matriz.columns.tolist() if c != 'TOTAL CX']
    cols.append('TOTAL CX')
    col_width = 240 / (len(cols) + 1)
    
    pdf.cell(50, 7, "Cliente", 1, 0, 'C')
    for col in cols:
        pdf.cell(col_width, 7, str(col)[:10], 1, 0, 'C')
    pdf.ln()
    
    pdf.set_font("Arial", "", 7)
    for index, row in df_matriz.iterrows():
        # Trata o index que pode ser multi-nível ou string
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
        with st.form("form_usuarios_fix"):
            n_u = st.text_input("Login")
            n_s = st.text_input("Senha", type="password")
            n_l = st.selectbox("Nível", ["total", "visualizacao"])
            mods = ["Cadastro", "Produtos", "Pedidos", "Gestão de Rotas", "Gestão de Usuários", "Logs"]
            sel = [m for m in mods if st.checkbox(m, value=True, key=f"mod_{m}")]
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
        with st.form("form_prod_fix"):
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
        with st.form("form_lancar_fix"):
            st.subheader(f"Pedido #{prox_id}")
            cliente = st.text_input("Nome do Cliente")
            uf = st.selectbox("Estado", ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"])
            prod_sel = st.selectbox("Produto", [""] + df_prod['descricao'].tolist())
            qtd = st.number_input("Caixas", 1, step=1)
            
            if st.form_submit_button("✅ Confirmar Lançamento"):
                if cliente and prod_sel:
                    dp = df_prod[df_prod['descricao'] == prod_sel].iloc[0]
                    peso_f = float(qtd * float(dp['peso_unitario'])) if dp['tipo'] == "padrão" else 1.0
                    aba_ped.append_row([prox_id, f"{cliente} ({uf})", prod_sel, qtd, peso_f, "pendente"])
                    st.success("Pedido registrado!"); st.rerun()

    with t2:
        df_pend = df_ped[df_ped['status'] == 'pendente']
        if not df_pend.empty:
            sel_idx = st.selectbox("Pedido", df_pend.index, format_func=lambda x: f"ID {df_pend.loc[x,'id']} - {df_pend.loc[x,'cliente']}")
            with st.form("form_edit_fix"):
                ped = df_pend.loc[sel_idx]
                n_cli = st.text_input("Cliente/UF", ped['cliente'])
                n_qtd = st.number_input("Caixas", value=int(ped['caixas']), min_value=1)
                if st.form_submit_button("Salvar Alterações"):
                    all_v = aba_ped.get_all_values()
                    for i, r in enumerate(all_v):
                        if str(r[0]) == str(ped['id']) and r[5] == 'pendente':
                            aba_ped.update_cell(i+1, 2, n_cli)
                            aba_ped.update_cell(i+1, 4, n_qtd)
                            aba_ped.update_cell(i+1, 5, n_qtd * (float(ped['peso'])/int(ped['caixas'])))
                    st.success("Atualizado!"); st.rerun()

def tela_pedidos(user):
    st.header("🚚 Montagem de Carga")
    sh = get_gc().open(PLANILHA_NOME).worksheet("pedidos")
    df = pd.DataFrame(sh.get_all_records())
    df_pend = df[df['status'] == 'pendente'].copy()
    
    if df_pend.empty: st.info("Nada pendente."); return

    # FILTRO UF RESTAURADO
    df_pend['uf'] = df_pend['cliente'].str.extract(r'\((.*?)\)')
    ufs = sorted(df_pend['uf'].dropna().unique().tolist())
    f_uf = st.sidebar.multiselect("Filtrar por UF", ufs, default=ufs)
    df_filtrado = df_pend[df_pend['uf'].isin(f_uf)]

    sel = st.dataframe(df_filtrado.drop(columns=['uf']), use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row")
    
    if sel.selection.rows:
        df_sel = df_filtrado.iloc[sel.selection.rows].copy()
        
        # MATRIZ RESTAURADA COM CORREÇÃO DE ID DUPLICADO
        # Criamos um índice único combinando ID e Cliente para não dar erro no pivot
        df_sel['key_unique'] = df_sel['id'].astype(str) + " - " + df_sel['cliente']
        
        try:
            matriz = df_sel.pivot_table(index=['id', 'cliente'], columns='produto', values='caixas', aggfunc='sum', fill_value=0)
            matriz['TOTAL CX'] = matriz.sum(axis=1)
            
            # Totais
            t_cx = matriz.sum().to_frame().T
            t_cx.index = [('', 'TOTAL CAIXAS')]
            t_peso = df_sel.groupby('produto')['peso'].sum().to_frame().T
            t_peso = t_peso.reindex(columns=matriz.columns, fill_value=0)
            t_peso['TOTAL CX'] = df_sel['peso'].sum()
            t_peso.index = [('', 'TOTAL PESO (kg)')]
            
            df_final = pd.concat([matriz, t_cx, t_peso])
            st.subheader("📊 Matriz de Carregamento")
            st.dataframe(df_final, use_container_width=True)
            
            c1, c2 = st.columns(2)
            c1.download_button("📄 Gerar PDF do Mapa", gerar_pdf_rota(df_final), f"mapa_{datetime.now().strftime('%H%M')}.pdf", "application/pdf")
            
            if (user['nivel'] == 'total' or user['usuario'] == 'admin') and c2.button("🚀 Confirmar Saída para Rota"):
                ids = df_sel['id'].astype(str).tolist()
                all_d = sh.get_all_values()
                for i, lin in enumerate(all_d):
                    if str(lin[0]) in ids and lin[5] == 'pendente':
                        sh.update_cell(i + 1, 6, "em rota")
                st.success("Carga confirmada!"); st.rerun()
        except Exception as e: st.error(f"Erro ao gerar matriz: {e}")

def tela_gestao_rotas(user):
    st.header("🔄 Pedidos em Rota")
    sh = get_gc().open(PLANILHA_NOME).worksheet("pedidos")
    df = pd.DataFrame(sh.get_all_records())
    df_rota = df[df['status'] == 'em rota'].copy()
    
    if df_rota.empty: st.info("Nada em rota."); return
    
    sel = st.dataframe(df_rota, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row")
    if sel.selection.rows:
        df_sel = df_rota.iloc[sel.selection.rows]
        c1, c2 = st.columns(2)
        with c1.expander("❌ Retornar ao Pendente"):
            if st.button("Confirmar Retorno"):
                ids = df_sel['id'].astype(str).tolist()
                all_d = sh.get_all_values()
                for i, r in enumerate(all_d):
                    if str(r[0]) in ids and r[5] == 'em rota':
                        sh.update_cell(i+1, 6, "pendente")
                st.rerun()
        with c2.expander("📉 Saída Parcial (Solução ID Duplicado)"):
            for _, r in df_sel.iterrows():
                # Cada item tem seu próprio formulário para evitar erros de submissão
                with st.form(key=f"baixa_{r['id']}_{_}"):
                    st.write(f"ID {r['id']} - {r['cliente']}")
                    qtd_e = st.number_input("Qtd Entregue", 0, int(r['caixas']), int(r['caixas']))
                    if st.form_submit_button("Dar Baixa"):
                        p_u = float(r['peso'])/int(r['caixas'])
                        all_v = sh.get_all_values()
                        for i, lin in enumerate(all_v):
                            # BUSCA SEGURA: ID + Status + Produto para evitar duplicados
                            if str(lin[0]) == str(r['id']) and lin[5] == 'em rota' and lin[2] == r['produto']:
                                sh.update_cell(i+1, 6, "entregue")
                                sh.update_cell(i+1, 4, qtd_e)
                                sh.update_cell(i+1, 5, qtd_e * p_u)
                                sobra = int(r['caixas']) - qtd_e
                                if sobra > 0:
                                    sh.append_row([r['id'], r['cliente'], r['produto'], sobra, sobra * p_u, "pendente"])
                        st.success("Baixa realizada!"); st.rerun()

# --- MAIN ---
st.set_page_config(page_title="Sistema Carga", layout="wide")
if 'usuario_logado' not in st.session_state: st.session_state.usuario_logado = None

if st.session_state.usuario_logado is None:
    st.title("Login")
    with st.form("login_fix"):
        u = st.text_input("Usuário"); s = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            d = login_usuario(u, s)
            if d: st.session_state.usuario_logado = d; st.rerun()
            else: st.error("Acesso negado")
else:
    u = st.session_state.usuario_logado
    st.sidebar.title(f"👤 {u['usuario']}")
    op = ["Cadastro", "Produtos", "Pedidos", "Gestão de Rotas", "Gestão de Usuários", "Logs"]
    menu = st.sidebar.radio("Menu", op if u['modulos'] == 'todos' else u['modulos'].split(','))
    if menu == "Cadastro": tela_cadastro(u)
    elif menu == "Produtos": tela_produtos(u)
    elif menu == "Pedidos": tela_pedidos(u)
    elif menu == "Gestão de Rotas": tela_gestao_rotas(u)
    elif menu == "Gestão de Usuários": tela_usuarios(u)
    if st.sidebar.button("Sair"): st.session_state.usuario_logado = None; st.rerun()
