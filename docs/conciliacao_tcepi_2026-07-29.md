# Integração TCE-PI (Portal da Cidadania) e conciliação de empenhos — 2026-07-29

## Contexto

Exploração da API pública do Portal da Cidadania do TCE-PI
(`https://sistemas.tce.pi.gov.br/api/portaldacidadania/`) como TERCEIRA fonte
de validação, independente do SIAFE (execução orçamentária do Executivo) e do
PNCP/dadosabertos (divulgação de compras). A API **não exige autenticação**.

Os `idUnidadeGestora` do MPPI no TCE são idênticos aos códigos de UG já usados
na integração SIAFE:

| Chave local | UG | Nome no TCE |
|---|---|---|
| `pgj` | 250101 | MINISTÉRIO PÚBLICO - PROCURADORIA GERAL DE JUSTICA |
| `fmmp` | 250102 | MINISTÉRIO PÚBLICO - FUNDO ESPECIAL DO MINISTERIO PUBLICO |
| `fepdc` | 250104 | MINISTÉRIO PÚBLICO - FUNDO DE PROTECAO E DEFESA DO CONSUMIDOR |

## O que foi construído

**Novo app `apps/tcepi/`** — `TcePiClient` (sem autenticação, com paginação
automática): órgãos, despesas por elemento/função/natureza, credores,
licitações por órgão/data, documentos. Registrado em `INSTALLED_APPS`;
`TCEPI_BASE_URL` em `settings.py`.

**Comandos novos** (todos somente leitura, exceto os de correção explícita):

| Comando | Função |
|---|---|
| `conciliar_tcepi` | Cruza `Empenho` local × credores do TCE por órgão/exercício |
| `listar_empenhos_credor` | Lista os `Empenho` locais de um CNPJ (bruto e líquido de anulação) |
| `investigar_ne_faltante` | Busca no SIAFE todas as NEs de um credor e diz quais não foram importadas, e por quê |
| `listar_nes_sem_contrato_local` | Lista NEs cujo `codContrato` não bate com nenhum contrato local, separando compra direta |
| `sugerir_vinculo_ne_contrato` | Para cada `codContrato` órfão, sugere se falta só o `codigo_siafe` ou o contrato inteiro |
| `auditar_empenhos_manuais` | Confere `Empenho` com `importado_siafe=False` contra o SIAFE |
| `cadastrar_contrato_manual` | Cadastra contrato confirmado por documento fonte (idempotente) |
| `corrigir_codigo_siafe_manual` | Preenche/corrige `codigo_siafe` com vínculo confirmado |
| `corrigir_unidade_orcamentaria_manual` | Preenche `unidade_orcamentaria` confirmada manualmente |
| `inferir_fonte_contratos_via_tcepi` | Infere `unidade_orcamentaria` cruzando CNPJ com credores do TCE |

## Resultado da conciliação (exercício 2026)

**52 CONFERE | 4 DIVERGE | 2 NÃO ENCONTRADO** nos três órgãos.

Partindo de 25 CONFERE / 4 DIVERGE só na PGJ, no início.

## Correções aplicadas

1. **Bug no `conciliar_tcepi`**: NEs `tipo='anulacao'` estavam sendo somadas como
   positivas. Master Facilities aparecia com R$6,08mi local × R$1,07mi no TCE;
   descontando a anulação (`2026NE00738`, R$2.504.625,82) sobre a NE
   `2026NE00434` (R$3.572.724,80), o líquido é R$1.068.098,98 — bate exato.
2. **EPSG (CNPJ 04276973000109)**: contratos pk=230 (`23002407`) e pk=238
   (`21/2024`) estavam sem `unidade_orcamentaria`. A soma dos 3 contratos dela
   (R$545.495,59) bate exatamente com o total do TCE para a PGJ — confirmando
   que os 3 são PGJ. Aplicado via `corrigir_unidade_orcamentaria_manual`.
3. **Contrato 13/2026/PGJ (Laís G de Sousa) não existia no banco**. Achado via
   `investigar_ne_faltante`: NE `2026NE00165` (R$22.501,00) com
   `codContrato=26100672` sem par local. Confirmado pelo PDF SEI
   19.21.0428.0012055/2026-09. Cadastrado via `cadastrar_contrato_manual`.
