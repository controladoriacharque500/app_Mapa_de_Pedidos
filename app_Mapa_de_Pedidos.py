import streamlit as st
import pandas as pd
from datetime import datetime
import gspread
from fpdf import FPDF
import requests
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
        if gc:
            aba_log = gc.open(PLANILHA_NOME).worksheet("log_operacoes")
            aba_log.append_row([datetime.now().strftime("%d/%m/%Y %H:%M:%S"), usuario, acao, detalhes])
    except Exception:
        pass

def login_usuario(usuario, senha):
    gc = get_gc()
    if gc:
        try:
            sh = gc.open(PLANILHA_NOME)
            wks = sh.worksheet("usuarios")
            df_users = pd.DataFrame(wks.get_all_records())
            user_match = df_users[(df_users['usuario'].astype(str) == str(usuario)) & (df_users['senha'].astype(str) == str(senha))]
            return user_match.iloc[0].to_dict() if not user_match.empty else None
        except Exception as e:
            st.error(f"Erro ao consultar usuários: {e}")
            return None
    return None

def buscar_pedidos_api(api_url, data_inicio='2026-01-01'):
    try:
        headers = {"ngrok-skip-browser-warning": "69420"}
        url = f"{api_url}/pedidos?data_inicio={data_inicio}"
        res = requests.get(url, headers=headers, timeout=30)
        if res.status_code == 200:
            return pd.DataFrame(res.json())
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Erro ao conectar na API: {e}")
        return pd.DataFrame()

def gerar_pdf_rota(df_matriz):
    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, f"MAPA DE CARREGAMENTO - {datetime.now().strftime('%d/%m/%Y')}", ln=True, align='C')
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
        else:
            pdf.set_font("Arial", "", 7)
        pdf.cell(50, 6, label[:30], 1, 0, 'L', fill)
        for col in cols:
            val = row[col]
            txt = f"{val:.2f}" if "PESO" in str(index) else str(int(val))
            pdf.cell(col_width, 6, txt, 1, 0, 'C', fill)
        pdf.ln()
    return bytes(pdf.output())

# --- MÓDULOS DE TELA ---

def tela_usuarios(user):
    st.header("👥 Gestão de Usuários e Permissões")
    gc = get_gc()
    if not gc:
        st.error("Erro ao conectar ao serviço do Google Sheets.")
        return
    sh = gc.open(PLANILHA_NOME)
    aba_user = sh.worksheet("usuarios")
    
    with st.expander("➕ Cadastrar / Editar Usuário"):
        with st.form("form_usuario"):
            novo_u = st.text_input("Usuário (Login)")
            nova_s = st.text_input("Senha", type="password")
            nivel = st.selectbox("Nível (Total libera botões de ação)", ["total", "visualizacao"])
            m1 = st.checkbox("Cadastro", True)
            m2 = st.checkbox("Produtos", True)
            m3 = st.checkbox("Pedidos", True)
            m4 = st.checkbox("Gestão de Rotas", True)
            m5 = st.checkbox("Gestão de Usuários", False)
            m6 = st.checkbox("Logs", True)
            m7 = st.checkbox("Relatórios", True)
            
            if st.form_submit_button("Salvar"):
                mods = [m for m, val in zip(["Cadastro", "Produtos", "Pedidos", "Gestão de Rotas", "Gestão de Usuários", "Logs", "Relatórios"], [m1, m2, m3, m4, m5, m6, m7]) if val]
                df_u = pd.DataFrame(aba_user.get_all_records())
                if not df_u.empty and novo_u in df_u['usuario'].values:
                    idx = df_u[df_u['usuario'] == novo_u].index[0] + 2
                    aba_user.delete_rows(int(idx))
                aba_user.append_row([novo_u, nova_s, nivel, ",".join(mods)])
                registrar_log(user['usuario'], "USUÁRIO", f"Salvo/Atualizado usuário {novo_u}")
                st.success("Usuário salvo com sucesso!")
                st.rerun()
                
    st.dataframe(pd.DataFrame(aba_user.get_all_records()), use_container_width=True)

