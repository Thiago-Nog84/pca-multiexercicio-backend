# Super Prompt — Microsoft Copilot (SharePoint/M365)
# Projeto PCA Multiexercício — MPPI

> Cole o bloco abaixo diretamente no Copilot (chat, Teams, ou Copilot.microsoft.com).
> Adapte as seções marcadas com `[AJUSTE]` conforme o nome real das pastas/sites no SharePoint.

---

## PROMPT COMPLETO

---

Você é um assistente de pesquisa documental especializado em licitações e contratos públicos. Estou construindo um sistema Django de gestão de Atas de Registro de Preços (ARPs) e contratos do **Ministério Público do Piauí (MPPI)** — CNPJ `05.805.924/0001-89`, UASG `926092`.

Preciso que você **pesquise nos arquivos do SharePoint** [AJUSTE: indique o site/pasta raiz, ex: "no site 'MPPI - Contratos'" ou "na pasta 'SRP 2024-2025'"] e me retorne dados estruturados para alimentar o sistema. Siga cada bloco de tarefa abaixo em sequência.

---

### BLOCO 1 — Atas de Registro de Preços (ARPs) originadas pelo MPPI

Busque planilhas, documentos Word/PDF e arquivos nomeados com termos como:
- "ATA", "ARP", "Registro de Preços", "Pregão", "Ata nº", "Ata de RP"

Para cada ARP encontrada, extraia e liste em formato de tabela:

| Campo | Exemplo esperado |
|---|---|
| Número da ARP | 00012/2025 |
| Ano | 2025 |
| Objeto resumido | Registro de preços para eventual aquisição de... |
| CNPJ do fornecedor | 00.000.000/0001-00 |
| Razão social do fornecedor | Empresa X Ltda |
| Valor total registrado (R$) | 150.000,00 |
| Data início vigência | 01/03/2025 |
| Data fim vigência | 01/03/2026 |
| Número do processo SEI | 00000/2025-XX |
| Número do pregão/edital | 001/2025 |
| Unidade requisitante gestora | DAF / CEAC / INFRA |
| Link/caminho do documento no SharePoint | https://... |

Se houver **itens individuais da ARP** (com código, descrição, quantidade, unidade, valor unitário), liste-os em tabela separada vinculada ao número da ARP.

---

### BLOCO 2 — Contratos decorrentes de ARPs

Busque arquivos com termos: "contrato", "nota de empenho", "NE", "ordem de fornecimento", "contratação decorrente", "processo de compra".

Para cada contrato identificado como decorrente de ARP, extraia:

| Campo | Exemplo esperado |
|---|---|
| Número do contrato/NE | 2025NE00139 ou 25018921 |
| CNPJ do contratado | 00.000.000/0001-00 |
| Razão social do contratado | Empresa X Ltda |
| Objeto do contrato | Aquisição de cadeiras empilháveis |
| Valor do contrato (R$) | 12.500,00 |
| Data de assinatura | 15/04/2025 |
| ARP de origem referenciada | ARP nº 00012/2025 |
| Número do processo SEI vinculado | 00000/2025-XX |
| Número da nota de empenho | 2025NE00139 |
| Unidade requisitante | DAF / CEAC / INFRA |
| Link/caminho do documento | https://... |

**Atenção especial:** Se o objeto do contrato mencionar termos como "adesão", "carona", "adesão à ata", "adesão ao registro" ou "ata de outro órgão", marque a coluna "Tipo" como **CARONA** e indique o órgão gerenciador da ARP externa se mencionado.

---

### BLOCO 3 — Planilhas de acompanhamento de ARPs

Busque arquivos Excel (.xlsx, .xls) ou planilhas do tipo:
- "Acompanhamento ARP", "Controle de Ata", "Controle SRP", "Saldo ARP", "Painel SRP"

Para cada planilha encontrada, identifique e descreva:
1. Nome do arquivo e caminho no SharePoint
2. Quais ARPs são referenciadas (números)
3. Quais colunas existem (liste os cabeçalhos da planilha)
4. Se há dados de **saldo utilizado vs. saldo disponível por item**
5. Se há vínculo entre contratos/NEs e itens da ARP

