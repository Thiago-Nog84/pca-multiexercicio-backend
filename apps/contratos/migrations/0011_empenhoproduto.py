# Generated manually (mesmo padrão do makemigrations) em 2026-07-30 — sandbox
# sem acesso a Django/DB, ver docs/nota_empenho_fonte_de_verdade.md §2.

import django.db.models.deletion
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contratos', '0010_paginacontratosmppi'),
    ]

    operations = [
        migrations.CreateModel(
            name='EmpenhoProduto',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ordem', models.PositiveSmallIntegerField(default=0, help_text='Posição do item dentro do bloco produtos[] da NE')),
                ('nome_produto', models.CharField(blank=True, help_text='nomeProdutoGenerico da API SIAFE', max_length=255)),
                ('descricao_produto', models.TextField(blank=True, help_text='descricaoProdutoGenerico da API SIAFE')),
                ('unidade_fornecimento', models.CharField(blank=True, help_text='unidadeFornecimentoGenerico da API SIAFE', max_length=30)),
                ('quantidade', models.DecimalField(decimal_places=4, default=Decimal('0'), max_digits=14)),
                ('preco_unitario', models.DecimalField(decimal_places=4, default=Decimal('0'), max_digits=16)),
                ('preco_total', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=16)),
                ('criado_em', models.DateTimeField(auto_now_add=True)),
                ('atualizado_em', models.DateTimeField(auto_now=True)),
                ('empenho', models.ForeignKey(help_text='Nota de Empenho da qual este item faz parte', on_delete=django.db.models.deletion.CASCADE, related_name='produtos', to='contratos.empenho')),
            ],
            options={
                'verbose_name': 'Item da Nota de Empenho',
                'verbose_name_plural': 'Itens da Nota de Empenho',
                'ordering': ['empenho', 'ordem'],
                'unique_together': {('empenho', 'ordem')},
            },
        ),
    ]
