"""
Models do app SIAFE.
SiafeLogConsulta: auditoria de cada chamada a API externa.
"""
from django.conf import settings
from django.db import models


class SiafeLogConsulta(models.Model):
    ENDPOINT_CHOICES = [
        ("nota_empenho",        "Nota de Empenho"),
        ("saldo_orcamentario",  "Saldo Orcamentario"),
        ("saldo_contabil",      "Saldo Contabil"),
        ("acoes",               "Acoes de Governo"),
        ("natureza_despesa",    "Natureza de Despesa"),
        ("credores",            "Credores"),
        ("programas",           "Programas"),
        ("contratos_convenios", "Contratos e Convenios"),
        ("exec_orcamentaria",   "Execucao Orcamentaria"),
        ("exec_financeira",     "Execucao Financeira"),
        ("fatos_contratos",     "Fatos de Contratos"),
        ("planejamento_loa",    "Planejamento LOA"),
        ("outro",               "Outro"),
    ]

    endpoint = models.CharField(max_length=30, choices=ENDPOINT_CHOICES, default="outro")
    parametros = models.JSONField(default=dict, help_text="Parametros enviados na consulta")
    status_http = models.PositiveSmallIntegerField(null=True, blank=True)
    sucesso = models.BooleanField(default=True)
    erro_detalhe = models.TextField(blank=True)
    tempo_resposta_ms = models.PositiveIntegerField(null=True, blank=True)
    consultado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="siafe_consultas",
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Log de Consulta SIAFE"
        verbose_name_plural = "Logs de Consultas SIAFE"
        ordering = ["-criado_em"]

    def __str__(self):
        ok = "OK" if self.sucesso else "ERRO"
        return "[{}] {} - {}".format(ok, self.get_endpoint_display(), self.criado_em.strftime("%d/%m/%Y %H:%M"))
