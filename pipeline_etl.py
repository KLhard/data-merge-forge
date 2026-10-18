"""
================================================================================
PIPELINE DE INTEGRAÇÃO E TRANSFORMAÇÃO DE DADOS HETEROGÊNEOS
================================================================================
Atividade: Extração de valor de bases de dados heterogêneas (Governança de TI)

Bases de entrada:
    1) Base_de_Dados_1-_Cadastro_de_Clientes.xlsx     (cadastro / lead)
    2) Base_de_Dados_2-_Acessos_e_Compras_no_Site.xlsx (sessões de navegação)
    3) Base_de_Dados_3-_Detalhes_dos_Pedidos.xlsx      (itens efetivamente comprados)

Saída:
    - clientes_360.csv  -> tabela mestre, 1 linha por cliente, com as métricas
                            de negócio Total_Gasto e Conversao.

Cada etapa abaixo contém, em comentário, a JUSTIFICATIVA da técnica escolhida
(governança), não apenas o "como".
================================================================================
"""

import io
import re
import unicodedata
import difflib
from datetime import datetime

import pandas as pd
import numpy as np

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 160)

CAMINHO_CLIENTES = "/mnt/user-data/uploads/Base_de_Dados_1-_Cadastro_de_Clientes.xlsx"
CAMINHO_ACESSOS = "/mnt/user-data/uploads/Base_de_Dados_2-_Acessos_e_Compras_no_Site.xlsx"
CAMINHO_PEDIDOS = "/mnt/user-data/uploads/Base_de_Dados_3-_Detalhes_dos_Pedidos.xlsx"

CAMINHO_SAIDA = "clientes_360.csv"


# ==============================================================================
# ETAPA 0 — LEITURA DOS ARQUIVOS (correção de um problema estrutural)
# ==============================================================================
# DIAGNÓSTICO: os três .xlsx não foram exportados como planilha "de verdade".
# Cada linha inteira (todas as colunas, separadas por vírgula) foi jogada dentro
# de UMA ÚNICA célula da coluna A. Um pd.read_excel() comum, portanto, devolve
# um DataFrame de 1 coluna só, inutilizável para merge.
#
# POR QUE ESSA TÉCNICA: em vez de reformatar o Excel manualmente (não escala e
# não é reprodutível), tratamos o conteúdo da coluna A como um "arquivo CSV
# embutido": concatenamos todas as linhas em uma string e reprocessamos com
# pd.read_csv(io.StringIO(...)). Isso reaproveita o parser de CSV do pandas,
# que já sabe lidar com vírgulas dentro de aspas (ex.: o produto
# 'Livro "Aprenda Mineração de Dados"' na Base 3, que contém um título com
# aspas). Um split(',') manual quebraria nesse caso.
def carregar_excel_mal_formatado(caminho: str) -> pd.DataFrame:
    bruto = pd.read_excel(caminho, header=None)
    texto_csv = "\n".join(bruto[0].astype(str).tolist())
    return pd.read_csv(io.StringIO(texto_csv))


# ==============================================================================
# FUNÇÕES AUXILIARES DE LIMPEZA (reaproveitadas nas 3 bases)
# ==============================================================================

def normalizar_texto(valor: str) -> str:
    """
    Remove acentuação, espaços extras e padroniza para minúsculo.
    POR QUÊ: essa função NÃO é usada para exibição, e sim como CHAVE DE
    JUNÇÃO/COMPARAÇÃO. Nomes como 'José Alves' e 'jose alves ' precisam ser
    reconhecidos como o mesmo texto antes de qualquer merge ou deduplicação.
    """
    if pd.isna(valor):
        return ""
    valor = str(valor).strip().lower()
    valor = unicodedata.normalize("NFKD", valor).encode("ascii", "ignore").decode("ascii")
    valor = re.sub(r"\s+", " ", valor)
    return valor


