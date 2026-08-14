# PCA Multiexercício — Melhorias de front-end para apresentação em congresso

Pesquisa e recomendações para elevar o acabamento visual do sistema antes da apresentação em
congresso, e para o sistema passar a atender melhor três perfis de usuário: **servidor**,
**coordenador** e **gestor**. Continua o trabalho já feito nas 4 rodadas de
`docs/melhorias_visuais_storytelling.md` (roscas → barras, declutter, subtítulo dinâmico,
ordenação, tabelas) — este documento não repete o que já foi resolvido, foca no que falta.

---

## Implementação — 2026-08-03 (todo o roadmap abaixo, P0 a P7)

**P0 (achado durante a implementação, não estava no roadmap original) — bug crítico de
formatação monetária corrigido.** `floatformat:"2g"`/`"0g"` nunca foram argumentos válidos do
Django (só aceita inteiro) — o filtro falhava silenciosamente e devolvia o Decimal cru sem
formatação (ex. "1234567.891" em vez de "R$ 1.234.567,89") em **~85 pontos** do sistema, e
`floatformat:N|intcomma` (mais 16 pontos) produzia número ERRADO por dupla-formatação (ex.
"1,234,567,89"). Corrigido em **18 templates** com dois filtros novos em
`apps/core/templatetags/core_extras.py`: `brl` (dinheiro, padrão BR) e `qtd_br` (quantidade, sem
zeros à direita — preserva frações reais de rateio de item, ver
`[[project-pca-fracao-quantidades-pendente]]`). Verificado: `manage.py check` limpo, os 22
templates tocados compilam sem erro, filtros testados via `Template().render()` real do Django.

- **P1 (fonte Inter) e P2 (modo apresentação)** — feitos em `templates/base.html`: fonte Inter via
  Google Fonts; botão de tela cheia no topbar que esconde sidebar/topbar/footer e amplia KPIs via
  `body.presentation-mode` (CSS com `clamp()`, sai também com Esc).
- **P4 (números animados)** — helper `data-countup` genérico em `base.html` (progressive
  enhancement: o valor formatado pelo Django fica como fallback se o JS não rodar); aplicado nos
  KPIs dos 4 dashboards principais (PCA, Contratos, SRP, Licitação) e no novo Dashboard Executivo.
- **P3 (sparkline/tendência)** — não havia série mensal limpa reaproveitável nos 4 dashboards
  existentes (os gráficos "por ano" ali são recalculados client-side a partir da tabela filtrada,
  não servem de fonte para um mini-gráfico). Em vez de forçar um retrofit frágil, o gráfico de
  tendência real (empenhado por mês, a partir de `contratos.Empenho.data_emissao`) foi implementado
  dentro do P7 — é lá que ele faz sentido como conteúdo, não como card avulso.
- **P5 (contraste)** — script próprio de contraste WCAG (fórmula oficial, sem libs) rodado sobre
  todos os pares cor-de-fundo/cor-de-texto do sistema (badges, alert-pill, topbar, KPIs). Achado:
  `.kpi-sub` e `footer` usavam `#94a3b8` sobre branco (**2,56:1 — reprovado**, mínimo é 4,5:1).
  Trocado por `#6b7688` (4,59:1, aprovado) em `base.html` + 2 templates que repetiam a mesma cor
  em texto (`pca/relatorios.html`, `pca/suspensas.html`). Badges, alert-pill, topbar e botões já
  estavam todos acima de 6:1 — nada mudou neles.
- **P6 (seletor de visão)** — dropdown "Ver como…" no topbar (Operacional → `pca:demandas`,
  Coordenação → `srp:dashboard`, Gestão → `pca:dashboard_executivo`), preferência lembrada em
  `localStorage`. É atalho de navegação, não controle de acesso — RBAC real (P8) continua fora do
  escopo desta rodada.
- **P7 (Dashboard Executivo)** — nova tela `pca:dashboard_executivo`
  (`apps/pca/templates/pca/dashboard_executivo.html` + `DashboardExecutivoView` em
  `apps/pca/views_template.py`): 6 KPIs grandes (valor do PCA, % executado, % concluído, contratos
  vencendo em 90 dias, riscos em atraso, valor retido), 1 gráfico de tendência (empenhado por mês,
  linha única, sem grade — mesmo padrão dos outros 4 dashboards) e os 5 riscos mais críticos sem
  paginação. Nenhum modelo novo — reaproveita `ItemPCA`, `Contrato` e `Empenho` já existentes.