4. **`codigo_siafe` preenchido em 3 contratos** (valor e objeto idênticos aos da NE):
   - pk=268 `43/2026/FMMPPI` → `26000337` (DOMINI, R$42.940,40)
   - pk=264 `07/2026/FMMPPI` → `26100631` (NORDESTE, R$31.860,00)
   - pk=263 `05/2026/PGJ` → `26100643` (NTSEC, R$1.553.207,77) — **resolve a
     pendência antiga** "05/2026/PGJ (NTSEC) NÃO foi preenchido, numeração
     interna do MPPI não corresponde 1:1 à sequência SIASG"
5. **`codigo_siafe` corrigido**: pk=176 `10/2026/FPDC` (SORELLE) apontava para
   `25017404` (código de 2025 num contrato de 2026); correto é `26100669`.
6. **`unidade_orcamentaria` inferida em massa**: 51 de 75 contratos sem
   classificação resolvidos automaticamente cruzando CNPJ com credores do TCE
   (`inferir_fonte_contratos_via_tcepi`), mais 6 pelo `inferir_fonte_contratos`
   por sufixo. 11 ficaram ambíguos (CNPJ presente em mais de um órgão) e 13 não
   encontrados no TCE (quase todos pessoa física, locação de imóvel antiga).
7. **Timeout do `SiafeClient`**: autenticação usava 15s enquanto as consultas
   usam 30s — causou `ReadTimeout` real. Alinhado para 30s.

## Limitação estrutural documentada (não é bug)

O TCE soma **todo** o empenhado do credor, inclusive despesas **sem instrumento
contratual** (compra direta / dispensa). O modelo `Empenho` local exige FK
obrigatória para `Contrato`, então NE sem contrato não é registrável — no SIAFE
ela vem com `codContrato='00000000'` e é contada como "avulsa" (832 NEs em 2026).

Consequência: para credores com compra direta, o total local fica legitimamente
abaixo do TCE. Caso confirmado: ZENITE, diferença de R$5.568,00 = NE
`2026NE00818`, contratação sem contrato. **Nada a corrigir.**

Isso está documentado no docstring do `conciliar_tcepi` e a saída do comando já
sugere rodar `investigar_ne_faltante` quando local < TCE.

---

# PENDENTE — retomar daqui

## 1. Empenhos manuais fabricados (PRIORIDADE — decisão pendente)

`auditar_empenhos_manuais --exercicio 2025` revelou que **~38 dos 62** registros
de `Empenho` com `importado_siafe=False` têm `numero_empenho` **fabricado a
partir do número do contrato**, não são NEs reais:

| Contrato local | `numero_empenho` gravado |
|---|---|
| `56/2025 PGJ` | `2025NE00056` |
| `78/2025` | `2025NE00078` |
| `120/2025` | `2025NE00120` |
| `25017488` | `25017488` (codigo_siafe copiado) |

