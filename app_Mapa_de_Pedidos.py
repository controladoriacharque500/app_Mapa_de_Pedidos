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

def gerar_pdf_rota(df_matriz):
    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, f"MAPA DE CARREGAMENTO - {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True, align='C')
    pdf.ln(5)
    pdf.set_font("Arial", "B", 7)
    cols = df_matriz.columns.tolist()
    col_width = 240 / (len(cols) + 1)
    pdf.cell(50, 7, "Cliente", 1, 0, 'C')
    for col in cols:
        pdf.cell(col_width, 7, str(col)[:10], 1, 0, 'C')
    pdf.ln()
    pdf.set_font("Arial", "", 7)
    for index, row in df_matriz.iterrows():
        label = str(index[1]) if isinstance(index, tuple) else str(index)
        fill = index in ['TOTAL CAIXAS', 'TOTAL PESO (kg)']
        if fill: 
            pdf.set_fill_color(230, 230, 230)
            pdf.set_font("Arial", "B", 7)
        else: pdf.set_font("Arial", "", 7)
        pdf.cell(50, 6, label[:30], 1, 0, 'L', fill)
        for col in cols:
            val = row[col]
            try:
                txt = f"{float(val):.2f}" if "PESO" in str(index) else str(int(val))
            except: txt = str(val)
            pdf.cell(col_width, 6, txt, 1, 0, 'C', fill)
        pdf.ln()
    return bytes(pdf.output())

# --- MÓDULOS DE TELA ---

def tela_usuarios(user):
    st.header("👥 Gestão de Usuários e Permissões")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME); aba_user = sh.worksheet("usuarios")
    with st.expander("➕ Cadastrar / Editar Usuário"):
        with st.form("form_usuario"):
            novo_u = st.text_input("Usuário (Login)")
            nova_s = st.text_input("Senha", type="password")
            nivel = st.selectbox("Nível", ["total", "visualizacao"])
            m1 = st.checkbox("Cadastro", True); m2 = st.checkbox("Produtos", True)
            m3 = st.checkbox("Pedidos", True); m4 = st.checkbox("Gestão de Rotas", True)
            m5 = st.checkbox("Gestão de Usuários", False); m6 = st.checkbox("Logs", True); m7 = st.checkbox("Relatórios", True)
            if st.form_submit_button("Salvar"):
                mods = [m for m, val in zip(["Cadastro", "Produtos", "Pedidos", "Gestão de Rotas", "Gestão de Usuários", "Logs", "Relatórios"], [m1, m2, m3, m4, m5, m6, m7]) if val]
                aba_user.append_row([novo_u, nova_s, nivel, ",".join(mods)])
                st.success("Usuário salvo!"); st.rerun()
    st.dataframe(pd.DataFrame(aba_user.get_all_records()), use_container_width=True)

def tela_produtos(user):
    st.header("📦 Cadastro de Produtos")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME); aba_prod = sh.worksheet("produtos")
    with st.expander("➕ Novo Produto"):
        with st.form("form_prod"):
            desc = st.text_input("Descrição")
            p_unit = st.number_input("Peso Unitário", min_value=0.0, step=0.01)
            tipo = st.selectbox("Tipo de Peso", ["padrão", "variável"])
            if st.form_submit_button("Cadastrar"):
                aba_prod.append_row([desc, p_unit, tipo])
                st.success("Cadastrado!"); st.rerun()
    st.dataframe(pd.DataFrame(aba_prod.get_all_records()), use_container_width=True)

