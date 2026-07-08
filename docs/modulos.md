# PCA Multiexercício — Levantamento de Requisitos por Módulos

**Órgão:** MPPI (CNPJ 05805924000189, UASG 926092)
**Stack:** Django 5.2 / Python 3.14 / PostgreSQL / Bootstrap 5
**Base normativa:** Lei 14.133/2021 · Ato PGJ 1381/2024 (PCA) · Ato PGJ 1414-1415/2024 · Decreto 11.462/2023 (SRP) · Res. CNMP 283/2024 (TI)
**Equipe:** Thiago Nogueira (negócio + full-stack) · João Carlos (CTI, back-end)
**Última revisão:** 08/07/2026

---

## Como usar este documento

Cada módulo abaixo é uma unidade de trabalho independente. A regra de colaboração é:

1. Módulos **sem dependência entre si** podem ser trabalhados em paralelo, cada um em sua branch, sem risco de conflito.
2. Módulos **dependentes** (ver campo "Depende de" de cada um) exigem reunião prévia para dividir a tarefa e combinar o contrato de interface (nomes de campos, endpoints, models compartilhados).
3. A coluna "Situação" diz o que já existe — muito do sistema já está construído; o levantamento serve tanto para requisitos novos quanto para mapa do que já há.

**Grafo de dependências (visão rápida):**

```
M1 Cadastros Básicos (core)
 └─► M2 Planejamento PCA ──► M3 Workflow/Validação ──► M9 Relatórios
 │        │                                              ▲
 │        ▼                                              │
 └─► M4 ARP/SRP ◄──► M5 Contratos ──► M6 Execução SIAFE ─┘
          │              │
          ▼              ▼
 M7 Integrações API (PNCP/Compras.gov)   M8 Licitação/Instrução
                                          M10 Alertas/Notificações (lê M2, M4, M5)
```

---

## M1 — Cadastros Básicos e Controle de Acesso (`apps/core`)

**O que faz:** cadastros estruturais que todos os outros módulos usam: órgão, unidades requisitantes e perfis de acesso.

**O que mostra:** administração de `Orgao`, `UnidadeRequisitante` (sigla, nome, responsável) e `Perfil` (usuário × perfil × unidade — 16 perfis do fluxo de contratação: requisitante, APG, autoridade, gestor de contrato, fiscais etc.).

**Inclusão/exclusão/atualização:** via Django admin. Unidades não devem ser excluídas se tiverem DFD/contrato vinculado (proteger com `on_delete` adequado — revisar).

**Relatórios:** nenhum próprio; alimenta filtros de todos os demais.

**Depende de:** nada. É a raiz do grafo.

**Situação:** models prontos e populados. **Gap:** o model `Perfil` existe mas quase nada o consulta — só o painel de fases (M3) checa perfil. Falta aplicar permissão por unidade nas telas (requisitante só vê/edita a própria unidade).

**Sugestão de divisão:** João Carlos — middleware/mixins de permissão por perfil e unidade (trabalho puramente back-end, alto impacto em todos os módulos). Thiago — definição de quais perfis acessam o quê (regra de negócio).

---

## M2 — Planejamento PCA (`apps/pca`) — o coração do sistema

**O que faz:** gestão do Plano de Contratações Anual multiexercício: DFDs, itens de demanda, catálogo institucional de itens, orçamento por unidade, renovação/clonagem entre exercícios.

**O que mostra:**
- Dashboard do PCA (valores, status, categorias, alertas de prazo) com seletor de exercício;
- Lista de demandas com filtros (busca, status, categoria, modalidade, unidade);
- Detalhe do item; demandas suspensas;
- **Cadastro em grupo** (1 DFD + N itens numa transação) com: autocomplete de descrição (catálogo + histórico com preços), painel de saldo de ARP por item, painel de contrato vigente (renovações), vínculo `VinculoPCAItemARP` validado contra saldo;
- Orçamento planejado por unidade (aprovado × comprometido);
- Renovação multiexercício (itens contínuos) e clonagem de PCA completo;
- Relatório de possíveis duplicatas (CATMAT igual / descrição semelhante entre unidades).

