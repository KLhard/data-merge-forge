# Memorial Descritivo — Pipeline de Integração de Dados OmniStore

**Disciplina:** Mineração de Dados / Governança de TI  
**Objeto:** Integração e tratamento de três bases heterogêneas da OmniStore  
**Entregáveis técnicos:** `pipeline_etl.py`, `kpis_negocio.py`, `clientes_360.csv`

---

## Sumário Executivo

*(Para leitura gerencial — não exige conhecimento de Python)*

A OmniStore possuía três bases de dados isoladas: o cadastro de clientes, o registro de navegação no site e o detalhamento dos pedidos. Isoladas, elas não respondiam a nenhuma pergunta estratégica; integradas, revelaram o comportamento real de 39 clientes.

O achado mais relevante deste trabalho não foi um KPI, e sim um **erro de qualidade de dados que inflava a receita da empresa em praticamente 100%**. A base de pedidos registrava cada venda duas vezes. Qualquer relatório construído sobre os dados brutos apontaria um faturamento de R$ 18.007, quando o valor real é **R$ 8.973,50**. Uma decisão de investimento, contratação ou compra de estoque tomada sobre esse número estaria errada pela metade.

Isso ilustra a premissa central da atividade: o valor da OmniStore não está no volume de dados que ela possui, mas na confiabilidade deles.

---

## I. Seleção — Integração das Bases

### I.1 Mapeamento das fontes

| Base | Granularidade (o que é 1 linha) | Volume bruto |
|---|---|---|
| 1 — Cadastro de Clientes | Um registro cadastral | 105 linhas |
| 2 — Acessos e Compras no Site | Uma sessão de navegação | 105 linhas |
| 3 — Detalhes dos Pedidos | Um item comprado | 115 linhas |

As três bases estão em **granularidades diferentes**. Esse é o primeiro desafio de qualquer integração: não se pode simplesmente unir tabelas que descrevem coisas distintas (uma pessoa, uma visita e um produto) sem decidir antes qual será o grão final da análise.

**Decisão adotada:** a tabela mestre final tem **granularidade de cliente** (uma linha por pessoa). Justificativa de negócio: as métricas solicitadas pela OmniStore — gasto total e conversão de lead em cliente — são, por definição, atributos de uma pessoa, não de uma visita ou de um produto.

### I.2 Obstáculo inicial: as bases não eram planilhas de verdade

Antes de qualquer junção, houve um problema estrutural. Os três arquivos `.xlsx` não foram exportados como planilhas reais: cada linha inteira, com todas as colunas separadas por vírgula, estava comprimida dentro de **uma única célula da coluna A**. Uma leitura convencional produzia uma tabela de uma coluna só, impossível de cruzar.

**Técnica escolhida:** tratar o conteúdo da coluna A como um arquivo CSV embutido e reprocessá-lo com o interpretador de CSV do Pandas (`pd.read_csv` sobre um buffer em memória).

**Por que não separar o texto manualmente por vírgula:** a base de pedidos contém o produto `Livro "Aprenda Mineração de Dados"` — um título com vírgula e aspas dentro do próprio nome. Uma quebra manual por vírgula dividiria esse produto em colunas erradas e desalinharia a linha inteira. O interpretador de CSV já conhece a convenção de aspas e resolve isso corretamente. Esta é uma decisão de robustez: a solução precisa funcionar também nas próximas cargas, não apenas nesta.

### I.3 Chaves de junção escolhidas

**Junção A — Acessos ↔ Pedidos, pela chave `ID_Sessao`.**
Esta é a junção confiável do pipeline. `ID_Sessao` é um identificador gerado automaticamente pelo sistema, sem digitação humana envolvida, portanto sem risco de erro de grafia. Como uma sessão pode conter vários itens, os pedidos foram primeiro **agregados por sessão** (somando valores e quantidades) antes de subir ao nível de cliente. Agregar antes de juntar evita a multiplicação indevida de linhas.

**Junção B — Clientes ↔ Sessões, pela chave `Nome`.**
Aqui está a fragilidade estrutural do modelo de dados da OmniStore: **a base de acessos não possui `ID_Cliente`**. O único elo entre quem navega e quem está cadastrado é o nome digitado. Nomes são chaves ruins — admitem erro de digitação, variação de acentuação, abreviação e homonímia.