**P8 (RBAC real por grupo Django) continua não implementado**, como já indicado no roadmap
original — é trabalho de backend/permissões, fora do escopo desta rodada de front-end.

## Extensão do P4 (count-up) para telas secundárias — 2026-08-03

A pedido do Thiago, os números animados deixaram de valer só nos 4 dashboards principais e no
executivo. Passaram a ter `data-countup` os KPIs de topo de: `pca/demandas.html`,
`pca/riscos.html`, `pca/prazos.html`, `pca/orcamento.html`, `pca/suspensas.html`,
`pca/validacao.html`, `contratos/empenhos.html`, `srp/unidade_dashboard.html`,
`srp/contratacoes_decorrentes.html`, `srp/arp_detalhe.html` e `planejamento/dashboard.html` — só
os cards-resumo do topo de cada tela, não números repetidos dentro de tabelas/loops (ex. valor por
ARP em `unidade_dashboard.html`), para não animar dezenas de números ao mesmo tempo. Total no
sistema: 64 elementos com `data-countup` em 17 templates. Aproveitei para também trocar
`floatformat:0`/`floatformat:2` "soltos" (sem bug, mas sem separador de milhar) por `brl`/`qtd_br`
em `pca/suspensas.html` (money) e `srp/arp_detalhe.html` (quantidade total da ARP — usa `qtd_br`
para não arredondar frações reais).

**Achado colateral: 2 arquivos com bytes nulos no final do arquivo em disco**
(`srp/arp_detalhe.html` — introduzido durante a correção do P0 nesta mesma sessão; e
`srp/base_srp.html` — já existia desde 25/06/2026, antes desta sessão, confirmado pela data de
modificação do arquivo). Sintoma: o arquivo "parece" maior no disco do que o conteúdo real, com
`\x00` preenchendo a sobra — é o mesmo mecanismo do problema de truncamento em escrita já registrado
na memória do projeto (mount Windows/Linux). Corrigido removendo os bytes nulos finais dos dois
arquivos; conteúdo verificado íntegro (nenhuma perda de texto, `{% block %}` fechando corretamente
antes do padding). Rodada uma varredura no repositório inteiro (`.html`/`.py`) — não há mais
nenhum arquivo com byte nulo. Vale ficar atento a esse sintoma (arquivo "pesado" mas com conteúdo
visualmente cortado) em futuras edições grandes feitas por script em vez de pela ferramenta de
edição.

## P7 revertido — Dashboard Executivo removido (2026-08-03)

A tela `/pca/executivo/` estava lenta/travando ao vivo (provável causa: agregação de
`Empenho` por mês sem filtro além do ano, somada às demais queries da view, tudo em uma
única requisição sem cache). A pedido do Thiago, a página foi **excluída** — não só
desativada: `DashboardExecutivoView` removida de `apps/pca/views_template.py`, rota
`pca:dashboard_executivo` removida de `apps/pca/urls.py`, template
`dashboard_executivo.html` apagado, link "Visão Executiva" removido da sidebar. O item
"Gestão" do seletor de visão (P6, topbar) passou a apontar para `pca:dashboard` (Visão
Geral) em vez da página removida — a decisão do Thiago foi que a própria Visão Geral deve
servir a necessidade da Alta Gestão, em vez de uma tela separada. Ver seção seguinte.

## Visão Geral (`pca/dashboard.html`) — cards do topo reformulados (2026-08-03)

Os 4 cards principais tinham formatação inconsistente entre si (2 mostravam centavos, 2
não) e misturavam demandas/valor de TODOS os status com métricas que fazem mais sentido
filtradas. Reformulados a pedido do Thiago para refletir a visão macro da Alta Gestão:

- **Total de Demandas (Ativas)** — antes contava todos os itens do PCA (incluindo
  concluídos/suspensos); agora usa a mesma queryset `ativos` que a view já calculava para
  atrasados/vencendo (`exclude(status__in=["concluido","suspenso"])`). Novo contexto
  `total_ativas` em `DashboardPCAView`.
- **Valor PCA Ativo** — mesma lógica, soma de `valor_total_estimado` só das demandas
  ativas (`valor_pca_ativo`, novo). Antes ("Valor PCA Estimado") somava TODAS as demandas.
