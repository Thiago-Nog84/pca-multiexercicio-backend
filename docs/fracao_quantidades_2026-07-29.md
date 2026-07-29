# Fração de quantidades em ContratacaoDecorrente — registro de 2026-07-29

## Contexto

A auditoria (`auditar_consistencia_srp`, checagem `[fracao]`) encontrou 42 casos de
quantidade não-inteira em `ContratacaoDecorrente` de itens físicos (produtos
contáveis, sem unidade contínua como m²/kg/hora), espalhados por ~31 ARPs. Este
documento registra o trabalho de investigação e correção feito em 2026-07-29,
como continuação do plano de 4 baldes (encerrar ARPs vencidas, duplicatas de
contrato, datas placeholder, e este — quantidades fracionárias).

Comando usado para gerar a lista original de ARPs a processar, da menor pra
maior (mais barato de rodar primeiro): `contar_itens_arp`.

---

## 1. Bug de performance corrigido (causa real dos "travamentos")

Durante a execução em lote das 31 ARPs, três delas (00023/2025, 00046/2025,
00011/2024) travaram de verdade — precisaram de `Ctrl+C` (`KeyboardInterrupt`)
dentro da mesma função em todas: `_resolver_combinacao_unica` (arquivo
`apps/srp/services/dadosabertos_contratos.py`).

**Causa:** a função faz busca por *backtracking* para achar, entre os itens
candidatos de uma ARP, a combinação de quantidades inteiras que fecha com o
`valor_inicial` de um contrato. O `backtrack()` interno não tinha nenhum
limite — para contratos com vários itens de valor baixo e teto alto, a árvore
de busca cresce explosivamente e o comando fica rodando por tempo
indeterminado (não é um bug de rede, apesar de várias hipóteses de rede terem
sido investigadas antes nesta mesma sessão).

**Fix aplicado:** adicionado um orçamento de nós (`max_nos=200_000`,
parâmetro da função). Se o backtracking visitar mais nós que isso sem
terminar, aborta e retorna `None` — mesma semântica de "ambíguo/sem solução
única" que a função já tinha, cai automaticamente no fallback de
similaridade/valor já existente. Nunca mais trava indefinidamente; o pior
caso agora é limitado no tempo.

**Tentativa descartada:** cheguei a testar reordenar os candidatos por valor
unitário decrescente antes de recursar, na hipótese de que itens caros
podariam a árvore mais cedo. Testei com dados sintéticos (`random.seed`,
vários cenários) e o resultado foi o oposto do esperado — em vários casos essa
ordenação piorou o tempo de busca em vez de melhorar. Não existe uma ordem
universalmente melhor para esse tipo de busca combinatória; o orçamento de
nós é quem garante o teto de tempo, não a ordenação.

**Validação:** depois do fix, todas as 31 ARPs da lista de fração rodaram até
o fim sem nenhum travamento (incluindo as 3 que antes travavam).

---

## 2. Achado estrutural: itens compartilhados entre contratos quebram o fallback

O fallback `[fallback - similaridade/valor]` em `conciliar_dashboard_srp.py`
(por volta da linha 197) pega `val_restante = contrato.valor_inicial` (o
valor TOTAL do contrato) e distribui esse valor contra os itens da ARP,
ordenados por similaridade de texto entre o objeto do contrato e a descrição
de cada item, indo até o valor zerar.

Duas falhas de premissa foram identificadas, ambas comprovadas com documentos
reais (SEI/PNCP/Nota de Empenho):

### Problema 1 — contrato parcial vs. valor_inicial do contrato inteiro

Quando o `numero_contrato` do `Contrato` local é, na prática, uma NOTA DE
EMPENHO específica (ex.: `2025NE01038`) mas o campo `valor_inicial` foi
preenchido com o valor do CONTRATO INTEIRO (ex.: R$ 108.135,00 para 24 meses,
quando essa nota de empenho cobre só R$ 51.625,00 de uma 1ª aquisição de 12
meses), o fallback divide o valor errado (o do contrato inteiro) contra um
pedido que é só uma fatia dele. O "troco" que sobra vira uma fração fantasma
no último item elegível por similaridade.

**Caso comprovado:** ARP 00035/2025, contrato/pedido `2025NE01038` — ver
seção 4.

### Problema 2 — item com teto compartilhado entre 2+ contratos