Duas medidas foram adotadas para mitigar isso:

1. **Normalização prévia** — todos os nomes foram convertidos para minúsculas, sem acentuação e sem espaços duplicados, criando uma chave técnica de comparação (`Nome_Norm`). Sem isso, "José Alves" e "jose alves " seriam tratados como duas pessoas.
2. **Reconciliação por similaridade (*fuzzy matching*)** — a base de acessos registra `José Alvez`, enquanto o cadastro traz `José Alves`. Um cruzamento exato descartaria silenciosamente as sessões dessa pessoa. Utilizou-se `difflib.get_close_matches` com limiar de similaridade de 0,85, aplicado **exclusivamente aos nomes sem correspondência exata**.

**Por que um limiar alto (0,85) e não uma correção permissiva:** um limiar baixo corrigiria erros de digitação, mas também fundiria clientes genuinamente diferentes com nomes parecidos, atribuindo compras à pessoa errada. Em governança de dados, o erro de *juntar indevidamente* é mais grave e mais difícil de detectar do que o erro de *deixar de juntar* — o primeiro corrompe a análise em silêncio; o segundo, ao menos, aparece como dado faltante. Optou-se pelo conservadorismo.

**Por que não corrigir o nome manualmente:** correção manual não é reproduzível nem auditável. Na próxima carga de dados, um novo erro de digitação passaria despercebido. A regra codificada aplica-se automaticamente a toda carga futura.

### I.4 O desafio da integridade referencial

Integridade referencial é a garantia de que toda referência entre tabelas aponta para um registro que de fato existe. Duas quebras foram identificadas:

**Quebra 1 — Pedido órfão.** A base de pedidos registra a venda de um mouse (R$ 60,00) vinculada à sessão `S110`, que **não existe na base de acessos**. Há uma venda registrada sem rastro de como o cliente chegou até ela.

*Decisão:* o registro foi excluído da consolidação por cliente e **reportado explicitamente no log de execução**. Deliberadamente não se criou uma sessão fictícia para acomodá-lo. Inventar um dado para "fechar" a tabela transformaria uma falha conhecida em um número aparentemente correto — precisamente o tipo de maquiagem que a governança existe para impedir. Registrar a perda de R$ 60,00 é mais honesto e mais útil ao gestor do que escondê-la.

**Quebra 2 — Contradição lógica entre sistemas.** Quatro sessões estão marcadas como `Compra_Finalizada = Não` na base de acessos, mas possuem **pedido real, com produto, quantidade e valor** na base de pedidos. As duas fontes discordam sobre o mesmo fato.

*Decisão:* registrada e quantificada no relatório de KPIs. Dois clientes (Bruna Santos e Patrícia Gomes) aparecem como "não convertidos" apesar de terem comprado. A recomendação técnica que decorre disso está na Conclusão.

### I.5 Tipo de junção utilizada

Utilizou-se `LEFT JOIN` a partir da base de clientes, e não `INNER JOIN`. A diferença é estratégica: o `INNER JOIN` manteria apenas quem comprou, apagando da análise exatamente o público que mais interessa a uma área comercial — **os leads que visitaram e não converteram**. Com `LEFT JOIN`, esses clientes permanecem na tabela final com `Total_Gasto = 0` e `Conversao = 0`, tornando-se mensuráveis e, portanto, acionáveis.

---

## II. Pré-processamento — Limpeza e Padronização

### II.1 Por que remover duplicatas

Duplicidade é o erro mais perigoso de uma base de dados porque **não gera erro visível**. Um campo nulo aparece como vazio no relatório; uma duplicata simplesmente soma duas vezes e entrega um total que parece perfeitamente legítimo. O gestor não tem como desconfiar.

Foram encontrados **dois tipos distintos** de duplicidade, com causas e tratamentos diferentes.

#### Duplicidade tipo 1 — Cadastral (Base 1)

A base continha 105 registros, mas apenas 39 pessoas reais. O mesmo cliente havia sido cadastrado várias vezes, com `ID_Cliente` diferente a cada vez (João Santos, por exemplo, aparecia três vezes com nome, telefone e data de nascimento idênticos).

