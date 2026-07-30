# Bloco `produtos[]` da NE, resolução de frações e conciliação TCE FMMP/2025 — 2026-07-30

Continuação de `docs/conciliacao_tcepi_2026-07-29.md` (item 5 do "PENDENTE": importar
`produtos[]`) e de `docs/fracao_quantidades_2026-07-29.md`.

## 1. Novo modelo `EmpenhoProduto`

`apps/contratos/models_empenho.py` — um-para-muitos com `Empenho`
(`related_name="produtos"`). Campos: `ordem`, `nome_produto`,
`descricao_produto`, `unidade_fornecimento`, `quantidade`, `preco_unitario`,
`preco_total`. Migração `contratos/0011_empenhoproduto.py` (conferida por
`makemigrations --check --dry-run`).

`importar_empenhos_siafe` agora persiste o bloco `produtos[]` de cada NE
(delete + recria a cada reimportação — não acumula histórico próprio, sempre
reflete o último payload do SIAFE).

`investigar_fracao_pendente` passou a mostrar os `produtos[]` das NEs do
contrato encontrado, para cruzar com os itens da ARP.

## 2. Frações de quantidade resolvidas via `produtos[]`

6 entradas novas em `OFFICIAL_CONTRACT_ITEMS` (`conciliar_dashboard_srp.py`),
todas com evidência de preço unitário exato ou soma de valor exata:

| ARP | Contrato | Item(ns) |
|---|---|---|
| 00043/2025 | 25018822 | 4: SSD SATA III 480GB (200 un) |
| 00049/2025 | 03/2022/PGJ | 2: assinatura proteção dispositivos (1.600 un) |
| 00024/2025 | 2025NE00106 | 15: poltrona operacional fixa (10 un) |
| 00019/2025 | 23/2026/FPDC | 4: ar-condicionado 30.000 BTU (4 un) |
| 00029/2025 | 2025NE00058 | 8/9/10/11 — soma exata R$171.000,00 |
| 00029/2025 | 27/2026-FMMPPI | 8: 100 un — soma exata R$19.000,00 |

Aplicadas e verificadas pelo usuário (`--dry-run` + real, sem saldo negativo).

## 3. Vínculos ARP↔contrato corrigidos

- **ARP 00016/2025 (toner/video wall)**: contrato 159 (REPREMIG,
  2025NE00141) era uma **carona externa** para a Ata 039/PMSC/2024 (Polícia
  Militar de Santa Catarina), não uma contratação própria do MPPI.
  `corrigir_arp_origem_carona` desvinculou `arp_origem`;
  `cadastrar_arp_externa_manual` criou o `ARPExterna` e ligou
  `arp_externa_origem`. Confirmado por PDF SEI
  19.21.0427.0019479/2025-78.
- **`25018988` (storage NVMe duplicado)**: era o mesmo contrato real de
  `120/2025` (SEI 19.21.0016.0043009/2025-75), só que fatiado por elemento de
  despesa diferente no SIAFE (NE 2025NE00082, migração+treinamento,
  R$79.000,00). `mesclar_contrato_duplicado` moveu o `Empenho` e apagou o
  duplicado.
- **ARP 00018/2025 (multi-órgão)**: achado estrutural — os itens locais
  registram a quantidade **total da Ata** (multi-órgão: MPPI + ES + RO + MA +
  PA + AL + SE), não a quota própria do MPPI. **Não corrigido nesta sessão** —
  sem saldo negativo hoje, mas é um gap de dado conhecido. Ver também a
  pendência do contrato `32/2025/FMMP/PI` (item 14, só ~R$5,76M de R$8,45M
  evidenciados pelo `produtos[]`).

## 4. Conciliação TCE FMMP/2025 — de 4 DIVERGE a 0

`conciliar_tcepi --exercicio 2025 --orgao fmmp` tinha 4 divergências
(RADNOR, COINSTEL, MULTIPAR, ALTACON). Depois de investigar e cadastrar todos
os contratos faltando (13 no total nesta sessão, contando os de PGJ da sessão
anterior), fechou em **29 CONFERE / 0 DIVERGE**.

### RADNOR — 2 contratos distintos, não confundir

- pk=179 `25017188` (Buriti dos Lopes e Campo Maior) — já existia.
- **novo**: `12/2025/FMMP/PI` (SEI 19.21.0431.0028803/2025-82), Ata 11/2024,
  cerca elétrica capital+interior, R$107.387,68 (líquido R$82.655,13 após
  anulação parcial NE 2025NE00076).

### COINSTEL — nova, sem ARP

`17/2025/FMMP/PI` (SEI 19.21.0431.0018074/2025-26), Concorrência Eletrônica
90002/2024, implantação da sede de Barras-PI, R$1.198.997,67.

### MULTIPAR — 6 contratos, todos sob a Ata 12/2025 ou Ata 21/2023