Provável origem: o antigo comando `vincular_empenhos_siafe`, que tinha um dict
`EMPENHOS_CONHECIDOS` hardcoded (ver memória do projeto: "69 linhas, TODAS
`importado_siafe=False`").

Três variantes:

- **24 casos `CREDOR DIFERENTE`** — o número fabricado colide com uma NE real do
  SIAFE que pertence a outro credor (diárias, suprimento de fundos, folha de
  pagamento). Dano comprovado: inflam o empenhado do credor errado e quebram a
  conciliação com o TCE.
- **4 casos com sufixo "A"** inventado (`2025NE00058A`, `104A`, `105A`, `106A`).
- **10 casos** usando `codigo_siafe` de 8 dígitos ou número de nota de reserva
  (`2025NR00104`) no lugar do número de empenho.

Os valores também não batem — o `valor_empenhado` desses registros parece ser o
valor do **contrato**, não de um empenho (ex: pk=3 local R$23.370,00 × SIAFE
R$53.400,00).

**Caso que originou a investigação:** pk=26, NE `2026NE00010`, R$25.132,47,
registrado como SORELLE no contrato `10/2026/FPDC`. O documento SIAFE
(NL `2026NL00135` / OB `2026OB00362`) prova que essa NE é de **L H C HAIDAR
SOUSA** (CNPJ 42.489.485/0001-79), **UG 250102 (FMMP)**, contrato SIAFE
`26100660`, objeto "projetos de prevenção e combate a incêndio" — credor, órgão
e objeto totalmente diferentes.

**Decisão pendente** (opções levantadas):
- (a) apagar todos os ~38 fabricados e repovoar com `importar_empenhos_siafe`;
- (b) apagar só os 24 com credor errado (dano comprovado), deixando os 14
  "NÃO ENCONTRADA" para análise;
- (c) só gerar relatório e levar à equipe antes de excluir;
- (d) rodar `auditar_empenhos_manuais --exercicio 2026` antes de decidir, para
  dimensionar o problema nos dois exercícios.

**`auditar_empenhos_manuais --exercicio 2026` ainda NÃO foi rodado.**

## 2. Contratos faltando cadastrar (20 casos)

`sugerir_vinculo_ne_contrato --exercicio 2026`, grupo (2). Maiores:

| codContrato | Valor | Credor |
|---|---|---|
| `26000322` | R$463.980,00 | HPE AUTOMOTORES (2 caminhonetes Mitsubishi Triton) |
| `26100663` | R$47.299,62 | BIM PROJETOS (projetos de incêndio) |
| `26000324` | R$36.731,23 | INOVARE ENGENHARIA |
| `26000334` | R$33.760,00 | L F DE LIMA (segurança eletrônica) |
| `26100671` | R$31.014,15 | E PACHECO LOPES FILHO (higiene e limpeza) |

Vários têm contrato equivalente de 2025 no banco (Rainha do Gás, Porto Seguro,
Double Soluções, EASWELL) — provavelmente renovações/novos contratos do
exercício ainda não cadastrados. Cada um precisa do documento fonte (SEI/PNCP)
antes de usar `cadastrar_contrato_manual`.

## 3. Casos ambíguos de vínculo

- **ALFA GESTÃO (2 casos)**: `26000315` (R$2.504.625,82, "auxiliar de serviços
  gerais, bombeiro") e `26000311` (R$926.168,89, "46 postos de agente de
  limpeza"). Candidatos locais: pk=262 `36/2026` (R$4.017.118,08, "Agente de
  Limpeza") e pk=265 `35/2026/PGJ` (R$10.863.437,28, registro de preços).
  Pelo objeto, `26000311`→pk=262 e `26000315`→pk=265, mas os valores não batem.
  **Nota importante:** o valor de `26000315` (R$2.504.625,82) é **exatamente** o
  da anulação da Master Facilities no contrato `29/2026/PGJ` — indício forte de
  sucessão contratual (troca de prestador no mesmo objeto).
- **pk=102 `06/2026/FPDC`** tem `codigo_siafe='26100635'`, mas o SIAFE mostra o
  contrato do SISTEMA AVANÇADO (mesmo valor R$10.080,00) como `26100634` —
  diferença de um dígito, possível erro de digitação. Conferir qual é o correto.

## 4. Divergências de conciliação ainda abertas

- **READY TECNOLOGIA** (FMMP): local R$1.277.258,75 × TCE R$4.777.258,75 —
  diferença de **exatamente R$3.500.000,00** (número redondo demais para ser
  coincidência).
- **ALTACON ENGENHARIA** (FMMP): R$1.490.701,03 local, mas não aparece como
  credor do FMMP no TCE — possível `unidade_orcamentaria` errada.
- **MULTIPAR** (FMMP): local R$770,64 × TCE R$6.459,16.
- **LCS COMÉRCIO DE FOTOGRAFIA** (FEPDC): R$47.169,78 local, ausente no TCE.

## 5. Outros pendentes

- 11 contratos com `unidade_orcamentaria` ambígua (CNPJ em mais de um órgão) e
  13 não encontrados no TCE (pessoa física / locações antigas 2015–2018).
- `liquidado local = R$0,00` em todos os credores: a importação do SIAFE só traz
  empenho, não liquidação. Melhorar cruzando com `notas_liquidacao_por_ug`.
- Endpoint de licitações do TCE não retorna nada para os órgãos do MPPI no
  exercício — investigar se é questão de esfera/parâmetro ou ausência de dado.
