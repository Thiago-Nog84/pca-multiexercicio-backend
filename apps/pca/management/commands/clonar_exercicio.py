"""
Clona TODOS os itens de um PCA (origem) para um PCA de destino.

Itens ativos  -> status="nao_iniciado"  (prontos para validacao pelo setor)
Itens suspensos -> status="suspenso", tipo_suspensao preservado

Uso:
    python manage.py clonar_exercicio --de 2026 --para 2027
    python manage.py clonar_exercicio --de 2026 --para 2027 --dry-run
    python manage.py clonar_exercicio --de 2026 --para 2027 --so-ativos
    python manage.py clonar_exercicio --de 2026 --para 2027 --forcar   # re-cria mesmo duplicados
"""
import datetime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.models import Orgao
from apps.pca.models import DocumentoFormalizacaoDemanda, ItemPCA, PlanoContratacaoAnual


User = get_user_model()

CAMPOS_ITEM = [
    "item_catalogo", "classificacao_continuidade", "categoria",
    "codigo_catmat_catser", "descricao", "unidade_fornecimento",
    "quantidade_estimada", "valor_unitario_estimado", "valor_total_estimado",
    "tipo_demanda", "modalidade", "normativo", "unidade_orcamentaria",
    "is_srp", "numero_lote_pca", "tipo_suspensao",
]


class Command(BaseCommand):
    help = "Clona todos os itens de um exercicio PCA para outro"

    def add_arguments(self, parser):
        parser.add_argument("--de", type=int, required=True, help="Exercicio de origem (ex: 2026)")
        parser.add_argument("--para", type=int, required=True, help="Exercicio de destino (ex: 2027)")
        parser.add_argument("--dry-run", action="store_true", help="Simula sem gravar")
        parser.add_argument("--so-ativos", action="store_true", help="Exclui itens suspensos")
        parser.add_argument("--forcar", action="store_true", help="Re-cria mesmo que ja exista origem_item no destino")

    def handle(self, *args, **options):
        ano_de = options["de"]
        ano_para = options["para"]
        dry_run = options["dry_run"]
        so_ativos = options["so_ativos"]
        forcar = options["forcar"]

        # --- PCA origem ---
        try:
            pca_origem = PlanoContratacaoAnual.objects.get(exercicio=ano_de)
        except PlanoContratacaoAnual.DoesNotExist:
            raise CommandError(f"PCA {ano_de} nao encontrado no banco de dados.")

        # --- PCA destino: cria se nao existir ---
        orgao = pca_origem.orgao
        pca_destino, criado_pca = PlanoContratacaoAnual.objects.get_or_create(
            orgao=orgao,
            exercicio=ano_para,
            defaults={"status": "coleta"},
        )
        if criado_pca:
            self.stdout.write(self.style.SUCCESS(f"PCA {ano_para} criado automaticamente."))
        else:
            self.stdout.write(f"PCA {ano_para} ja existe (status: {pca_destino.get_status_display()}).")

        # --- Itens a clonar ---
        qs = ItemPCA.objects.filter(dfd__pca=pca_origem).select_related(
            "dfd", "dfd__unidade", "item_catalogo"
        ).order_by("dfd__unidade__sigla", "numero_item")

        if so_ativos:
            qs = qs.exclude(status="suspenso")
            self.stdout.write("Modo --so-ativos: excluindo itens suspensos.")

        total_origem = qs.count()
        self.stdout.write(f"Itens no PCA {ano_de}: {total_origem}")

        criados = ignorados = erros = 0

        with transaction.atomic():
            # Agrupa por unidade para reusar/criar um DFD por setor
            dfds_cache = {}

            for item in qs:
                unidade = item.dfd.unidade

                # Verifica duplicata
                if not forcar:
                    ja_existe = ItemPCA.objects.filter(
                        origem_item=item, dfd__pca=pca_destino
                    ).exists()
                    if ja_existe:
                        ignorados += 1
                        continue

                # DFD de destino (um por unidade)
                if unidade.pk not in dfds_cache:
                    dfd_num = f"DFD-{ano_para}-{unidade.sigla}"
                    dfd_destino, _ = DocumentoFormalizacaoDemanda.objects.get_or_create(
                        pca=pca_destino,
                        unidade=unidade,
                        numero_dfd=dfd_num,
                        defaults={
                            "descricao_objeto": (
                                f"Demandas de {unidade.sigla} — PCA {ano_para} "
                                f"(importadas do PCA {ano_de})"
                            ),
                            "justificativa": (
                                f"Clonagem automatica das demandas do PCA {ano_de} "
                                f"para o exercicio {ano_para}. "
                                f"Setor requisitante deve validar cada item."
                            ),
                            "prazo_necessidade": datetime.date(ano_para, 12, 31),
                            "grau_prioridade": item.dfd.grau_prioridade,
                            "status": "rascunho",
                        },
                    )
                    dfds_cache[unidade.pk] = dfd_destino
                else:
                    dfd_destino = dfds_cache[unidade.pk]

                # Numero sequencial no DFD destino
                from django.db.models import Max
                ultimo = (
                    ItemPCA.objects.filter(dfd=dfd_destino)
                    .aggregate(m=Max("numero_item"))["m"]
                ) or 0

                # Status no destino
                if item.status == "suspenso":
                    status_destino = "suspenso"
                else:
                    status_destino = "pendente_validacao"

                kwargs = {field: getattr(item, field) for field in CAMPOS_ITEM}
                kwargs.update({
                    "dfd": dfd_destino,
                    "numero_item": ultimo + 1,
                    "origem_item": item,
                    "status": status_destino,
                    "observacoes": (
                        f"Importado do PCA {ano_de} ({item.codigo_pca}). "
                        f"Aguardando validacao do setor requisitante."
                    ),
                    "data_pretendida_conclusao": None,
                    "data_envio_pgea": None,
                    "data_finalizacao_licitacao": None,
                    "data_conclusao_efetiva": None,
                    "valor_empenhado": 0,
                    "numero_lote_pca": item.numero_lote_pca,
                })

                label = f"  {'[DRY] ' if dry_run else ''}{item.codigo_pca} ({unidade.sigla}) -> {status_destino}"
                self.stdout.write(label)

                if not dry_run:
                    try:
                        ItemPCA.objects.create(**kwargs)
                        criados += 1
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f"    ERRO: {e}"))
                        erros += 1
                else:
                    criados += 1

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"Concluido: {criados} clonados, {ignorados} ja existiam, {erros} erros."
        ))
        if dry_run:
            self.stdout.write(self.style.WARNING("Modo DRY-RUN: nada foi gravado."))
        else:
            self.stdout.write(
                f"Execute 'python manage.py migrate' se necessario, "
                f"depois acesse /pca/?exercicio={ano_para}"
            )