**Impacto se não tratado:** o cálculo de gasto médio por cliente seria dividido por 105 em vez de 39, subestimando o valor de cada cliente em quase três vezes. A empresa concluiria que seus clientes valem muito menos do que realmente valem.

**Chave de deduplicação escolhida:** `Nome normalizado + Data de Nascimento`.

**Por que não usar o e-mail como chave**, que seria a escolha intuitiva: a base contém clientes cujo e-mail foi digitado com erro em apenas um dos cadastros. Fernanda Lima aparece uma vez com `fernandalima.com` (sem o símbolo @) e outras vezes com `fernandalima@email.com` — mesmo telefone, mesma data de nascimento, mesma pessoa. Deduplicar por e-mail a manteria dividida em dois clientes distintos, e o erro de cadastro se tornaria permanente na análise. A data de nascimento, ao contrário, é um atributo estável da identidade da pessoa: não muda e raramente é digitada errado. Combinada ao nome, a chance de colisão entre duas pessoas diferentes é desprezível neste volume.

**Critério de desempate:** ao colapsar registros duplicados, preservou-se aquele com **maior completude** (com telefone preenchido e e-mail válido) e, em caso de empate, o de menor `ID_Cliente` — o cadastro mais antigo, adotado como identificador canônico. O objetivo é que a fusão de registros *aumente* a qualidade da informação retida, e não simplesmente descarte linhas ao acaso.

#### Duplicidade tipo 2 — Lançamento em dobro (Base 3) — *achado crítico*

**114 das 115 linhas da base de pedidos eram o mesmo pedido registrado duas vezes**: mesma sessão, mesmo produto, mesma quantidade, mesmo preço e mesma data, alterando apenas o `ID_Pedido` — um número sequencial, não uma nova venda.

**Impacto financeiro:** a receita apurada saltava de R$ 8.973,50 (real) para R$ 18.007,00 (aparente) — **inflação de aproximadamente 100%**.

**Chave de deduplicação:** `ID_Sessao + Produto + Categoria + Quantidade + Preço Unitário + Data da Compra`. O `ID_Pedido` foi deliberadamente **excluído** da chave, pois é justamente o campo que difere entre as cópias — incluí-lo faria o sistema considerar as duplicatas como registros legítimos.

**Cuidado analítico necessário:** foi preciso distinguir a duplicidade real do comportamento legítimo da base, em que uma mesma sessão contém dois produtos *diferentes* (compra com múltiplos itens). Por isso a chave inclui produto, preço e data simultaneamente: apenas linhas idênticas em todos esses atributos foram consideradas lançamento em dobro.

*Observação metodológica relevante:* esta duplicidade permaneceu **invisível durante a primeira execução do pipeline**. Metade das datas da base continha um espaço em branco invisível ao final (`'2025-01-24 '`), o que fazia o Pandas falhar na conversão e transformar 57 datas em valor nulo. Com as datas nulas, as linhas duplicadas não pareciam idênticas e escapavam à detecção. Só após a correção da conversão de datas (com remoção de espaços antes da conversão) a duplicidade se tornou visível. **Um defeito de qualidade de dados estava mascarando outro** — razão pela qual auditoria de dados é um processo iterativo, não uma etapa única.

### II.2 Normalização de tipos

| Campo | Estado original | Tratamento | Justificativa |
|---|---|---|---|
| `Data_Compra` | Texto, metade com espaço final | Remoção de espaços antes da conversão para data | Sem isso, 57 de 115 datas viravam nulo silenciosamente |
| `Data_Nascimento` | Texto | Conversão para tipo data | Permite calcular idade; impede ordenação alfabética incorreta |
| `Quantidade` / `Preço` | Texto | Conversão para tipo numérico | Texto não pode ser somado nem multiplicado |
| `Compra_Finalizada` | Texto "Sim"/"Nao" | Conversão para verdadeiro/falso | Permite somar diretamente para obter taxas de conversão |
| `Horário início/término` | Texto | Conversão para hora e cálculo de duração | Transforma dois campos brutos em uma métrica de engajamento |

### II.3 Limpeza de "sujeira" nos dados

