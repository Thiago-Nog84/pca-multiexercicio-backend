from django.conf import settings
from django.db import models


class ETP(models.Model):
    """
    Estudo Técnico Preliminar — art. 18 NLLC + IN SEGES 58/2022.
    """

    STATUS = [
        ("rascunho", "Rascunho"),
        ("em_revisao", "Em revisão"),
        ("aprovado", "Aprovado"),
    ]

    item_pca = models.OneToOneField(
        "pca.ItemPCA", on_delete=models.CASCADE, related_name="etp_origem", null=True, blank=True
    )
    numero_sei = models.CharField(max_length=30, blank=True)
    numero_etp = models.CharField(max_length=30)
    is_ti = models.BooleanField(default=False)
    necessidade_contratacao = models.TextField()
    requisitos_contratacao = models.TextField()
    levantamento_mercado = models.TextField()
    descricao_solucao = models.TextField()
    estimativa_quantidade = models.TextField()
    estimativa_custo = models.DecimalField(max_digits=16, decimal_places=2, null=True)
    justificativa_parcelamento = models.TextField()
    contratacoes_correlatas = models.TextField(blank=True)
    alinhamento_pca = models.TextField()
    resultados_pretendidos = models.TextField()
    providencias_previas = models.TextField(blank=True)
    impactos_ambientais = models.TextField()
    declaracao_viabilidade = models.BooleanField(default=False)
    tco_total = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    solucao_em_outros_orgaos = models.TextField(blank=True)
    software_livre_avaliado = models.BooleanField(default=False)
    gerado_por_ia = models.BooleanField(default=False)
    ia_modelo_utilizado = models.CharField(max_length=50, blank=True)
    ia_revisado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="etps_revisados"
    )
    status = models.CharField(max_length=15, choices=STATUS, default="rascunho")
    etp_dispensado = models.BooleanField(default=False)
    fundamento_dispensa_etp = models.CharField(max_length=200, blank=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.numero_etp or f"ETP #{self.pk}"


class EquipePlanejamentoTI(models.Model):
    etp = models.OneToOneField(ETP, on_delete=models.CASCADE, related_name="equipe_planejamento_ti")
    integrante_requisitante = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="ep_requisitante"
    )
    integrante_tecnico = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="ep_tecnico"
    )
    integrante_administrativo = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="ep_administrativo"
    )
    lider = models.CharField(
        max_length=20,
        choices=[("requisitante", "Requisitante"), ("tecnico", "Técnico"), ("administrativo", "Administrativo")],
        default="requisitante",
    )
    ato_designacao_sei = models.CharField(max_length=30, blank=True)


class MatrizRisco(models.Model):
    etp = models.OneToOneField(ETP, on_delete=models.CASCADE, related_name="matriz_risco")
    fase_atual = models.CharField(
        max_length=20,
        choices=[("planejamento", "Planejamento"), ("selecao", "Seleção"), ("gestao", "Gestão")],
        default="planejamento",
    )


class RiscoItem(models.Model):
    PROBABILIDADE = [(1, "Muito baixa"), (2, "Baixa"), (3, "Média"), (4, "Alta"), (5, "Muito alta")]
    IMPACTO = [(1, "Muito baixo"), (2, "Baixo"), (3, "Médio"), (4, "Alto"), (5, "Muito alto")]
    RESPONSAVEL = [("adm", "Administração"), ("contratado", "Contratado"), ("compartilhado", "Compartilhado")]

    matriz = models.ForeignKey(MatrizRisco, on_delete=models.CASCADE, related_name="itens")
    descricao_risco = models.TextField()
    causa = models.TextField()
    consequencia = models.TextField()
    probabilidade = models.PositiveSmallIntegerField(choices=PROBABILIDADE)
    impacto = models.PositiveSmallIntegerField(choices=IMPACTO)
    nivel_risco = models.PositiveSmallIntegerField(editable=False)
    responsavel = models.CharField(max_length=20, choices=RESPONSAVEL)
    acao_preventiva = models.TextField()
    acao_contingencia = models.TextField()

    def save(self, *args, **kwargs):
        self.nivel_risco = self.probabilidade * self.impacto
        super().save(*args, **kwargs)


class TermoReferencia(models.Model):
    STATUS = [
        ("rascunho", "Rascunho"),
        ("em_revisao", "Em revisão"),
        ("appl", "Aguardando análise APPL"),
        ("aprovado", "Aprovado"),
        ("publicado", "Publicado"),
    ]

    etp = models.OneToOneField(ETP, on_delete=models.CASCADE, related_name="termo_referencia")
    numero_sei = models.CharField(max_length=30, blank=True)
    objeto = models.TextField()
    fundamentacao_legal = models.TextField()
    descricao_solucao = models.TextField()
    requisitos_habilitacao = models.TextField()
    criterio_julgamento = models.CharField(max_length=30, choices=[
        ("menor_preco", "Menor Preço"), ("maior_desconto", "Maior Desconto"),
        ("melhor_tecnica", "Melhor Técnica e Preço"), ("maior_retorno", "Maior Retorno Econômico"),
    ])
    prazo_execucao = models.PositiveIntegerField()
    local_execucao = models.TextField()
    obrigacoes_contratante = models.TextField()
    obrigacoes_contratado = models.TextField()
    criterios_medicao = models.TextField()
    is_servico_continuo = models.BooleanField(default=False)
    prazo_inicial_meses = models.PositiveSmallIntegerField(null=True, blank=True)
    prazo_maximo_meses = models.PositiveSmallIntegerField(null=True, blank=True)
    is_srp = models.BooleanField(default=False)
    justificativa_srp = models.TextField(blank=True)
    modalidade_remuneracao_ti = models.CharField(max_length=30, blank=True, choices=[
        ("pontos_funcao", "Pontos de função + horas"), ("sprint", "Valor fixo por sprint"),
        ("alocacao", "Alocação vinculada a resultados"), ("fixo_mensal", "Valor fixo mensal por sistema"),
        ("fixo_alocacao", "Fixo por alocação com resultados"),
    ])
    vedacoes_ti_observadas = models.BooleanField(default=False)
    gerado_por_ia = models.BooleanField(default=False)
    modelo_agu_base = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=15, choices=STATUS, default="rascunho")
    atualizado_em = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.objeto[:60]
