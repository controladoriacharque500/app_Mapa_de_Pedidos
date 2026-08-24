import streamlit as st
import pandas as pd
from datetime import datetime
import gspread
from fpdf import FPDF
import requests

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

def limpar_e_converter_float(valor, padrao=0.0):
    """Trata conversões de número garantindo retorno float seguro."""
    if pd.isna(valor) or valor == "" or valor is None:
        return float(padrao)
    
    val_str = str(valor).strip()
    if ',' in val_str:
        val_str = val_str.replace('.', '').replace(',', '.')
    try:
        return float(val_str)
    except ValueError:
        return float(padrao)

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
        is_total_row = index in ['TOTAL CAIXAS', 'TOTAL PESO (kg)']
        
        if is_total_row: 
            pdf.set_fill_color(230, 230, 230)
            pdf.set_font("Arial", "B", 7)
        else:
            pdf.set_font("Arial", "", 7)
            
        pdf.cell(50, 6, label[:30], 1, 0, 'L', is_total_row)
        
        for col in cols:
            val = row[col]
            if not is_total_row and (pd.isna(val) or val == 0):
                txt = ""
            else:
                txt = f"{val:.2f}" if "PESO" in str(index) else str(int(val))
                
            pdf.cell(col_width, 6, txt, 1, 0, 'C', is_total_row)
        pdf.ln()
    return bytes(pdf.output())

# --- FUNÇÃO DE PROCESSAMENTO COM TRAVA DE SEGURANÇA PARA CLIENTES ---