**Telefones — padronização por expressão regular.**
O mesmo número aparecia em pelo menos seis formatos diferentes: `(11) 98765-4321`, `11987654322`, `31-99888-7777`, `(31)99999-8888`, além do texto literal `NA`. O tratamento extrai apenas os dígitos e os reformata no padrão brasileiro `(XX) XXXXX-XXXX`.

**Por que reformatar e não apenas remover a máscara:** o dado limpo destina-se a alimentar sistemas de CRM e campanhas de contato. Um formato único é requisito de integração. Números fora do padrão esperado (comprimento inválido) foram classificados como ausentes, e não "consertados" por adivinhação.

**E-mails — sinalizar, não corrigir.**
Dois e-mails apresentavam formato inválido: `maria@email` (sem domínio de topo) e `fernandalima.com` (sem o símbolo @). Criou-se a coluna indicadora `Email_Valido` em vez de corrigir ou excluir o registro.

**Por que essa é uma decisão ética, e não apenas técnica:** não existe maneira segura de deduzir o endereço correto. "Corrigir" `maria@email` para `maria@email.com` é um palpite — e um palpite errado significa enviar dados de um cliente para o endereço de um terceiro. Excluir a linha inteira, por sua vez, descartaria nome, telefone e histórico de compras válidos por causa de um único campo defeituoso. Sinalizar preserva o dado útil, isola o dado suspeito e devolve a decisão a quem tem autoridade sobre ela — a área de negócio, não o script.

**Valores ausentes — a escolha de não preencher.**
O campo `Valor_Carrinho` apresentava nulos, inclusive em sessões marcadas como compra concluída. **Não foi preenchido com zero nem com a média.**

Preencher com zero afirmaria que o carrinho estava vazio, o que é factualmente falso — o dado apenas não foi capturado. Preencher com a média inventaria receita inexistente e distorceria qualquer análise financeira. A solução foi obter o valor real a partir da base de pedidos, que é a **fonte de verdade** para valores transacionados. Quando existem duas fontes para o mesmo fato, a governança exige eleger uma como autoritativa — e essa escolha precisa ser documentada.

**Produto não informado — preservar o valor financeiro.**
Dois pedidos não tinham o nome do produto, mas possuíam quantidade e preço válidos. As linhas foram mantidas, com o texto rotulado como "Não informado". Descartá-las subtrairia receita real do faturamento da empresa por causa de um campo descritivo ausente.

### II.4 Auditoria — métricas de qualidade

Conforme a orientação de que "o minerador de dados vive de métricas de qualidade", o pipeline **imprime no console o efeito de cada limpeza**, permitindo auditoria de qualquer execução:

```
[Clientes] Duplicidade cadastral removida: 105 -> 39 clientes únicos (66 registros redundantes eliminados).
[Acessos]  Nomes corrigidos por similaridade (fuzzy match): {'jose alvez': 'jose alves'}
[Acessos]  2 sessão(ões) com Compra_Finalizada=True e Valor_Carrinho nulo (inconsistência sinalizada).
[Pedidos]  2 pedido(s) com Produto não informado -> rotulados (linha mantida pelo valor financeiro).
[Pedidos]  Duplicidade de lançamento removida: 115 -> 58 pedidos únicos (57 lançamentos em dobro eliminados).
[Integração] Sessão(ões) em Pedidos sem correspondência em Acessos: ['S110']
```

Nenhuma linha desaparece silenciosamente: toda exclusão é contabilizada e justificada no momento em que ocorre.

---

## III. Transformação — Engenharia de Variáveis

Nesta etapa, dados operacionais tornam-se informação de negócio. Cada variável criada responde a uma pergunta que a OmniStore não conseguia responder antes.

### III.1 `Total_Gasto`

**O que é:** a soma de tudo que cada cliente efetivamente gastou, calculada a partir dos itens de pedido (quantidade × preço unitário), agregada por pessoa.

**Por que calcular:** o cadastro dizia *quem* são os clientes; a base de acessos dizia *que* eles visitaram o site. Nenhuma das duas dizia **quanto cada pessoa vale para a empresa**. Sem essa variável, todos os clientes são tratados como iguais — e não são: o cliente de maior gasto na base movimenta R$ 855,00, enquanto vários movimentam zero.

