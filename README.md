# OmniStore — Integração de Dados e KPIs de Negócio

Projeto de ETL e análise de dados da OmniStore. O pipeline consolida cadastro de clientes, sessões de navegação e itens de pedidos em uma visão única por cliente. Um segundo script calcula indicadores comerciais a partir das mesmas fontes.

## Objetivos

- Integrar fontes com granularidades diferentes (cliente, sessão e item de pedido).
- Identificar e tratar problemas de qualidade, incluindo cadastros repetidos e lançamentos de pedidos duplicados.
- Gerar uma tabela mestre com uma linha por cliente (`clientes_360.csv`).
- Calcular sete KPIs de negócio para apoiar análises de receita, conversão, perfil e segmentação.

## Arquivos

| Arquivo | Descrição |
|---|---|
| `pipeline_etl.py` | Leitura, limpeza, integração, criação de variáveis e geração do CSV mestre. |
| `kpis_negocio.py` | Cálculo e exibição dos sete KPIs; reutiliza as funções de limpeza do pipeline. |
| `clientes_360.csv` | Resultado consolidado: 39 clientes e 12 colunas. É usado também pelo script de KPIs. |
| `memorial_descritivo.md` / `memorial_descritivo.pdf` | Memorial metodológico, resultados detalhados, limitações e recomendações. |

## Requisitos

- Python 3.9 ou superior.
- Bibliotecas Python: `pandas`, `numpy` e `openpyxl`.

Instale as dependências com:

```bash
python -m pip install pandas numpy openpyxl
```

## Dados de entrada

Para executar o ETL e recalcular os indicadores, são necessárias as três planilhas `.xlsx` originais:

1. Cadastro de clientes (`Base_de_Dados_1-_Cadastro_de_Clientes.xlsx`)
2. Acessos e compras no site (`Base_de_Dados_2-_Acessos_e_Compras_no_Site.xlsx`)
3. Detalhes dos pedidos (`Base_de_Dados_3-_Detalhes_dos_Pedidos.xlsx`)

Essas planilhas não estão entre os arquivos disponibilizados junto a este README. O CSV `clientes_360.csv` é uma saída pronta do ETL, não substitui as fontes originais para reconstruir a tabela de itens nem para recalcular todos os KPIs.

Antes de executar, edite no início de `pipeline_etl.py` as constantes `CAMINHO_CLIENTES`, `CAMINHO_ACESSOS` e `CAMINHO_PEDIDOS` para apontarem para os caminhos locais das três planilhas. Os valores atuais apontam para `/mnt/user-data/uploads`, um caminho específico do ambiente original. Mantenha os arquivos `.xlsx` no local indicado. O CSV de saída é gravado como `clientes_360.csv` no diretório de execução.

## Como executar

Coloque os dois scripts, as três planilhas de origem e o CSV de saída na mesma pasta. No terminal, nessa pasta, execute:

```bash
python pipeline_etl.py
python kpis_negocio.py
```

A primeira etapa imprime contagens e ocorrências de qualidade dos dados e grava `clientes_360.csv`. A segunda lê esse CSV e volta às fontes originais para montar a tabela de itens usada pelos KPIs. Portanto, execute primeiro o pipeline; execute o script de KPIs depois, com as fontes e o CSV disponíveis.

Se as fontes e o CSV já estiverem preparados, é possível consultar os indicadores executando apenas `python kpis_negocio.py`, desde que os caminhos de origem no pipeline estejam válidos.

## O que o pipeline faz

1. Lê os arquivos Excel que contêm linhas CSV armazenadas em células e interpreta o conteúdo usando o parser CSV do pandas.
2. Normaliza nomes para comparação, consolida cadastros repetidos e padroniza telefones e datas; e-mails inválidos são sinalizados, não corrigidos por suposição.
3. Reconcilia nomes de sessão com o cadastro usando correspondência aproximada conservadora quando não há correspondência exata.
4. Converte quantidades, preços, horários e flags para tipos apropriados; calcula subtotais e duração das sessões.
5. Remove lançamentos de pedido repetidos com base nos atributos do item, preservando itens distintos da mesma sessão.
6. Integra pedidos às sessões por `ID_Sessao` e sessões aos clientes pelo nome normalizado. Registros sem correspondência são reportados no console.
7. Agrega as métricas ao nível de cliente e grava uma linha por pessoa.

## Indicadores calculados

O script `kpis_negocio.py` apresenta:

1. Ticket médio por sessão com pedido.
2. Participação das sessões por categoria comprada.
3. Receita por categoria.
4. Perfil demográfico dos clientes no quartil superior de gasto.
5. Cinco clientes com maior gasto.
6. Segmentação de clientes por conversão, gasto e número de sessões, com categoria dominante por segmento.
7. Casos atípicos e inconsistências que podem distorcer relatórios.

A métrica chamada de conversão por categoria representa a proporção do total de sessões associada a compras daquela categoria; não é um funil por intenção de compra, pois essa intenção não está registrada nas fontes.

## Colunas de `clientes_360.csv`

| Coluna | Significado |
|---|---|
| `ID_Cliente` | Identificador canônico do cadastro. |
| `Nome` | Nome do cliente. |
| `Email` | E-mail cadastrado. |
| `Email_Valido` | Indicador de validação básica do formato do e-mail. |
| `Telefone` | Telefone padronizado, quando válido. |
| `Data_Nascimento` | Data de nascimento. |
| `Idade` | Idade calculada na execução do ETL. |
| `Total_Gasto` | Soma dos itens de pedidos atribuídos ao cliente. |
| `Qtd_Sessoes` | Número de sessões distintas registradas. |
| `Qtd_Compras_Finalizadas` | Número de sessões marcadas como compra finalizada. |
| `Tempo_Medio_Sessao_Seg` | Duração média das sessões em segundos. |
| `Conversao` | Indicador 0/1: ao menos uma sessão marcada como compra finalizada. |

## Resultados registrados no memorial

Os resultados documentados para a carga analisada incluem R$ 8.973,50 em receita após deduplicação, ticket médio de R$ 157,43 e conversão de 76,9% entre os 39 clientes cadastrados. São resultados daquela carga específica, não garantias para execuções com novos dados.

## Limitações e cuidados de interpretação

- A base de clientes é pequena (39 pessoas) e não representa necessariamente todos os visitantes do site.
- O vínculo entre cadastro e navegação usa nomes, pois a fonte de acessos não contém identificador de cliente. A correspondência aproximada pode exigir revisão em novas cargas.
- Pedidos sem sessão correspondente são excluídos da consolidação por cliente e reportados; o memorial registra um pedido órfão (`S110`) de R$ 60,00.
- Há divergências entre a flag de compra finalizada e a existência de pedidos; a coluna `Conversao` é derivada da flag de sessão no código atual.
- A região usada em análises é estimada pelo DDD do telefone, não informada diretamente.
- O memorial aponta concentração de durações em 300 segundos, o que limita o uso do tempo de sessão como medida de engajamento.
- A idade é calculada na data da execução, então pode variar entre execuções.

Consulte o memorial descritivo para o detalhamento das decisões de governança, resultados e recomendações.
