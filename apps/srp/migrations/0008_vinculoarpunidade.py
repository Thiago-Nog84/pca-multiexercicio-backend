# Generated migration — VinculoARPUnidade
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("srp", "0007_ataregistroprecos_link_ata_pncp"),
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="VinculoARPUnidade",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("papel", models.CharField(
                    choices=[("gestora", "Gestora — responsável pela ata"), ("demandante", "Demandante — usuária da ata")],
                    default="gestora", max_length=15,
                )),
                ("observacoes", models.TextField(blank=True)),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("arp", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="vinculos_unidades",
                    to="srp.ataregistroprecos",
                )),
                ("unidade", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="vinculos_arp",
                    to="core.unidaderequisitante",
                )),
            ],
            options={
                "verbose_name": "Vínculo ARP × Unidade",
                "verbose_name_plural": "Vínculos ARP × Unidades",
                "ordering": ["papel", "unidade__sigla"],
                "unique_together": {("arp", "unidade")},
            },
        ),
    ]