**Por que a partir dos pedidos e não do valor do carrinho:** o carrinho registra intenção; o pedido registra a transação concluída. Além disso, o campo de carrinho continha nulos justamente em sessões com compra confirmada. Elegeu-se a fonte transacional como autoritativa.

**O que revela:** é a base de qualquer política de relacionamento — programa de fidelidade, atendimento prioritário, régua de recompra. É também o insumo para o cálculo de valor vitalício do cliente, caso a OmniStore passe a acumular histórico.

### III.2 `Conversao`

**O que é:** variável binária (1 ou 0) indicando se o lead se tornou cliente pagante — atribuída ao cliente que registrou ao menos uma compra finalizada.

**Por que representar como 0/1 e não como "Sim"/"Não":** a média de uma coluna de 0 e 1 **é** a taxa de conversão. A representação numérica permite calcular a taxa por qualquer recorte (faixa etária, região, canal) com uma única operação, e torna a variável diretamente utilizável como alvo em modelos preditivos futuros — por exemplo, estimar a probabilidade de um novo lead converter.

**O que revela:** separa o público em dois grupos com estratégias completamente distintas. Quem converteu deve ser retido; quem não converteu, ativado. São problemas de marketing diferentes, e sem essa variável ambos os grupos recebem o mesmo tratamento.

### III.3 Variáveis de apoio

| Variável | O que revela sobre o negócio |
|---|---|
| `Qtd_Sessoes` | Mede interesse. Muitas sessões com conversão zero indicam fricção no site, e não desinteresse — um problema corrigível. |
| `Qtd_Compras_Finalizadas` | Distingue **recorrência** de valor pontual. Foi essa variável que revelou o perfil real do melhor cliente da OmniStore (ver Conclusão). |
| `Idade` | Derivada da data de nascimento. Idade é analisável em faixas; data de nascimento isolada, não. |
| `Tempo_Medio_Sessao_Seg` | Proxy de engajamento — cuja fragilidade nesta base está documentada na seção IV.3. |
| `Email_Valido` | Indicador operacional: mede quantos clientes são efetivamente alcançáveis por e-mail. |
| `Subtotal_Item` | Valor por linha de pedido; insumo intermediário para receita por categoria e por cliente. |

### III.4 Redução de dimensionalidade

A tabela final foi reduzida a **12 colunas com uma linha por cliente**, a partir de três bases somando dezoito colunas em granularidades distintas.

**Critérios de exclusão aplicados:**

**Chaves técnicas** (`Nome_Norm`, `Nome_Cliente`) — versões normalizadas dos nomes, criadas apenas para viabilizar as junções. Cumprida sua função, tornam-se redundantes em relação à coluna `Nome`.

**Campos substituídos por derivadas** (`Horario_Inicio`, `Horario_Termino`) — substituídos por `Tempo_Medio_Sessao_Seg`. O horário absoluto de início de uma sessão específica não informa nada sobre o cliente quando agregado; a duração média, sim.

**Campos de outra granularidade** (`ID_Sessao`, `ID_Pedido`, `Produto`, `Categoria`, `Quantidade`, `Preco_Unitario`, `Data_Compra`) — pertencem ao nível de sessão ou de item, e já estão sintetizados nas métricas de cliente. Mantê-los na tabela mestre **misturaria dois grãos diferentes na mesma tabela**, erro clássico que gera dupla contagem em ferramentas de BI: ao somar `Total_Gasto` em um painel com uma linha por item, o valor do cliente seria contado tantas vezes quantos itens ele comprou.

**Princípio adotado:** reduzir dimensionalidade não é descartar informação, é **separar responsabilidades**. A tabela mestre responde perguntas sobre clientes. O detalhe transacional permanece disponível nas tabelas intermediárias limpas, geradas pelo mesmo script e utilizadas pelo `kpis_negocio.py` para as análises por categoria de produto.

---

## IV. Conclusão — Resultados e Recomendação Estratégica

### IV.1 Resultados dos KPIs

**Ticket médio: R$ 157,43** por pedido, apurado sobre R$ 8.973,50 de receita real distribuída em 57 pedidos legítimos.