def limpar_e_converter_float(valor):
    """
    Trata valores numéricos vindos do ERP.
    Se o valor contiver ponto e for um inteiro formatado (ex: '7.227'),
    ou se a API retornar o peso em gramas/inteiro alto, ajusta a escala.
    """
    if pd.isna(valor) or valor == "" or valor is None:
        return 0.0
    
    val_str = str(valor).strip()
    
    # Se vier com vírgula (padrão PT-BR: "7,23" -> 7.23)
    if ',' in val_str:
        val_str = val_str.replace('.', '').replace(',', '.')
        try:
            return float(val_str)
        except ValueError:
            return 0.0

    try:
        val_float = float(val_str)
        # SE A API RETORNA PESO EM GRAMAS / MULTIPLICADO POR 1000 (ex: 7227 ou 7.227 no float):
        # Caso o valor venha como 7227 (ou 7.227 lido como 7.227 mas que no ERP representa 7,227 kg com erro de escala)
        if val_float > 1000 and "." not in val_str:
            # Exemplo: se 7227 na verdade são 7.227 kg (gramas para kg)
            return val_float / 1000.0
        elif val_float > 500: 
            # Ajuste de escala para pedidos com representação em gramas
            return val_float / 1000.0
            
        return val_float
    except ValueError:
        return 0.0


def processar_dados_api_para_pedidos(user):
    """Lê a aba Dados_api, ajusta escala de peso e grava na aba pedidos."""
    gc = get_gc()
    if not gc:
        return 0, "Erro na conexão com o Google Sheets."

    sh = gc.open(PLANILHA_NOME)
    aba_api = sh.worksheet("Dados_api")
    aba_prod = sh.worksheet("produtos")
    aba_pedidos = sh.worksheet("pedidos")
    
    try:
        aba_hist = sh.worksheet("historico")
        df_hist = pd.DataFrame(aba_hist.get_all_records()).fillna("")
    except Exception:
        df_hist = pd.DataFrame()

    df_api = pd.DataFrame(aba_api.get_all_records()).fillna("")
    df_prod = pd.DataFrame(aba_prod.get_all_records()).fillna("")
    df_ped = pd.DataFrame(aba_pedidos.get_all_records()).fillna("")

    if df_api.empty:
        return 0, "Aba Dados_api está vazia."

    de_para_map = {}
    if not df_prod.empty and 'descricao_sistema' in df_prod.columns:
        for _, r in df_prod.iterrows():
            desc_sis = str(r.get('descricao_sistema', '')).strip()
            if desc_sis:
                desc_abrev = str(r.get('descricao', '')).strip()
                p_unit = limpar_e_converter_float(r.get('peso_unitario', 1.0))
                tipo_peso = str(r.get('tipo', 'padrão')).strip().lower()
                if p_unit <= 0:
                    p_unit = 1.0
                de_para_map[desc_sis] = (desc_abrev, p_unit, tipo_peso)

    pedidos_existentes = set()
    if not df_ped.empty and 'NUMEROPEDIDOVENDA' in df_ped.columns:
        pedidos_existentes.update(df_ped['NUMEROPEDIDOVENDA'].astype(str).str.strip().tolist())
    if not df_hist.empty and 'NUMEROPEDIDOVENDA' in df_hist.columns:
        pedidos_existentes.update(df_hist['NUMEROPEDIDOVENDA'].astype(str).str.strip().tolist())

    ultimo_id = 0
    if not df_ped.empty and 'id' in df_ped.columns:
        ids_validos = pd.to_numeric(df_ped['id'], errors='coerce').dropna()
        if not ids_validos.empty:
            ultimo_id = int(ids_validos.max())

    novas_linhas_pedidos = []
    linhas_api_para_manter = [] 
    pedidos_duplicados_count = 0

    for _, row in df_api.iterrows():
        num_pedido = str(row.get('NUMEROPEDIDOVENDA', '')).strip()
        prod_erp = str(row.get('PRODUTO', '')).strip()

        if not num_pedido and not prod_erp:
            continue

        if num_pedido in pedidos_existentes:
            pedidos_duplicados_count += 1
            continue

        if prod_erp in de_para_map:
            desc_abrev, peso_unit, tipo_peso = de_para_map[prod_erp]
            
            # Captura bruta do ERP
            qtde_raw = str(row.get('QTDE', 0)).strip()
            
            # Força remoção de ponto caso venha como "7.227" e converte
            if "." in qtde_raw and "," not in qtde_raw:
                # Remove ponto de milhar/formatação incorreta
                qtde_limpa = qtde_raw.replace(".", "")
                qtde_num = float(qtde_limpa)
            else:
                qtde_num = limpar_e_converter_float(qtde_raw)

            # Se o número resultante for alto (ex: 7227), divide por 1000 para virar 7.227 kg
            if qtde_num > 500:
                qtde_peso = round(qtde_num / 1000.0, 3)
            else:
                qtde_peso = round(qtde_num, 3)

            # Cálculo do número de caixas
            if tipo_peso == "variável":
                caixas = 1 if (0 < qtde_peso <= peso_unit) else int(round(qtde_peso / peso_unit))
            else:
                caixas = int(round(qtde_peso / peso_unit)) if peso_unit > 0 else 0

            nome_cli = str(row.get('NOME_CLIENTE', '')).strip()
            obs_raw = row.get('OBSERVACAO', row.get('OBS', ''))
            obs_cli = str(obs_raw).strip() if pd.notna(obs_raw) and str(obs_raw).upper() != "NONE" else ""
            uf_cli = str(row.get('UF', '')).strip()

            if obs_cli:
                cliente_fmt = f"{nome_cli} [{obs_cli}] ({uf_cli})"
            else:
                cliente_fmt = f"{nome_cli} ({uf_cli})"
            
            ultimo_id += 1
            novas_linhas_pedidos.append([
                ultimo_id, cliente_fmt, desc_abrev, caixas, qtde_peso, "pendente", num_pedido
            ])
        else:
            linhas_api_para_manter.append(row.tolist())

    registros_processados = len(novas_linhas_pedidos)

    valores_existentes = aba_api.get_all_values()
    if len(valores_existentes) > 1:
        aba_api.delete_rows(2, len(valores_existentes))

    if linhas_api_para_manter:
        aba_api.append_rows(linhas_api_para_manter, value_input_option='USER_ENTERED')

    if registros_processados > 0:
        aba_pedidos.append_rows(novas_linhas_pedidos, value_input_option='USER_ENTERED')
        registrar_log(user['usuario'], "IMPORTACAO_PEDIDOS", f"{registros_processados} pedidos transferidos de Dados_api para pedidos")
        return registros_processados, f"✅ {registros_processados} item(ns) transferido(s) com sucesso!"

    return 0, "Nenhum pedido pendente para processamento."


