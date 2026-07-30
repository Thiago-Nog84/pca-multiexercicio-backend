# Integração TCE-PI (Portal da Cidadania) e conciliação de empenhos — 2026-07-29/30

> **Status: conciliação CONCLUÍDA.** Nos três órgãos do MPPI, todas as
> divergências restantes têm causa identificada e documentada. Nenhuma decorre
> de erro de dado. Ver "Estado final" abaixo.

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
| `limpar_empenhos_fabricados` | Remove empenhos manuais com número fabricado (dupla condição de segurança) |
| `dump_ne_siafe` | Despeja o JSON bruto de uma NE em todas as UGs |
| `cadastrar_contrato_manual` | Cadastra contrato confirmado por documento fonte (idempotente) |
| `corrigir_codigo_siafe_manual` | Preenche/corrige `codigo_siafe` com vínculo confirmado |
| `corrigir_unidade_orcamentaria_manual` | Preenche `unidade_orcamentaria` confirmada manualmente |
| `inferir_fonte_contratos_via_tcepi` | Infere `unidade_orcamentaria` cruzando CNPJ com credores do TCE |

---

# Estado final (exercício 2026)

| Órgão | Divergências | Situação |
|---|---|---|
| **FMMP** (250102) | 0 | conciliado |
| **FEPDC** (250104) | 0 | conciliado |
| **PGJ** (250101) | 2 | ambas NE sem instrumento contratual |

Evolução: começou em **25 CONFERE / 4 DIVERGE / 2 NÃO ENCONTRADO** (só PGJ) e
terminou com **0 NÃO ENCONTRADO** e todas as divergências explicadas.

## As 2 divergências remanescentes (sem correção possível)

| Credor | Diferença | NE | Causa |
|---|---|---|---|
| INSS | R$ 130.000,00 | `2026NE00167` | juros de dívida contratual, `codContrato='00000000'` |
| ZENITE | R$ 5.568,00 | `2026NE00818` | contratação sem contrato (compra direta) |

Ambas são o mesmo caso: **NE sem instrumento contratual**. O modelo `Empenho`
exige FK obrigatória para `Contrato`, então despesa direta não é registrável
por design (são 832 NEs "avulsas" em 2026). Se um dia for necessário
contabilizá-las, a saída é tornar `Empenho.contrato` opcional — decisão de
modelagem, não correção de dado.

O caso do INSS foi previsto pela leitura das despesas por elemento do TCE:
"Principal da Dívida Contratual Resgatado" R$123.310,88 (= valor local) e
"Juros sobre a Dívida por Contrato" R$130.000,00 (= a diferença).

---

# Correções aplicadas

## Bugs de código

1. **`conciliar_tcepi` somava anulação como positiva.** NEs
   `tipo='anulacao'` reduzem o empenhado; somá-las dobrava a divergência.
   Master Facilities aparecia com R$6,08mi local × R$1,07mi no TCE; descontando
   a anulação `2026NE00738` (R$2.504.625,82) sobre a NE `2026NE00434`
   (R$3.572.724,80), o líquido é R$1.068.098,98 — bate exato.
2. **`SiafeClient`: timeout da autenticação era 15s** enquanto as consultas usam
   30s — causou `ReadTimeout` real. Alinhado para 30s. (O SIAFE ainda apresenta
   timeouts intermitentes; basta repetir o comando.)

## Limpeza de dados fabricados (41 registros, R$ 11.929.638,15)

`auditar_empenhos_manuais` revelou que 41 dos 65 `Empenho` com
`importado_siafe=False` tinham `numero_empenho` **fabricado a partir do número
do contrato** — provável origem: o antigo `vincular_empenhos_siafe` e seu dict
`EMPENHOS_CONHECIDOS` hardcoded.

| Contrato local | `numero_empenho` gravado |
|---|---|
| `56/2025 PGJ` | `2025NE00056` |
| `120/2025` | `2025NE00120` |
| `58/2025/PGJ` | `2025NE00058A` (sufixo inventado) |
| `2025NR00104` | `2025NR00104` (nota de RESERVA, não empenho) |
| `25017488` | `25017488` (codigo_siafe copiado) |

Por coincidência, NEs com esses números existem no SIAFE — mas pertencem a
outros credores (diárias, suprimento de fundos, folha de pagamento). Os valores
também não correspondiam a empenho nenhum: eram o valor do **contrato**.

Caso comprovado por documento: pk=26, NE `2026NE00010`, R$25.132,47, registrado
como SORELLE no contrato `10/2026/FPDC`. A NE `2026NE00010` real da UG 250102 é
de L H C HAIDAR SOUSA, R$7.672,50, contrato SIAFE `26100660` — credor, órgão,
objeto e valor diferentes.