def limpar_telefone(valor) -> str:
    """
    Extrai somente os dígitos e reformata no padrão (XX) 9XXXX-XXXX.
    POR QUÊ REGEX + PADRÃO ÚNICO: a base traz o mesmo telefone em >5 formatos
    distintos ('(11) 98765-4321', '11987654322', '11-99999-2222', 'NA'...).
    Sem padronizar, o mesmo número seria tratado como valores diferentes em
    qualquer agrupamento ou exportação para sistemas downstream (ex.: CRM).
    Optamos por reformatar (não apenas remover a máscara) porque o padrão
    (XX) 9XXXX-XXXX é o formato de referência de telefone celular no Brasil.
    """
    if pd.isna(valor) or str(valor).strip().upper() == "NA":
        return np.nan
    digitos = re.sub(r"\D", "", str(valor))
    if len(digitos) == 11:  # DDD + 9 dígitos (celular)
        return f"({digitos[0:2]}) {digitos[2:7]}-{digitos[7:11]}"
    if len(digitos) == 10:  # DDD + 8 dígitos (fixo)
        return f"({digitos[0:2]}) {digitos[2:6]}-{digitos[6:10]}"
    return np.nan  # número fora do padrão esperado -> tratado como ausente


REGEX_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validar_email(valor) -> bool:
    """
    Valida formato básico usuario@dominio.tld.
    POR QUÊ NÃO 'CONSERTAR' O E-MAIL: encontramos e-mails como 'maria@email'
    (sem TLD) e 'fernandalima.com' (sem '@'). Não há forma segura de inferir
    o valor correto sem risco de enviar comunicação para o endereço errado.
    A decisão de governança foi: SINALIZAR como inválido (Email_Valido=False)
    em vez de adivinhar ou descartar a linha inteira — o restante do cadastro
    (nome, telefone, nascimento) continua íntegro e útil.
    """
    if pd.isna(valor):
        return False
    return bool(REGEX_EMAIL.match(str(valor).strip()))