| codContrato | Contrato | Valor | NE(s) | Fonte |
|---|---|---|---|---|
| `25015651` | `41/2025/FMMP/PI` | R$27.841,71 (líq. R$19.291,90) | 2025NE00027, anulação 2025NE00063 | PDF Termo de Contrato |
| `25016114` | `52/2025/FMMPPI` | R$25.988,25 (líq. R$12.709,22) | 2025NE00037, anulação 2025NE00062 | PDF Termo de Contrato |
| `24012761` | `70/2024/FMMPPI` | R$16.659,93 + apostilamento R$927,96 | 2024NE00057 + 2025NE00005 | PDF contrato + NF |
| `24008509` | `14/2024/FMMP/PI` | R$238.385,32 + Aditivo 01 R$12.481,48 | 2024NE00024 + 2025NE00032 | PDF contrato + aditivo |
| `24012839` | (sem Termo de Contrato — só AE) | R$6.303,84 | 2025NE00011 | payload bruto SIAFE (ver §5) |

Todos sob a **Ata de Registro de Preços própria nº 12/2025** (P.E.
90018/2024, manutenção predial, Lote I-Teresina) ou a **Ata nº 21/2023** (P.E.
25/2023, mesmo objeto genérico, Lote 1-Teresina) — a MULTIPAR tem múltiplos
Termos de Contrato/Autorizações de Empenho distintos rodando em paralelo sob
essas duas Atas.

Dois casos (`24012761`, `24008509`) têm NE original de **2024** — precisou
rodar `importar_empenhos_siafe` para os exercícios 2024 E 2025.

### ALTACON — nova, sem ARP

`1/2025/FMMP/PI` (SEI 19.21.0431.0011193/2024-61), Concorrência Eletrônica
90001/2024, reforma e ampliação da sede das Promotorias de Piripiri/PI,
R$432.000,00, NE 2025NE00001.

## 5. Bug corrigido: `investigar_ne_faltante` dava falso positivo de "já importada"

**Causa raiz**: número de NE **não é único entre UGs/credores diferentes**
(achado já documentado em `docs/conciliacao_tcepi_2026-07-29.md` §"Achados
estruturais" item 1, mas o `investigar_ne_faltante` não tinha sido corrigido
para isso). O check de "já importada localmente" comparava só
`numero_empenho` + `ano_exercicio`, sem o CNPJ do credor — então uma NE
`2025NE00011` de ANALYSIS BRASIL LTDA (UG 250104, contrato 08/2022/FPDC) fazia
o comando reportar como "já importada" a NE `2025NE00011` **da MULTIPAR** (UG
250102), que na verdade nunca tinha sido importada.

**Corrigido**: a checagem agora usa `(numero_empenho, cnpj_favorecido)` como
chave. Verificado nesta sessão: sem a correção, o codContrato `24012839`
(MULTIPAR, R$6.303,84) ficaria permanentemente escondido como "falso já
importado" e a divergência do TCE nunca fecharia via esse fluxo de
investigação.

**Melhoria adicional**: o comando agora imprime automaticamente, para toda NE
NAO IMPORTADA, os dados completos do payload SIAFE (observação/CPPT, processo
SEI, embasamento legal, `produtos[]`) — antes só mostrava número/valor/tipo.
Pedido explícito do usuário: sempre puxar todos os dados da NE quando houver
divergência, não só o resumo. Isso resolveu o caso `24012839` sem precisar de
PDF novo — a própria observação da NE já citava a AE (SEI 0964150) e a Ata de
Registro de Preços (21/2023).

**Ressalva sobre `24012839`**: cadastrado só com base no payload SIAFE
(`numOriginalContrato` veio `null` — indício de que não há Termo de Contrato
formal, só Autorização de Empenho direto contra a Ata). `data_assinatura`/
`data_inicio_vigencia`/`data_fim_vigencia` são CALCULADAS a partir da
`dataEmissao` da NE, não de um instrumento formal. Se aparecer um Termo de
Contrato depois, corrigir a entrada em `cadastrar_contrato_manual.py` (mesmo
padrão do que ocorreu com `25015651`, que também começou como "AE only" até o
usuário achar o `41/2025/FMMP/PI` real).

---

# PENDENTE

1. **ARP 00018/2025 multi-órgão** — itens locais usam quantidade total da Ata,
   não a quota do MPPI. Sem saldo negativo hoje; gap de dado conhecido, ainda
   sem decisão do usuário sobre como corrigir.
2. **Contrato `32/2025/FMMP/PI`** (item 14, PAM/usuários privilegiados) — só
   ~R$5,76M de R$8,45M evidenciados pelo `produtos[]`; item 14 continua no
   fallback de alocação proporcional (0,1975 contratada).
3. Frações menores sem evidência limpa em `produtos[]`: ARP 00022/2025
   (escada), 00046/2025 (símbolo), 00023/2025 (mesa redonda), 00011/2024
   (cercas elétricas), 00048/2025 (storage quase-inteiro).
4. Aplicar a mesma correção de `investigar_ne_faltante` (chave por CNPJ, não
   só número de NE) em qualquer outro comando que ainda compare NEs só pelo
   número — não auditado nesta sessão.