def tela_produtos(user):
    st.header("📦 Cadastro de Produtos e De-Para ERP")
    gc = get_gc()
    if not gc:
        st.error("Erro de conexão.")
        return
    sh = gc.open(PLANILHA_NOME)
    aba_prod = sh.worksheet("produtos")
    
    with st.expander("➕ Novo Produto"):
        with st.form("form_prod"):
            desc = st.text_input("Descrição (Abreviada)")
            desc_sis = st.text_input("Descrição Sistema/ERP (Opcional)")
            p_unit = st.number_input("Peso Unitário", min_value=0.0, step=0.01)
            tipo = st.selectbox("Tipo de Peso", ["padrão", "variável"])
            if st.form_submit_button("Cadastrar Produto"):
                aba_prod.append_row([desc, p_unit, tipo, desc_sis])
                registrar_log(user['usuario'], "PRODUTO", f"Cadastrado produto {desc}")
                st.success("Cadastrado com sucesso!")
                st.rerun()

    with st.expander("🔗 Vincular Produtos Pendentes do ERP (De-Para)"):
        try:
            aba_dados_api = sh.worksheet("Dados_api")
            df_api = pd.DataFrame(aba_dados_api.get_all_records()).fillna("")
            df_prod = pd.DataFrame(aba_prod.get_all_records()).fillna("")

            if 'descricao_sistema' not in df_prod.columns:
                df_prod['descricao_sistema'] = ""

            if not df_api.empty and 'PRODUTO' in df_api.columns:
                prods_api_unicos = [str(p).strip() for p in df_api['PRODUTO'].dropna().unique() if str(p).strip() != ""]
                prods_ja_vinculados = [str(p).strip() for p in df_prod['descricao_sistema'].dropna().unique() if str(p).strip() != ""]
                prods_pendentes = [p for p in prods_api_unicos if p not in prods_ja_vinculados]

                if not prods_pendentes:
                    st.success("🎉 Todos os produtos da aba Dados_api já possuem vínculo cadastrado!")
                    if st.button("🚀 Processar Pedidos Pendentes Agora", type="primary", use_container_width=True):
                        qtd, msg = processar_dados_api_para_pedidos(user)
                        st.info(msg)
                        st.rerun()
                else:
                    st.info(f"Existem **{len(prods_pendentes)}** produtos da API sem vínculo com o cadastro local.")
                    
                    with st.form("form_depara"):
                        prod_erp_sel = st.selectbox("1. Selecione o Produto vindo do ERP (Dados_api):", options=prods_pendentes)
                        prods_locais = df_prod['descricao'].tolist() if 'descricao' in df_prod.columns else []
                        prod_local_sel = st.selectbox("2. Vincule ao Produto Local equivalente (Abreviado):", options=prods_locais)

                        if st.form_submit_button("💾 Salvar Vínculo De-Para e Processar Pedidos"):
                            if prod_erp_sel and prod_local_sel:
                                celula = aba_prod.find(prod_local_sel)
                                if celula:
                                    aba_prod.update_cell(celula.row, 4, prod_erp_sel)
                                    registrar_log(user['usuario'], "DE_PARA", f"Vinculado '{prod_erp_sel}' -> '{prod_local_sel}'")
                                    
                                    qtd_proc, msg_proc = processar_dados_api_para_pedidos(user)
                                    st.success(f"✅ Vínculo salvo! {msg_proc}")
                                    st.rerun()
                                else:
                                    st.error("Produto local não encontrado na planilha.")
                            else:
                                st.warning("Selecione ambos os produtos para salvar.")
            else:
                st.info("Nenhum dado pendente encontrado na aba 'Dados_api'.")
        except Exception as e:
            st.error(f"Erro ao carregar dados para o De-Para: {e}")

    st.subheader("📋 Produtos Cadastrados")
    try:
        dados_prod = aba_prod.get_all_records()
        df_exibir = pd.DataFrame(dados_prod).fillna("")
        st.dataframe(df_exibir, use_container_width=True)
    except Exception as e:
        st.error(f"Erro ao listar produtos: {e}")

