"""
Checklist de conformidade documental por contrato.

Instrumento de controle interno: percorre os documentos e atos que devem
existir no processo, da fase de licitação/contratação até a execução, e
mede o percentual de conformidade.

Modelagem: o catálogo de itens vive em constantes Python (não em colunas),
e só os itens efetivamente tocados viram linha em ItemChecklist. Assim,
incluir ou renomear um item do checklist não exige migração de schema —
diferente do sistema de referência, que tem uma coluna booleana por item.
"""

from django.conf import settings
from django.db import models


class ChecklistConformidade(models.Model):
    """Cabeçalho do checklist — um por contrato."""

    # (chave, rótulo) — a chave é gravada em ItemChecklist.chave.
    FASE_LICITACAO = [
        ("termo_referencia_aprovado", "Termo de Referência aprovado"),
        ("pesquisa_mercado", "Pesquisa de mercado"),
        ("pareceres_juridicos", "Pareceres jurídicos sobre a licitação"),
        ("publicacao_edital", "Publicação do edital conforme as normas"),
        ("atas_certame", "Atas do certame"),
        ("termo_homologacao", "Termo de homologação"),
        ("termo_adjudicacao", "Termo de adjudicação"),
        ("atos_autorizacao", "Atos de autorização registrados"),
        ("documentacao_fornecedor", "Documentação do fornecedor completa"),
        ("assinatura_contrato", "Assinatura do contrato"),
        ("publicacao_contrato", "Publicação do extrato do contrato"),
    ]

    FASE_EXECUCAO = [
        ("documento_aceite", "Documento de aceite"),
        ("justificativa_vantajosidade", "Justificativa da vantajosidade"),
        ("declaracao_conformidade", "Declaração de conformidade"),
        ("pesquisa_precos", "Pesquisa de preços"),
        ("mapa_comparativo", "Mapa comparativo"),
        ("certidoes_habilitacao", "Certidões de habilitação / contrato social"),
        ("margem_calculo", "Memória de cálculo"),
        ("parecer_orcamentario_financeiro", "Pareceres orçamentário e financeiro"),
        ("parecer_juridico_execucao", "Parecer jurídico"),
        ("parecer_conint", "Parecer CONINT"),
        ("oficio_autorizacao_empenho", "Ofício e autorização de empenho"),
        ("atualizar_certidoes", "Atualização de certidões"),
        ("termo_aditivo_apostilamento", "Termo aditivo / apostilamento"),
        ("publicacoes_execucao", "Publicações"),
    ]

    FASES = [
        ("licitacao", "Licitação e Contratação", FASE_LICITACAO),
        ("execucao", "Execução", FASE_EXECUCAO),
    ]

    TODOS_ITENS = FASE_LICITACAO + FASE_EXECUCAO
    ROTULOS = dict(TODOS_ITENS)
    CHAVES_VALIDAS = set(ROTULOS)

    contrato = models.OneToOneField(
        "contratos.Contrato",
        on_delete=models.CASCADE,
        related_name="checklist",
    )
    observacoes = models.TextField(
        blank=True,
        help_text="Anotações gerais da auditoria sobre este contrato.",
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    atualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="checklists_atualizados",
    )

    class Meta:
        verbose_name = "Checklist de Conformidade"
        verbose_name_plural = "Checklists de Conformidade"

    def __str__(self):
        return f"Checklist — {self.contrato.numero_contrato}"

    # ------------------------------------------------------------------
    # Cálculo de conformidade
    # ------------------------------------------------------------------

    @property
    def total_itens(self):
        return len(self.TODOS_ITENS)

    @property
    def chaves_marcadas(self):
        """
        Só conta chaves que existem no catálogo atual — um item removido do
        catálogo não deve continuar inflando o percentual.
        """
        return {
            i.chave for i in self.itens.all()
            if i.marcado and i.chave in self.CHAVES_VALIDAS
        }

    @property
    def qtd_marcados(self):
        return len(self.chaves_marcadas)

    @property
    def percentual(self):
        if not self.total_itens:
            return 0
        return round(self.qtd_marcados * 100 / self.total_itens)

    @property
    def faixa(self):
        """Classe de contexto Bootstrap conforme o percentual."""
        pct = self.percentual
        if pct >= 80:
            return "success"
        if pct >= 30:
            return "warning"
        return "danger"

    def resumo_por_fase(self):
        """[(chave_fase, rótulo, marcados, total), ...] para os cabeçalhos."""
        marcadas = self.chaves_marcadas
        return [
            (
                chave_fase,
                rotulo,
                len([c for c, _ in itens if c in marcadas]),
                len(itens),
            )
            for chave_fase, rotulo, itens in self.FASES
        ]

    def itens_por_fase(self):
        """
        Estrutura pronta para o template: para cada fase, a lista completa do
        catálogo com o estado atual (marcado, observação, quem marcou).
        Itens nunca tocados aparecem como não marcados.
        """
        existentes = {i.chave: i for i in self.itens.select_related("marcado_por")}
        resultado = []
        for chave_fase, rotulo_fase, itens in self.FASES:
            linhas = [
                {
                    "chave": chave,
                    "rotulo": rotulo,
                    "registro": existentes.get(chave),
                    "marcado": bool(existentes.get(chave) and existentes[chave].marcado),
                }
                for chave, rotulo in itens
            ]
            resultado.append({
                "chave": chave_fase,
                "rotulo": rotulo_fase,
                "linhas": linhas,
                "marcados": len([linha for linha in linhas if linha["marcado"]]),
                "total": len(linhas),
            })
        return resultado


class ItemChecklist(models.Model):
    """Estado de um item do checklist. Criado sob demanda, ao ser tocado."""

    checklist = models.ForeignKey(
        ChecklistConformidade,
        on_delete=models.CASCADE,
        related_name="itens",
    )
    chave = models.CharField(max_length=50)
    marcado = models.BooleanField(default=False)
    observacao = models.CharField(max_length=300, blank=True)
    marcado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="itens_checklist_marcados",
    )
    marcado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Item do Checklist"
        verbose_name_plural = "Itens do Checklist"
        unique_together = ("checklist", "chave")
        ordering = ("chave",)

    def __str__(self):
        return f"{self.chave} — {'OK' if self.marcado else 'pendente'}"

    @property
    def rotulo(self):
        return ChecklistConformidade.ROTULOS.get(self.chave, self.chave)
