from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("srp", "0004_add_contrato_empenho_comprasnet"),
    ]

    operations = [
        migrations.AddField(
            model_name="ataregistroprecos",
            name="prorrogada",
            field=models.BooleanField(
                default=False,
                verbose_name="Prorrogada",
                help_text="Vigência prorrogada por Termo Aditivo",
            ),
        ),
        migrations.AddField(
            model_name="ataregistroprecos",
            name="data_fim_vigencia_original",
            field=models.DateField(
                null=True,
                blank=True,
                verbose_name="Fim vigência original",
                help_text="Data fim original antes da prorrogação",
            ),
        ),
        migrations.AddField(
            model_name="ataregistroprecos",
            name="quantitativos_renovados",
            field=models.BooleanField(
                default=False,
                verbose_name="Quantitativos renovados",
                help_text="Se True, os quantitativos foram renovados junto com a prorrogação",
            ),
        ),
        migrations.AddField(
            model_name="ataregistroprecos",
            name="data_prorrogacao",
            field=models.DateField(
                null=True,
                blank=True,
                verbose_name="Data da prorrogação",
                help_text="Data de publicação da prorrogação no PNCP",
            ),
        ),
    ]
