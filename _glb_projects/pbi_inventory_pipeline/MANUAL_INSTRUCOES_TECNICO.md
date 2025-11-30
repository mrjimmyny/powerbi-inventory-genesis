# 2. Tutorial Técnico — Como o framework realmente funciona

> Público-alvo: **desenvolvedores, arquitetos de dados e pessoas curiosas** que querem entender _como_ o framework funciona por dentro — não só apertar o botão e torcer para o melhor. 😄

---

## 0. Como ler este tutorial

Se o Tutorial 1 é o “**como usar**”, este aqui é o “**como construímos isso tudo**”.

Aqui você vai encontrar:

1. **Visão de arquitetura** – por que usamos PBIP, TMDL e JSON, e qual é o papel de cada arquivo.
2. **Deep-dive nos scripts** – como o *minerador* e o *constructor* trabalham.
3. **Mapa dos bancos do Notion (BD1, BD2, BD3, BD5, BD6, BD7, BD8)**.
4. **Pipeline completo em modo fluxograma** – de ponta a ponta.
5. **Como estender o framework** sem quebrar o que já funciona.
6. **Preparação para GitHub** – para virar um projeto nível open‑source profissional.   

A promessa é simples: depois deste tutorial você consegue:

- auditar,
- melhorar,
- expandir e
- manter o framework de forma madura.   

---

## 1. Visão geral da arquitetura

Vamos começar pelo **desenho mental**.

### 1.1. O que o framework faz em uma frase

> “Ler um projeto Power BI em formato **PBIP**, transformar tudo em **inventário estruturado** e publicar em **bancos do Notion** com links clicáveis entre Projeto → Tabelas → Medidas → Páginas → Visuais.”

### 1.2. Os três blocos principais

Pensa no framework em 3 blocos:

1. **Minerador** (`minerator` / script 1)  
   - Lê o projeto PBIP.  
   - Analisa TMDL, JSON de report, conexões etc.  
   - Gera arquivos estruturados (JSON / CSV), principalmente o `model_structure.json`.

2. **Constructor** (`constructor` / script 2)  
   - Lê o que o minerador produziu.  
   - Cria ou atualiza os bancos no Notion (BD1, BD2, BD3, BD5, BD6, BD7, BD8).   
   - Faz a primeira carga de registros (linhas) com todos os metadados.

3. **Pós‑processamento** (`notion_post_links_ids` / script 3)  
   - Usa o que já está no Notion para **cruzar IDs**.  
   - Preenche campos de relacionamento e links clicáveis (ex: “Ver medida no Notion”, “Ver página”, “Ver visual”).  
   - Gera a navegação que deixa tudo com cara de “mini‑portal de documentação”.

### 1.3. Por que PBIP, TMDL e JSON?

- **PBIP** é o formato “projeto” do Power BI:
  - Você ganha pastas e arquivos legíveis (Git‑friendly).
  - Consegue versionar, comparar, revisar e minerar sem precisar abrir o Power BI Desktop.

- **TMDL** (Tabular Model Definition Language):
  - Representa o modelo tabular em texto (tabelas, colunas, medidas, relacionamentos).
  - Facilita extrair metadados sem DMVs, só olhando o arquivo.

- **JSON**:
  - `report.json` e `visual.json` trazem a parte visual:
    - páginas, visuais, campos usados em cada visual, etc.
  - Arquivos auxiliares trazem a parte de **conexão** (M code, fontes, parâmetros…).

A lógica é:

> **PBIP** guarda tudo → **TMDL + JSON** tornam legível → framework faz o resto.

---

## 2. Anatomia do projeto (pastas e arquivos importantes)

Aqui é a visão de “árvore do projeto” em modo simplificado:

```text
pbi-project/
├─ dataset/
│  ├─ model.tmdl              # Modelo tabular (tabelas, colunas, medidas, RLS, relationships)
│  └─ connections/            # M code, fontes, credenciais (metadados)
├─ report/
│  ├─ report.json             # Páginas, layouts, temas, etc.
│  └─ sections/               # Arquivos por página / visual (dependendo da versão)
├─ pbi_config.json            # Configuração do framework (nome do projeto, IA on/off, etc.)
└─ (outros arquivos do PBIP)
```

Depois que o minerador termina, entram alguns arquivos gerados pelo próprio framework (exemplos):

```text
_output/
├─ model_structure.json       # Estrutura consolidada para o constructor
├─ measures_for_ai.csv        # Medidas preparadas para enriquecimento por IA
├─ measures_enriched.csv      # Medidas com descrições geradas pela IA (quando ativada)
└─ outros CSVs auxiliares
```

---