def tela_cadastro(user):
    st.header("📝 Gestão de Pedidos")
    gc = get_gc()
    if not gc:
        st.error("Erro ao conectar com o Google Sheets.")
        return
        
    sh = gc.open(PLANILHA_NOME)
    
    # Abre ou valida a aba Dados_api
    try:
        aba_dados_api = sh.worksheet("Dados_api")
    except Exception:
        st.error("Aba 'Dados_api' não encontrada no Google Sheets! Verifique o nome exatamente como criado.")
        return

    st.subheader("🔄 Importar Pedidos do ERP para 'Dados_api'")
    api_url = st.secrets.get("API_URL", "https://surpass-entwine-sasquatch.ngrok-free.dev")
    data_filtro = st.date_input("Buscar pedidos a partir de:", value=pd.to_datetime('2026-01-01'))

    if st.button("🔎 Buscar Pedidos Pendentes no ERP", use_container_width=True):
        with st.spinner("Consultando ERP..."):
            df_api = buscar_pedidos_api(api_url, data_inicio=data_filtro.strftime('%Y-%m-%d'))
            st.session_state['df_api_bruto'] = df_api

    if 'df_api_bruto' in st.session_state:
        df_api = st.session_state['df_api_bruto']
        
        if df_api.empty:
            st.warning("Nenhum pedido pendente encontrado na API para esta data.")
        else:
            st.success(f"Foram retornados **{len(df_api)}** itens pendentes da API.")
            
            # Colunas exibidas na interface incluindo OBSERVACAO
            cols_desejadas = ['NUMEROPEDIDOVENDA', 'NOME_CLIENTE', 'UF', 'PRODUTO', 'QTDE', 'STATUS_ATENDIMENTO', 'OBSERVACAO']
            cols_presentes = [c for c in cols_desejadas if c in df_api.columns]
            
            st.dataframe(df_api[cols_presentes], use_container_width=True)

            if st.button("💾 Gravar na Aba 'Dados_api'", type="primary", use_container_width=True):
                with st.spinner("Enviando registros para a aba Dados_api..."):
                    linhas_para_gravar = []
                    
                    for idx, row in df_api.iterrows():
                        num_pedido = int(row['NUMEROPEDIDOVENDA']) if str(row['NUMEROPEDIDOVENDA']).isdigit() else str(row['NUMEROPEDIDOVENDA'])
                        cliente = str(row.get('NOME_CLIENTE', ''))
                        uf = str(row.get('UF', ''))
                        produto = str(row.get('PRODUTO', ''))
                        
                        try:
                            qtde = float(row.get('QTDE', 0))
                        except (ValueError, TypeError):
                            qtde = 0.0
                            
                        status = str(row.get('STATUS_ATENDIMENTO', 'Pendente'))
                        obs = str(row.get('OBSERVACAO', ''))

                        id_seq = idx + 1
                        
                        # Estrutura das colunas A até H em Dados_api:
                        # [ID, NUMEROPEDIDOVENDA, NOME_CLIENTE, UF, PRODUTO, QTDE, STATUS_ATENDIMENTO, OBSERVACAO]
                        linhas_para_gravar.append([id_seq, num_pedido, cliente, uf, produto, qtde, status, obs])

                    try:
                        aba_dados_api.resize(rows=1000, cols=10)
                        celulas_existentes = aba_dados_api.get_all_values()
                        if len(celulas_existentes) > 1:
                            aba_dados_api.delete_rows(2, len(celulas_existentes))

                        aba_dados_api.append_rows(linhas_para_gravar, value_input_option='USER_ENTERED')
                        
                        registrar_log(user['usuario'], "IMPORTACAO_RAW", f"{len(linhas_para_gravar)} itens salvos em Dados_api")
                        st.success(f"✅ Sucesso! {len(linhas_para_gravar)} registros gravados na aba **Dados_api**.")
                    
                    except Exception as err:
                        st.error(f"Ocorreu um erro ao gravar via gspread: {err}")

