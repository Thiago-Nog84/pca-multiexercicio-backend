# Melhorias visuais no sistema PCA à luz de *Storytelling com Dados*

Análise dos princípios de Cole Nussbaumer Knaflic (*Storytelling com Dados*, Alta Books, 2019)
aplicada às telas gerenciais do PCA Multiexercício (dashboards SRP, contratações decorrentes,
empenhos e contratos). Cada recomendação cita o capítulo de origem e aponta o arquivo a corrigir.

---

## Diagnóstico rápido

Hoje o sistema tem **5 gráficos de rosca**, paletas "arco-íris" com até 12 cores por gráfico,
linhas de grade padrão do Chart.js e títulos meramente descritivos ("Por status"). O livro
condena diretamente vários desses pontos. Abaixo, o que mudar — em ordem de impacto.

---

## P1 — Substituir os gráficos de rosca por barras horizontais

**O que o livro diz (Cap. 2 — "A escolha de um visual eficaz"):** a autora lista pizza **e rosca**
entre os recursos a evitar. Sobre a rosca: *"estamos pedindo para comparar o comprimento de um
arco com o comprimento de outro… Quão confiante você se sente na capacidade de seus olhos de
atribuir valores nesse espaço?"*. O olho humano compara comprimentos (barras) muito melhor do que
ângulos ou arcos.

**Onde violamos:**
- `srp/dashboard.html` — rosca "Por status"
- `srp/contratacoes_decorrentes.html` — roscas "Por status" e "Por unidade gestora/fonte"
- `contratos/empenhos.html` — rosca "Por fonte de recurso"
- `contratos/dashboard.html` — 1 rosca

**Correção:** trocar `type: 'doughnut'` por barras horizontais (`type: 'bar'`, `indexAxis: 'y'`),
ordenadas por valor. Mantém o clique/drill-down. Para o caso "parte do todo" (ex.: fonte
orçamentária), uma barra horizontal única empilhada 100% comunica a proporção sem pedir
comparação de arcos.

---

## P2 — Cor com moderação e propósito (não decorativa)

**O que o livro diz (Cap. 4 — "Focalize a atenção" / Cap. 5):** cor é um **atributo pré-atentivo**
(como tamanho e posição) e deve dirigir a atenção. *"São os dados que devem ser salientados, não
as bordas… empurrá-las para o fundo, tornando-as cinza."* Usar muitas cores dilui o foco — o
recomendado é cinza para o conjunto e **uma cor de destaque** para o que importa.

**Onde violamos:** arrays `CORES` com 12 cores aplicadas barra a barra (empenhos, contratações,
dashboards). Cada barra ganha uma cor diferente sem significado — a cor não codifica nada.

**Correção:** uma cor única (institucional — vermelho `#A61B2B` ou azul `#1a56db`) para todas as
barras de um gráfico; reservar uma cor de destaque só para a barra/fatia que se quer enfatizar
(ex.: a fonte com maior consumo, o contrato vencendo). Multicolor só quando a cor **for** o dado
(ex.: verde/amarelo/vermelho = faixa de vigência).

---

## P3 — Reduzir saturação (declutter)

**O que o livro diz (Cap. 3 — "A saturação é sua inimiga!"):** *"cada elemento adicionado absorve
carga cognitiva"*. Remover tudo que não carrega informação: linhas de grade fortes, bordas,
rótulos redundantes, casas decimais desnecessárias.

**Onde violamos:** os gráficos usam a grade padrão do Chart.js (linhas horizontais/verticais
cheias) e caixas de legenda mesmo quando há poucas categorias.

**Correção:**
- Remover/clarear as linhas de grade (`grid: { display: false }` ou cor bem clara).
- Nas barras horizontais, dispensar o eixo X inteiro e **rotular o valor na ponta da barra**
  (rótulo direto > eixo + grade).
- Substituir legendas por rótulos diretos quando possível (Cap. 4 recomenda o "rótulo direto").
- Formatar valores de forma enxuta ("R$ 1,6 mi" em vez de "R$ 1.605.460,00" nos eixos — já
  fazemos parcialmente com "Xk").

---

## P4 — Títulos que contam a história, não só rotulam

**O que o livro diz (Cap. 7 — "Lições sobre storytelling"):** o título deve carregar a
**conclusão**, não apenas nomear o eixo. "Por status" é rótulo; "R$ 47 mi empenhados, 88%
concentrados na PGJ" é história.

**Onde violamos:** todos os títulos de gráfico são descritivos ("Por fonte", "Top ARPs por valor").

**Correção:** gerar um subtítulo dinâmico com o dado-chave do recorte atual (ex.:
"PGJ concentra 74% do valor empenhado"), calculado na view. Barato e de alto impacto para leitura
executiva.

---

## P5 — Ordenação intencional das categorias

**O que o livro diz (Cap. 2):** *"reflita sobre como as categorias são ordenadas. Se houver uma
ordem natural, aproveite-a"* (ex.: exercícios em ordem cronológica); senão, ordenar por valor.

**Situação:** em boa parte já ordenamos por valor decrescente (bom) e exercício por ano (bom).
Conferir que **toda** barra categórica siga essa regra — evitar ordem alfabética de sigla quando
o valor seria mais informativo.

---

## P6 — Linha de base zero e eixos honestos

**O que o livro diz (Cap. 2):** *"gráficos de barras sempre com linha de base zero; caso
contrário, comparação visual falsa"* (exemplo da Fox News).

**Situação:** o Chart.js já inicia o eixo em zero por padrão — **manter** e nunca definir `min`
diferente de zero em gráfico de barras. Registrado como regra a preservar.

---

## P7 — Tabelas: bordas ao fundo, dados à frente

**O que o livro diz (Cap. 3):** em tabelas, *"empurrar as bordas para o fundo, tornando-as
cinza… são os dados que devem ser salientados"*. Cita Stephen Few (*Show Me the Numbers*).

**Correção:** nas tabelas de empenhos/contratações, clarear as bordas internas, remover zebra
pesada, manter o realce só no hover e no número (alinhado à direita, com peso maior).

---

## Ordem de execução sugerida

1. **P1 + P2 juntos** (maior impacto, mesma rodada): trocar as 5 roscas por barras horizontais de
   cor única, ordenadas por valor. Resolve o problema mais grave que o livro aponta e já limpa a
   cor.
2. **P3**: passar por todos os gráficos removendo grade e usando rótulo direto de valor.
3. **P4**: subtítulos dinâmicos com a conclusão do recorte.
4. **P5–P7**: ajustes finos de ordenação, eixo zero e bordas de tabela.

Nenhuma dessas mudanças altera dados ou lógica — são só de camada de apresentação (templates +
config do Chart.js), portanto de baixo risco.
