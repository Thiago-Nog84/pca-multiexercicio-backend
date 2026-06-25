from decimal import Decimal
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("srp", "0005_arp_prorrogacao"),
    ]

    operations = [
        migrations.CreateModel(
            name="ContratoARP",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("arp", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="contratos_arp",
                    to="srp.ataregistroprecos",
                )),
                ("numero_contrato", models.CharField(max_length=100, help_text="Número do contrato (ex: 00005/2024)")),
                ("contratado_cnpj", models.CharField(blank=True, max_length=20)),
                ("contratado_nome", models.CharField(blank=True, max_length=255)),
                ("uasg_contratante", models.CharField(
                    blank=True, max_length=10,
                    help_text="UASG que firmou o contrato (pode diferir do gerenciador em caronas)",
                )),
                ("nome_uasg_contratante", models.CharField(blank=True, max_length=255)),
                ("data_assinatura", models.DateField(blank=True, null=True)),
                ("data_inicio_vigencia", models.DateField(blank=True, null=True)),
                ("data_fim_vigencia", models.DateField(blank=True, null=True)),
                ("valor_total", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=18)),
                ("numero_pncp", models.CharField(blank=True, max_length=100)),
                ("is_carona", models.BooleanField(
                    default=False,
                    help_text="True quando o contratante é diferente do órgão gerenciador da ARP",
                )),
                ("importado_em", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Contrato decorrente de ARP",
                "verbose_name_plural": "Contratos decorrentes de ARP",
                "ordering": ["-data_assinatura"],
                "unique_together": {("arp", "numero_contrato", "uasg_contratante")},
            },
        ),
        migrations.CreateModel(
            name="ItemContratoARP",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("contrato", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="itens",
                    to="srp.contratoarp",
                )),
                ("item_arp", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="itens_contratos",
                    to="srp.itemarp",
                    help_text="Item da ARP ao qual este item de contrato corresponde",
                )),
                ("numero_item", models.PositiveIntegerField()),
                ("descricao", models.TextField(blank=True)),
                ("unidade", models.CharField(blank=True, max_length=30)),
                ("quantidade_contratada", models.DecimalField(decimal_places=4, default=Decimal("0"), max_digits=14)),
                ("valor_unitario", models.DecimalField(decimal_places=4, default=Decimal("0"), max_digits=14)),
                ("valor_total", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=18)),
            ],
            options={
                "verbose_name": "Item de contrato (ARP)",
                "verbose_name_plural": "Itens de contrato (ARP)",
                "ordering": ["numero_item"],
                "unique_together": {("contrato", "numero_item")},
            },
        ),
    ]
