# Roteiro de melhorias inspirado no sistema legado (pca-mppi)

Levantamento feito em 14/08/2026 a partir do código do sistema do Cleriston
(`pca-mppi`, React + Supabase), versão de 04/08/2026 — cerca de duas semanas
mais nova que a última comparação registrada em julho.

A ordem abaixo é de esforço crescente, com o item 4 adiantado por impacto.
Itens 1 a 3 estão concluídos.

---

## Concluídos

### 1. Modalidades Concurso e Credenciamento — `d7ce31e`

`credenciamento` (art. 79 NLLC) adicionado a `ItemPCA.MODALIDADE` e a
`ProcessoLicitatorio.Modalidade`. `concurso` já existia no PCA.

**Pendência de decisão:** `ItemPCA.data_inicio_prevista` (regra do Tutorial
PCA-MPPI, pág. 14) classifica as modalidades em licitação competitiva
(conclusão − 150 dias) e contratação direta (− 90 dias). Credenciamento não foi
incluído em nenhum dos dois grupos e cai no padrão de 120 dias. Confirmar o
prazo correto com a CLC.

### 2. Notificações in-app — `d7ce31e`

Models `Notificacao` + `NotificacaoLida` em `apps/core`. Central em
`/notificacoes/`, sino com contador no topbar (via context processor),
publicação pelo admin.

Diferenças deliberadas em relação ao legado, que usa texto livre no
destinatário e não valida quem vê o quê:

- `unidade_destino` é FK real para `UnidadeRequisitante` (em branco = todos);
  o escopo é calculado cruzando os `Perfil` ativos do usuário.
- Exclusão é lógica (`ativa=False`), preservando a trilha de leitura.

### 3. Controle de Prazos — `34f4419`

Ao começar, constatou-se que `/pca/prazos/` já era mais rica que a tela do
legado na leitura (KPIs, 4 colunas de data, dias restantes, filtros) e que
todos os campos de data já existiam em `ItemPCA`. O escopo virou acrescentar
o que faltava: edição inline das datas (restrita a APG/autoridade/superuser),
filtro por mês, restrição do requisitante à própria unidade e o model
`HistoricoDataItemPCA`.

**Regra de negócio nova:** justificativa é obrigatória ao *adiar* a conclusão
prevista — sem isso o indicador de "vencidos" poderia ser zerado empurrando
datas para a frente. Antecipar e os demais campos não exigem motivo.

---

## Pendentes

### 4. Checklist de conformidade por contratação — P1, esforço médio

Referência: `src/pages/AvaliacaoConformidade.tsx` no legado.

Duas fases com itens marcáveis e percentual de conformidade calculado:

- **Licitação/Contratação (11):** termo de referência aprovado, pesquisa de
  mercado, pareceres jurídicos, publicação do edital, atas do certame, termo
  de homologação, termo de adjudicação, atos de autorização, documentação do
  fornecedor, assinatura do contrato, publicação do extrato.
- **Execução (14):** documento de aceite, justificativa da vantajosidade,
  declaração de conformidade, pesquisa de preços, mapa comparativo, certidões
  de habilitação, margem de cálculo, pareceres orçamentário/financeiro,
  parecer jurídico, parecer CONINT, ofício e autorização de empenho,
  atualização de certidões, termo aditivo/apostilamento, publicações.

É o item de maior valor de controle interno da lista — hoje não existe nada
equivalente no nosso sistema. Modelar como `ChecklistConformidade` ligado a
`Contrato` (ou a `ItemPCA`, a decidir).

### 5. Bloqueio orçamentário rígido por UO — P2, esforço médio/alto

Referência: trigger `check_orcamento_limite` e funções `orcamento_setorial` /
`saldo_uo_por_demanda` no legado.

Impede (não apenas avisa) que o reservado da unidade orçamentária ultrapasse
`valor_aprovado + excedentes_autorizados`, com exceção para administrador.
Já era ideia nossa de prioridade baixa; agora há implementação de referência.
Mexe com dinheiro real — pede teste mais cuidadoso antes de valer em produção.

### 6. Sobrestamento parcial de demanda — P2, esforço médio/alto

Referência: funções `sobrestar_parcial` e `reativar_suspensao` no legado.

Hoje só existe suspensão total. O legado permite suspender parte da
quantidade: cria uma demanda "filha" com a fração suspensa e `parent_id`
apontando para a original, reduz quantidade/valor do pai e mantém tabela de
auditoria da relação. A reativação faz o merge de volta no pai.

### 7. Módulo de licitação/disputa — escopo a decidir antes de estimar

Referência: `src/modules/srp/` e os 5 arquivos SQL na raiz do repo do legado.

Sala de lances, desempate ME/EPP, negociação pós-lance (art. 61), adjudicação
por item ou por grupo com trava de justificativa ("bloqueio TCU"), conta
corrente de ARP com limite de carona (2× o registrado, art. 86) e limite
individual de 50% por órgão aderente, e log de auditoria com encadeamento de
hash.

**Não começar sem decisão de produto:** isto muda o escopo do sistema, que
hoje consome o resultado da licitação em vez de conduzi-la. Boa parte do
código de referência ainda é protótipo (comentários "for the demo", função
`check_arp_balance_guard` com corpo vazio).

---

## Outras telas do legado ainda não analisadas

`Artefatos`, `PrioridadesAtencao`, `PrioridadesContratacao`,
`ResultadosAlcancados`, `SetoresDemandantes`, `VisaoGeral`,
`GerenciamentoUnidades`, `GerenciamentoUsuarios`, `SelecaoExercicio` e o fluxo
de redefinição de senha (`EsqueciSenha` / `RedefinirSenha`).