**Receita por categoria:** Eletrônicos lidera com R$ 3.760,50 (41,9% do faturamento), seguido de Vestuário (R$ 2.470,00 / 27,5%), Acessórios (R$ 1.533,00), Esportes (R$ 640,00) e Livros (R$ 570,00). **Eletrônicos e Vestuário concentram quase 70% de toda a receita.**

**Participação por categoria nas sessões do site:** Eletrônicos 19,0%, Vestuário 15,2%, Acessórios 12,4%, Livros 4,8%, Esportes 2,9%.

*Ressalva metodológica:* este indicador não é uma taxa de conversão de funil em sentido estrito. As bases não registram qual categoria o visitante pretendia comprar quando abandonou o carrinho — apenas o que foi efetivamente adquirido. O número mede participação de cada categoria no total de visitas, e deve ser lido como tal.

**Conversão geral:** 30 dos 39 clientes converteram (**76,9%**). Índice elevado, porque a base contém apenas pessoas já cadastradas — não representa a conversão de visitantes anônimos do site.

**Perfil demográfico dos maiores compradores:** entre os 25% que mais gastam, a idade média é de 33,9 anos, contra 33,4 da média geral. **Idade não é fator discriminante.** A distribuição regional (estimada por DDD) também é equilibrada entre RJ, SP, MG e SC, sem concentração significativa.

*Limitação relevante:* nenhuma das três bases contém campo de cidade ou estado. A região foi **inferida a partir do DDD do telefone** — uma aproximação, não um dado cadastral. Cinco clientes não possuem telefone e ficam sem região atribuída. Registrar essa limitação é parte da entrega: um gestor precisa saber o grau de confiança do número que recebe.

**Melhores clientes:** Alexandre Souza (R$ 855,00), Gustavo Mendes (R$ 735,00), Pedro Costa (R$ 725,00), João Santos (R$ 650,50) e Carlos Rodrigues (R$ 450,00).

**O que os une não é demografia — é recorrência.** Esses cinco clientes realizaram em média **3,2 compras**, contra 1,4 da base geral. Idade e região variam entre eles; o comportamento de recompra, não. Cerca de 76% do que gastam concentra-se em Eletrônicos.

**Segmentos identificados:**
- **Compradores de Alto Valor** (17 clientes) — converteram e gastam acima da mediana; concentram-se em **Eletrônicos**.
- **Compradores Ocasionais** (13 clientes) — converteram com gasto abaixo da mediana; concentram-se em **Vestuário**.
- **Leads Engajados não convertidos** (9 clientes) — visitaram duas ou mais vezes sem nunca comprar.

Há, portanto, **relação clara entre segmento e categoria**: Eletrônicos é a categoria do cliente de alto valor; Vestuário, a de entrada. Não existe segmento "frio" na base — todo cliente cadastrado visitou o site ao menos uma vez.

### IV.2 Recomendação estratégica

**Prioridade 1 — Corrigir a duplicação de pedidos na origem.**
A remoção das duplicatas neste pipeline resolve o sintoma, não a causa. Enquanto o sistema transacional continuar gravando cada venda duas vezes, todo relatório extraído diretamente dele — por qualquer área, em qualquer ferramenta — apresentará receita dobrada. Recomenda-se investigação junto à TI e criação de restrição de unicidade na origem. **Esta é a recomendação de maior impacto do trabalho**, porque nenhum tratamento posterior é confiável quando a fonte gera dados falsos continuamente.

**Prioridade 2 — Criar identificador de cliente na base de acessos.**
A ligação entre navegação e cadastro depende hoje de um nome digitado. Funcionou nesta base porque não há homônimos, mas é uma fragilidade estrutural: basta um cliente novo com nome semelhante ao de outro para que compras sejam atribuídas à pessoa errada. Recomenda-se incluir `ID_Cliente` no registro de sessão.

**Prioridade 3 — Eleger a existência do pedido como fonte de verdade da conversão.**
Bruna Santos e Patrícia Gomes compraram, mas constam como não convertidas porque a marcação da sessão contradiz o pedido registrado. Relatórios de conversão baseados apenas nessa marcação **subestimam o desempenho comercial da empresa**. Recomenda-se que a métrica oficial passe a considerar a existência de pedido, e não a flag de sessão.

