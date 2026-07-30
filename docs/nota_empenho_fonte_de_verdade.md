# Nota de Empenho (API SIAFE) — a fonte mais confiável de validação

Registro consolidado em 2026-07-30, a partir da conciliação com o TCE-PI e da
verificação campo a campo do payload da API contra o PDF oficial da NE.

## 1. Regra geral

**Em qualquer divergência entre banco local, planilha de controle, PNCP e SIAFE,
a Nota de Empenho da API do SIAFE é a referência**, salvo prova documental em
contrário (Termo de Contrato, memória de cálculo, processo SEI).

Justificativa empírica desta sessão:

- 41 de 65 registros de `Empenho` cadastrados manualmente tinham número
  **fabricado** a partir do número do contrato, com valores que não
  correspondiam a empenho nenhum (ver `conciliacao_tcepi_2026-07-29.md`).
- Contratos locais foram encontrados com `codigo_siafe` apontando para o
  contrato errado (ex: `10/2026/FPDC` com código de 2025).
- Divergências que pareciam "credor ausente no TCE" eram, na verdade, empenhos
  locais que nunca existiram — o TCE estava certo.

Em nenhum caso desta sessão a NE da API do SIAFE se mostrou incorreta.

## 2. A API traz a NE praticamente completa

Verificado campo a campo contra o PDF oficial da NE `2026NE00010` (UG 250102,
credor L H C HAIDAR SOUSA) — **bate integralmente**.

Campos disponíveis em `SiafeClient.nota_empenho_por_ug()`:

| Campo | Conteúdo |
|---|---|
| `codigo` | Número da NE (ex: `2026NE00010`) |
| `codigoUG` / `nomeUG` | Unidade gestora |
| `dataEmissao` / `dataContabilizacao` | Datas |
| `cnpjCredor` / `cpfCredor` / `nomeCredor` | Credor |
| `valor` | Valor empenhado |
| `codNR` | Nota de reserva (ex: `2026NR00010`) |
| `codContrato` | Código SIAFE do contrato (`00000000` = sem contrato) |
| `codFonte`, `codNatureza`, `codAcao` | Classificação orçamentária |
| `codProcesso` | Processo SEI |
| `modalidade` | GLOBAL / ESTIMATIVO / ORDINARIO |
| `tipoAlteracaoNE` | NENHUMA / REFORCO / **ANULACAO** |
| `codigoModalidadeLicitacao` / `descModalidadeLicitacao` | Ex: `06` / "Dispensa de Licitação" |
| `embasamentoLegal` | Ex: "Dispensa Eletrônica nº 35/2025, art. 75, I, Lei 14.133/2021" |
| `observacao` | Texto descritivo completo do empenho |
| `statusDocumento` | Ex: CONTABILIZADO |
| `ordenadoresDespesa` | Nome, CPF e cargo do ordenador |
| `dataCancelamento` / `justificativaCancelamento` | Cancelamento |
| `classificadores` | 19 classificadores orçamentários |
| `itens` | Tipo patrimonial e sub-item da despesa |
| **`produtos`** | **produto, quantidade, unidade, preço unitário, preço total** |

**Não vem da API** (existe só no PDF): Origem, Local de Entrega (UF/Município),
quadro de Saldo da Dotação, e rodapé de quem emitiu/imprimiu. Nada essencial.

**Valores codificados vêm sem descrição:** Tipo Patrimonial `43` (no PDF:
"Serviços de Terceiros - Pessoa Jurídica"), Sub-item `2736.51` (no PDF:
"51 - SERVIÇOS TECNICOS PROFISSIONAIS"). Exibir o texto exigiria tabela de-para.

### Oportunidade: o bloco `produtos` não é importado

`produtos[]` traz `nomeProdutoGenerico`, `descricaoProdutoGenerico`,
`unidadeFornecimentoGenerico`, `quantidade`, `precoUnitario` e `precoTotal`.

É exatamente o dado que faltou na investigação de quantidades fracionárias
(`fracao_quantidades_2026-07-29.md`) — poderia resolver vários daqueles casos
sem depender de caçar PDF no SEI. Hoje o `importar_empenhos_siafe` ignora esse
bloco por completo.

## 3. ARMADILHA: número de NE não é único — é sequencial POR UG

Confirmado em 2026-07-30: `2026NE00010` existe nas três UGs do MPPI, com
credores, valores e contratos completamente diferentes:

| UG | Credor | Valor | `codContrato` |
|---|---|---|---|
| 250101 | J P BARBOSA E SILVA | R$ 13.478,50 | `22000628` |
| 250102 | L H C HAIDAR SOUSA | R$ 7.672,50 | `26100660` |
| 250104 | EDIVAR CRUZ CARVALHO | R$ 1.007,50 | `00000000` (diária) |

**Qualquer casamento por número de NE precisa levar a UG em conta.**

Impacto no código atual:
- `Empenho.Meta.unique_together = ("contrato", "numero_empenho")` — não
  considera UG (funciona na prática porque o contrato já é de uma UG, mas o
  número sozinho não identifica).
- `auditar_empenhos_manuais` pega `ocorrencias[0]` quando nenhum CNPJ bate — a
  conclusão do diagnóstico continua válida, mas a UG mostrada no relatório pode
  não ser a da NE pretendida.
- `dump_ne_siafe` já varre as três UGs e avisa quando há mais de uma ocorrência.

## 4. Valor do empenho ≠ valor do contrato — e isso NÃO é erro

**Um empenho pode se referir à despesa total do contrato OU apenas à despesa
prevista para o exercício.** Contratos de execução continuada são o caso típico.

Exemplo (valores fictícios): contrato continuado com vigência de 24 meses no
valor de R$ 240.000,00, com empenho inicial de R$ 60.000,00 para cobrir os 6
meses de contrato que caem dentro do exercício inicial. O restante será
empenhado nos exercícios seguintes.

Casos reais observados no MPPI:

| Contrato | Valor do contrato | Empenho | Cobertura |
|---|---|---|---|
| 92/2025/PGJ (MVS Cartuchos) | R$ 108.135,00 (24 meses) | `2025NE01038` R$ 51.625,00 | 1ª aquisição, 12 meses |
| 13/2026/PGJ (Laís G de Sousa) | R$ 34.966,00 (24 meses) | `2026NE00165` R$ 22.501,00 | exercício de 2026 |

### Consequências práticas

1. **Nunca tratar `valor_empenhado < valor_inicial` como erro por si só.**
2. O fallback de similaridade/valor do `conciliar_dashboard_srp` erra quando
   divide o valor TOTAL do contrato contra um pedido que corresponde só à fatia
   do exercício — é a causa raiz de quantidades fracionárias fantasma.
3. Ao conciliar com o TCE, comparar **empenho contra empenho**: o TCE soma o
   empenhado do exercício, não o valor do contrato.
4. Em NE de anulação (`tipoAlteracaoNE = ANULACAO`), o valor **subtrai**. Somar
   como positivo dobra a divergência em vez de zerá-la (bug real corrigido no
   `conciliar_tcepi` em 2026-07-29).

## Comando de apoio

```
python manage.py dump_ne_siafe --numero 2026NE00010 --exercicio 2026 --so-chaves
python manage.py dump_ne_siafe --numero 2026NE00010 --exercicio 2026 --saida ne.json
```

Despeja o JSON bruto da NE em todas as UGs do MPPI, sem nenhum mapeamento —
útil para conferir uma nota específica ou descobrir campos ainda não importados.
