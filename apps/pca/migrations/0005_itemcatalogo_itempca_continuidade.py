"""
Migration 0005: ItemCatalogo + campos de continuidade e linhagem no ItemPCA.

Adds:
  - pca.ItemCatalogo   (novo model — catálogo institucional Ato PGJ 1.415/2024)
  - ItemPCA.item_catalogo         (FK → ItemCatalogo, nullable)
  - ItemPCA.classificacao_continuidade  (CharField, default='eventual')
  - ItemPCA.origem_item           (FK → self, nullable — linhagem multiexercício)
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pca", "0004_itempca_numero_lote_pca"),
    ]

    operations = [
        # ── 1. Cria ItemCatalogo ──────────────────────────────────────────────
        migrations.CreateModel(
            name="ItemCatalogo",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("codigo_catalogo", models.CharField(
                    max_length=20,
                    unique=True,
                    help_text="Código no formato CONT-FORN-001, CONT-SERV-001, CONT-MDO-001",
                )),
                ("descricao_padrao", models.CharField(max_length=300)),
                ("categoria", models.CharField(
                    max_length=20,
                    choices=[
                        ("material",    "Material (CATMAT)"),
                        ("servico",     "Serviço (CATSER)"),
                        ("obras",       "Obras e Serviços de Engenharia"),
                        ("solucao_ti",  "Solução de TIC (Res. CNMP 283/2024)"),
                        ("publicidade", "Publicidade (Dec. 21.813/2023)"),
                    ],
                )),
                ("classificacao", models.CharField(
                    max_length=30,
                    db_index=True,
                    default="eventual",
                    choices=[
                        ("continuo_fornecimento", "Fornecimento contínuo (Art. 3º — Ato PGJ 1.415/2024)"),
                        ("continuo_servico",      "Serviço contínuo (Art. 4º — Ato PGJ 1.415/2024)"),
                        ("continuo_servico_mdo",  "Serviço contínuo c/ ded. exclusiva de MO (Art. 4º §1º — Ato PGJ 1.415/2024)"),
                        ("eventual",              "Eventual / pontual"),
                    ],
                )),
                ("base_normativa", models.CharField(max_length=150, blank=True, help_text="Ex: Art. 3º, I — Ato PGJ 1.415/2024")),
                ("codigo_catmat_catser", models.CharField(max_length=20, blank=True)),
                ("unidade_medida_padrao", models.CharField(max_length=30, blank=True)),
                ("modalidade_sugerida", models.CharField(
                    max_length=20,
                    blank=True,
                    choices=[
                        ("pregao_eletronico", "Pregão Eletrônico"),
                        ("concorrencia",      "Concorrência"),
                        ("dispensa",          "Contratação Direta — Dispensa"),
                        ("inexigibilidade",   "Contratação Direta — Inexigibilidade"),
                    ],
                )),
                ("ativo", models.BooleanField(default=True)),
                ("criado_em",    models.DateTimeField(auto_now_add=True)),
                ("atualizado_em", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Item do Catálogo",
                "verbose_name_plural": "Catálogo de Itens",
                "ordering": ["classificacao", "descricao_padrao"],
            },
        ),

        # ── 2. Novos campos no ItemPCA ────────────────────────────────────────
        migrations.AddField(
            model_name="itempca",
            name="classificacao_continuidade",
            field=models.CharField(
                max_length=30,
                default="eventual",
                choices=[
                    ("continuo_fornecimento", "Fornecimento contínuo (Art. 3º — Ato PGJ 1.415/2024)"),
                    ("continuo_servico",      "Serviço contínuo (Art. 4º — Ato PGJ 1.415/2024)"),
                    ("continuo_servico_mdo",  "Serviço contínuo c/ ded. exclusiva de MO (Art. 4º §1º — Ato PGJ 1.415/2024)"),
                    ("eventual",              "Eventual / pontual"),
                ],
                help_text="Classificação conforme Ato PGJ 1.415/2024",
            ),
        ),
        migrations.AddField(
            model_name="itempca",
            name="item_catalogo",
            field=models.ForeignKey(
                to="pca.ItemCatalogo",
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="itens_pca",
                help_text=(
                    "Item do catálogo institucional que originou esta demanda. "
                    "Pré-preenche descrição, categoria e classificação de continuidade."
                ),
            ),
        ),
        migrations.AddField(
            model_name="itempca",
            name="origem_item",
            field=models.ForeignKey(
                to="pca.ItemPCA",
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="renovacoes",
                help_text=(
                    "Item do exercício anterior que originou esta renovação/continuidade. "
                    "Permite rastrear a evolução da despesa ao longo dos anos."
                ),
            ),
        ),
    ]