def converter_numero_sheet(val):
    """
    Elimina a parte decimal (tudo após vírgula ou ponto)
    para evitar inflar o peso na leitura de strings do Google Sheets.
    Ex: '7,227' -> 7 | '7.227' -> 7 | '20' -> 20
    """
    if pd.isna(val) or val == "" or val is None:
        return 0
    
    val_str = str(val).strip()
    
    # Corta o texto na primeira vírgula ou ponto que encontrar
    val_str = val_str.split(',')[0].split('.')[0]
    
    try:
        return int(val_str)
    except ValueError:
        return 0


def tela_pedidos(user):
    st.header("🚚 Montagem de Carga")
    gc = get_gc()
    if not gc:
        st.error("Erro de conexão.")
        return
        
    sh = gc.open(PLANILHA_NOME)
    aba_pedidos = sh.worksheet("pedidos")
    df_p = pd.DataFrame(aba_pedidos.get_all_records())
    
    if df_p.empty:
        st.info("Sem pedidos cadastrados.")
        return

    # --- CORREÇÃO DA LEITURA DE CAIXAS E PESO ---
    # Em vez do pd.to_numeric direto, usamos a conversão com tratamento de vírgula
    df_p['caixas'] = df_p['caixas'].apply(converter_numero_sheet)
    df_p['peso'] = df_p['peso'].apply(converter_numero_sheet)
    # --------------------------------------------

    df_pendentes = df_p[df_p['status'] == 'pendente'].copy()

    if df_pendentes.empty:
        st.info("Sem pedidos pendentes.")
        return

    df_pendentes['uf_extraida'] = df_pendentes['cliente'].str.extract(r'\((.*?)\)')
    ufs = sorted(df_pendentes['uf_extraida'].dropna().unique().tolist())
    f_uf = st.sidebar.multiselect("Filtrar por UF", options=ufs, default=ufs)
    df_filtrado = df_pendentes[df_pendentes['uf_extraida'].isin(f_uf)]

    selecao = st.dataframe(
        df_filtrado.drop(columns=['uf_extraida']), 
        use_container_width=True, 
        hide_index=True, 
        on_select="rerun", 
        selection_mode="multi-row"
    )
    
    if selecao.selection.rows:
        df_sel = df_filtrado.iloc[selecao.selection.rows]
        matriz = df_sel.pivot_table(index='cliente', columns='produto', values='caixas', aggfunc='sum', fill_value=0)
        matriz['TOTAL CX'] = matriz.sum(axis=1)
        
        totais_cx = matriz.sum().to_frame().T
        totais_cx.index = ['TOTAL CAIXAS']
        
        peso_resumo = df_sel.groupby('produto')['peso'].sum().to_frame().T
        peso_resumo = peso_resumo.reindex(columns=matriz.columns, fill_value=0)
        peso_resumo.index = ['TOTAL PESO (kg)']
        
        # Soma do peso mantendo a precisão decimal correta
        peso_resumo['TOTAL CX'] = round(df_sel['peso'].sum(), 3)
        
        df_final = pd.concat([matriz, totais_cx, peso_resumo])
        
        st.subheader("📊 Matriz de Carregamento")
        st.dataframe(df_final, use_container_width=True)
        
        c_pdf, c_conf = st.columns(2)
        try:
            pdf_bytes = gerar_pdf_rota(df_final)
            c_pdf.download_button(
                "📄 Baixar PDF do Mapa", 
                data=pdf_bytes, 
                file_name=f"mapa_{datetime.now().strftime('%d%m_%H%M')}.pdf", 
                mime="application/pdf", 
                use_container_width=True
            )
        except Exception as e:
            c_pdf.error(f"Erro PDF: {e}")
        
        if (user['nivel'] == 'total' or user['usuario'] == 'admin') and c_conf.button("🚀 Confirmar Saída para Rota", use_container_width=True):
            ids = df_sel['id'].astype(str).tolist()
            data = aba_pedidos.get_all_values()
            for i, lin in enumerate(data):
                if str(lin[0]) in ids:
                    aba_pedidos.update_cell(i + 1, 6, "em rota")
            registrar_log(user['usuario'], "ROTA", "Carga confirmada")
            st.rerun()
        elif user['nivel'] == 'visualizacao':
            c_conf.warning("Nível 'visualizacao' não pode confirmar rota.")

