from django.db import models


class ProcessoLicitatorio(models.Model):
    """
    Metadados do processo licitatório (fase interna).
    A condução completa do certame (fase externa) está fora do escopo
    atual — ver roadmap, Estágio 3.
    """

    MODALIDADES = [
        ("pregao", "Pregão"),
        ("concorrencia", "Concorrência"),
        ("dispensa", "Dispensa"),
        ("inexigibilidade", "Inexigibilidade"),
        ("concurso", "Concurso"),
        ("leilao", "Leilão"),
        ("dialogo_competitivo", "Diálogo Competitivo"),
    ]

    STATUS = [
        ("em_preparacao", "Em preparação"),
        ("publicado", "Publicado"),
        ("em_julgamento", "Em julgamento"),
        ("homologado", "Homologado"),
        ("revogado", "Revogado"),
        ("anulado", "Anulado"),
        ("fracassado", "Fracassado"),
        ("deserto", "Deserto"),
    ]

    orgao = models.ForeignKey("core.Orgao", on_delete=models.CASCADE, related_name="processos_licitatorios")
    numero_processo = models.CharField(max_length=30)
    ano = models.PositiveSmallIntegerField()
    numero_sei = models.CharField(max_length=30, blank=True)
    modalidade = models.CharField(max_length=25, choices=MODALIDADES)
    objeto = models.TextField()
    is_srp = models.BooleanField(default=False, help_text="Conduzido por Sistema de Registro de Preços")
    status = models.CharField(max_length=20, choices=STATUS, default="em_preparacao")
    data_publicacao = models.DateField(null=True, blank=True)
    data_homologacao = models.DateField(null=True, blank=True)
    pncp_id = models.CharField(max_length=100, blank=True)
    publicado_pncp = models.BooleanField(default=False)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("orgao", "numero_processo", "ano")
        verbose_name = "Processo Licitatório"

    def __str__(self):
        return f"{self.numero_processo}/{self.ano}"
