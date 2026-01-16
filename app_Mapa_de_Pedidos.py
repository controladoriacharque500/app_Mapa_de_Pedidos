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
    
    # Ajuste para lidar com MultiIndex ou Colunas simples
    df_reset = df_matriz.reset_index()
    cols = df_reset.columns.tolist()
    col_width = 240 / (len(cols))
    
    pdf.set_font("Arial", "B", 7)
    for col in cols:
        pdf.cell(col_width, 7, str(col)[:15], 1, 0, 'C')
    pdf.ln()
    
    pdf.set_font("Arial", "", 7)
    for _, row in df_reset.iterrows():
        label = str(row.iloc[1]) # Geralmente o nome do cliente
        fill = "TOTAL" in label.upper()
        if fill:
            pdf.set_fill_color(230, 230, 230)
            pdf.set_font("Arial", "B", 7)
        else:
            pdf.set_font("Arial", "", 7)
            
        for val in row:
            txt = f"{float(val):.2f}" if isinstance(val, (float, int)) and fill and val > 500 else str(val)
            pdf.cell(col_width, 6, txt[:30], 1, 0, 'C', fill)
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
            m1 = st.checkbox("Cadastro", True); m2 = st.checkbox("Produtos", True)
            m3 = st.checkbox("Pedidos", True); m4 = st.checkbox("Gestão de Rotas", True)
            m5 = st.checkbox("Gestão de Usuários", True); m6 = st.checkbox("Logs", True)
            if st.form_submit_button("Salvar"):
                mods = [m for m, val in zip(["Cadastro", "Produtos", "Pedidos", "Gestão de Rotas", "Gestão de Usuários", "Logs"], [m1, m2, m3, m4, m5, m6]) if val]
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
        ids_all = pd.to_numeric(df_ped['id'], errors='coerce').dropna()
        proximo_id = int(ids_all.max()) + 1 if not ids_all.empty else 1
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
                peso_f = col_b.number_input("Peso", value=float(qtd * float(dados_p['peso_unitario'])))
                if st.button("Confirmar Lançamento"):
                    if cliente:
                        aba_pedidos.append_row([proximo_id, f"{cliente} ({uf})", prod_sel, qtd, peso_f, "pendente"])
                        registrar_log(user['usuario'], "CADASTRO", f"ID {proximo_id}")
                        st.success("Lançado!"); st.rerun()