## 3. Deep‑dive no minerador

Agora vamos entrar no bloco 1: **minerador**.

> Metáfora oficial: é o “crawler” do Power BI. Ele entra no seu PBIP, vasculha cada cantinho e volta com um inventário completo.

### 3.1. Responsabilidades principais

O minerador faz, no mínimo, estes passos:

1. Lê o `pbi_config.json` para saber:
   - nome do projeto,
   - localização do PBIP,
   - se a IA está ligada ou não,
   - parâmetros de ambiente (por exemplo, qual Notion workspace usar).

2. Varre o diretório do PBIP:
   - Encontra `dataset/model.tmdl`,
   - Encontra `report/report.json` (e arquivos filhos),
   - Encontra arquivos de conexões / M (dependendo da versão).

3. Faz o _parsing_ de cada peça:
   - **TMDL** → tabelas, colunas, medidas, relacionamentos, roles de RLS.
   - **JSON de report** → páginas, visuais, campos usados.
   - **M code** → conexões de banco / fonte de dados.

4. Constrói objetos internos em Python:
   - listas/dicionários representando:
     - Tabelas,
     - Colunas,
     - Medidas,
     - Relacionamentos,
     - Páginas,
     - Visuais,
     - Conexões.

5. Escreve tudo num **artefato único**: `model_structure.json`.

Esse `model_structure.json` é a “verdade única” que o constructor vai usar.

---

### 3.2. Como o parser do TMDL funciona (alto nível)

Sem entrar em sintaxe a cada linha, o fluxo é:

1. Abrir o `model.tmdl` como texto.
2. Percorrer bloco a bloco:
   - `table` → tabela de modelo,
   - `column` → colunas físicas ou calculadas,
   - `measure` → medidas DAX,
   - `relationship` → relacionamentos,
   - `role` → RLS.

3. Para cada elemento, gerar um registro com:
   - ID interno do framework (mais sobre isso abaixo),
   - nome que aparece no modelo,
   - tabela “pai” (quando fizer sentido),
   - expressão DAX (para medidas / colunas calculadas),
   - tipo de dado,
   - metadados básicos.

4. Guardar tudo numa estrutura intermediária (dicionário Python ou lista de objetos).

#### Sobre IDs

O framework evita depender só do nome da medida/tabela. Motivo:

- nomes podem mudar,
- podem ter duplicatas em contextos distintos.

Então a regra geral é:

- gerar um ID **estável** baseado em:
  - nome,
  - tipo do objeto (tabela/coluna/medida/visual),
  - e, quando faz sentido, o caminho (tabela + nome, página + visual etc.).

Isso costuma ser algo como:

- um **hash** do caminho completo (ex: `employee_dimension/employee_id`), ou
- um identificador incremental, mas sempre associado ao “caminho lógico”.

O ponto é: o ID da medida no `model_structure.json` é o mesmo que depois aparece nos bancos do Notion, permitindo cruzar tudo.

---

### 3.3. Parsing de `report.json` e arquivos de visual

Aqui o objetivo não é o layout bonitinho. É saber:

- Quais **páginas** existem,
- Quais **visuais** existem,
- Quais **campos/medidas** aparecem em cada visual.

Fluxo típico:

1. Abrir `report/report.json`.
2. Percorrer as seções (pages/sections):
   - Cada seção → uma **Página do relatório**:
     - Nome,
     - Ordem,
     - Identificador único.
3. Para cada página:
   - Percorrer os visuais declarados,
   - Identificar:
     - tipo de visual (table, barChart, slicer…),
     - campos ligados àquele visual (tabelas, colunas, medidas).

4. Criar uma estrutura tipo:

```jsonc
{
  "pages": [
    {
      "page_id": "PAGE_001",
      "name": "Overview",
      "visuals": [
        {
          "visual_id": "VISUAL_001",
          "type": "table",
          "fields": [
            "employee_dimension[employee_name]",
            "measures[active_period_cnt_ctx_cltpj_cy]"
          ]
        }
      ]
    }
  ]
}
```

> Nota: os nomes acima são apenas ilustrativos — o importante é o conceito.

---

### 3.4. Parsing do M code (conexões)

A partir dos arquivos de conexão, o minerador:

1. Abre os arquivos onde o M está salvo (em JSON ou outro formato interno).
2. Extrai:

   - Nome da fonte (por ex. `Sql.Database` / `BigQuery.Database` / `SharePoint.Files`),
   - Servidor / DataSource principal,
   - Banco / Schema / Dataset quando estiver disponível,
   - Nomes das Queries.

3. Cria uma coleção de “**Conexões DB**” que depois alimenta o BD7 no Notion.   