**Inclusão/exclusão/atualização:** itens via cadastro em grupo (tela própria), admin e API DRF (`/pca/api/`). Código `codigo_pca` gerado automaticamente. Exclusão deve ser rara — preferir status `suspenso`.

**Relatórios:** base completa (CSV/HTML), orçamento setorial, prazos críticos, suspensas, por modalidade, duplicatas.

**Depende de:** M1 (unidades, perfis). Consome M4 (saldo de ARP) e M5 (contrato vigente) nas buscas do cadastro em grupo — interfaces já definidas (endpoints JSON internos).

**Situação:** o módulo mais maduro. PCA 2026 (549 itens reais) e 2027 (importado, em validação). **Gaps:** busca insensível a acento (habilitar extensão `unaccent` no Postgres), promover `numero_lote_pca` a entidade própria (avaliar), cotação de preços automática via PNCP para valor estimado (backlog).

**Sugestão de divisão:** Thiago — validação de dados 2027, regras de negócio, telas. João Carlos — extensão unaccent + refatoração da busca, endpoint de cotação de preços PNCP (mediana/outliers).

---

## M3 — Workflow e Validação do PCA (`apps/pca` — views_workflow, views_validacao)

**O que faz:** conduz o PCA pelas fases do Ato PGJ 1381/2024 (coleta → consolidação → aprovação PGJ → publicado PNCP → revisões) e valida demandas item a item (aprovar/devolver/vincular ARP).

**O que mostra:**
- Painel de fases (stepper) com avançar/recuar restrito a APG/Autoridade, justificativa obrigatória ao recuar, trilha de auditoria (`HistoricoFasePCA`);
- Tela de validação por exercício: aprovar/devolver itens `pendente_validacao`, vincular a ARPs vigentes.

**Inclusão/exclusão/atualização:** só transições de status (nunca editar histórico — admin read-only).

**Relatórios:** histórico de fases (auditoria); itens por status de validação.

**Depende de:** M2 (itens/DFDs) e M1 (perfis). Relatórios (M9) leem o status daqui.

**Situação:** painel de fases implementado (08/07/2026) e validação funcional. **Gaps:** fluxo de DFD (enviar → devolver → aprovar) sem tela própria — hoje status muda no admin; notificação ao requisitante quando devolvido (depende de M10).

**Sugestão de divisão:** reunião obrigatória com M2 — mesmo app, arquivos distintos. João Carlos — transições de DFD com regras server-side. Thiago — critérios de validação.

---

## M4 — Atas de Registro de Preços / SRP (`apps/srp`)

**O que faz:** gestão das 4 dimensões do SRP: (1) ARPs gerenciadas pelo MPPI, (2) contratações decorrentes, (3) caronas cedidas a outros órgãos, (4) caronas recebidas (ARP externa). Controla saldo por item.

**O que mostra:**
- Dashboard SRP; detalhe da ARP com itens, lotes e saldos;
- Saldo por item: registrado − comprometido no PCA − contratado − cedido em carona = `quantidade_disponivel_eventual`;
- Visão por unidade (`VinculoARPUnidade`);
- Importação de ARPs (tela + management commands).

**Inclusão/exclusão/atualização:** ARP/itens via admin, importação automática (M7) ou tela. `ContratacaoDecorrente.save()` debita saldo automaticamente; `AdesaoARP` (carona cedida) idem. Validações fortes nos `clean()` (vigência, teto de adesão, coerência de lote).

**Relatórios:** saldo por ARP/item/lote; contratos decorrentes por ARP; caronas.

**Depende de:** M1. M2 e M5 consomem seus saldos. M7 o alimenta.