Quando dois contratos da mesma ARP disputam o mesmo `ItemARP`, a quantidade
disponível (`quantidade_registrada - quantidade_contratada`) é um pool
compartilhado que vai sendo consumido conforme os contratos são processados
em sequência. Se o PRIMEIRO contrato processado já aloca errado — mesmo sem
gerar fração nele mesmo, podendo fechar em número inteiro e ainda assim estar
errado — o SEGUNDO contrato encontra esse item já sem saldo disponível e é
forçado a cair num item pior (errado), o que aí sim produz uma fração
visível nele.

Ou seja: um erro silencioso (sem fração, número inteiro, mas incorreto) num
contrato pode contaminar a fração de outro contrato inteiramente diferente
que compartilha os mesmos itens da ARP.

**Caso comprovado:** ARP 00029/2025, item 8 vs. item 9 — ver seção 5.

### Conclusão prática

Corrigir uma fração isoladamente, sem checar os outros contratos que
compartilham os mesmos itens da ARP, arrisca esconder ou até criar novos
erros. O ideal é ter, para cada caso, o documento de origem (SEI, nota de
empenho, memória de cálculo) não só do contrato com a fração, mas de todos
os contratos que disputam aquele(s) item(ns).

---

## 3. Correção aplicada — ARP 00035/2025 (toners MVS Cartuchos)

**Contrato/pedido:** `2025NE01038` (Contrato local pk=161).

**Fonte:** PDF SEI `19.21.0428.0031214/2025-20`, conferido em 4 pontos
independentes do mesmo processo — Autorização de Empenho (pg. 57), Nota de
Empenho do SIAFE (pg. 61), Ordem de Fornecimento (pg. 89) e Controle de Saldo
(pg. 97) — todos batendo exatamente em R$ 51.625,00 para a 1ª aquisição (12
meses).

**Antes (fallback):**

| Item | Registrado | Contratada (errado) |
|---|---|---|
| 1 (MLT-D203U, Lote 1) | 315 | 216,0000 |
| 2 (MLT-D205E, Lote 1) | 135 | 135,0000 |
| 3 (MLT-D205L, Lote 1) | 135 | 135,0000 |
| 4 (MLT-D203U, Lote 2/ME-EPP) | 35 | **0,7614 ⚠ fração** |
| 5 (Lote 2) | 15 | 15,0000 |
| 6 (Lote 2) | 15 | 15,0000 |

**Real, conforme os 4 documentos:** a nota de empenho `2025NE01038` cobriu
apenas Lote 1, itens 1 e 3 — nada do Lote 2 (itens 4, 5, 6), e zero do item 2.

**Correção aplicada** (`OFFICIAL_CONTRACT_ITEMS` em
`apps/srp/management/commands/conciliar_dashboard_srp.py`):

```python
("00035/2025", "2025NE01038"): {
    1: Decimal("150"),  # Toner MLT-D203U (SL-M4070FR), Lote 1
    3: Decimal("65"),   # Toner MLT-D205L (SCX-4833), Lote 1
    # Item 2 (MLT-D205E) e itens 4/5/6 (Lote 2) não foram comprados
    # nesta nota — 0.
},
```

**Verificado em dry-run** (2026-07-29): item 4 agora mostra
`Contratada=0.0000`, sem fração. Comando:

```
python manage.py conciliar_dashboard_srp --dry-run --arp 00035/2025
```

**Pendente:** rodar sem `--dry-run` para persistir.

---

## 4. Achado confirmado mas NÃO aplicado — ARP 00029/2025 (headsets)

**Contrato:** `27/2026-FMMPPI` (Contrato local pk=112, valor_inicial =
R$ 19.000,00).

**Itens candidatos na ARP** (via `listar_itens_arp_completo --arp 00029/2025`):

| Item | Descrição | Valor unit. | Registrado | Contratada hoje |
|---|---|---|---|---|
| 8 | FONE OUVIDO, TIPO FONE HEADSET BIAURICULAR... | R$ 190,00 | 400 | 400,0000 (saldo 0) |
| 9 | FONE OUVIDO, TIPO INTRA AURICULAR... | R$ 110,00 | 400 | 343,5455 |

**Fonte (PDF do Termo de Contrato, anexado por Thiago):** o contrato
27/2026-FMMPPI é, comprovadamente, a aquisição de **100 (cem) HEADSETS
(circumaural over-ear)** a R$ 190,00 = **R$ 19.000,00 exatos** — inclusive
confirmado na Nota de Empenho SIAFE (2026NE00025), no extrato do PNCP e no
recibo do Tribunal de Contas anexados ao mesmo PDF. Produto e preço batem
exatamente com o **item 8** da ARP, não com o item 9.

