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
        st.error(f"Erro na conexão com Google Sheets: {e}")
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
        fill = "TOTAL" in label.upper()
        if fill: pdf.set_fill_color(230, 230, 230)
        pdf.cell(50, 6, label[:30], 1, 0, 'L', fill)
        for col in cols:
            val = row[col]
            txt = f"{val:.2f}" if "PESO" in label.upper() else str(int(val))
            pdf.cell(col_width, 6, txt, 1, 0, 'C', fill)
        pdf.ln()
    return bytes(pdf.output())

# --- TELAS DO SISTEMA ---

def tela_usuarios(user):
    st.header("👥 Gestão de Usuários")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME); aba_user = sh.worksheet("usuarios")
    with st.expander("➕ Configurar Usuário"):
        with st.form("form_u_fix"):
            n_u = st.text_input("Login")
            n_s = st.text_input("Senha")
            n_l = st.selectbox("Nível", ["total", "visualizacao"])
            mods = ["Cadastro", "Produtos", "Pedidos", "Gestão de Rotas", "Gestão de Usuários", "Logs"]
            sel_mods = [m for m in mods if st.checkbox(m, value=True, key=f"mod_{m}")]
            submit = st.form_submit_button("Salvar Usuário")
            if submit:
                df = pd.DataFrame(aba_user.get_all_records())
                if n_u in df['usuario'].values: aba_user.delete_rows(int(df[df['usuario']==n_u].index[0]+2))
                aba_user.append_row([n_u, n_s, n_l, ",".join(sel_mods)])
                st.success("Usuário salvo com sucesso!"); st.rerun()
    st.dataframe(pd.DataFrame(aba_user.get_all_records()), use_container_width=True)

def tela_produtos(user):
    st.header("📦 Produtos")
    sh = get_gc().open(PLANILHA_NOME).worksheet("produtos")
    with st.expander("Novo Produto"):
        with st.form("form_p_fix"):
            d = st.text_input("Descrição")
            p = st.number_input("Peso Unitário", 0.0)
            t = st.selectbox("Tipo", ["padrão", "variável"])
            if st.form_submit_button("Cadastrar Produto"):
                sh.append_row([d, p, t])
                st.success("Produto cadastrado!"); st.rerun()
    st.dataframe(pd.DataFrame(sh.get_all_records()), use_container_width=True)

def tela_cadastro(user):
    st.header("📝 Gestão de Pedidos")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME)
    aba_ped = sh.worksheet("pedidos"); aba_prod = sh.worksheet("produtos")
    df_ped = pd.DataFrame(aba_ped.get_all_records())
    df_prod = pd.DataFrame(aba_prod.get_all_records())

    t1, t2 = st.tabs(["🚀 Lançar", "✏️ Editar/Excluir"])
    
    with t1:
        prox_id = int(pd.to_numeric(df_ped['id']).max()) + 1 if not df_ped.empty else 1
        with st.form("form_lancar_fix"):
            cli = st.text_input("Cliente")
            uf = st.selectbox("UF", ["RJ", "SP", "MG", "ES", "PR", "SC", "RS", "PE", "BA", "CE", "DF", "GO", "MT", "MS", "PA", "PB", "PI", "RN", "RO", "RR", "SE", "TO"])
            prod = st.selectbox("Produto", [""] + df_prod['descricao'].tolist())
            q = st.number_input("Caixas", 1)
            # Cálculo de peso simplificado dentro do form para evitar erros de renderização
            if st.form_submit_button("Confirmar Lançamento"):
                if cli and prod:
                    dp = df_prod[df_prod['descricao']==prod].iloc[0]
                    p_final = float(q * dp['peso_unitario']) if dp['tipo'] == "padrão" else 1.0 # Peso padrão 1 para variável se não informado
                    aba_ped.append_row([prox_id, f"{cli} ({uf})", prod, q, p_final, "pendente"])
                    st.success("Pedido lançado!"); st.rerun()
                else: st.error("Preencha Cliente e Produto.")

    with t2:
        df_pend = df_ped[df_ped['status']=='pendente']
        if not df_pend.empty:
            s_idx = st.selectbox("Escolha o pedido", df_pend.index, format_func=lambda x: f"#{df_pend.loc[x,'id']} - {df_pend.loc[x,'cliente']}")
            with st.form("form_edit_fix"):
                n_c = st.text_input("Nome/UF", df_pend.loc[s_idx, 'cliente'])
                n_q = st.number_input("Qtd Caixas", value=int(df_pend.loc[s_idx, 'caixas']))
                c_e, c_d = st.columns(2)
                if c_e.form_submit_button("✅ Salvar"):
                    all_v = aba_ped.get_all_values()
                    for i, r in enumerate(all_v):
                        if str(r[0]) == str(df_pend.loc[s_idx, 'id']) and r[5] == 'pendente':
                            aba_ped.update_cell(i+1, 2, n_c)
                            aba_ped.update_cell(i+1, 4, n_q)
                            # Recalcula peso
                            peso_unit = float(df_pend.loc[s_idx,'peso'])/int(df_pend.loc[s_idx,'caixas'])
                            aba_ped.update_cell(i+1, 5, n_q * peso_unit)
                    st.rerun()
                if c_d.form_submit_button("🗑️ Excluir"):
                    all_v = aba_ped.get_all_values()
                    for i, r in enumerate(all_v):
                        if str(r[0]) == str(df_pend.loc[s_idx, 'id']) and r[5] == 'pendente':
                            aba_ped.delete_rows(i+1); break
                    st.rerun()