def tela_pedidos(user):
    st.header("🚚 Montagem de Carga")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME); aba_pedidos = sh.worksheet("pedidos")
    df_p = pd.DataFrame(aba_pedidos.get_all_records())
    if df_p.empty: st.info("Sem pedidos."); return
    
    df_p['caixas'] = pd.to_numeric(df_p['caixas'], errors='coerce').fillna(0)
    df_p['peso'] = pd.to_numeric(df_p['peso'], errors='coerce').fillna(0)
    df_pendentes = df_p[df_p['status'] == 'pendente'].copy()

    if df_pendentes.empty: st.info("Sem pedidos pendentes."); return

    df_pendentes['uf_extraida'] = df_pendentes['cliente'].str.extract(r'\((.*?)\)')
    ufs = sorted(df_pendentes['uf_extraida'].dropna().unique().tolist())
    f_uf = st.sidebar.multiselect("Filtrar por UF", options=ufs, default=ufs)
    df_filtrado = df_pendentes[df_pendentes['uf_extraida'].isin(f_uf)]

    selecao = st.dataframe(df_filtrado.drop(columns=['uf_extraida']), use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row")
    
    if selecao.selection.rows:
        df_sel = df_filtrado.iloc[selecao.selection.rows]
        matriz = df_sel.pivot_table(index=['id', 'cliente'], columns='produto', values='caixas', aggfunc='sum', fill_value=0)
        matriz['TOTAL CX'] = matriz.sum(axis=1)
        
        totais_cx = matriz.sum().to_frame().T
        totais_cx.index = pd.MultiIndex.from_tuples([(999998, 'TOTAL CAIXAS')])
        
        peso_resumo = df_sel.groupby('produto')['peso'].sum().to_frame().T
        peso_resumo = peso_resumo.reindex(columns=matriz.columns, fill_value=0)
        peso_resumo.index = pd.MultiIndex.from_tuples([(999999, 'TOTAL PESO (kg)')])
        peso_resumo['TOTAL CX'] = df_sel['peso'].sum()
        
        df_final = pd.concat([matriz, totais_cx, peso_resumo])
        st.dataframe(df_final, use_container_width=True)
        
        pdf_bytes = gerar_pdf_rota(df_final)
        st.download_button("📄 Baixar PDF", data=pdf_bytes, file_name="mapa.pdf", mime="application/pdf")
        
        if st.button("🚀 Confirmar Saída para Rota"):
            ids = [str(x) for x in df_sel['id'].tolist()]
            data = aba_pedidos.get_all_values()
            for i, lin in enumerate(data):
                if str(lin[0]) in ids: aba_pedidos.update_cell(i + 1, 6, "em rota")
            st.success("Em rota!"); st.rerun()

def tela_gestao_rotas(user):
    st.header("🔄 Baixa de Entregas")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME)
    aba_pedidos = sh.worksheet("pedidos")
    aba_hist = sh.worksheet("historico")
    
    df_ped = pd.DataFrame(aba_pedidos.get_all_records())
    df_rota = df_ped[df_ped['status'] == 'em rota'].copy()
    
    if df_rota.empty: st.info("Nada em rota."); return
    
    sel = st.dataframe(df_rota, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row")
    
    if sel.selection.rows:
        df_sel = df_rota.iloc[sel.selection.rows]
        for _, r in df_sel.iterrows():
            with st.expander(f"Baixa: ID {r['id']} - {r['cliente']}", expanded=True):
                qtd_entregue = st.number_input(f"Qtd entregue de {r['produto']}", 0, int(r['caixas']), int(r['caixas']), key=f"ent_{r['id']}")
                if st.button(f"Confirmar Entrega #{r['id']}", key=f"btn_{r['id']}"):
                    peso_u = float(r['peso']) / int(r['caixas'])
                    ent_peso = qtd_entregue * peso_u
                    
                    # --- LÓGICA DE HISTÓRICO (SOMA OU CRIA) ---
                    df_h = pd.DataFrame(aba_hist.get_all_records())
                    match = df_h[(df_h['id'].astype(str) == str(r['id'])) & (df_h['produto'] == r['produto'])]
                    
                    if not match.empty:
                        idx_h = match.index[0] + 2
                        nova_qtd_h = int(match.iloc[0]['caixas']) + qtd_entregue
                        novo_peso_h = float(match.iloc[0]['peso']) + ent_peso
                        aba_hist.update_cell(idx_h, 4, nova_qtd_h)
                        aba_hist.update_cell(idx_h, 5, novo_peso_h)
                    else:
                        aba_hist.append_row([r['id'], r['cliente'], r['produto'], qtd_entregue, ent_peso, "entregue"])
                    
                    # --- ATUALIZA ABA PEDIDOS ---
                    sobra = int(r['caixas']) - qtd_entregue
                    data_ped = aba_pedidos.get_all_values()
                    for i, lin in enumerate(data_ped):
                        if str(lin[0]) == str(r['id']) and lin[2] == r['produto'] and lin[5] == "em rota":
                            if sobra > 0:
                                aba_pedidos.update_cell(i+1, 4, sobra)
                                aba_pedidos.update_cell(i+1, 5, sobra * peso_u)
                                aba_pedidos.update_cell(i+1, 6, "pendente")
                            else:
                                aba_pedidos.delete_rows(i+1)
                            break
                    st.rerun()

# --- MAIN ---
st.set_page_config(page_title="Sistema Logístico", layout="wide")
if 'usuario_logado' not in st.session_state: st.session_state.usuario_logado = None

if st.session_state.usuario_logado is None:
    st.title("Login")
    with st.form("login_form"):
        u = st.text_input("Usuário")
        s = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            d = login_usuario(u, s)
            if d: st.session_state.usuario_logado = d; st.rerun()
            else: st.error("Erro")
else:
    user = st.session_state.usuario_logado
    st.sidebar.title(f"👤 {user['usuario']}")
    
    # Lógica corrigida da barra lateral
    op_full = ["Cadastro", "Produtos", "Pedidos", "Gestão de Rotas", "Gestão de Usuários", "Logs"]
    mod_str = str(user.get('modulos', ''))
    opcoes = op_full if (mod_str.lower() in ['todos', 'total'] or user['usuario'] == 'admin') else mod_str.split(',')
    
    menu = st.sidebar.radio("Menu:", [o.strip() for o in opcoes if o.strip() in op_full])
    
    if menu == "Cadastro": tela_cadastro(user)
    elif menu == "Produtos": tela_produtos(user)
    elif menu == "Pedidos": tela_pedidos(user)
    elif menu == "Gestão de Rotas": tela_gestao_rotas(user)
    elif menu == "Gestão de Usuários": tela_usuarios(user)
    elif menu == "Logs":
        try:
            df_l = pd.DataFrame(get_gc().open(PLANILHA_NOME).worksheet("log_operacoes").get_all_records())
            st.dataframe(df_l, use_container_width=True)
        except: st.info("Sem logs.")
        
    if st.sidebar.button("Sair"):
        st.session_state.usuario_logado = None
        st.rerun()