---

### 3.5. Estrutura do `model_structure.json`

De forma simplificada, esse arquivo costuma ter seções como:

```jsonc
{
  "project": {
    "name": "HR KPIs Board",
    "path": "..."
  },
  "tables": [...],
  "columns": [...],
  "measures": [...],
  "relationships": [...],
  "pages": [...],
  "visuals": [...],
  "connections": [...],
  "roles": [...]
}
```

Cada seção traz os campos necessários para o constructor entender:

- o **que** existe no modelo,
- **como** se relaciona,
- e **onde** isso aparece no relatório.

---

## 4. Deep‑dive no constructor

Agora entramos no bloco 2: **constructor**.

> Metáfora: é o “pedreiro chique” que pega o caminhão de tijolos (JSON/CSV) e levanta um prédio organizado (Notion) com tudo linkado.

### 4.1. O que o constructor faz

1. Lê o `model_structure.json` (e outros arquivos auxiliares, como `measures_enriched.csv` quando a IA está ligada).
2. Conecta na API do Notion (usando as credenciais definidas no setup).
3. Garante que os bancos de destino existam (BD1, BD2, BD3, BD5, BD6, BD7, BD8).   
4. Cria (ou atualiza) páginas/linhas em cada BD com os registros correspondentes:
   - cada tabela,
   - cada coluna,
   - cada medida,
   - cada relacionamento,
   - cada página de relatório,
   - cada visual,
   - cada conexão / fonte de dados,
   - cada role de RLS.

5. Preenche campos técnicos + campos “editoriais” mínimos (ex: status, tags).

### 4.2. Os bancos do Notion (BD1…BD8)

Pelo plano, temos pelo menos estes bancos:   

- **BD1 – Relacionamentos**
  - Uma linha por relacionamento do modelo.
  - Campos típicos:
    - Tabela From,
    - Coluna From,
    - Tabela To,
    - Coluna To,
    - Cardinalidade,
    - Direção de filtro,
    - Ativo? (sim/não).

- **BD2 – Tabelas**
  - Uma linha por tabela do modelo.
  - Campos:
    - Nome da tabela,
    - Tipo (fato, dimensão, bridge, auxiliar),
    - Número de colunas,
    - Número de medidas ligadas,
    - Área / domínio (ex: HR, Finance, Operação),
    - Comentários.

- **BD3 – Páginas do Relatório**
  - Uma linha por página do relatório.
  - Campos:
    - Nome da página,
    - Ordem,
    - Código interno / ID,
    - Quantidade de visuais,
    - Visuais principais (resumo),
    - Status (ativo, em construção, legado).

- **BD5 – Medidas DAX**
  - Uma linha por medida.
  - Campos:
    - Nome da medida,
    - Tabela “host”,
    - Expressão DAX (limpa),
    - Categoria (KPI, auxiliar, governança, etc.),
    - Se foi enriquecida por IA ou não,
    - Onde é usada (páginas/visuais) – alimentado pelo pós‑processamento.

- **BD6 – Tabelas DAX (tabelas calculadas)**
  - Uma linha por tabela calculada.
  - Campos:
    - Nome,
    - Expressão DAX,
    - Uso principal,
    - Relação com outras tabelas.

- **BD7 – Conexões DB**
  - Uma linha por conexão / fonte.
  - Campos:
    - Tipo de fonte (SQL, BigQuery, SharePoint, etc.),
    - Servidor / host,
    - Banco / dataset,
    - Tabelas / queries principais,
    - Ambiente (dev, stage, prod).

- **BD8 – RLS**
  - Uma linha por role de RLS.
  - Campos:
    - Nome da role,
    - Tabela alvo,
    - Filtro DAX,
    - Responsável,
    - Observações (quem pediu, quando, para quê).

> Importante: Os nomes “BD1”, “BD2” etc. são apenas apelidos internos. No Notion eles podem estar com nomes mais amigáveis, ex: “Relatórios – Relacionamentos”, “Relatórios – Medidas DAX”…  

---

### 4.3. Como o constructor cria e atualiza os BD

Fluxo padrão:

1. Para cada BD:
   - Verifica se já existe (pelo ID salvo em configuração ou pelo nome).
   - Se não existe:
     - Cria o banco com as colunas (propriedades) necessárias.
   - Se existe:
     - Garante que as propriedades mínimas estão lá (adiciona se faltar).

2. Para cada objeto vindo do `model_structure.json`:
   - Monta um payload para a API do Notion com:
     - propriedades técnicas (nome, tipo, IDs),
     - propriedades funcionais (status, tags, área…).

