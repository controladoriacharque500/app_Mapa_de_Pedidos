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
    
    # Extrair colunas e remover IDs/Clientes da lista de produtos
    cols = [c for c in df_matriz.columns if c not in ['id', 'cliente']]
    col_width = 230 / (len(cols) + 1)
    
    pdf.cell(60, 7, "Cliente", 1, 0, 'C')
    for col in cols:
        pdf.cell(col_width, 7, str(col)[:10], 1, 0, 'C')
    pdf.ln()
    
    pdf.set_font("Arial", "", 7)
    for _, row in df_matriz.iterrows():
        label = str(row['cliente'])
        is_total = any(x in label.upper() for x in ["TOTAL", "PESO"])
        
        if is_total:
            pdf.set_fill_color(230, 230, 230)
            pdf.set_font("Arial", "B", 7)
        else:
            pdf.set_font("Arial", "", 7)
            
        pdf.cell(60, 6, label[:35], 1, 0, 'L', is_total)
        for col in cols:
            val = row[col]
            try:
                txt = f"{float(val):.2f}" if "PESO" in label.upper() else str(int(float(val)))
            except: txt = str(val)
            pdf.cell(col_width, 6, txt, 1, 0, 'C', is_total)
        pdf.ln()
    return bytes(pdf.output())

# --- MÓDULOS DE TELA ---

def tela_usuarios(user):
    st.header("👥 Gestão de Usuários")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME); aba_user = sh.worksheet("usuarios")
    # ... (mesma lógica anterior)
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
    aba_historico = sh.worksheet("historico")
    
    # Busca IDs tanto em pedidos ativos quanto no histórico para nunca repetir
    df_ped = pd.DataFrame(aba_pedidos.get_all_records())
    df_hist = pd.DataFrame(aba_historico.get_all_records())
    ids_totais = pd.concat([df_ped['id'], df_hist['id']]) if not df_hist.empty else df_ped['id']
    
    proximo_id = int(pd.to_numeric(ids_totais, errors='coerce').max() or 0) + 1

    df_prod = pd.DataFrame(aba_produtos.get_all_records())
    tab_lançar, tab_editar = st.tabs(["🚀 Novo Lançamento", "✏️ Editar / Excluir"])

    with tab_lançar:
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
                peso_f = col_b.number_input("Peso Real", min_value=0.1, value=float(qtd * float(dados_p['peso_unitario'])))
                if st.button("Confirmar Lançamento"):
                    aba_pedidos.append_row([proximo_id, f"{cliente} ({uf})", prod_sel, qtd, peso_f, "pendente"])
                    st.success("Lançado!"); st.rerun()

    with tab_editar:
        df_pend = df_ped[df_ped['status'] == 'pendente'].copy()
        if not df_pend.empty:
            sel = st.selectbox("Pedido", df_pend.index, format_func=lambda x: f"#{df_pend.loc[x,'id']} - {df_pend.loc[x,'cliente']}")
            # Lógica de edição similar à anterior...