**Prioridade 4 — Ativar os 9 leads engajados.**
São clientes que visitaram o site repetidamente e nunca compraram. Não é desinteresse: é o grupo de conversão mais barata da base, porque a atração já foi paga. Recomenda-se campanha dirigida com oferta de entrada em Vestuário — a categoria de menor ticket, porta natural do primeiro pedido.

**Prioridade 5 — Explorar a recorrência, não o ticket alto.**
Como o melhor cliente da OmniStore é definido por frequência e não por valor unitário, a alavanca de crescimento mais eficiente é a **régua de recompra** — e não a tentativa de elevar o valor de cada pedido isolado. Eletrônicos é o eixo natural dessa estratégia, por concentrar o gasto dos clientes de maior valor.

**Prioridade 6 — Auditar o cadastro de produtos.**
O item "Câmera" registra preços entre R$ 75,00 e R$ 800,00 sob o mesmo nome, e responde por 28% da receita de Eletrônicos. Provavelmente produtos distintos estão agrupados sob uma etiqueta genérica, o que distorce qualquer análise por produto e impede gestão de estoque confiável.

### IV.3 Limitações declaradas

A integridade deste trabalho exige explicitar o que os dados **não** permitem afirmar:

1. **Região é inferida, não cadastrada** — derivada do DDD; cinco clientes sem telefone ficam sem atribuição.
2. **Tempo de sessão não é confiável** — 90% das sessões duram exatamente 300 segundos, padrão incompatível com comportamento humano real. Métricas de engajamento baseadas nesse campo não sustentam decisão.
3. **Volume reduzido** — 39 clientes. O grupo dos maiores compradores tem 8 pessoas; diferenças demográficas nesse recorte não são estatisticamente significativas.
4. **R$ 60,00 de receita não rastreável** — o pedido órfão da sessão `S110` está fora da consolidação por cliente.
5. **Janela temporal curta** — os pedidos cobrem de janeiro a março de 2025, o que impede análise de sazonalidade e cálculo de valor vitalício.

### IV.4 Considerações sobre ética e integridade

A atividade estabelece que "se os dados estiverem errados, a decisão estratégica da empresa será errada". Este pipeline produziu uma demonstração concreta dessa afirmação: **a receita da OmniStore aparentava ser o dobro da real.**

Uma decisão de expansão, contratação ou compra de estoque tomada sobre R$ 18.007 de faturamento presumido — quando o valor efetivo é R$ 8.973,50 — comprometeria a empresa financeiramente. O erro não seria detectado por auditoria contábil superficial, porque a soma está aritmeticamente correta: ela apenas soma duas vezes o mesmo pedido.

Três princípios nortearam as decisões técnicas documentadas:

**Não inventar dados.** Nenhum valor ausente foi preenchido por estimativa. Onde o dado não existe, permanece ausente e sinalizado. Preencher lacunas com médias produz tabelas visualmente completas e analiticamente falsas.

**Não ocultar perdas.** Toda linha excluída é contabilizada e justificada no log de execução. O pedido órfão de R$ 60,00 foi reportado, não silenciado.

**Documentar as limitações com o mesmo rigor dos resultados.** A seção IV.3 tem peso equivalente à seção IV.1. Um KPI entregue sem sua margem de confiança é uma informação incompleta apresentada como certeza — e o gestor que a recebe não tem meios de saber disso.

---

## Anexo — Arquivos entregues

| Arquivo | Conteúdo |
|---|---|
| `pipeline_etl.py` | Pipeline completo: leitura, limpeza, integração e engenharia de variáveis (Parte 1) |
| `kpis_negocio.py` | Cálculo dos sete KPIs de negócio (Parte 2) |
| `clientes_360.csv` | Tabela mestre: 39 clientes, 12 variáveis |
| `memorial_descritivo.pdf` | Este documento (Parte 3) |

**Ordem de execução:** `python pipeline_etl.py` (gera a tabela mestre) e, em seguida, `python kpis_negocio.py` (calcula os indicadores). Ambos os scripts devem estar na mesma pasta que os três arquivos `.xlsx` originais.