3. Aplica uma estratégia de **upsert**:
   - Se já existe uma página/registro com aquele ID lógico:
     - atualiza os campos.
   - Senão:
     - cria um novo registro.

Assim, você consegue rodar o framework várias vezes sem duplicar tudo.

---

## 5. Pós‑processamento e construção dos links

O terceiro script faz a parte mais “agradável para o usuário final”: **links navegáveis**.

### 5.1. O que ele faz na prática

1. Lê dos BD:
   - todas as medidas (BD5),
   - todas as páginas (BD3),
   - todos os visuais (se você tiver um BD específico para visuais / layouts),
   - tabelas e colunas quando necessário.

2. Para cada medida:
   - localiza em quais páginas/visuais ela aparece,
   - monta uma lista de referências.

3. Atualiza os registros no Notion:
   - campos de relação (por ex.: propriedade “Páginas onde aparece”),
   - campos de links (por ex.: URL para a página da medida, URL para a página do visual).

### 5.2. De onde vêm as informações de uso da medida?

Do cruzamento:

- Minerador disse:
  - “Visual X usa a medida Y.”
- Constructor criou:
  - BD3 (páginas),
  - BD‑Visuais (caso exista),
  - BD5 (medidas).

Pós‑processamento então consegue fazer:

- Visual → Medidas,
- Medida → Visuais,
- Medida → Páginas.

É isso que transforma o Notion numa espécie de:

> “Google interno” da documentação do projeto.

---

## 6. Fluxograma arquitetural (end‑to‑end)

### 6.1. Pipeline completo (modo linha de produção)

```text
1. PBIP pronto
   ↓
2. Rodar Minerador
   - Lê model.tmdl
   - Lê report.json
   - Lê conexões / M
   - Gera model_structure.json + CSVs auxiliares
   ↓
3. Rodar Constructor
   - Lê model_structure.json
   - Cria/atualiza BD1, BD2, BD3, BD5, BD6, BD7, BD8
   - Carrega registros técnicas e funcionais
   ↓
4. Rodar Pós-processamento
   - Lê Notion
   - Cruza IDs (medidas, páginas, visuais)
   - Atualiza relacionamentos e links
   ↓
5. Resultado
   - Inventário vivo e navegável no Notion
```

### 6.2. Mapa de dependência entre componentes

- **Scripts Python** dependem de:
  - Estrutura do PBIP,
  - Configuração (`pbi_config.json`),
  - Credenciais / token da API do Notion.

- **Bancos (BD1–BD8)** dependem de:
  - `model_structure.json`,
  - Padrão de IDs consistente,
  - Regras de criação do constructor.

- **Links navegáveis** dependem de:
  - Execução bem‑sucedida do pós‑processamento,
  - Nome / ID estáveis dentro do Notion.

Regra de ouro:

> Se você quebrar o padrão de IDs, você quebra os links.  
> Se você respeitar os IDs, pode refatorar praticamente qualquer outra coisa.

---

## 7. Como estender o framework (sem virar Frankenstein)

Aqui entra a parte divertida para quem gosta de evoluir framework. 🧱  

### 7.1. Adicionando novos blocos de informação

Exemplos de extensões:

- Inventário de:
  - KPIs “oficiais” vs “auxiliares”.
  - Métricas de qualidade (ex: medidas sem descrição, tabelas sem uso, etc.).
  - Versões de deployment (prod, stage, sandbox).

Caminho seguro:

1. **Comece pelo minerador**:
   - Pergunta: “Que nova informação eu quero capturar do PBIP?”
   - Ajuste o parser para incluir esses dados em `model_structure.json`.

2. **Depois vá para o constructor**:
   - Crie um novo BD (ex: BD9 – Governança).
   - Adicione as propriedades mínimas.
   - Alimente esse BD usando os dados novos do `model_structure.json`.

3. **Se precisar de navegação**:
   - Ajuste o script de pós‑processamento para cruzar seus novos IDs com BD existentes.

### 7.2. Ativando módulos futuros

Você pode tratar módulos como “feature flags”:

- Exemplo: `enable_ai_enrichment`, `enable_rls_inventory`, `enable_kpi_governance`.
- A chave fica no `pbi_config.json`.
- Scripts só executam aquela parte se a flag estiver ativada.

Isso facilita:

- Testar coisas novas sem impactar o fluxo principal.
- Manter o framework **backwards compatible**.

### 7.3. Alterando templates

Os templates principais hoje são:

- Estrutura do `model_structure.json`,
- Estrutura dos bancos no Notion (propriedades / campos),
- Padrão visual dos PDFs / HTML (no caso do docs_generator).

Se for alterar:

1. **Documente a versão** (ex: `schema_version = "1.1"` dentro do JSON).
2. **Atualize o README / Tutorial Técnico** com o que mudou.
3. **Mantenha migrações simples**:
   - Exemplo: caso mude propriedade de “Texto” para “Select” no Notion, trate isso num passo de migração isolado.

### 7.4. Adaptando para Azure Data Lake, Fabric, Purview

O framework já está pronto para ser “amigo” de outros mundos:

- **Azure Data Lake / Fabric**:
  - Podem ser mais uma camada de origem (na parte de conexões / M).
  - Você pode estender o BD7 com campos específicos:
    - Lakehouse / Warehouse,
    - Workspace Fabric,
    - Camada (Bronze/Silver/Gold).

- **Purview / Governança corporativa**:
  - O inventário do Power BI pode alimentar catálogos corporativos.
  - Você pode exportar partes do Notion para:
    - CSV,
    - APIs,
    - outros sistemas de catalogação.

A ideia é simples: o framework entrega um **modelo organizado de metadados**.  
De lá, você pode plugar em praticamente qualquer stack de governança.

---

## 8. Preparação para GitHub — distribuição pública e escalável

Essa parte é o “modo Open Source ON”.   

O plano é transformar este framework em um repositório nível profissional, com:

- README caprichado,
- dois tutoriais bem amarrados,
- estrutura de pastas limpa,
- exemplos de uso,
- e um roadmap claro.

### 8.1. Posição do GitHub no ecossistema

Pense no GitHub como:

> **Ponto de verdade do framework**,  
> e não apenas “onde o código mora”.

Ele deve contar a história completa:

- O que é o projeto,
- Como instalar,
- Como rodar,
- Como contribuir,
- O que está por vir.

### 8.2. Checklist de um repositório bem‑cuidado

Itens que vale ter:

- `README.md` com:
  - visão geral,
  - arquitetura,
  - requisitos,
  - tutoriais (1 e 2),
  - links para exemplos / GIFs.

- Estrutura de pastas clara, por exemplo:

```text
/ docs/                 # Tutoriais, diagramas, exemplos
/ src/                  # Código-fonte dos scripts Python
    /miner/             # Lógica do minerador
    /constructor/       # Lógica do constructor
    /post_processing/   # Scripts de links / pós-processamento
/ examples/             # PBIP de exemplo (anonimizado)
/ .gitignore
/ LICENSE
/ CHANGELOG.md
```

- `LICENSE` (ex: MIT ou Apache 2.0).
- `CHANGELOG.md` com versões (`v1.0.0`, `v1.1.0`…).
- Seção de **Contribuição**:
  - Como abrir issues,
  - Como sugerir novas features,
  - Como abrir PR.

### 8.3. Como este Tutorial 2 se conecta com o GitHub

Este tutorial já é praticamente o “**README técnico avançado**”:

- Ele explica o **porquê** de cada escolha (PBIP, TMDL, JSON, Notion).
- Ele detalha **como o código está organizado logicamente**.
- Ele dá gasolina para qualquer dev contribuir sem medo.

No GitHub, você pode:

- Linkar este conteúdo direto em `/docs/tutorial_tecnico.md`.
- Referenciar as seções no próprio README (ex: “Quer entender a arquitetura? Veja o Tutorial Técnico.”).

---

## 9. Checklist mental para quem vai mexer no código

Antes de alterar qualquer coisa no framework, pergunte:

1. **Estou respeitando o padrão de IDs?**
2. **Estou preservando a estrutura do `model_structure.json` ou atualizando a versão do schema?**
3. **Estou mantendo a compatibilidade com os BD do Notion (BD1–BD8)?**
4. **Se estou adicionando algo novo, já pensei onde isso entra no pipeline (minerador, constructor, pós)?**
5. **Atualizei a documentação (Tutorial 1 ou 2 + README)?**

Se a resposta para tudo isso é “sim”, pode seguir.  
Se alguma resposta for “não sei”, volta duas casas, respira, pega um café ☕ e revisa com calma.

---

## 10. Fechamento

Parabéns por chegar até aqui. 🎉

Se o Tutorial 1 te ensinou a **dirigir o carro**,  
este Tutorial 2 te mostrou **como o motor foi desenhado**.

- Você sabe onde está o minerador,
- você sabe o que o constructor faz,
- você sabe como o pós‑processamento monta os links,
- e você tem um mapa claro de como estender o framework sem travar a operação.

Daqui pra frente, o jogo muda:

> Em vez de perguntar “como isso funciona?”,  
> você começa a perguntar “o que dá pra melhorar aqui?”. 😎

Bom proveito — e que venham os próximos módulos.