O `limpar_empenhos_fabricados` exige **duas condições** para apagar: (1) não
conferir com nenhuma NE real do SIAFE (mesmo número E mesmo credor, em qualquer
UG) e (2) padrão de fabricação detectado. Registros que falham só na condição 1
vão para REVISAR e nunca são apagados automaticamente — na prática deu zero.
Salvaguardas: aborta se a consulta ao SIAFE falhar em qualquer UG, e recalcula
`valor_empenhado` dos contratos afetados a partir do que sobrou.

Efeito colateral positivo: duas divergências que apareciam como "NÃO ENCONTRADO
NO TCE" (ALTACON R$1.490.701,03 e LCS R$47.169,78) eram exatamente registros
fabricados. O TCE estava certo o tempo todo.

## Contratos que não existiam no banco

1. **13/2026/PGJ (Laís G de Sousa)** — achado via NE `2026NE00165` (R$22.501,00)
   com `codContrato=26100672` sem par local. Fonte: PDF SEI
   19.21.0428.0012055/2026-09.
2. **29/2024/PGJ (EASWELL Engenharia)** — achado via `codContrato=24010263` com
   2 NEs de 2026 (`2026NE00885` R$25.000 peças + `2026NE00886` R$100.000
   serviços) sem par local; a diferença no TCE era exatamente R$125.000,00.
   Fonte: 4 documentos do SEI 19.21.0010.0018316/2024-04.

   Esse contrato tem um histórico de valor incomum — precisou de **dois
   apostilamentos** para corrigir um erro material de soma:

   | Documento | Data | Valor | Observação |
   |---|---|---|---|
   | Contrato | 24/07/2024 | R$223.042,39 declarado | texto dizia "R$61.956,21 serviços + R$10.000 peças" — não fecha |
   | Apostilamento 01 | 17/02/2025 | R$259.042,39 | corrigiu o total, mas manteve peças em R$10.000 — ainda não fechava |
   | Apostilamento 02 | 10/06/2025 | R$259.042,39 | corrigiu peças para R$36.000 — só então fecha |
   | Termo Aditivo 01 | 11/12/2025 | **R$271.367,89** | prorroga 18 meses de 24/01/2026 e reajusta pelo IPCA |

   Cadastrado com `valor_inicial` = R$259.042,39 e `valor_atual` = R$271.367,89.
   `saldo_disponivel` ficou provisoriamente igual ao `valor_atual` — os
   documentos não trazem medições executadas.

## Vínculos SIAFE corrigidos

- `codigo_siafe` **preenchido** (valor e objeto idênticos aos da NE):
  pk=268 `43/2026/FMMPPI` → `26000337`; pk=264 `07/2026/FMMPPI` → `26100631`;
  pk=263 `05/2026/PGJ` → `26100643` — este **resolve a pendência antiga** da
  NTSEC ("numeração interna do MPPI não corresponde 1:1 à sequência SIASG").
- `codigo_siafe` **corrigido**: pk=176 `10/2026/FPDC` (SORELLE) apontava para
  `25017404`, código de 2025 num contrato de 2026; correto é `26100669`.

## Classificação orçamentária (59 contratos)

- 51 resolvidos por `inferir_fonte_contratos_via_tcepi` (cruzamento de CNPJ com
  credores do TCE — resolve só quando o CNPJ aparece em UM único órgão).
- 6 por `inferir_fonte_contratos` (sufixo do número).
- 2 manualmente (EPSG pk=230 e pk=238): a soma dos 3 contratos dela
  (R$545.495,59) bate exatamente com o total do TCE para a PGJ.

**Isso não é cosmético.** O `conciliar_tcepi` filtra por
`contrato__unidade_orcamentaria`; contrato sem classificação não entra em
nenhum órgão. Foi exatamente a causa das divergências de READY TECNOLOGIA
(R$4.500.000) e MULTIPAR (R$5.688,52): todas as NEs estavam importadas, mas
parte dos contratos não tinha órgão, então ficavam fora da soma. Em ambos os
casos o total líquido local já batia 100% com o TCE.

---

# Achados estruturais (importantes para trabalho futuro)

## 1. Número de NE NÃO é único — é sequencial POR UG

`2026NE00010` existe nas TRÊS UGs do MPPI, com credores e valores diferentes:

| UG | Credor | Valor | `codContrato` |
|---|---|---|---|
| 250101 | J P BARBOSA E SILVA | R$ 13.478,50 | `22000628` |
| 250102 | L H C HAIDAR SOUSA | R$ 7.672,50 | `26100660` |
| 250104 | EDIVAR CRUZ CARVALHO | R$ 1.007,50 | `00000000` |