def tela_gestao_rotas(user):
    st.header("🔄 Gestão de Pedidos em Rota")
    gc = get_gc()
    if not gc:
        st.error("Erro de conexão com o Google Sheets.")
        return
    sh_pedidos = gc.open(PLANILHA_NOME).worksheet("pedidos")
    sh_hist = gc.open(PLANILHA_NOME).worksheet("historico")
    
    df = pd.DataFrame(sh_pedidos.get_all_records())
    if df.empty:
        st.info("Nada em rota.")
        return
    df_rota = df[df['status'] == 'em rota'].copy()
    
    if df_rota.empty:
        st.info("Nada em rota.")
        return
    
    selecao = st.dataframe(df_rota, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row")
    
    if selecao.selection.rows:
        df_sel = df_rota.iloc[selecao.selection.rows]
        c1, c2 = st.columns(2)
        
        with c1.expander("❌ Cancelar Total (Volta para Pendente)"):
            if st.button("Confirmar Retorno"):
                ids = df_sel['id'].astype(str).tolist()
                data = sh_pedidos.get_all_values()
                for i, row in enumerate(data):
                    if str(row[0]) in ids:
                        sh_pedidos.update_cell(i + 1, 6, "pendente")
                registrar_log(user['usuario'], "ROTA", f"Retorno confirmado para IDs: {ids}")
                st.rerun()
        
        with c2.expander("📉 Confirmar Entrega (Move para Histórico)"):
            for _, r in df_sel.iterrows():
                st.markdown(f"**Item ID {r['id']} - {r['produto']} ({r['cliente']})**")
                
                qtd_s = st.number_input(
                    f"Qtd entregue #{r['id']}", 
                    min_value=0, 
                    max_value=int(r['caixas']), 
                    value=int(r['caixas']), 
                    key=f"rot_{r['id']}"
                )
                
                sobra = int(r['caixas']) - qtd_s
                num_pedido_antigo = str(r.get('NUMEROPEDIDOVENDA', '')).strip()

                novo_num_pedido = num_pedido_antigo
                if sobra > 0:
                    novo_num_pedido = st.text_input(
                        f"⚠️ Novo nº do Pedido ERP para a Sobra (#{r['id']}):",
                        value=num_pedido_antigo,
                        key=f"novo_num_{r['id']}",
                        help="Altere este campo caso o ERP tenha gerado um novo número para o saldo remanescente."
                    ).strip()

                if st.button(f"Confirmar Baixa {r['id']}", key=f"btn_baixa_{r['id']}"):
                    peso_u = float(r['peso']) / int(r['caixas']) if int(r['caixas']) > 0 else 0
                    
                    sh_hist.append_row([
                        r['id'], 
                        r['cliente'], 
                        r['produto'], 
                        qtd_s, 
                        round(qtd_s * peso_u, 2), 
                        "entregue", 
                        datetime.now().strftime("%d/%m/%Y"),
                        num_pedido_antigo
                    ], value_input_option='USER_ENTERED')
                    
                    if sobra > 0:
                        sh_pedidos.append_row([
                            r['id'], 
                            r['cliente'], 
                            r['produto'], 
                            sobra, 
                            round(sobra * peso_u, 2), 
                            "pendente",
                            novo_num_pedido
                        ], value_input_option='USER_ENTERED')
                    
                    data_ped = sh_pedidos.get_all_values()
                    for i, lin in enumerate(data_ped):
                        if len(lin) > 0 and str(lin[0]) == str(r['id']) and len(lin) >= 6 and lin[5] == "em rota":
                            sh_pedidos.delete_rows(i + 1)
                            break

                    log_msg = f"Baixa ID {r['id']} (Entregue: {qtd_s} cx no Pedido {num_pedido_antigo})"
                    if sobra > 0:
                        log_msg += f" | Sobra: {sobra} cx no Novo Pedido {novo_num_pedido}"
                    
                    registrar_log(user['usuario'], "BAIXA_PARCIAL" if sobra > 0 else "BAIXA_TOTAL", log_msg)
                    st.success("Baixa realizada com sucesso!")
                    st.rerun()
                st.divider()

# --- MAIN ---
st.set_page_config(page_title="Sistema de Carga", layout="wide")
if 'usuario_logado' not in st.session_state:
    st.session_state.usuario_logado = None

if st.session_state.usuario_logado is None:
    st.title("Login")
    with st.form("l"):
        u, s = st.text_input("Usuário"), st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            d = login_usuario(u, s)
            if d:
                st.session_state.usuario_logado = d
                st.rerun()
            else:
                st.error("Login inválido")
else:
    user = st.session_state.usuario_logado
    st.sidebar.title(f"👤 {user['usuario']}")
    op_full = ["Cadastro", "Produtos", "Pedidos", "Gestão de Rotas", "Relatórios", "Gestão de Usuários", "Logs"]
    opcoes = op_full if user.get('modulos') == 'todos' else user.get('modulos', '').split(',')
    menu = st.sidebar.radio("Menu:", opcoes)
    
    if menu == "Cadastro": tela_cadastro(user)
    elif menu == "Produtos": tela_produtos(user)
    elif menu == "Pedidos": tela_pedidos(user)
    elif menu == "Gestão de Rotas": tela_gestao_rotas(user)
    elif menu == "Relatórios":
        st.header("📊 Relatório de Entregas (Histórico)")
        try:
            df_h = pd.DataFrame(get_gc().open(PLANILHA_NOME).worksheet("historico").get_all_records())
            st.dataframe(df_h.sort_index(ascending=False), use_container_width=True)
        except Exception:
            st.error("Aba 'historico' não encontrada ou vazia.")
    elif menu == "Gestão de Usuários": tela_usuarios(user)
    elif menu == "Logs":
        try:
            df_l = pd.DataFrame(get_gc().open(PLANILHA_NOME).worksheet("log_operacoes").get_all_records())
            st.dataframe(df_l.sort_index(ascending=False), use_container_width=True)
        except Exception:
            st.error("Aba 'log_operacoes' não encontrada ou vazia.")
    
    if st.sidebar.button("Sair"):
        st.session_state.usuario_logado = None
        st.rerun()