**Por que não foi corrigido ainda:** o sistema hoje mostra o item 8 com
`Contratada=400,0000` (saldo zero), inteiramente atribuído ao OUTRO contrato
dessa ARP, `2025NE00058` (valor R$ 171.000,00, objeto genérico "AQUISIÇÃO DE
EQUIPAMENTOS DE TIC (HEADSETS, FONES DE OUVIDO, DISPOSITIVOS DE ÁUDIO VIVA
VOZ E WEBCAMS)"). Se eu simplesmente realocar o `27/2026-FMMPPI` para o item
8 (100 unidades), o total do item 8 passaria a 500 (400 + 100), estourando o
teto registrado de 400 na ARP — a menos que a alocação de `2025NE00058`
também esteja errada e parte do que ele "consumiu" do item 8 na verdade
pertença a outro item (ex.: parte dos 400 alocados a ele hoje deveriam ir
para o item 9, sobrando espaço no item 8 para o 27/2026-FMMPPI).

**Necessário para fechar este caso:** documento de origem (SEI, memória de
cálculo ou nota de empenho) do contrato `2025NE00058` — mesmo padrão de
verificação usado nos outros dois casos documentados aqui.

---

## 5. Casos restantes sem investigação de documento (11 ARPs)

Decisão do Thiago em 2026-07-29: aplicar só os 2 casos já comprovados acima;
os demais ficam documentados como estimativa não confirmada, sem mais
escavação de PDF por enquanto. Todos vieram do
`[fallback - similaridade/valor]`, todos com `unidade_fornecimento` vazio no
`ItemARP` (produtos discretos/contáveis — nenhum é fração "legítima" óbvia
por natureza do item, ao contrário de itens medidos em m²/kg/hora):

| ARP | Item | Contrato | Fração | Registrado | Descrição |
|---|---|---|---|---|---|
| 00022/2025 | 109 | 53/2025/PGJ | 0,2732 | 5 | ESCADA EXTENSÍVEL DE ALUMÍNIO |
| 00046/2025 | 07 | 25018992 | 0,2950 | 36 | SÍMBOLO IDENTIFICADOR PRÉDIO |
| 00023/2025 | 06 | 22/2026/FPDC | 0,1208 | 16 | MESA REUNIÃO REDONDA |
| 00018/2025 | 14 | 25018988 | 0,1156 | 195 | Subscrição certificados digitais |
| 00018/2025 | 14 | 32/2025/FMMP/PI | 0,1975 | 195 | (mesmo item, 2º contrato) |
| 00011/2024 | 35 | 2025NE00045;2025NE00046 | 0,4299 | 10 | SERVIÇO DE CERCAS ELÉTRICAS |
| 00043/2025 | 04 | 25018822 | 0,1400 | 400 | DISCO SSD 480GB |
| 00048/2025 | 01 | 120/2025 | 0,9664 | 2 | SERVIDOR ARQUIVO (R$ 1.400.000,00/un) |
| 00049/2025 | 02 | 03/2022/PGJ | 0,4982 | 1600 | Subscrição indexação |
| 00024/2025 | 15 | 2025NE00106 | 27,4699 | 70 | CADEIRA FIXA |
| 00019/2025 | 04 | 23/2026/FPDC | 0,2160 | 22 | AR CONDICIONADO |
| 00016/2025 | 09 | 2025NE00141 | 0,1705 | 18 | TONER HP MAGENTA |

Além destes, **ARP 00033/2025** e **ARP 00034/2025** já haviam sido
confirmadas como fallback genuíno em sessão anterior (2026-07-28), itens
específicos não retomados neste documento.

### Como retomar qualquer um destes casos

```
python manage.py investigar_fracao_pendente --saida arquivo.txt
```
Mostra descrição, unidade, valor e contrato de cada caso da lista acima
(lista `CASOS` hardcoded no topo do arquivo — atualizar se a lista mudar).

```
python manage.py listar_itens_arp_completo --arp <numero> --saida arquivo.txt
```
Lista todos os itens de uma ARP com descrição completa — útil para achar um
item candidato alternativo quando há suspeita de vínculo errado, como no
caso do item 8/9 da ARP 00029/2025 (seção 4).

---

## 6. Comandos novos criados nesta sessão

Todos somente leitura, exceto a correção em `OFFICIAL_CONTRACT_ITEMS`:

- `apps/srp/management/commands/investigar_fracao_pendente.py`
- `apps/srp/management/commands/listar_itens_arp_completo.py`

Ambos aceitam `--saida <arquivo>` (grava em UTF-8, evita o mojibake do `>`
do PowerShell).
