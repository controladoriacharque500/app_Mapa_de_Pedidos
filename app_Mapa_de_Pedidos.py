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
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, f"MAPA DE CARREGAMENTO - {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True, align='C')
    pdf.ln(5)
    
    # Identificar colunas: assume que a segunda coluna é o nome do cliente
    cols_dados = df_matriz.columns.tolist()
    col_cliente = cols_dados[1] 
    produtos = [c for c in cols_dados if c not in [cols_dados[0], col_cliente]]
    
    # Cabeçalho
    pdf.set_font("Arial", "B", 8)
    col_width = 190 / (len(produtos) + 1)
    pdf.cell(60, 8, "Cliente", 1, 0, 'C')
    for p in produtos:
        pdf.cell(col_width, 8, str(p)[:12], 1, 0, 'C')
    pdf.ln()
    
    # Linhas
    pdf.set_font("Arial", "", 8)
    for _, row in df_matriz.iterrows():
        txt_cliente = str(row[col_cliente])
        is_total = "TOTAL" in txt_cliente.upper()
        
        if is_total:
            pdf.set_fill_color(220, 220, 220)
            pdf.set_font("Arial", "B", 8)
        else:
            pdf.set_font("Arial", "", 8)
            
        pdf.cell(60, 7, txt_cliente[:35], 1, 0, 'L', is_total)
        for p in produtos:
            val = row[p]
            txt_val = f"{float(val):.2f}" if "PESO" in txt_cliente.upper() else str(int(float(val or 0)))
            pdf.cell(col_width, 7, txt_val, 1, 0, 'C', is_total)
        pdf.ln()
        
    return bytes(pdf.output())

# --- MÓDULOS DE TELA ---