- **Valor Executado** — era "Valor Empenhado"; mesmo dado (`valor_empenhado`, todas as
  demandas — execução é histórico, não faz sentido restringir a ativas), só renomeado.
- **Demandas Concluídas** — mesmo dado (`concluidos`), rótulo completo.

Os dois cards de dinheiro passaram de `|brl` (2 casas) para `|brl:0` (sem centavos) —
agora os 4 cards usam o mesmo tamanho de fonte (`.kpi-value` padrão, 1.6rem/800), porque os
valores em R$ ficaram curtos o bastante para não precisar do `font-size:1rem` reduzido que
tinham antes. `total_itens`/`valor_total` (todas as demandas, sem filtro) continuam
existindo na view e no template — usados em outras seções da página (breakdown por status,
resumo financeiro mais abaixo) que não foram tocadas.

---

## Diagnóstico do estado atual

- **Identidade visual:** vermelho institucional MPPI (`#9B2335`) aplicado via CSS vars em
  `templates/base.html` — sidebar, topbar, botões, links. Consistente em todo o sistema.
- **Layout:** sidebar fixa + topbar, `Bootstrap 5.3.3` + `Bootstrap Icons`, KPI cards com sombra e
  hover, tabelas já com bordas clareadas (P7 do relatório anterior). Base sólida, sem gambiarra.
- **Gráficos:** `Chart.js 4.4.2` + `chartjs-plugin-datalabels`, já sem roscas, sem grade, com
  rótulo direto e subtítulo dinâmico nos 4 dashboards principais.
- **Tipografia:** nenhuma fonte web carregada — usa o stack padrão do Bootstrap
  (`-apple-system, Segoe UI...`). Funcional, mas genérica; não passa a mesma sensação de "produto
  acabado" que uma fonte intencional dá.
- **Navegação:** sidebar única, plana, com todos os itens visíveis para qualquer usuário logado
  (`@login_required` genérico; `is_superuser` só em 2 views específicas de `pca`). **Não existe
  diferenciação de papel hoje** — servidor, coordenador e gestor veem exatamente a mesma tela.
- **Modo apresentação:** não existe. Sem tela cheia dedicada, sem tema para telão/projetor, sem
  visão consolidada "um slide, uma história" pensada para pitch de auditório.

Isso baliza as duas partes do documento: (A) acabamento visual para o pitch, (B) proposta de
como o sistema pode servir aos três perfis — hoje inexistente, então é desenho novo, não conserto.

---

## Parte A — Visual, cores e gráficos

### A1. Cor: manter o vermelho como marca, não como "cor de dado"