**Situação:** models e regras prontos; 94 ARPs importadas. **Gaps:** número de lote não vem de API (preenchimento manual único a partir do edital — documentado); `ContratoARP` (importado) é desconectado de `contratos.Contrato` (manual) — unificação é decisão de arquitetura pendente.

**Sugestão de divisão:** João Carlos — unificação `ContratoARP` × `Contrato` (migração de dados + FK, back-end puro, exige reunião com M5). Thiago — preenchimento de lotes e conferência de saldos reais.

---

## M5 — Contratos (`apps/contratos`)

**O que faz:** ciclo de vida do contrato: cadastro, aditivos, apostilamentos, ordens de fornecimento, saldo, fiscalização (gestor/fiscais), vínculo com item do PCA e ARP de origem.

**O que mostra:** dashboard (status, execução, alertas TI 120d/demais 90d, transparência CNMP), painel de vencimentos consolidado (faixas 120/90/60/30 para contratos + ARPs + caronas).

**Inclusão/exclusão/atualização:** contrato/aditivo via admin (aditivo recalcula valor e vigência do contrato ao salvar). Exclusão não — usar status (encerrado/rescindido/suspenso).

**Relatórios:** vencimentos por faixa; execução por contrato; contratos sem empenho.

**Depende de:** M1, M4 (arp_origem), M2 (item_pca). M6 escreve `valor_empenhado` aqui.

**Situação:** funcional; 161 contratos com unidade vinculada. **Gaps:** 128 registros vencidos ainda com status "vigente" (saneamento de dados!); tela própria de detalhe do contrato (hoje só admin); bloqueio por regra: impedir ordem de fornecimento acima do saldo (hoje só valida no clean — avaliar endurecer).

**Sugestão de divisão:** Thiago — saneamento dos 128 vencidos (negócio: encerrar ou prorrogar?). João Carlos — tela de detalhe + bloqueios por regra.

---

## M6 — Execução Orçamentária SIAFE (`apps/siafe`, `apps/contratos` — empenhos)

**O que faz:** sincroniza Notas de Empenho do SIAFE-PI e vincula a contratos (via `codigo_siafe`), calculando valor empenhado por contrato.

**O que mostra:** tela de empenhos com ajuste de vínculo; botão de sincronização; última atualização.

**Inclusão/exclusão/atualização:** dados vêm da integração; ajuste manual só do vínculo empenho↔contrato.

**Relatórios:** empenhado × saldo por contrato; % de execução no dashboard.

**Depende de:** M5 (contratos). Integração externa SIAFE-PI.

**Situação:** funcional com sincronização manual. **Gap:** agendamento automático (job diário).

**Sugestão de divisão:** João Carlos — inteiro (integração e back-end é o forte dele).

---

## M7 — Integrações Compras.gov.br / PNCP (`apps/pncp`, commands em `apps/srp`)

**O que faz:** importa dados públicos: ARPs e itens (dadosabertos.compras.gov.br), contratos decorrentes (fallback PNCP), contratos Comprasnet, links de publicação.

**O que mostra:** não tem tela própria — abastece M4/M5. Logs no console/`SiafeLogConsulta`.

**Inclusão/exclusão/atualização:** management commands: `importar_arp_compras_gov`, `importar_contratos_arp`, `buscar_link_arp_mppi`, `vincular_contratos_arp_origem`.

**Relatórios:** relatório xlsx de vinculação de contratos a ARPs.

**Depende de:** M4/M5 (escreve neles). APIs externas instáveis (404 frequentes, campos vazios no PNCP, paginação limitada — usar `tamanhoPagina<=10`).

**Situação:** funcional, cobertura de API esparsa (2 contratos achados de 94 ARPs). **Gaps:** agendamento periódico; tratamento de encoding no console Windows (usar `PYTHONUTF8=1`); monitorar mudanças de API.

**Sugestão de divisão:** João Carlos — inteiro. Reunião com M4/M5 quando mexer nos models de destino.

---

## M8 — Licitação e Instrução Processual (`apps/licitacao`, `apps/planejamento`, `apps/juridico`, `apps/cotacao`)