Qualquer casamento por número de NE precisa levar a UG em conta. O
`auditar_empenhos_manuais` usa `ocorrencias[0]` quando nenhum CNPJ bate — a
conclusão do diagnóstico continua válida, mas a UG exibida pode não ser a
pretendida.

## 2. Valor de empenho ≠ valor de contrato

Um empenho pode cobrir a despesa **total** do contrato ou apenas a **prevista
para o exercício**. Ver `docs/nota_empenho_fonte_de_verdade.md` § 4.

## 3. A API do SIAFE não cobre 2024

`importar_empenhos_siafe --exercicio 2024` retorna **0 NEs** nas três UGs. A
cobertura parece começar em 2025. Conciliação histórica anterior a isso é
inviável por esse caminho (ex.: a NE `2024NE00671`, original do contrato
29/2024/PGJ, não é recuperável).

## 4. A base do TCE é atualizada continuamente

O valor do TCE para READY TECNOLOGIA mudou de R$4.777.258,75 para
R$5.777.258,75 entre 29 e 30/07. As despesas por elemento também subiram.
Divergências devem ser lidas na data em que foram apuradas.

## 5. O bloco `produtos[]` da NE não é importado

A API do SIAFE devolve, por NE, `nomeProdutoGenerico`,
`descricaoProdutoGenerico`, `unidadeFornecimentoGenerico`, `quantidade`,
`precoUnitario` e `precoTotal`. É exatamente o dado que falta para resolver os
casos de quantidade fracionária (`docs/fracao_quantidades_2026-07-29.md`) sem
depender de caçar PDF no SEI. **Próximo passo natural.**

---

# PENDENTE

## 1. Importar o bloco `produtos[]` das NEs (próximo passo acordado)

Envolve migration (novo modelo ou campo JSON). Ver § 5 acima e
`docs/nota_empenho_fonte_de_verdade.md`.

## 2. Contratos faltando cadastrar (18 casos restantes)

`sugerir_vinculo_ne_contrato --exercicio 2026`, grupo (2). Maiores:

| codContrato | Valor | Credor |
|---|---|---|
| `26000322` | R$463.980,00 | HPE AUTOMOTORES (2 caminhonetes Mitsubishi Triton) |
| `26100663` | R$47.299,62 | BIM PROJETOS (projetos de incêndio) |
| `26000324` | R$36.731,23 | INOVARE ENGENHARIA |
| `26000334` | R$33.760,00 | L F DE LIMA (segurança eletrônica) |
| `26100671` | R$31.014,15 | E PACHECO LOPES FILHO (higiene e limpeza) |

Vários têm contrato equivalente de 2025 no banco (Rainha do Gás, Porto Seguro,
Double Soluções) — provavelmente renovações. Cada um precisa do documento fonte
antes de usar `cadastrar_contrato_manual`. Note que esses **não** aparecem mais
como divergência no `conciliar_tcepi` (os credores conferem), mas as NEs deles
seguem sem vínculo local.

## 3. Casos ambíguos de vínculo

- **ALFA GESTÃO (2 casos)**: `26000315` (R$2.504.625,82, "auxiliar de serviços
  gerais, bombeiro") e `26000311` (R$926.168,89, "46 postos de agente de
  limpeza"). Candidatos: pk=262 `36/2026` e pk=265 `35/2026/PGJ`. Pelo objeto,
  `26000311`→pk=262 e `26000315`→pk=265, mas os valores não batem.
  **Nota:** o valor de `26000315` é **exatamente** o da anulação da Master
  Facilities no contrato `29/2026/PGJ` — indício forte de sucessão contratual
  (troca de prestador no mesmo objeto).
- **pk=102 `06/2026/FPDC`** tem `codigo_siafe='26100635'`, mas o SIAFE mostra o
  contrato do SISTEMA AVANÇADO (mesmo valor R$10.080,00) como `26100634` —
  diferença de um dígito.

## 4. Classificação orçamentária restante

11 contratos ambíguos (CNPJ em mais de um órgão) e 13 não encontrados no TCE
(quase todos pessoa física, locações de 2015–2018).

## 5. Outros

- `liquidado local = R$0,00` em todos os credores: a importação do SIAFE só traz
  empenho. Liquidação viria de `notas_liquidacao_por_ug`.
- Endpoint de licitações do TCE não retorna nada para os órgãos do MPPI —
  investigar se é parâmetro/esfera ou ausência de dado.
- ARP `23/2023` (origem do contrato 29/2024/PGJ) não existe no banco — some-se
  às ARPs faltantes já registradas como pendência.
- Cadastrar os 2 apostilamentos e o aditivo do contrato 29/2024/PGJ nos modelos
  `Apostilamento` e `Aditivo` (bom caso de teste: tem os dois tipos e três
  mudanças de valor).
