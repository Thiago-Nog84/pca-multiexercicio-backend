from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("pca", "0006_orcamento_planejado"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ConformidadeItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("termo_referencia_aprovado",   models.BooleanField(default=False)),
                ("pesquisa_mercado",            models.BooleanField(default=False)),
                ("pareceres_juridicos",         models.BooleanField(default=False)),
                ("mapa_comparativo",            models.BooleanField(default=False)),
                ("margem_calculo",              models.BooleanField(default=False)),
                ("pesquisa_precos",             models.BooleanField(default=False)),
                ("publicacao_edital",           models.BooleanField(default=False)),
                ("atas_certame",                models.BooleanField(default=False)),
                ("termo_homologacao",           models.BooleanField(default=False)),
                ("termo_adjudicacao",           models.BooleanField(default=False)),
                ("justificativa_vantajosidade", models.BooleanField(default=False)),
                ("documentacao_fornecedor",     models.BooleanField(default=False)),
                ("certidoes_habilitacao",       models.BooleanField(default=False)),
                ("assinatura_contrato",         models.BooleanField(default=False)),
                ("publicacao_contrato",         models.BooleanField(default=False)),
                ("declaracao_conformidade",     models.BooleanField(default=False)),
                ("atos_autorizacao",            models.BooleanField(default=False)),
                ("oficio_autorizacao_empenho",  models.BooleanField(default=False)),
                ("parecer_orcamentario_financeiro", models.BooleanField(default=False)),
                ("parecer_juridico_execucao",   models.BooleanField(default=False)),
                ("parecer_conint",              models.BooleanField(default=False)),
                ("documento_aceite",            models.BooleanField(default=False)),
                ("atualizar_certidoes",         models.BooleanField(default=False)),
                ("termo_aditivo_apostilamento", models.BooleanField(default=False)),
                ("publicacoes_execucao",        models.BooleanField(default=False)),
                ("observacao",                  models.TextField(blank=True)),
                ("atualizado_em",               models.DateTimeField(auto_now=True)),
                (
                    "item",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="conformidade",
                        to="pca.itempca",
                    ),
                ),
                (
                    "avaliado_por",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="conformidades_avaliadas",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Conformidade do Item",
                "verbose_name_plural": "Conformidade dos Itens",
            },
        ),
    ]