A pesquisa em dashboards institucionais é unânime: **poucas cores intencionais > paleta
arco-íris**, e paletas frias (azul/cinza) comunicam confiabilidade em contextos de governo — é
por isso que o próprio Design System do governo federal (`gov.br/ds`) usa azul (`#1351b4`) como
cor-base [gov.br DS](https://www.gov.br/ds/fundamentos-visuais/cores). O MPPI já tem uma
identidade própria (Resolução CPJ 08/2025, vermelho `#9B2335`) — não se troca isso — mas a
pesquisa sugere separar dois papéis que hoje estão um pouco misturados:

- **Vermelho institucional** → marca, navegação, botão de ação primária, elementos de "isto é
  MPPI". Já está correto em `base.html`.
- **Paleta neutra/azul-acinzentada** → gráficos e dados por padrão (já é o padrão desde a Rodada
  1-2, com `#2563eb` e cor única por gráfico). Não mudar.
- **Cor com significado, nunca decorativa** → já aplicado nos status (verde/cinza/laranja/
  vermelho). Manter essa regra ao criar qualquer gráfico novo.

**Ação prática:** nenhuma mudança de código aqui — é validar que a disciplina das rodadas
anteriores (cor única + cor semântica) continua sendo seguida em telas novas. Vale como checklist
de review antes do congresso.

### A2. Tipografia: trocar o stack padrão por uma fonte web intencional

Fontes de sistema são neutras, mas telas de dashboard "premiadas" hoje usam uma fonte web
específica — reforça a sensação de produto cuidado, especialmente projetado em telão
[UXPin — Dashboard Design Principles](https://www.uxpin.com/studio/blog/dashboard-design-principles/).
Recomendação: **Inter** (grátis, Google Fonts, feita para telas, ótima legibilidade em tamanhos
pequenos de KPI) ou **Public Sans**/**IBM Plex Sans** como alternativas no mesmo espírito
institucional-mas-moderno.

**Ação prática (baixo risco, alto impacto visual):**
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
```
em `templates/base.html`, e `body { font-family: 'Inter', -apple-system, ... }` como fallback.
Números de KPI ganham peso 800 (`font-weight:800`) em vez de 700 para destacar ainda mais o dado
central — recomendação recorrente em benchmarks de dashboard executivo.

### A3. Modo apresentação / telão

Nenhuma pesquisa de dashboard para auditório deixa de citar isto: **tela cheia em 1920×1080**,
sem cabeçalho/menu, com poucos KPIs grandes e um ou dois gráficos por "slide"
[boas práticas de dashboards em TV](https://wiki.setic.ro.gov.br/home/base_conhecimento/estudos_tecnicos/cagd/boas_praticas_dashboards).
Hoje o sistema não tem isso — todo dashboard sempre mostra sidebar + topbar + múltiplos cards.

**Proposta:** um botão "Modo apresentação" nos dashboards principais (`srp/dashboard.html`,
`contratos/dashboard.html`, `pca/dashboard.html`) que:
1. Esconde sidebar/topbar via classe CSS (`body.modo-apresentacao`), usando F11/Fullscreen API do
   navegador.
2. Aumenta a fonte dos KPIs e dos rótulos dos gráficos (`clamp()` CSS já resolve isso sem JS).
3. Opcional: paginação automática entre 3-4 "slides" de dashboard a cada N segundos — útil para
   deixar rodando num telão do estande, não necessariamente para o pitch ao vivo.

Isso é a peça com **maior impacto percebido pelo público do congresso** pelo menor custo de
implementação: é CSS + um botão, reaproveita 100% dos gráficos já decluttered.

### A4. Biblioteca de gráficos: manter Chart.js, não trocar

Comparando Chart.js, ApexCharts e ECharts: ECharts vale para datasets muito grandes (milhões de
pontos) e ApexCharts dá visual pronto com menos configuração, mas ambos exigiriam reescrever os
16 gráficos já decluttered nas rodadas anteriores
[comparativo de bibliotecas](https://npm-compare.com/apexcharts,chart.js,echarts,recharts). Os
dados do PCA são pequenos (dezenas/centenas de pontos) — **Chart.js já entrega tudo que os dados
exigem**, e o investimento das 4 rodadas anteriores (datalabels, subtítulo dinâmico, cor
semântica) só existe em Chart.js hoje. Trocar de biblioteca às vésperas do congresso é risco sem
retorno visual proporcional.

**O que vale adicionar, sem trocar de biblioteca:**
- **Sparklines** (mini-gráfico de linha, sem eixos) ao lado de 2-3 KPIs-chave — Chart.js faz isso
  nativamente com um canvas pequeno e `scales:{x:{display:false},y:{display:false}}`. Mostra
  tendência num piscar de olhos, item recorrente em dashboards executivos modernos.
- **Números animados** ("count-up") nos KPI cards ao carregar a página — pequena biblioteca JS
  (`CountUp.js`, ~3kb) ou `requestAnimationFrame` simples. Efeito comum em dashboards 2026 e
  barato de implementar; dá sensação de "dado vivo" no pitch.

### A5. Densidade e whitespace

A pesquisa reforça: dashboards são **olhados, não lidos** — o essencial precisa estar no canto
superior esquerdo, e espaço em branco reduz carga cognitiva
[UXPin](https://www.uxpin.com/studio/blog/dashboard-design-principles/). O padrão atual
(`padding: 1.75rem`, cards com `border-radius:12px` e sombra leve) já segue essa linha. Ponto de
atenção real: **conferir se os dashboards com mais KPIs (contratos, PCA) não passaram de 6-8
métricas na dobra inicial** — se passou, é candidato a mover para uma seção "ver mais" abaixo da
dobra, não para a primeira tela.

### A6. Contraste e acessibilidade

O vermelho institucional (`#9B2335`) tem contraste alto o suficiente contra branco para texto
grande/botões (a cor já é escura). Ponto a validar antes do congresso: **badges e alertas**
usam fundos claros (`#fff4f4`, `#eff6ff`) com texto escuro — combinação segura. Recomendação:
rodar um checker de contraste (ex. WebAIM) nos pares cor-de-fundo/cor-de-texto usados nos badges
de status uma única vez, documentar os pares aprovados, e não reinventar cor nova sem checar
[guia WCAG 2026](https://www.webability.io/blog/color-contrast-for-accessibility). Baixo
esforço, evita surpresa numa tela grande onde qualquer contraste fraco fica mais visível.

---

## Parte B — Atender servidores, coordenadores e gestores

Hoje o sistema **não diferencia papéis** — é uma lacuna real, não só estética, e é provavelmente
a pergunta mais forte que pode vir da plateia do congresso ("o sistema serve só a quem opera, ou
também a quem decide?"). A pesquisa em dashboards por persona é consistente: executivo, tático e
operacional consultam dado de formas diferentes, em cadências diferentes, e misturar os três numa
tela única sobrecarrega todo mundo
[Qlik — Dashboard Design](https://www.qlik.com/us/dashboard-examples/dashboard-design),
[Yellowfin — 3 personas de analytics](https://www.yellowfinbi.com/blog/three-personas-design-analytics-app).

### Os três perfis, informados pelo domínio do PCA

| Perfil | Pergunta que faz | Cadência | Nível de detalhe |
|---|---|---|---|
| **Servidor** (opera: cadastra DFD, acompanha ARP/contrato específico) | "O que eu preciso fazer hoje? Está tudo certo no que eu cadastrei?" | Diária, ativa | Alto — registro individual, formulário, pendência pontual |
| **Coordenador** (gerencia uma frente: SRP, Contratos, Licitação) | "Minha área está no prazo? Onde estão os gargalos da minha equipe?" | Semanal | Médio — agregado por unidade/fase, com drill-down para o caso específico |
| **Gestor** (decide sobre o PCA como um todo) | "O planejamento anual está sendo cumprido? Onde está o risco financeiro?" | Mensal/pontual (reunião, prestação de contas) | Baixo — 5-8 indicadores estratégicos, tendência, exceção |

Essa tabela reflete o padrão operacional → tático → estratégico encontrado na pesquisa de
hierarquia de KPIs [Domo — Executive Reporting](https://www.domo.com/learn/article/the-ultimate-guide-to-creating-executive-level-reporting-dashboards),
adaptado à realidade do MPPI: o "servidor" do PCA é quem cadastra DFD/acompanha uma ARP; o
"coordenador" é quem hoje já olha `srp/dashboard.html` ou `contratos/dashboard.html` inteiros; o
"gestor" é quem precisaria de uma síntese que **não existe hoje** — o mais próximo é
`pca:dashboard`, mas ele mistura granularidade de demanda com indicadores agregados.

### O que muda para cada perfil (proposta, sem RBAC completo)

Implementar controle de acesso por grupo Django (`django.contrib.auth.models.Group` +
`@permission_required`) é o caminho correto a médio prazo, mas é trabalho de backend, fora do
escopo desta rodada (que é só front-end). Para o congresso, a proposta é **visual e de
navegação**, não de permissão:

1. **Um seletor de "visão" no topbar** (não é login diferente — é um filtro de densidade de
   informação), com 3 opções: Operacional / Coordenação / Gestão. Persistido em `localStorage`,
   como já é feito com o estado da sidebar colapsada.
2. **Visão Gestão = uma nova página-síntese** (`pca:dashboard_executivo`, por exemplo): 6-8 KPIs
   grandes (valor total planejado, % executado, contratos a vencer em 90 dias, risco financeiro
   agregado), sem tabela de linha a linha, com os sparklines da seção A4. É a tela que se abre
   direto no modo apresentação (A3) para o congresso.
3. **Visão Coordenação = os dashboards atuais** (`srp:dashboard`, `contratos:dashboard`,
   `licitacao:dashboard`), já bons depois das 4 rodadas de storytelling — só precisam do seletor
   de visão no topbar para se anunciarem como "isto é a visão de quem coordena esta frente".
4. **Visão Operacional = as telas de listagem/cadastro** (`pca:demandas`,
   `srp:arp_detalhe`, formulários) — já existem, só faltam aparecer como destino natural do
   seletor, com foco em "o que está pendente comigo" (uso de `alert-pill` já existente no
   design system, mas hoje pouco usado fora de 1-2 telas).

**Por que essa abordagem e não RBAC completo agora:** o pedido desta tarefa é front-end; criar
grupos/permissões reais envolve migração, decisão de quem entra em cada grupo, e testes de
segurança — trabalho maior, de outra natureza. A proposta acima entrega 80% do efeito
demonstrável no congresso (mostrar que o sistema "pensa" nos três perfis) com risco quase zero,
e deixa o RBAC de verdade como próximo passo natural depois, se o Thiago quiser seguir.

### Página nova recomendada: Dashboard Executivo (gestor)

É a peça que mais falta hoje. Sugestão de conteúdo, só com dados que já existem no sistema
(nenhum modelo novo necessário):
- 4-6 KPIs grandes: valor total do PCA do exercício, % de demandas em cada fase do workflow,
  contratos vencendo em 90 dias (já existe em `contratos:vencimentos`), valor total empenhado vs
  planejado.
- 1 gráfico de tendência (linha) — evolução do valor planejado/executado por mês do exercício.
- 1 lista curta de "riscos" (já existe conceito em `pca:riscos`) — só os 5 mais críticos, sem
  paginação, com link para a lista completa.
- Sem tabela de detalhe de item nem filtro complexo — é para ser visto em 30 segundos.

---

## Roadmap priorizado

| # | Item | Esforço | Risco | Onde |
|---|---|---|---|---|
| P1 | Fonte web (Inter) em `base.html` | Baixo | Baixo | `templates/base.html` |
| P2 | Botão "Modo apresentação" (fullscreen + esconder sidebar/topbar) | Baixo-médio | Baixo | `base.html` + 3-4 dashboards |
| P3 | Sparklines nos KPI cards principais | Médio | Baixo | dashboards existentes |
| P4 | Números animados (count-up) nos KPIs | Baixo | Baixo | dashboards existentes |
| P5 | Checklist de contraste dos badges (documentar, sem mudar cor se já aprovado) | Baixo | Nenhum | validação, não código |
| P6 | Seletor de "visão" no topbar (Operacional/Coordenação/Gestão) | Médio | Baixo | `base.html` |
| P7 | Dashboard Executivo novo (`pca:dashboard_executivo`) | Alto | Médio (view nova + query) | `apps/pca` |
| P8 (futuro, fora do escopo front-end) | RBAC real por grupo Django | Alto | Médio-alto | backend, outro pedido |

Sugestão de ordem para render mais rápido antes do congresso: **P1 → P2 → P4 → P3**, que já
mudam a "sensação" do sistema em poucas horas de trabalho, cada um isolado e reversível. P6/P7
entregam a resposta à pergunta "e os diferentes usuários?" e valem a pena se houver tempo antes
da apresentação; P8 fica para depois.

---

## Fontes consultadas

- [UXPin — Dashboard Design Principles: The Definitive Guide (2026)](https://www.uxpin.com/studio/blog/dashboard-design-principles/)
- [Dashboard Design in 2026: Do's and Don'ts](https://think.design/blog/dashboard-design-in-2026-dos-and-donts/)
- [Muzli — 50 Best Dashboard Design Examples for 2026](https://muz.li/blog/best-dashboard-design-examples-inspirations-for-2026/)
- [Padrão Digital de Governo — Design System (gov.br/ds), cores](https://www.gov.br/ds/fundamentos-visuais/cores)
- [Wiki SETIC-RO — Boas Práticas de Dashboards (telão/TV)](https://wiki.setic.ro.gov.br/home/base_conhecimento/estudos_tecnicos/cagd/boas_praticas_dashboards)
- [npm-compare — Chart.js vs ApexCharts vs ECharts vs Recharts](https://npm-compare.com/apexcharts,chart.js,echarts,recharts)
- [WebAbility — Color Contrast for Accessibility: WCAG Guide (2026)](https://www.webability.io/blog/color-contrast-for-accessibility)
- [Domo — Executive Reporting Dashboard Guide](https://www.domo.com/learn/article/the-ultimate-guide-to-creating-executive-level-reporting-dashboards)
- [Qlik — Dashboard Design: 7 Best Practices & Examples](https://www.qlik.com/us/dashboard-examples/dashboard-design)
- [Yellowfin — Designing Analytics Apps? Know These 3 User Personas](https://www.yellowfinbi.com/blog/three-personas-design-analytics-app)