**O que faz (futuro, em grande parte):** fase entre o PCA aprovado e o contrato: ETP, matriz de risco, TR, processo licitatório, pareceres jurídicos, cotação de preços.

**O que mostra:** dashboards básicos já existem (cotação/jurídico vazios); models `ETP`, `MatrizRisco`, `TermoReferencia`, `ProcessoLicitatorio`, `ItemLicitacao`, `EquipePlanejamentoTI` criados.

**Inclusão/exclusão/atualização:** a definir por submódulo. Referências de mercado: ETP guiado, matriz 5×5 (TCU), reaproveitamento DFD→ETP→TR.

**Relatórios:** conformidade processual (checklist `ConformidadeItem` já existe em M2).

**Depende de:** M2 (herda dados do DFD/item), M4/M5 (resultado gera ARP ou contrato).

**Situação:** esqueleto. É o módulo com mais requisito a levantar — **bom candidato a spec conjunta com João Carlos antes de codar**.

**Sugestão de divisão:** definir juntos; depois João Carlos assume geração de documentos/back-end e Thiago o conteúdo normativo (modelos AGU/MPPI).

---

## M9 — Relatórios e Painéis Transversais (`apps/pca` — views_relatorios, views_prazos)

**O que faz:** relatórios CSV/HTML imprimível e painéis de controle de prazos, riscos e pendências cruzando os módulos.

**O que mostra:** landing de relatórios com filtros repassados; controle de prazos; riscos.

**Depende de:** lê M2/M3/M4/M5 — não escreve em nada (baixo risco de conflito).

**Situação:** funcional. **Gaps:** exportação PDF nativa; relatório "PCA planejado × executado" (cruza M2 com M5/M6 — o mais pedido pela gestão).

**Sugestão de divisão:** qualquer um; bom módulo para trabalhar em paralelo sem conflito.

---

## M10 — Alertas e Notificações (`apps/notificacoes`)

**O que faz (futuro):** transforma os alertas que hoje são visuais (vencimentos, prazos, devoluções de DFD) em notificações ativas (e-mail/painel), com agendamento.

**O que mostra:** central de notificações do usuário; preferências.

**Inclusão/exclusão/atualização:** geradas por jobs; usuário marca como lida.

**Relatórios:** log de notificações enviadas.

**Depende de:** M2, M3, M4, M5 (fontes de eventos). App `notificacoes` existe vazio.

**Situação:** não iniciado. Requisito inicial sugerido: job diário que materializa as faixas 120/90/60/30 do painel de vencimentos em e-mails para gestor/fiscal do contrato.

**Sugestão de divisão:** João Carlos — infraestrutura (jobs, e-mail); Thiago — quem recebe o quê e quando.

---

## Resumo da divisão sugerida

| Módulo | Thiago | João Carlos | Reunião necessária? |
|---|---|---|---|
| M1 Cadastros/Acesso | regras de perfil | mixins de permissão | sim (contrato de interface) |
| M2 Planejamento PCA | dono | unaccent, cotação PNCP | pontual |
| M3 Workflow/Validação | critérios | transições DFD | sim (mesmo app do M2) |
| M4 ARP/SRP | dados/lotes | unificação ContratoARP×Contrato | sim (com M5) |
| M5 Contratos | saneamento vencidos | detalhe + bloqueios | sim (com M4) |
| M6 SIAFE | — | dono | não |
| M7 Integrações | — | dono | pontual (models M4/M5) |
| M8 Licitação | conteúdo normativo | back-end | sim (spec conjunta) |
| M9 Relatórios | livre | livre | não |
| M10 Notificações | destinatários/regras | jobs/e-mail | pontual |

**Pares que exigem coordenação:** M2↔M3 (mesmo app), M4↔M5 (unificação de contratos), M7→M4/M5 (escreve nos models), M8 (spec conjunta). Todo o resto pode andar em paralelo.
