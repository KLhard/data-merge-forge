"""
================================================================================
PARTE 2 — DESAFIO DE NEGÓCIO: KPIs DA OMNISTORE
================================================================================
Este script REUTILIZA as funções de limpeza do pipeline_etl.py (Parte 1) e
responde às 7 perguntas de negócio da atividade.

IMPORTANTE: coloque este arquivo na MESMA PASTA que pipeline_etl.py e os
3 arquivos .xlsx originais antes de executar.
================================================================================
"""

import datetime
import pandas as pd

import pipeline_etl as pe  # reaproveita toda a limpeza já validada na Parte 1

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 160)


def montar_tabela_fato():
    """
    Reconstrói a tabela em grão de ITEM DE PEDIDO com os atributos de cliente
    já anexados (Idade, Região). É a granularidade certa para os KPIs 1, 2, 3
    e 7, que olham para categoria/produto — informação que a tabela mestre
    'clientes_360' (1 linha por cliente) já não carrega, por design (ver
    seção de redução de dimensionalidade no pipeline_etl.py).
    """
    clientes_raw = pe.carregar_excel_mal_formatado(pe.CAMINHO_CLIENTES)
    acessos_raw = pe.carregar_excel_mal_formatado(pe.CAMINHO_ACESSOS)
    pedidos_raw = pe.carregar_excel_mal_formatado(pe.CAMINHO_PEDIDOS)

    clientes = pe.tratar_clientes(clientes_raw)
    nomes_validos = set(clientes["Nome_Norm"])
    acessos = pe.tratar_acessos(acessos_raw, nomes_validos)
    pedidos = pe.tratar_pedidos(pedidos_raw)  # já remove os pedidos duplicados

    # Sessão órfã (S110) não tem como ser ligada a um cliente -> fica de fora
    # da tabela fato (é reportada separadamente no KPI 7).
    pedidos_validos = pedidos[pedidos["ID_Sessao"] != "S110"]

    fato = pedidos_validos.merge(
        acessos[["ID_Sessao", "Nome_Norm", "Compra_Finalizada", "Duracao_Sessao_Seg"]],
        on="ID_Sessao", how="left",
    )
    fato = fato.merge(
        clientes[["Nome_Norm", "ID_Cliente_Canonico", "Nome", "Data_Nascimento", "Telefone"]],
        on="Nome_Norm", how="left",
    )

    hoje = pd.Timestamp(datetime.date.today())
    fato["Idade"] = (hoje - fato["Data_Nascimento"]).dt.days // 365

    # PROXY DE REGIÃO: as bases não têm campo de cidade/estado. Usamos o DDD
    # do telefone como aproximação — é uma estimativa, não um dado direto
    # (documentar essa limitação é parte da governança da análise).
    ddd_para_uf = {"11": "SP", "21": "RJ", "31": "MG", "47": "SC"}
    fato["DDD"] = fato["Telefone"].str.extract(r"\((\d{2})\)")
    fato["Regiao_Estimada"] = fato["DDD"].map(ddd_para_uf).fillna("Desconhecida")

    return clientes, acessos, pedidos, fato


def kpi1_ticket_medio(fato):
    receita_total = fato["Subtotal_Item"].sum()
    n_pedidos = fato["ID_Sessao"].nunique()
    ticket_medio = receita_total / n_pedidos
    print(f"\n[KPI 1] Ticket Médio: R$ {ticket_medio:.2f}  "
          f"(Receita total R$ {receita_total:.2f} / {n_pedidos} pedidos)")
    return ticket_medio


def kpi2_conversao_por_categoria(fato, acessos):
    # Definição adotada: % do total de sessões do site que resultaram em
    # compra de cada categoria. NÃO é um funil completo (não sabemos a
    # categoria pretendida pelos leads que não compraram).
    total_sessoes = acessos["ID_Sessao"].nunique()
    por_categoria = fato.groupby("Categoria")["ID_Sessao"].nunique()
    taxa = (por_categoria / total_sessoes * 100).sort_values(ascending=False)
    print("\n[KPI 2] Taxa de participação/conversão por categoria (% das sessões do site):")
    print(taxa.round(1))
    return taxa


def kpi3_receita_por_categoria(fato):
    receita_cat = fato.groupby("Categoria")["Subtotal_Item"].sum().sort_values(ascending=False)
    print("\n[KPI 3] Receita por categoria:")
    print(receita_cat)
    print(f"Categoria líder: {receita_cat.idxmax()} "
          f"({receita_cat.max() / receita_cat.sum() * 100:.1f}% da receita total)")
    return receita_cat


def kpi4_perfil_demografico(clientes_360, fato):
    compradores = clientes_360[clientes_360["Total_Gasto"] > 0].copy()
    limiar = compradores["Total_Gasto"].quantile(0.75)
    top25 = compradores[compradores["Total_Gasto"] >= limiar]
    print(f"\n[KPI 4] Perfil demográfico — Top 25% por gasto (n={len(top25)} de {len(compradores)}):")
    print(f"  Idade média geral: {compradores['Idade'].mean():.1f} | "
          f"Idade média Top 25%: {top25['Idade'].mean():.1f}")
    regiao_top = (
        fato[fato["ID_Cliente_Canonico"].isin(top25["ID_Cliente"])]
        .drop_duplicates("ID_Cliente_Canonico")["Regiao_Estimada"].value_counts()
    )
    print(f"  Região (estimada por DDD) do Top 25%:\n{regiao_top}")
    return top25