def tela_pedidos(user):
    st.header("🚚 Montagem de Carga")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME); aba_pedidos = sh.worksheet("pedidos")
    df_p = pd.DataFrame(aba_pedidos.get_all_records())
    
    df_p['caixas'] = pd.to_numeric(df_p['caixas'], errors='coerce').fillna(0)
    df_p['peso'] = pd.to_numeric(df_p['peso'], errors='coerce').fillna(0)
    df_pendentes = df_p[df_p['status'] == 'pendente'].copy()

    if df_pendentes.empty:
        st.info("Sem pedidos pendentes."); return

    df_pendentes['uf_extraida'] = df_pendentes['cliente'].str.extract(r'\((.*?)\)')
    ufs = sorted(df_pendentes['uf_extraida'].dropna().unique().tolist())
    f_uf = st.sidebar.multiselect("Filtrar UF", options=ufs, default=ufs)
    df_filtrado = df_pendentes[df_pendentes['uf_extraida'].isin(f_uf)]

    selecao = st.dataframe(df_filtrado.drop(columns=['uf_extraida']), use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row")
    
    if selecao.selection.rows:
        df_sel = df_filtrado.iloc[selecao.selection.rows]
        
        # Matriz pivotada
        matriz = df_sel.pivot_table(index=['id', 'cliente'], columns='produto', values='caixas', aggfunc='sum', fill_value=0)
        matriz['TOTAL CX'] = matriz.sum(axis=1)
        
        totais_cx = matriz.sum().to_frame().T
        totais_cx.index = pd.MultiIndex.from_tuples([(999998, 'TOTAL CAIXAS')])
        
        peso_resumo = df_sel.groupby('produto')['peso'].sum().to_frame().T
        peso_resumo = peso_resumo.reindex(columns=matriz.columns, fill_value=0)
        peso_resumo.index = pd.MultiIndex.from_tuples([(999999, 'TOTAL PESO (kg)')])
        peso_resumo['TOTAL CX'] = df_sel['peso'].sum()
        
        df_final = pd.concat([matriz, totais_cx, peso_resumo]).reset_index()
        df_final.columns = [str(c) for c in df_final.columns]
        
        st.subheader("📊 Matriz de Carregamento")
        st.dataframe(df_final, use_container_width=True, hide_index=True)
        
        c_pdf, c_conf = st.columns(2)
        pdf_bytes = gerar_pdf_rota(df_final)
        c_pdf.download_button("📄 Baixar PDF", data=pdf_bytes, file_name="mapa.pdf", mime="application/pdf")
        
        if c_conf.button("🚀 Confirmar Saída para Rota", use_container_width=True):
            ids = df_sel['id'].astype(str).tolist()
            # Atualiza status para em rota
            for i, row in enumerate(aba_pedidos.get_all_values()):
                if str(row[0]) in ids and row[5] == 'pendente':
                    aba_pedidos.update_cell(i+1, 6, "em rota")
            st.rerun()

def tela_gestao_rotas(user):
    st.header("🔄 Gestão de Pedidos em Rota")
    sh_plan = get_gc().open(PLANILHA_NOME)
    aba_pedidos = sh_plan.worksheet("pedidos")
    aba_historico = sh_plan.worksheet("historico")
    
    df = pd.DataFrame(aba_pedidos.get_all_records())
    df_rota = df[df['status'] == 'em rota'].copy()
    
    if df_rota.empty:
        st.info("Nada em rota."); return
    
    selecao = st.dataframe(df_rota, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row")
    
    if selecao.selection.rows:
        df_sel = df_rota.iloc[selecao.selection.rows]
        
        for index, r in df_sel.iterrows():
            with st.container(border=True):
                st.write(f"**#{r['id']} - {r['cliente']}** ({r['produto']})")
                qtd_entregue = st.number_input(f"Qtd Entregue", 0, int(r['caixas']), int(r['caixas']), key=f"q_{index}")
                
                if st.button(f"Confirmar Baixa #{r['id']}", key=f"btn_{index}"):
                    peso_u = float(r['peso']) / int(r['caixas'])
                    
                    # 1. Move o que FOI ENTREGUE para o Histórico
                    aba_historico.append_row([
                        r['id'], r['cliente'], r['produto'], 
                        qtd_entregue, qtd_entregue * peso_u, "entregue"
                    ])
                    
                    # 2. Se sobrou algo, cria novo pedido PENDENTE na aba pedidos
                    sobra = int(r['caixas']) - qtd_entregue
                    if sobra > 0:
                        aba_pedidos.append_row([
                            r['id'], r['cliente'], r['produto'], 
                            sobra, sobra * peso_u, "pendente"
                        ])
                    
                    # 3. Remove a linha antiga da aba PEDIDOS (limpeza total)
                    # Procuramos a linha exata para deletar
                    data_pedidos = aba_pedidos.get_all_values()
                    for i, lin in enumerate(data_pedidos):
                        if str(lin[0]) == str(r['id']) and lin[2] == r['produto'] and lin[5] == 'em rota':
                            aba_pedidos.delete_rows(i+1)
                            break
                    
                    st.success("Movido para histórico!"); st.rerun()

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
            else: st.error("Invalido")
else:
    user = st.session_state.usuario_logado
    st.sidebar.title(f"👤 {user['usuario']}")
    menu = st.sidebar.radio("Menu:", ["Cadastro", "Produtos", "Pedidos", "Gestão de Rotas"])
    if menu == "Cadastro": tela_cadastro(user)
    elif menu == "Produtos": tela_produtos(user)
    elif menu == "Pedidos": tela_pedidos(user)
    elif menu == "Gestão de Rotas": tela_gestao_rotas(user)
    if st.sidebar.button("Sair"): st.session_state.usuario_logado = None; st.rerun()
