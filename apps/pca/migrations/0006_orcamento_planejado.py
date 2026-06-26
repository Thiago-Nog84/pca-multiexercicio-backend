from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
        ("pca", "0005_itemcatalogo_itempca_continuidade"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="OrcamentoPlanejado",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("valor_pgj",   models.DecimalField(decimal_places=2, default=0, max_digits=16, verbose_name="Teto PGJ")),
                ("valor_fmmp",  models.DecimalField(decimal_places=2, default=0, max_digits=16, verbose_name="Teto FMMP")),
                ("valor_fepdc", models.DecimalField(decimal_places=2, default=0, max_digits=16, verbose_name="Teto FEPDC")),
                ("trava_ativa", models.BooleanField(default=False, verbose_name="Trava ativa")),
                ("atualizado_em", models.DateTimeField(auto_now=True)),
                (
                    "pca",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="orcamentos",
                        to="pca.planocontratacaoanual",
                        verbose_name="PCA",
                    ),
                ),
                (
                    "unidade",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="orcamentos",
                        to="core.unidaderequisitante",
                        verbose_name="Setor requisitante",
                    ),
                ),
                (
                    "atualizado_por",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="orcamentos_atualizados",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Orcamento Planejado",
                "verbose_name_plural": "Orcamentos Planejados",
                "ordering": ["pca", "unidade"],
                "unique_together": {("pca", "unidade")},
            },
        ),
    ]