def tela_cadastro(user):
    st.header("📝 Gestão de Pedidos")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME)
    aba_pedidos = sh.worksheet("pedidos"); aba_produtos = sh.worksheet("produtos")
    aba_historico = sh.worksheet("historico")
    
    # Lendo dados com tratamento de erro para valores vazios
    df_ped = pd.DataFrame(aba_pedidos.get_all_records()).replace('', 0)
    df_hist = pd.DataFrame(aba_historico.get_all_records()).replace('', 0)
    
    ids_existentes = pd.concat([df_ped['id'], df_hist['id']]) if not df_hist.empty else df_ped['id']
    proximo_id = int(pd.to_numeric(ids_existentes, errors='coerce').max() or 0) + 1

    df_prod = pd.DataFrame(aba_produtos.get_all_records())
    
    with st.container(border=True):
        st.subheader(f"Novo Lançamento: #{proximo_id}")
        c1, c2 = st.columns(2)
        cliente = c1.text_input("Nome do Cliente")
        uf = c2.selectbox("UF", ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"])
        prod_sel = st.selectbox("Selecione o Produto", [""] + df_prod['descricao'].tolist())
        
        if prod_sel:
            p_info = df_prod[df_prod['descricao'] == prod_sel].iloc[0]
            col_q, col_p = st.columns(2)
            qtd = col_q.number_input("Qtd Caixas", min_value=1, step=1)
            peso_sugestao = float(qtd * float(p_info['peso_unitario'] or 0))
            peso_real = col_p.number_input("Peso Total (kg)", min_value=0.0, value=peso_sugestao)
            
            if st.button("🚀 Salvar Pedido", use_container_width=True):
                if cliente:
                    aba_pedidos.append_row([proximo_id, f"{cliente} ({uf})", prod_sel, qtd, peso_real, "pendente"])
                    st.success("Pedido registrado!"); st.rerun()
                else: st.error("Informe o cliente.")

def tela_pedidos(user):
    st.header("🚚 Montagem de Carga")
    gc = get_gc(); sh = gc.open(PLANILHA_NOME); aba_pedidos = sh.worksheet("pedidos")
    
    # Tratamento para evitar erro de conversão em células vazias
    data = aba_pedidos.get_all_records()
    if not data:
        st.info("Nenhum pedido cadastrado."); return
        
    df_p = pd.DataFrame(data)
    df_p['caixas'] = pd.to_numeric(df_p['caixas'], errors='coerce').fillna(0)
    df_p['peso'] = pd.to_numeric(df_p['peso'], errors='coerce').fillna(0)
    
    df_pendentes = df_p[df_p['status'] == 'pendente'].copy()
    if df_pendentes.empty:
        st.info("Todos os pedidos já foram processados."); return

    df_pendentes['uf'] = df_pendentes['cliente'].str.extract(r'\((.*?)\)')
    ufs = sorted(df_pendentes['uf'].dropna().unique().tolist())
    f_uf = st.sidebar.multiselect("Filtrar por UF", ufs, default=ufs)
    df_filtrado = df_pendentes[df_pendentes['uf'].isin(f_uf)]

    st.write("Selecione os pedidos para o mapa:")
    sel = st.dataframe(
        df_filtrado.drop(columns=['uf']), 
        use_container_width=True, 
        hide_index=True, 
        on_select="rerun", 
        selection_mode="multi-row"
    )
    
    if sel.selection.rows:
        df_sel = df_filtrado.iloc[sel.selection.rows]
        
        try:
            # Pivotar a matriz
            matriz = df_sel.pivot_table(index=['id', 'cliente'], columns='produto', values='caixas', aggfunc='sum', fill_value=0)
            matriz['TOTAL CX'] = matriz.sum(axis=1)
            
            # Linha de Totais de Caixas
            totais_cx = matriz.sum().to_frame().T
            totais_cx.index = pd.MultiIndex.from_tuples([(999998, 'TOTAL CAIXAS')])
            
            # Linha de Totais de Peso
            peso_resumo = df_sel.groupby('produto')['peso'].sum().to_frame().T
            peso_resumo = peso_resumo.reindex(columns=matriz.columns, fill_value=0)
            peso_resumo.index = pd.MultiIndex.from_tuples([(999999, 'TOTAL PESO (kg)')])
            peso_resumo['TOTAL CX'] = df_sel['peso'].sum()
            
            df_final = pd.concat([matriz, totais_cx, peso_resumo]).reset_index()
            
            st.subheader("📊 Matriz Gerada")
            st.dataframe(df_final, use_container_width=True, hide_index=True)
            
            c_pdf, c_conf = st.columns(2)
            
            # Gerar PDF
            pdf_b = gerar_pdf_rota(df_final)
            c_pdf.download_button("📄 Baixar PDF do Mapa", data=pdf_b, file_name="mapa_carga.pdf", mime="application/pdf")
            
            if (user['nivel'] == 'total' or user['usuario'] == 'admin') and c_conf.button("🚚 Confirmar Saída em Rota", use_container_width=True):
                ids_confirmar = df_sel['id'].astype(str).tolist()
                raw_data = aba_pedidos.get_all_values()
                for i, row in enumerate(raw_data):
                    if str(row[0]) in ids_confirmar and row[5] == 'pendente':
                        aba_pedidos.update_cell(i+1, 6, "em rota")
                st.success("Pedidos atualizados para 'em rota'!"); st.rerun()
                
        except Exception as e:
            st.error(f"Erro ao processar matriz: {e}")

def tela_gestao_rotas(user):
    st.header("🔄 Baixa de Entregas")
    sh = get_gc().open(PLANILHA_NOME)
    aba_pedidos = sh.worksheet("pedidos")
    aba_historico = sh.worksheet("historico")
    
    df = pd.DataFrame(aba_pedidos.get_all_records())
    df_rota = df[df['status'] == 'em rota'].copy()
    
    if df_rota.empty:
        st.info("Nenhum pedido em trânsito no momento."); return
    
    st.write("Selecione para dar baixa (Parcial ou Total):")
    sel = st.dataframe(df_rota, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row")
    
    if sel.selection.rows:
        df_sel = df_rota.iloc[sel.selection.rows]
        
        for _, r in df_sel.iterrows():
            with st.expander(f"Baixa: {r['cliente']} - {r['produto']}", expanded=True):
                c1, c2 = st.columns(2)
                entregue = c1.number_input(f"Qtd Entregue (ID {r['id']})", 0, int(r['caixas']), int(r['caixas']), key=f"ent_{r['id']}")
                
                if c2.button(f"Confirmar Baixa #{r['id']}", key=f"btn_{r['id']}"):
                    peso_un = float(r['peso']) / int(r['caixas'])
                    
                    # 1. Salva o que foi entregue no Histórico
                    aba_historico.append_row([r['id'], r['cliente'], r['produto'], entregue, entregue * peso_un, "entregue"])
                    
                    # 2. Se for parcial, gera novo pendente
                    sobra = int(r['caixas']) - entregue
                    if sobra > 0:
                        aba_pedidos.append_row([r['id'], r['cliente'], r['produto'], sobra, sobra * peso_un, "pendente"])
                    
                    # 3. Remove o registro original da aba pedidos
                    data_raw = aba_pedidos.get_all_values()
                    for i, lin in enumerate(data_raw):
                        if str(lin[0]) == str(r['id']) and lin[2] == r['produto'] and lin[5] == 'em rota':
                            aba_pedidos.delete_rows(i+1)
                            break
                    st.rerun()

# --- MAIN ---
st.set_page_config(page_title="Sistema Logístico", layout="wide")
if 'usuario_logado' not in st.session_state: st.session_state.usuario_logado = None

if st.session_state.usuario_logado is None:
    st.title("Acesso ao Sistema")
    with st.form("login"):
        u = st.text_input("Usuário")
        s = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            user_data = login_usuario(u, s)
            if user_data:
                st.session_state.usuario_logado = user_data
                st.rerun()
            else: st.error("Dados incorretos.")
else:
    user = st.session_state.usuario_logado
    st.sidebar.title(f"Olá, {user['usuario']}")
    menu = st.sidebar.radio("Navegação", ["Cadastro", "Pedidos", "Gestão de Rotas"])
    
    if menu == "Cadastro": tela_cadastro(user)
    elif menu == "Pedidos": tela_pedidos(user)
    elif menu == "Gestão de Rotas": tela_gestao_rotas(user)
    
    if st.sidebar.button("Sair"):
        st.session_state.usuario_logado = None
        st.rerun()