def processar_dados_api_para_pedidos(user):
    """
    Lê Dados_api, verifica se TODOS os clientes possuem abreviação cadastrada na aba 'cliente'.
    Se houver cliente sem abreviação, BLOQUEIA o processamento e NÃO apaga a Dados_api.
    """
    gc = get_gc()
    if not gc:
        return 0, "Erro na conexão com o Google Sheets.", False

    sh = gc.open(PLANILHA_NOME)
    aba_api = sh.worksheet("Dados_api")
    aba_prod = sh.worksheet("produtos")
    aba_pedidos = sh.worksheet("pedidos")
    
    # 1. Leitura do De-Para de Clientes
    try:
        aba_cli = sh.worksheet("cliente")
        df_cli = pd.DataFrame(aba_cli.get_all_records()).fillna("")
    except Exception:
        df_cli = pd.DataFrame()

    df_api = pd.DataFrame(aba_api.get_all_records()).fillna("")
    df_prod = pd.DataFrame(aba_prod.get_all_records()).fillna("")
    df_ped = pd.DataFrame(aba_pedidos.get_all_records()).fillna("")

    if df_api.empty:
        return 0, "Aba Dados_api está vazia.", True

    # Monta mapa de clientes
    de_para_cli = {}
    if not df_cli.empty and 'Nome_Sistema' in df_cli.columns and 'Nome_Abreviado' in df_cli.columns:
        for _, r in df_cli.iterrows():
            nome_sis = str(r.get('Nome_Sistema', '')).strip()
            nome_abrev = str(r.get('Nome_Abreviado', '')).strip()
            if nome_sis and nome_abrev:
                de_para_cli[nome_sis] = nome_abrev

    # --- TRAVA DE SEGURANÇA: VERIFICAÇÃO DE CLIENTES NÃO ABREVIADOS ---
    clientes_na_api = set(df_api['NOME_CLIENTE'].astype(str).str.strip().unique()) if 'NOME_CLIENTE' in df_api.columns else set()
    clientes_na_api.discard("") # Remove vazios se houver

    clientes_sem_abreviacao = [cli for cli in clientes_na_api if cli not in de_para_cli]

    if clientes_sem_abreviacao:
        msg_erro = f"🛑 **BLOQUEIO DE SEGURANÇA:** Existem {len(clientes_sem_abreviacao)} cliente(s) pendentes de abreviação na aba 'Clientes':\n\n"
        for cli in clientes_sem_abreviacao:
            msg_erro += f"• **{cli}**\n"
        msg_erro += "\nPor favor, acesse o menu **Clientes**, faça a abreviação e tente novamente."
        return 0, msg_erro, False

    # 2. Leitura do Histórico de Pedidos para evitar duplicidade
    try:
        aba_hist = sh.worksheet("historico")
        df_hist = pd.DataFrame(aba_hist.get_all_records()).fillna("")
    except Exception:
        df_hist = pd.DataFrame()

    # Map de Produtos
    de_para_map = {}
    if not df_prod.empty and 'descricao_sistema' in df_prod.columns:
        for _, r in df_prod.iterrows():
            desc_sis = str(r.get('descricao_sistema', '')).strip()
            if desc_sis:
                desc_abrev = str(r.get('descricao', '')).strip()
                p_unit = limpar_e_converter_float(r.get('peso_unitario'), padrao=1.0)
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

    for _, row in df_api.iterrows():
        num_pedido = str(row.get('NUMEROPEDIDOVENDA', '')).strip()
        prod_erp = str(row.get('PRODUTO', '')).strip()

        if not num_pedido and not prod_erp:
            continue

        if num_pedido in pedidos_existentes:
            continue

        if prod_erp in de_para_map:
            desc_abrev, peso_unit, tipo_peso = de_para_map[prod_erp]
            peso_unit_seguro = peso_unit if (peso_unit and peso_unit > 0) else 1.0

            qtde_raw = str(row.get('QTDE', 0)).strip()
            if "." in qtde_raw and "," not in qtde_raw:
                qtde_num = limpar_e_converter_float(qtde_raw.replace(".", ""))
            else:
                qtde_num = limpar_e_converter_float(qtde_raw)

            # Lógica de conversão
            if tipo_peso == "padrão":
                if qtde_num >= peso_unit_seguro and (qtde_num % peso_unit_seguro == 0):
                    caixas = int(qtde_num // peso_unit_seguro)
                    qtde_peso = round(qtde_num, 3)
                elif qtde_num > 1000:
                    qtde_peso = round(qtde_num / 1000.0, 3)
                    caixas = int(round(qtde_peso / peso_unit_seguro))
                else:
                    qtde_peso = round(qtde_num, 3)
                    caixas = int(round(qtde_peso / peso_unit_seguro))
                    if caixas == 0 and qtde_peso > 0:
                        caixas = 1
            else:
                if qtde_num > 1000 and (qtde_num % peso_unit_seguro != 0):
                    qtde_peso = round(qtde_num / 1000.0, 3)
                else:
                    qtde_peso = round(qtde_num, 3)
                caixas = 1 if (0 < qtde_peso <= peso_unit_seguro) else int(round(qtde_peso / peso_unit_seguro))

            # Nome abreviado do cliente garantido pela trava acima
            nome_cli_erp = str(row.get('NOME_CLIENTE', '')).strip()
            nome_cli_final = de_para_cli[nome_cli_erp]

            obs_raw = row.get('OBSERVACAO', row.get('OBS', ''))
            obs_cli = str(obs_raw).strip() if pd.notna(obs_raw) and str(obs_raw).upper() != "NONE" else ""
            uf_cli = str(row.get('UF', '')).strip()

            if obs_cli:
                cliente_fmt = f"{nome_cli_final} [{obs_cli}] ({uf_cli})"
            else:
                cliente_fmt = f"{nome_cli_final} ({uf_cli})"
            
            ultimo_id += 1
            novas_linhas_pedidos.append([
                ultimo_id, cliente_fmt, desc_abrev, caixas, qtde_peso, "pendente", num_pedido
            ])
        else:
            linhas_api_para_manter.append(row.tolist())

    registros_processados = len(novas_linhas_pedidos)

    # Limpa Dados_api somente SE passou na trava e processou os itens
    valores_existentes = aba_api.get_all_values()
    if len(valores_existentes) > 1:
        aba_api.delete_rows(2, len(valores_existentes))

    if linhas_api_para_manter:
        aba_api.append_rows(linhas_api_para_manter, value_input_option='USER_ENTERED')

    if registros_processados > 0:
        aba_pedidos.append_rows(novas_linhas_pedidos, value_input_option='USER_ENTERED')
        registrar_log(user['usuario'], "IMPORTACAO_PEDIDOS", f"{registros_processados} pedidos transferidos de Dados_api para pedidos")
        return registros_processados, f"✅ {registros_processados} item(ns) transferido(s) com sucesso!", True

    return 0, "Nenhum pedido pendente para processamento.", True

# --- TELAS DO SISTEMA ---

def tela_clientes(user):
    st.header("👤 Cadastro e Abreviação de Clientes (De-Para)")
    gc = get_gc()
    if not gc:
        st.error("Erro ao conectar com o Google Sheets.")
        return
        
    sh = gc.open(PLANILHA_NOME)
    
    try:
        aba_cli = sh.worksheet("cliente")
    except Exception:
        st.error("Aba 'cliente' não encontrada no Google Sheets! Crie uma aba com o nome 'cliente' e os cabeçalhos: Nome_Sistema, Nome_Abreviado")
        return

    try:
        aba_api = sh.worksheet("Dados_api")
        df_api = pd.DataFrame(aba_api.get_all_records()).fillna("")
    except Exception:
        df_api = pd.DataFrame()

    df_cli = pd.DataFrame(aba_cli.get_all_records()).fillna("")
    
    if 'Nome_Sistema' not in df_cli.columns:
        df_cli['Nome_Sistema'] = ""
    if 'Nome_Abreviado' not in df_cli.columns:
        df_cli['Nome_Abreviado'] = ""

    clientes_api = [str(c).strip() for c in df_api['NOME_CLIENTE'].dropna().unique() if str(c).strip() != ""] if not df_api.empty and 'NOME_CLIENTE' in df_api.columns else []
    clientes_cadastrados = [str(c).strip() for c in df_cli['Nome_Sistema'].dropna().unique() if str(c).strip() != ""]
    clientes_pendentes = [c for c in clientes_api if c not in clientes_cadastrados]

    with st.expander("➕ Abreviar Novo Cliente vindo da API / ERP", expanded=True):
        if clientes_pendentes:
            st.warning(f"⚠️ Existe(m) **{len(clientes_pendentes)}** cliente(s) novo(s) na aba Dados_api que precisam ser abreviados antes de transferir os pedidos!")
            with st.form("form_novo_cliente_api"):
                cli_sel = st.selectbox("Selecione o Cliente do ERP:", options=clientes_pendentes)
                nome_abrev_input = st.text_input("Digite o Nome Abreviado para o PDF/Mapa:", value=cli_sel[:20])
                
                if st.form_submit_button("💾 Salvar Abreviação"):
                    if cli_sel and nome_abrev_input:
                        aba_cli.append_row([cli_sel, nome_abrev_input.strip()], value_input_option='USER_ENTERED')
                        registrar_log(user['usuario'], "DE_PARA_CLIENTE", f"Cadastrado {cli_sel} -> {nome_abrev_input}")
                        st.success(f"Cliente '{cli_sel}' abreviado como '{nome_abrev_input}' com sucesso!")
                        st.rerun()
                    else:
                        st.warning("Preencha todos os campos.")
        else:
            st.success("🎉 Todos os clientes da aba Dados_api já possuem abreviação cadastrada!")

    with st.expander("📝 Cadastrar/Editar Abreviação Manualmente"):
        with st.form("form_cliente_manual"):
            nome_sis_man = st.text_input("Nome_Sistema (exatamente como vem no ERP)")
            nome_abrev_man = st.text_input("Nome_Abreviado")
            
            if st.form_submit_button("Salvar Registro"):
                if nome_sis_man and nome_abrev_man:
                    if not df_cli.empty and nome_sis_man in df_cli['Nome_Sistema'].values:
                        cel = aba_cli.find(nome_sis_man)
                        if cel:
                            aba_cli.update_cell(cel.row, 2, nome_abrev_man.strip())
                            st.success("Abreviação atualizada!")
                    else:
                        aba_cli.append_row([nome_sis_man.strip(), nome_abrev_man.strip()], value_input_option='USER_ENTERED')
                        st.success("Cliente cadastrado!")
                    registrar_log(user['usuario'], "CLIENTE_MANUAL", f"Salvo {nome_sis_man} -> {nome_abrev_man}")
                    st.rerun()

    st.subheader("📋 Clientes Cadastrados (De-Para)")
    if not df_cli.empty:
        st.dataframe(df_cli, use_container_width=True)
    else:
        st.info("Nenhum cliente cadastrado ainda.")

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
            m3 = st.checkbox("Clientes", True)
            m4 = st.checkbox("Pedidos", True)
            m5 = st.checkbox("Gestão de Rotas", True)
            m6 = st.checkbox("Gestão de Usuários", False)
            m7 = st.checkbox("Logs", True)
            m8 = st.checkbox("Relatórios", True)
            
            if st.form_submit_button("Salvar"):
                mods = [m for m, val in zip(["Cadastro", "Produtos", "Clientes", "Pedidos", "Gestão de Rotas", "Gestão de Usuários", "Logs", "Relatórios"], [m1, m2, m3, m4, m5, m6, m7, m8]) if val]
                df_u = pd.DataFrame(aba_user.get_all_records())
                if not df_u.empty and novo_u in df_u['usuario'].values:
                    idx = df_u[df_u['usuario'] == novo_u].index[0] + 2
                    aba_user.delete_rows(int(idx))
                aba_user.append_row([novo_u, nova_s, nivel, ",".join(mods)])
                registrar_log(user['usuario'], "USUÁRIO", f"Salvo/Atualizado usuário {novo_u}")
                st.success("Usuário salvo com sucesso!")
                st.rerun()
                
    st.dataframe(pd.DataFrame(aba_user.get_all_records()), use_container_width=True)

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
                        qtd, msg, ok = processar_dados_api_para_pedidos(user)
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)
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
                                    
                                    qtd_proc, msg_proc, ok_proc = processar_dados_api_para_pedidos(user)
                                    if ok_proc:
                                        st.success(f"✅ Vínculo salvo! {msg_proc}")
                                        st.rerun()
                                    else:
                                        st.error(msg_proc)
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
    
    try:
        aba_dados_api = sh.worksheet("Dados_api")
    except Exception:
        st.error("Aba 'Dados_api' não encontrada no Google Sheets!")
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
    if pd.isna(val) or val == "" or val is None:
        return 0
    val_str = str(val).strip().split(',')[0].split('.')[0]
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

    df_p['caixas'] = df_p['caixas'].apply(converter_numero_sheet)
    df_p['peso'] = df_p['peso'].apply(converter_numero_sheet)

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
    op_full = ["Cadastro", "Produtos", "Clientes", "Pedidos", "Gestão de Rotas", "Relatórios", "Gestão de Usuários", "Logs"]
    opcoes = op_full if user.get('modulos') == 'todos' else user.get('modulos', '').split(',')
    
    opcoes = [o.strip() for o in opcoes if o.strip() in op_full]
    if not opcoes:
        opcoes = op_full

    menu = st.sidebar.radio("Menu:", opcoes)
    
    if menu == "Cadastro": tela_cadastro(user)
    elif menu == "Produtos": tela_produtos(user)
    elif menu == "Clientes": tela_clientes(user)
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