# ==============================================================================
# ETAPA 1 — PRÉ-PROCESSAMENTO: BASE 1 (CADASTRO DE CLIENTES)
# ==============================================================================
def tratar_clientes(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["Nome"] = df["Nome"].astype(str).str.strip()
    df["Nome_Norm"] = df["Nome"].apply(normalizar_texto)

    df["Telefone"] = df["Telefone"].apply(limpar_telefone)

    df["Email"] = df["Email"].astype(str).str.strip().str.lower()
    df["Email_Valido"] = df["Email"].apply(validar_email)

    df["Data_Nascimento"] = pd.to_datetime(df["Data_Nascimento"], errors="coerce")

    # --------------------------------------------------------------------
    # TRATAMENTO DE DUPLICIDADE SISTÊMICA
    # --------------------------------------------------------------------
    # DIAGNÓSTICO: 105 linhas, mas só 40 nomes distintos e 42 e-mails
    # distintos -> a mesma pessoa foi cadastrada várias vezes (ex.: 'João
    # Santos' aparece 3x com nome/telefone/nascimento idênticos).
    #
    # CHAVE DE DEDUPLICAÇÃO ESCOLHIDA: Nome_Norm + Data_Nascimento.
    # POR QUÊ NÃO USAR E-MAIL COMO CHAVE: encontramos casos do MESMO cliente
    # com e-mail digitado errado em um dos cadastros (ex.: Fernanda Lima
    # aparece com 'fernandalima.com' em um registro e
    # 'fernandalima@email.com' nos demais — mesmo telefone e nascimento).
    # Usar e-mail como chave faria o pipeline tratar essa pessoa como 2
    # clientes diferentes. Data de nascimento é um atributo estável de
    # identidade e, combinada ao nome normalizado, tem baixíssima chance de
    # colisão espúria neste contexto.
    #
    # CRITÉRIO DE DESEMPATE: ao colapsar duplicatas, mantemos a linha com
    # o maior número de campos preenchidos (telefone e e-mail válido têm
    # prioridade) e, em caso de empate, o menor ID_Cliente (cadastro mais
    # antigo) como identificador canônico.
    df["_score_completude"] = (
        df["Telefone"].notna().astype(int) + df["Email_Valido"].astype(int)
    )
    df = df.sort_values(
        by=["Nome_Norm", "Data_Nascimento", "_score_completude", "ID_Cliente"],
        ascending=[True, True, False, True],
    )
    antes = len(df)
    df_dedup = df.drop_duplicates(subset=["Nome_Norm", "Data_Nascimento"], keep="first").copy()
    depois = len(df_dedup)
    print(f"[Clientes] Duplicidade cadastral removida: {antes} -> {depois} clientes únicos "
          f"({antes - depois} registros redundantes eliminados).")

    df_dedup = df_dedup.drop(columns=["_score_completude"])
    df_dedup = df_dedup.rename(columns={"ID_Cliente": "ID_Cliente_Canonico"})

    return df_dedup.reset_index(drop=True)


# ==============================================================================
# ETAPA 2 — PRÉ-PROCESSAMENTO: BASE 2 (ACESSOS E COMPRAS NO SITE)
# ==============================================================================
def tratar_acessos(df: pd.DataFrame, nomes_validos_norm: set) -> pd.DataFrame:
    df = df.copy()

    df["Nome_Cliente"] = df["Nome_Cliente"].astype(str).str.strip()
    df["Nome_Norm"] = df["Nome_Cliente"].apply(normalizar_texto)

    # --------------------------------------------------------------------
    # RECONCILIAÇÃO DE CHAVE DE JUNÇÃO (fuzzy matching)
    # --------------------------------------------------------------------
    # DIAGNÓSTICO: esta base NÃO possui ID_Cliente — o único vínculo com o
    # cadastro é o NOME digitado manualmente durante a sessão. Encontramos
    # 'José Alvez' aqui, enquanto o cadastro tem 'José Alves' (erro de
    # digitação de 1 caractere). Um merge exato perderia essas sessões.
    #
    # POR QUÊ FUZZY MATCHING (difflib) E NÃO CORREÇÃO MANUAL: correção manual
    # não escala e não é reprodutível para novas cargas de dados. Usamos
    # difflib.get_close_matches com cutoff=0.85 (alta similaridade) apenas
    # para os nomes que NÃO possuem correspondência exata — isso minimiza o
    # risco de juntar pessoas diferentes por engano, corrigindo somente erros
    # de digitação plausíveis.
    sem_correspondencia = sorted(set(df["Nome_Norm"]) - nomes_validos_norm)
    mapa_correcao = {}
    for nome in sem_correspondencia:
        candidatos = difflib.get_close_matches(nome, nomes_validos_norm, n=1, cutoff=0.85)
        if candidatos:
            mapa_correcao[nome] = candidatos[0]

    if mapa_correcao:
        print(f"[Acessos] Nomes corrigidos por similaridade (fuzzy match): {mapa_correcao}")
    df["Nome_Norm"] = df["Nome_Norm"].replace(mapa_correcao)

    # Horários -> duração da sessão em segundos (feature útil de engajamento)
    df["Horario_Inicio"] = pd.to_datetime(df["Horario_Inicio"], format="%H:%M:%S", errors="coerce")
    df["Horario_Termino"] = pd.to_datetime(df["Horario_Termino"], format="%H:%M:%S", errors="coerce")
    df["Duracao_Sessao_Seg"] = (df["Horario_Termino"] - df["Horario_Inicio"]).dt.total_seconds()

    df["Compra_Finalizada"] = (
        df["Compra_Finalizada"].astype(str).str.strip().str.lower().map({"sim": True, "nao": False})
    )

    # --------------------------------------------------------------------
    # Valor_Carrinho nulo: NÃO preenchemos com 0 nem com média.
    # --------------------------------------------------------------------
    # POR QUÊ: 0 sugeriria "carrinho vazio", o que é factualmente incerto
    # (o dado simplesmente não foi capturado); e a média distorceria a
    # variável para análises financeiras. Mantemos NaN aqui e, na etapa de
    # integração, o valor real gasto por sessão será obtido a partir da
    # Base 3 (Pedidos), que é a fonte de verdade para valores transacionados.
    df["Valor_Carrinho"] = pd.to_numeric(df["Valor_Carrinho"], errors="coerce")

    inconsistentes = df[(df["Compra_Finalizada"]) & (df["Valor_Carrinho"].isna())]
    if len(inconsistentes) > 0:
        print(f"[Acessos] {len(inconsistentes)} sessão(ões) com Compra_Finalizada=True e "
              f"Valor_Carrinho nulo (inconsistência sinalizada, não corrigida artificialmente).")

    return df.reset_index(drop=True)


# ==============================================================================
# ETAPA 3 — PRÉ-PROCESSAMENTO: BASE 3 (DETALHES DOS PEDIDOS)
# ==============================================================================
def tratar_pedidos(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["Quantidade"] = pd.to_numeric(df["Quantidade"], errors="coerce").fillna(0).astype(int)
    df["Preco_Unitario"] = pd.to_numeric(df["Preco_Unitario"], errors="coerce")
    # CORREÇÃO: cerca de metade das linhas tinha um espaço em branco extra ao
    # final da data (ex.: '2025-01-24 '). Sem o .str.strip(), o pandas infere
    # o formato a partir do primeiro valor da coluna e aplica esse formato de
    # forma rígida aos demais — como a coluna mistura strings com e sem esse
    # espaço, ~metade das datas virava NaT silenciosamente. strip() antes de
    # converter elimina a ambiguidade de formato na raiz.
    df["Data_Compra"] = pd.to_datetime(df["Data_Compra"].astype(str).str.strip(), errors="coerce")

    # Produto nulo: mantemos a linha (quantidade e preço são válidos e
    # compõem o faturamento real), apenas rotulamos o texto ausente.
    # POR QUÊ NÃO DESCARTAR A LINHA: o valor financeiro do pedido é
    # verdadeiro e relevante para o Total_Gasto do cliente; descartar a
    # linha subestimaria a receita real.
    n_produto_nulo = df["Produto"].isna().sum()
    if n_produto_nulo:
        print(f"[Pedidos] {n_produto_nulo} pedido(s) com Produto não informado -> "
              f"rotulados como 'Não informado' (linha mantida pelo valor financeiro).")
    df["Produto"] = df["Produto"].fillna("Não informado")
    df["Categoria"] = df["Categoria"].fillna("Não informado")

    # Feature de item: subtotal por linha de pedido
    df["Subtotal_Item"] = df["Quantidade"] * df["Preco_Unitario"]

    # --------------------------------------------------------------------
    # DUPLICIDADE SISTÊMICA CRÍTICA (lançamento em dobro de pedidos)
    # --------------------------------------------------------------------
    # DIAGNÓSTICO: 114 das 115 linhas desta base são o MESMO pedido lançado
    # duas vezes — idênticas em ID_Sessao + Produto + Categoria + Quantidade
    # + Preco_Unitario + Data_Compra, mudando apenas o ID_Pedido (chave
    # técnica sequencial, não uma nova venda). Isso é diferente do padrão
    # normal da base (uma sessão pode ter 2 produtos DIFERENTES); aqui é o
    # mesmo produto, mesmo preço, mesma sessão e mesma data repetidos.
    # RISCO DE NEGÓCIO: se não removida, essa duplicidade infla a receita
    # reportada em quase 2x (de ~R$9.034 reais para ~R$18.007 aparentes) —
    # o tipo de erro que "engana relatórios" sem gerar nenhum erro técnico
    # visível (soma perfeitamente, só que soma o mesmo pedido duas vezes).
    # CHAVE DE DEDUPLICAÇÃO: ID_Sessao+Produto+Categoria+Quantidade+
    # Preco_Unitario+Data_Compra (NÃO incluímos ID_Pedido, pois é
    # exatamente o campo que muda entre as cópias). Mantemos a 1ª ocorrência
    # (ID_Pedido mais baixo) como registro canônico.
    antes = len(df)
    df = df.drop_duplicates(
        subset=["ID_Sessao", "Produto", "Categoria", "Quantidade", "Preco_Unitario", "Data_Compra"],
        keep="first",
    )
    depois = len(df)
    print(f"[Pedidos] Duplicidade de lançamento removida: {antes} -> {depois} pedidos únicos "
          f"({antes - depois} lançamentos em dobro eliminados — receita estava quase 2x inflada).")

    return df.reset_index(drop=True)


# ==============================================================================
# ETAPA 4 — INTEGRAÇÃO (MERGE) DAS 3 BASES
# ==============================================================================
def integrar_bases(clientes: pd.DataFrame, acessos: pd.DataFrame, pedidos: pd.DataFrame) -> pd.DataFrame:

    # --- 4.1: Acessos (1) <-> Pedidos (N) via ID_Sessao -------------------
    # ID_Sessao é uma CHAVE FORTE (gerada pelo sistema, sem digitação
    # humana), por isso é a junção mais confiável do pipeline. Uma sessão
    # pode ter vários itens/pedidos (grão de "item de pedido"), então
    # agregamos por sessão antes de subir ao nível de cliente.
    resumo_sessao = (
        pedidos.groupby("ID_Sessao")
        .agg(Valor_Pedidos_Sessao=("Subtotal_Item", "sum"), Qtd_Itens_Comprados=("Quantidade", "sum"))
        .reset_index()
    )

    # LEFT JOIN a partir de Acessos: queremos manter TODAS as sessões,
    # inclusive as que não geraram pedido (Compra_Finalizada=Nao), pois elas
    # são necessárias para calcular taxa de conversão comportamental.
    sessoes = acessos.merge(resumo_sessao, on="ID_Sessao", how="left")

    # INTEGRIDADE REFERENCIAL: a Base 3 referencia 'S110', que não existe na
    # Base 2. Um merge 'left' a partir de Acessos simplesmente não traz essa
    # sessão fantasma — decisão consciente de governança: não inventamos uma
    # linha de acesso para um pedido órfão, apenas reportamos a perda.
    sessoes_pedidos_orfaos = set(pedidos["ID_Sessao"]) - set(acessos["ID_Sessao"])
    if sessoes_pedidos_orfaos:
        print(f"[Integração] Sessão(ões) em Pedidos sem correspondência em Acessos "
              f"(quebra de integridade referencial, excluída(s) da consolidação): "
              f"{sorted(sessoes_pedidos_orfaos)}")

    sessoes["Valor_Pedidos_Sessao"] = sessoes["Valor_Pedidos_Sessao"].fillna(0)
    sessoes["Qtd_Itens_Comprados"] = sessoes["Qtd_Itens_Comprados"].fillna(0)

    # --- 4.2: Clientes (1) <-> Sessoes (N) via Nome_Norm -------------------
    # Única chave disponível entre cadastro e navegação, após reconciliação
    # por fuzzy matching feita em tratar_acessos(). LEFT JOIN a partir de
    # Clientes: todo cliente cadastrado deve aparecer na base final, mesmo
    # que nunca tenha navegado no site (Total_Gasto = 0, Conversao = 0).
    base = clientes.merge(
        sessoes,
        on="Nome_Norm",
        how="left",
        suffixes=("", "_sessao"),
    )

    return base


# ==============================================================================
# ETAPA 5 — TRANSFORMAÇÃO / FEATURE ENGINEERING + REDUÇÃO DE DIMENSIONALIDADE
# ==============================================================================
def gerar_features(base: pd.DataFrame) -> pd.DataFrame:
    df = base.copy()

    # --- Idade: derivada de Data_Nascimento -------------------------------
    hoje = pd.Timestamp(datetime.today().date())
    df["Idade"] = ((hoje - df["Data_Nascimento"]).dt.days // 365).astype("Int64")

    # --- Agregação a nível de CLIENTE -------------------------------------
    # A granularidade final escolhida é 1 LINHA POR CLIENTE. Justificativa:
    # 'Total_Gasto' e 'Conversao' são, por definição, métricas de cliente
    # (não de sessão), e o objetivo de negócio declarado é medir conversão
    # de lead -> cliente pagante.
    agregado = (
        df.groupby("ID_Cliente_Canonico")
        .agg(
            Total_Gasto=("Valor_Pedidos_Sessao", "sum"),
            Qtd_Sessoes=("ID_Sessao", "nunique"),
            Qtd_Compras_Finalizadas=("Compra_Finalizada", "sum"),
            Tempo_Medio_Sessao_Seg=("Duracao_Sessao_Seg", "mean"),
        )
        .reset_index()
    )

    # --- Feature de negócio: Conversao ------------------------------------
    # DEFINIÇÃO (alinhada ao objetivo do negócio): um cliente é considerado
    # "convertido" (lead -> cliente) se teve PELO MENOS UMA sessão com
    # Compra_Finalizada = True. Representado como inteiro 0/1 (e não bool)
    # para facilitar uso direto em cálculos de taxa de conversão (média) e
    # em modelos estatísticos/ML posteriores.
    agregado["Conversao"] = (agregado["Qtd_Compras_Finalizadas"] > 0).astype(int)

    # --- Junta de volta aos dados cadastrais (1 linha por cliente) --------
    cadastro = df.drop_duplicates(subset="ID_Cliente_Canonico")[
        ["ID_Cliente_Canonico", "Nome", "Email", "Email_Valido", "Telefone",
         "Data_Nascimento", "Idade"]
    ]
    final = cadastro.merge(agregado, on="ID_Cliente_Canonico", how="left")

    # --------------------------------------------------------------------
    # REDUÇÃO DE DIMENSIONALIDADE
    # --------------------------------------------------------------------
    # Colunas descartadas e a justificativa de cada uma:
    #  - Nome_Norm, Nome_Cliente: eram apenas CHAVES TÉCNICAS de junção
    #    (texto normalizado), redundantes com 'Nome' após o merge.
    #  - Horario_Inicio / Horario_Termino: substituídas por
    #    'Duracao_Sessao_Seg' (derivada), que já carrega a informação
    #    relevante para análise (engajamento), sem o ruído de timestamps
    #    brutos por sessão que não fazem sentido agregados por cliente.
    #  - ID_Sessao, ID_Pedido, Valor_Carrinho, Compra_Finalizada (linha a
    #    linha), Produto, Categoria, Quantidade, Preco_Unitario,
    #    Subtotal_Item, Valor_Pedidos_Sessao, Qtd_Itens_Comprados,
    #    Data_Compra: são granularidade de SESSÃO/ITEM, já sintetizadas nas
    #    métricas de cliente (Total_Gasto, Qtd_Sessoes,
    #    Qtd_Compras_Finalizadas, Conversao). Mantê-las na tabela mestre
    #    duplicaria informação e misturaria grãos diferentes (cliente vs.
    #    item de pedido) na mesma tabela — o que dificultaria e o consumo
    #    por ferramentas de BI/dashboard a jusante.
    # Quem precisar do detalhe transacional completo pode consultar as
    # tabelas intermediárias já limpas (df_acessos_limpo / df_pedidos_limpo)
    # geradas por este mesmo script.
    final = final.rename(columns={"ID_Cliente_Canonico": "ID_Cliente"})

    return final.reset_index(drop=True)


# ==============================================================================
# EXECUÇÃO DO PIPELINE
# ==============================================================================
def main():
    print("=" * 80)
    print("ETAPA 0 — Leitura e correção estrutural dos arquivos")
    print("=" * 80)
    clientes_raw = carregar_excel_mal_formatado(CAMINHO_CLIENTES)
    acessos_raw = carregar_excel_mal_formatado(CAMINHO_ACESSOS)
    pedidos_raw = carregar_excel_mal_formatado(CAMINHO_PEDIDOS)
    print(f"Clientes: {clientes_raw.shape} | Acessos: {acessos_raw.shape} | Pedidos: {pedidos_raw.shape}")

    print("\n" + "=" * 80)
    print("ETAPA 1-3 — Pré-processamento por base")
    print("=" * 80)
    clientes = tratar_clientes(clientes_raw)
    nomes_validos_norm = set(clientes["Nome_Norm"])
    acessos = tratar_acessos(acessos_raw, nomes_validos_norm)
    pedidos = tratar_pedidos(pedidos_raw)

    print("\n" + "=" * 80)
    print("ETAPA 4 — Integração (merge) das bases")
    print("=" * 80)
    base_integrada = integrar_bases(clientes, acessos, pedidos)
    print(f"Base integrada (grão sessão): {base_integrada.shape}")

    print("\n" + "=" * 80)
    print("ETAPA 5 — Feature engineering e redução de dimensionalidade")
    print("=" * 80)
    clientes_360 = gerar_features(base_integrada)
    print(f"Tabela mestre final (1 linha por cliente): {clientes_360.shape}")
    print(f"Taxa de conversão geral da base: {clientes_360['Conversao'].mean():.1%}")

    clientes_360.to_csv(CAMINHO_SAIDA, index=False)
    print(f"\nArquivo final salvo em: {CAMINHO_SAIDA}")

    return clientes_360


if __name__ == "__main__":
    resultado = main()
    print("\nPrévia da tabela final:")
    print(resultado.head(10))