---

### BLOCO 4 — Documentos SEI relacionados a ARPs e Contratos

Busque arquivos que pareçam exportações do sistema SEI (PDF ou HTML com cabeçalho "MPPI", numeração tipo "SEI nº 0000000"):

Para cada documento SEI encontrado, extraia:

| Campo | Descrição |
|---|---|
| Número SEI | Ex: 0995485 |
| Tipo do documento | Ex: Ata de RP, Contrato, Empenho, Acompanhamento |
| ARP ou Contrato relacionado | Ex: ARP 00012/2025 |
| Data do documento | |
| Unidade emitente | |
| Resumo do conteúdo (2-3 linhas) | |

---

### BLOCO 5 — Fornecedores recorrentes

Com base em todos os documentos encontrados, gere uma lista consolidada de fornecedores que aparecem tanto em ARPs quanto em contratos, contendo:

| CNPJ | Razão Social | ARPs vinculadas | Contratos vinculados | Total R$ |
|---|---|---|---|---|

Isso me permite cruzar automaticamente ARPs e contratos pelo CNPJ do fornecedor.

---

### BLOCO 6 — Contratos SEM vínculo identificado com ARP

Liste os contratos encontrados que **não mencionam** nenhuma ARP, ata, pregão ou processo licitatório de origem. Esses são candidatos a vínculo manual ou investigação.

---

### BLOCO 7 — Índice geral de documentos encontrados

Ao final, gere um índice de todos os arquivos relevantes encontrados no SharePoint, organizado por tipo:

**ARPs:** (lista com número, fornecedor, valor, link)
**Contratos:** (lista com número, contratado, ARP origem se identificada, link)  
**Planilhas de controle:** (lista com nome, o que controla, link)
**Documentos SEI:** (lista com número SEI, tipo, link)
**Outros relevantes:** (qualquer outro arquivo útil para gestão de SRP/contratos)

---

### INSTRUÇÕES GERAIS DE COMPORTAMENTO

- Se um arquivo estiver protegido ou inacessível, anote "Sem acesso" e continue.
- Se um campo não puder ser extraído, use "N/I" (não identificado).
- Priorize arquivos modificados nos últimos 24 meses (2024 e 2025).
- Se encontrar arquivos com nomes duplicados ou versões (v1, v2, FINAL, revisado), liste apenas o mais recente mas mencione que há versões anteriores.
- Para valores monetários, mantenha o formato brasileiro (vírgula como decimal).
- Ao encontrar CNPJs, normalize-os para o formato `XX.XXX.XXX/XXXX-XX`.
- Se uma ARP mencionar **itens individuais** (com CATMAT/CATSER, descrição, quantidade), extraia esses itens — eles são críticos para correspondência com contratos.

---

### O QUE FAZER SE ENCONTRAR ESTES DOCUMENTOS ESPECÍFICOS

- **"Painel de Contratos"** ou **"Painel SRP"** → extraia todas as colunas; o painel costuma ter: N°, ANO, CONTRATANTE, OBJETO, STATUS REQUISITANTE — são dados de ouro.
- **"Mapa de Riscos"** ou **"Acompanhamento de Execução"** → extraia percentual executado por item da ARP.
- **"Notas de Empenho"** em PDF → extraia: número NE, CNPJ credor, valor, processo de referência, data.
- **"Minuta de ARP"** ou **"Termo de ARP"** → extraia número da ARP, CNPJ, objeto, itens com valores unitários.
- **"Memória de Cálculo"** → extraia qual ARP e item está sendo utilizado, quantidade, valor unitário aplicado.

---

**Formato de saída preferido:** tabelas Markdown, que posso copiar diretamente para meu sistema.  
**Idioma:** Português (Brasil).  
**Prioridade máxima:** CNPJ do fornecedor + número da ARP + datas de vigência — esses três campos permitem vincular automaticamente 80% dos contratos às suas ARPs de origem.

---

> **Versão do prompt:** 1.0 — 2026-06-28  
> **Projeto:** PCA Multiexercício — MPPI  
> **Repositório Django:** `C:\Dev\pca-multiexercicio-backend`
