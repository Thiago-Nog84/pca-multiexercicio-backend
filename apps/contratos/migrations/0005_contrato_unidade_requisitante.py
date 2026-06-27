# Generated manually on 2026-06-27

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("contratos", "0004_contrato_codigo_siafe"),
        ("core", "0003_add_conint_unidade"),
    ]

    operations = [
        migrations.AddField(
            model_name="contrato",
            name="unidade_requisitante",
            field=models.ForeignKey(
                blank=True,
                help_text="Unidade/setor que originou a demanda do contrato",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="contratos",
                to="core.unidaderequisitante",
            ),
        ),
    ]