def tela_pedidos(user):
    st.header("🚚 Montagem de Carga")
    sh = get_gc().open(PLANILHA_NOME).worksheet("pedidos")
    df = pd.DataFrame(sh.get_all_records())
    df_p = df[df['status']=='pendente'].copy()
    if df_p.empty: st.info("Nada pendente."); return
    
    sel = st.dataframe(df_p, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row")
    
    if sel.selection.rows:
        df_sel = df_p.iloc[sel.selection.rows]
        try:
            # Geração da Matriz com tratamento de erro
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
            
            c1, c2 = st.columns(2)
            pdf = gerar_pdf_rota(df_final)
            c1.download_button("📄 Baixar PDF", pdf, f"mapa_{datetime.now().strftime('%H%M')}.pdf", "application/pdf")
            
            if (user['nivel'] == 'total' or user['usuario'] == 'admin') and c2.button("🚀 Confirmar Saída"):
                ids_sel = df_sel['id'].astype(str).tolist()
                all_rows = sh.get_all_values()
                for i, row in enumerate(all_rows):
                    if str(row[0]) in ids_sel and row[5] == 'pendente':
                        sh.update_cell(i + 1, 6, "em rota")
                st.success("Pedidos enviados para rota!"); st.rerun()
        except Exception as e:
            st.error(f"Erro ao gerar matriz: Selecione itens válidos. (Erro: {e})")

def tela_gestao_rotas(user):
    st.header("🔄 Gestão de Rotas")
    sh = get_gc().open(PLANILHA_NOME).worksheet("pedidos")
    df = pd.DataFrame(sh.get_all_records())
    df_r = df[df['status']=='em rota'].copy()
    if df_r.empty: st.info("Nada em rota."); return
    
    sel = st.dataframe(df_r, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row")
    if sel.selection.rows:
        df_sel = df_r.iloc[sel.selection.rows]
        c1, c2 = st.columns(2)
        with c1.expander("❌ Retornar ao Pendente"):
            if st.button("Confirmar Retorno"):
                all_v = sh.get_all_values()
                ids_sel = df_sel['id'].astype(str).tolist()
                for i, r in enumerate(all_v):
                    if str(r[0]) in ids_sel and r[5] == 'em rota':
                        sh.update_cell(i+1, 6, "pendente")
                st.rerun()
        with c2.expander("📉 Saída Parcial"):
            for _, r in df_sel.iterrows():
                qtd_s = st.number_input(f"Qtd entregue #{r['id']}", 0, int(r['caixas']), int(r['caixas']), key=f"parc_{r['id']}")
                if st.button(f"Dar Baixa #{r['id']}"):
                    peso_u = float(r['peso'])/int(r['caixas'])
                    all_v = sh.get_all_values()
                    for i, lin in enumerate(all_v):
                        if str(lin[0]) == str(r['id']) and lin[5] == 'em rota':
                            sh.update_cell(i+1, 6, "entregue")
                            sh.update_cell(i+1, 4, qtd_s)
                            sh.update_cell(i+1, 5, qtd_s * peso_u)
                            if int(r['caixas']) - qtd_s > 0:
                                sob = int(r['caixas']) - qtd_s
                                sh.append_row([r['id'], r['cliente'], r['produto'], sob, sob*peso_u, "pendente"])
                            st.rerun()

# --- EXECUÇÃO PRINCIPAL ---
st.set_page_config(page_title="Sistema de Carga", layout="wide")
if 'usuario_logado' not in st.session_state: st.session_state.usuario_logado = None

if st.session_state.usuario_logado is None:
    st.title("Login")
    with st.form("login_fix"):
        u = st.text_input("Usuário")
        s = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            d = login_usuario(u, s)
            if d: st.session_state.usuario_logado = d; st.rerun()
            else: st.error("Usuário ou senha inválidos")
else:
    u_info = st.session_state.usuario_logado
    st.sidebar.title(f"👤 {u_info['usuario']}")
    lista_opcoes = ["Cadastro", "Produtos", "Pedidos", "Gestão de Rotas", "Gestão de Usuários", "Logs"]
    menu = st.sidebar.radio("Navegação:", lista_opcoes if u_info['modulos'] == 'todos' else u_info['modulos'].split(','))
    
    if menu == "Cadastro": tela_cadastro(u_info)
    elif menu == "Produtos": tela_produtos(u_info)
    elif menu == "Pedidos": tela_pedidos(u_info)
    elif menu == "Gestão de Rotas": tela_gestao_rotas(u_info)
    elif menu == "Gestão de Usuários": tela_usuarios(u_info)
    elif menu == "Logs":
        sh_log = get_gc().open(PLANILHA_NOME).worksheet("log_operacoes")
        st.dataframe(pd.DataFrame(sh_log.get_all_records()).sort_index(ascending=False), use_container_width=True)
    
    if st.sidebar.button("Sair"): 
        st.session_state.usuario_logado = None
        st.rerun()