def tela_cadastro(user):
    st.header("📝 Gestão de Pedidos")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME)
    aba_pedidos = sh.worksheet("pedidos"); aba_produtos = sh.worksheet("produtos")
    df_ped = pd.DataFrame(aba_pedidos.get_all_records())
    df_prod = pd.DataFrame(aba_produtos.get_all_records())
    tab_lançar, tab_editar = st.tabs(["🚀 Novo Lançamento", "✏️ Editar / Excluir Pendentes"])

    with tab_lançar:
        proximo_id = int(pd.to_numeric(df_ped['id'], errors='coerce').max()) + 1 if not df_ped.empty else 1
        with st.container(border=True):
            st.subheader(f"Novo Pedido: #{proximo_id}")
            c1, c2 = st.columns(2)
            cliente = c1.text_input("Cliente")
            uf = c2.selectbox("Estado", ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"])
            prod_sel = st.selectbox("Produto", [""] + df_prod['descricao'].tolist())
            if prod_sel:
                dados_p = df_prod[df_prod['descricao'] == prod_sel].iloc[0]
                col_a, col_b = st.columns(2)
                qtd = col_a.number_input("Caixas", min_value=1, step=1)
                if dados_p['tipo'] == "padrão":
                    peso_f = col_b.number_input("Peso (Calculado)", value=float(qtd * float(dados_p['peso_unitario'])), disabled=True)
                else: peso_f = col_b.number_input("Peso Real", min_value=0.1)
                if st.button("Confirmar Lançamento"):
                    if cliente:
                        aba_pedidos.append_row([proximo_id, f"{cliente} ({uf})", prod_sel, qtd, peso_f, "pendente"])
                        registrar_log(user['usuario'], "CADASTRO", f"ID {proximo_id}")
                        st.success("Lançado!"); st.rerun()

    with tab_editar:
        df_pend = df_ped[df_ped['status'] == 'pendente'].copy()
        if not df_pend.empty:
            sel_edit = st.selectbox("Selecione o pedido", df_pend.index, format_func=lambda x: f"ID {df_pend.loc[x,'id']} - {df_pend.loc[x,'cliente']}")
            ped_sel = df_pend.loc[sel_edit]
            with st.form("form_edit"):
                ed_cli = st.text_input("Nome Cliente/UF", ped_sel['cliente'])
                ed_qtd = st.number_input("Quantidade Caixas", value=int(ped_sel['caixas']), min_value=1)
                c_edit, c_del = st.columns(2)
                if c_edit.form_submit_button("✅ Salvar"):
                    # Lógica de atualização simplificada para garantir funcionamento
                    data = aba_pedidos.get_all_values()
                    for i, r in enumerate(data):
                        if str(r[0]) == str(ped_sel['id']):
                            aba_pedidos.update_cell(i+1, 2, ed_cli)
                            aba_pedidos.update_cell(i+1, 4, ed_qtd)
                    st.success("Editado!"); st.rerun()
                if c_del.form_submit_button("🗑️ Excluir"):
                    data = aba_pedidos.get_all_values()
                    for i, r in enumerate(data):
                        if str(r[0]) == str(ped_sel['id']):
                            aba_pedidos.delete_rows(i+1); break
                    st.rerun()

def tela_pedidos(user):
    st.header("🚚 Montagem de Carga")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME); aba_pedidos = sh.worksheet("pedidos")
    df_p = pd.DataFrame(aba_pedidos.get_all_records())
    df_pendentes = df_p[df_p['status'] == 'pendente'].copy()
    if df_pendentes.empty: st.info("Sem pedidos pendentes."); return

    df_pendentes['uf'] = df_pendentes['cliente'].str.extract(r'\((.*?)\)')
    f_uf = st.sidebar.multiselect("Filtrar por UF", options=sorted(df_pendentes['uf'].unique()), default=sorted(df_pendentes['uf'].unique()))
    df_filtrado = df_pendentes[df_pendentes['uf'].isin(f_uf)]

    selecao = st.dataframe(df_filtrado.drop(columns=['uf']), use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row")
    
    if selecao.selection.rows:
        df_sel = df_filtrado.iloc[selecao.selection.rows]
        try:
            matriz = df_sel.pivot_table(index=['id', 'cliente'], columns='produto', values='caixas', aggfunc='sum', fill_value=0)
            matriz['TOTAL CX'] = matriz.sum(axis=1)
            
            # Totais inferiores
            tot_cx = matriz.sum().to_frame().T
            tot_cx.index = [('999998', 'TOTAL CAIXAS')]
            
            # Peso total por produto
            peso_resumo = df_sel.groupby('produto')['peso'].sum().to_frame().T
            peso_resumo = peso_resumo.reindex(columns=matriz.columns, fill_value=0)
            peso_resumo['TOTAL CX'] = df_sel['peso'].sum()
            peso_resumo.index = [('999999', 'TOTAL PESO (kg)')]
            
            df_final = pd.concat([matriz, tot_cx, peso_resumo])
            st.subheader("📊 Matriz de Carregamento")
            st.dataframe(df_final, use_container_width=True)
            
            c_pdf, c_conf = st.columns(2)
            pdf_bytes = gerar_pdf_rota(df_final)
            c_pdf.download_button("📄 Baixar PDF", data=pdf_bytes, file_name="mapa.pdf", use_container_width=True)
            
            if c_conf.button("🚀 Confirmar Saída em Rota", use_container_width=True):
                ids = df_sel['id'].astype(str).tolist()
                all_data = aba_pedidos.get_all_values()
                for i, row in enumerate(all_data):
                    if str(row[0]) in ids: aba_pedidos.update_cell(i+1, 6, "em rota")
                st.rerun()
        except Exception as e: st.error(f"Erro ao gerar matriz: {e}")

def tela_gestao_rotas(user):
    st.header("🔄 Gestão de Pedidos em Rota")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME)
    aba_pedidos = sh.worksheet("pedidos"); aba_hist = sh.worksheet("historico")
    
    df = pd.DataFrame(aba_pedidos.get_all_records())
    df_rota = df[df['status'] == 'em rota'].copy()
    if df_rota.empty: st.info("Nada em rota."); return
    
    selecao = st.dataframe(df_rota, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row")
    
    if selecao.selection.rows:
        df_sel = df_rota.iloc[selecao.selection.rows]
        c1, c2 = st.columns(2)
        with c1.expander("❌ Cancelar"):
            if st.button("Voltar para Pendente"):
                ids = df_sel['id'].astype(str).tolist()
                for i, r in enumerate(aba_pedidos.get_all_values()):
                    if str(r[0]) in ids: aba_pedidos.update_cell(i+1, 6, "pendente")
                st.rerun()
        with c2.expander("📉 Confirmar Entrega"):
            for _, r in df_sel.iterrows():
                qtd_e = st.number_input(f"Entregue #{r['id']}", 0, int(r['caixas']), int(r['caixas']), key=f"r_{r['id']}")
                if st.button(f"Baixar #{r['id']}"):
                    peso_u = float(r['peso']) / int(r['caixas'])
                    p_entregue = round(qtd_e * peso_u, 2)
                    
                    # Histórico (Soma se existir ID e Produto)
                    df_h = pd.DataFrame(aba_hist.get_all_records())
                    if not df_h.empty and 'id' in df_h.columns:
                        match = df_h[(df_h['id'].astype(str) == str(r['id'])) & (df_h['produto'] == r['produto'])]
                        if not match.empty:
                            idx_h = int(match.index[0]) + 2
                            aba_hist.update_cell(idx_h, 4, int(match.iloc[0]['caixas']) + qtd_e)
                            aba_hist.update_cell(idx_h, 5, float(match.iloc[0]['peso']) + p_entregue)
                        else: aba_hist.append_row([r['id'], r['cliente'], r['produto'], qtd_e, p_entregue, "entregue", datetime.now().strftime("%d/%m/%Y")])
                    else: aba_hist.append_row([r['id'], r['cliente'], r['produto'], qtd_e, p_entregue, "entregue", datetime.now().strftime("%d/%m/%Y")])

                    # Atualiza Pedidos
                    sobra = int(r['caixas']) - qtd_e
                    for i, lin in enumerate(aba_pedidos.get_all_values()):
                        if str(lin[0]) == str(r['id']) and lin[2] == r['produto']:
                            if sobra > 0:
                                aba_pedidos.update_cell(i+1, 4, sobra)
                                aba_pedidos.update_cell(i+1, 5, round(sobra * peso_u, 2))
                                aba_pedidos.update_cell(i+1, 6, "pendente")
                            else: aba_pedidos.delete_rows(i+1)
                            break
                    st.rerun()

def tela_relatorios(user):
    st.header("📊 Relatórios")
    df_h = pd.DataFrame(get_gc().open(PLANILHA_NOME).worksheet("historico").get_all_records())
    if not df_h.empty:
        st.dataframe(df_h.groupby('produto')[['caixas', 'peso']].sum(), use_container_width=True)

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
    op_full = ["Cadastro", "Produtos", "Pedidos", "Gestão de Rotas", "Relatórios", "Gestão de Usuários", "Logs"]
    menu = st.sidebar.radio("Menu:", op_full if user['modulos'] == 'todos' else user['modulos'].split(','))
    
    if menu == "Cadastro": tela_cadastro(user)
    elif menu == "Produtos": tela_produtos(user)
    elif menu == "Pedidos": tela_pedidos(user)
    elif menu == "Gestão de Rotas": tela_gestao_rotas(user)
    elif menu == "Relatórios": tela_relatorios(user)
    elif menu == "Gestão de Usuários": tela_usuarios(user)
    elif menu == "Logs":
        st.dataframe(pd.DataFrame(get_gc().open(PLANILHA_NOME).worksheet("log_operacoes").get_all_records()).sort_index(ascending=False))
    if st.sidebar.button("Sair"): st.session_state.usuario_logado = None; st.rerun()