def kpi5_melhores_clientes(clientes_360, fato):
    top5 = clientes_360.sort_values("Total_Gasto", ascending=False).head(5)
    print("\n[KPI 5] Top 5 clientes por gasto total:")
    print(top5[["Nome", "Idade", "Total_Gasto", "Qtd_Sessoes", "Qtd_Compras_Finalizadas"]])
    print(f"  Compras finalizadas (média Top5): {top5['Qtd_Compras_Finalizadas'].mean():.1f} "
          f"vs. base geral: {clientes_360['Qtd_Compras_Finalizadas'].mean():.1f}")
    return top5


def kpi6_segmentacao(clientes_360, fato):
    compradores = clientes_360[clientes_360["Total_Gasto"] > 0]
    mediana_gasto = compradores["Total_Gasto"].median()

    def segmentar(linha):
        if linha["Conversao"] == 1 and linha["Total_Gasto"] >= mediana_gasto:
            return "Comprador de Alto Valor"
        if linha["Conversao"] == 1:
            return "Comprador Ocasional"
        if linha["Qtd_Sessoes"] >= 2:
            return "Lead Engajado (não converteu)"
        return "Lead Frio"

    df = clientes_360.copy()
    df["Segmento"] = df.apply(segmentar, axis=1)
    print("\n[KPI 6] Segmentos de clientes encontrados:")
    print(df["Segmento"].value_counts())

    fato_seg = fato.merge(df[["ID_Cliente", "Segmento"]], left_on="ID_Cliente_Canonico",
                           right_on="ID_Cliente", how="left")
    dominante = (
        fato_seg.groupby(["Segmento", "Categoria"])["Subtotal_Item"].sum()
        .groupby("Segmento", group_keys=False).apply(lambda s: s.sort_values(ascending=False).head(1))
    )
    print("\nCategoria dominante (receita) por segmento:")
    print(dominante)
    return df


def kpi7_casos_atipicos(clientes, acessos, pedidos_bruto, fato):
    print("\n[KPI 7] Casos atípicos que podem enganar relatórios:")

    # 1) Duplicidade de pedidos (já tratada em tratar_pedidos, aqui só reportamos o tamanho do efeito)
    pedidos_com_duplicata = pe.carregar_excel_mal_formatado(pe.CAMINHO_PEDIDOS)
    receita_bruta_com_duplicata = (
        pd.to_numeric(pedidos_com_duplicata["Quantidade"], errors="coerce").fillna(0)
        * pd.to_numeric(pedidos_com_duplicata["Preco_Unitario"], errors="coerce")
    ).sum()
    receita_real = fato["Subtotal_Item"].sum()
    print(f"  1) Pedidos duplicados: receita SEM tratar duplicidade seria R$ "
          f"{receita_bruta_com_duplicata:.2f} vs. R$ {receita_real:.2f} real "
          f"(~{receita_bruta_com_duplicata / receita_real:.1f}x inflada).")

    # 2) Sessão órfã
    orfaos = set(pe.tratar_pedidos(pe.carregar_excel_mal_formatado(pe.CAMINHO_PEDIDOS))["ID_Sessao"]) \
        - set(acessos["ID_Sessao"])
    print(f"  2) Sessões referenciadas em Pedidos sem correspondência em Acessos: {sorted(orfaos)}")

    # 3) Duração de sessão suspeita
    pct_300s = (acessos["Duracao_Sessao_Seg"] == 300).mean() * 100
    print(f"  3) {pct_300s:.0f}% das sessões duram exatamente 300s — padrão pouco natural, "
          f"sugere dado sintético (métricas de 'tempo de engajamento' não são confiáveis).")

    # 4) Compra_Finalizada = Sim mas sem valor
    inconsist_valor = acessos[(acessos["Compra_Finalizada"]) & (acessos["Valor_Carrinho"].isna())]
    print(f"  4) {len(inconsist_valor)} sessões com Compra_Finalizada=Sim e Valor_Carrinho nulo.")

    # 5) Pedido real em sessão marcada como não finalizada
    check = pedidos_bruto.merge(acessos[["ID_Sessao", "Compra_Finalizada", "Nome_Cliente"]],
                                 on="ID_Sessao", how="left")
    inconsist_flag = check[check["Compra_Finalizada"] == False]  # noqa: E712
    print(f"  5) {inconsist_flag['Nome_Cliente'].nunique()} cliente(s) com pedido real vinculado a "
          f"sessão marcada 'Compra_Finalizada=Não' — subestima conversão se usar só a Base 2:")
    print(f"     {sorted(inconsist_flag['Nome_Cliente'].unique())}")

    # 6) Mesmo produto, preços muito diferentes
    variacao = fato.groupby("Produto")["Preco_Unitario"].agg(["min", "max"])
    variacao["amplitude"] = variacao["max"] - variacao["min"]
    pior = variacao.sort_values("amplitude", ascending=False).head(1)
    print(f"  6) Produto com maior variação de preço sob o mesmo nome: {pior}")


def main():
    clientes, acessos, pedidos, fato = montar_tabela_fato()
    clientes_360 = pd.read_csv("clientes_360.csv")  # gerado pela Parte 1 (pipeline_etl.py)

    kpi1_ticket_medio(fato)
    kpi2_conversao_por_categoria(fato, acessos)
    kpi3_receita_por_categoria(fato)
    kpi4_perfil_demografico(clientes_360, fato)
    kpi5_melhores_clientes(clientes_360, fato)
    kpi6_segmentacao(clientes_360, fato)

    pedidos_bruto = pe.tratar_pedidos(pe.carregar_excel_mal_formatado(pe.CAMINHO_PEDIDOS))
    kpi7_casos_atipicos(clientes, acessos, pedidos_bruto, fato)


if __name__ == "__main__":
    main()
