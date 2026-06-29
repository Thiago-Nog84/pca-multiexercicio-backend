"""
Management command: vincular_arps_unidades
==========================================
Popula a tabela VinculoARPUnidade a partir de heurísticas sobre dados já
existentes no banco:

Fonte 1 — ContratacaoDecorrente.unidade_requisitante
    Uma unidade que emitiu pedidos de fornecimento a partir de uma ARP é
    "demandante" desta ARP.

Fonte 2 — Contrato.arp_origem + Contrato.unidade_requisitante
    Um contrato cujo arp_origem está preenchido vincula a unidade requisitante
    do contrato como "demandante" da ARP.

Fonte 3 — ARPExterna.unidade_requisitante
    ARPs externas (caronas recebidas) vinculam a unidade como "demandante"
    da ARP externa. (Informativo — não cria VinculoARPUnidade para ARPExterna.)

Observação sobre "gestora":
    Não é possível inferir automaticamente qual unidade é gestora de uma ARP
    apenas pelos contratos — isto deve ser registrado manualmente no Admin ou
    via flag --gestora-sigla. Se fornecido, a unidade informada será marcada
    como "gestora" de TODAS as ARPs que não tenham gestora definida.

Uso:
    python manage.py vincular_arps_unidades
    python manage.py vincular_arps_unidades --dry-run
    python manage.py vincular_arps_unidades --dry-run --relatorio
    python manage.py vincular_arps_unidades --gestora-sigla CLC
    python manage.py vincular_arps_unidades --sobrescrever
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Cria VinculoARPUnidade a partir de ContratacaoDecorrente e Contrato.arp_origem"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra o que seria feito sem persistir nada.",
        )
        parser.add_argument(
            "--relatorio",
            action="store_true",
            help="Exibe relatório detalhado por ARP.",
        )
        parser.add_argument(
            "--gestora-sigla",
            dest="gestora_sigla",
            default=None,
            help=(
                "Sigla da unidade a ser registrada como GESTORA "
                "para ARPs sem gestora definida (ex: CLC)."
            ),
        )
        parser.add_argument(
            "--sobrescrever",
            action="store_true",
            help="Recria vínculos mesmo que já existam (update observacoes).",
        )

    def handle(self, *args, **options):
        from apps.srp.models import AtaRegistroPrecos, ContratacaoDecorrente, VinculoARPUnidade
        from apps.contratos.models import Contrato

        dry_run = options["dry_run"]
        relatorio = options["relatorio"]
        gestora_sigla = options.get("gestora_sigla")
        sobrescrever = options["sobrescrever"]

        if dry_run:
            self.stdout.write(self.style.WARNING("*** MODO DRY-RUN — nenhuma alteração será salva ***\n"))

        # Resolve unidade gestora opcional
        unidade_gestora = None
        if gestora_sigla:
            from apps.core.models import UnidadeRequisitante
            try:
                unidade_gestora = UnidadeRequisitante.objects.get(sigla=gestora_sigla.upper())
            except UnidadeRequisitante.DoesNotExist:
                raise CommandError(f"Unidade '{gestora_sigla}' não encontrada.")
            self.stdout.write(f"Gestora padrão: {unidade_gestora.sigla} — {unidade_gestora.nome}\n")

        # Coleta mapeamentos ARP → {unidade_pk: papel}
        # estrutura: { arp_pk: { unidade_pk: "demandante"|"gestora" } }
        mapa: dict[int, dict[int, str]] = {}

        def _adicionar(arp_pk, unidade, papel):
            if unidade is None:
                return
            mapa.setdefault(arp_pk, {})
            # Gestora tem prioridade; não rebaixa para demandante
            existente = mapa[arp_pk].get(unidade.pk)
            if existente == "gestora":
                return
            mapa[arp_pk][unidade.pk] = papel

        # --- Fonte 1: ContratacaoDecorrente ---
        contratacoes = (
            ContratacaoDecorrente.objects
            .filter(unidade_requisitante__isnull=False)
            .select_related("arp", "unidade_requisitante")
        )
        cnt_fonte1 = 0
        for c in contratacoes:
            _adicionar(c.arp_id, c.unidade_requisitante, "demandante")
            cnt_fonte1 += 1

        self.stdout.write(f"Fonte 1 (ContratacaoDecorrente): {cnt_fonte1} registros analisados")

        # --- Fonte 2: Contrato.arp_origem ---
        contratos = (
            Contrato.objects
            .filter(arp_origem__isnull=False, unidade_requisitante__isnull=False)
            .select_related("arp_origem", "unidade_requisitante")
        )
        cnt_fonte2 = 0
        for c in contratos:
            _adicionar(c.arp_origem_id, c.unidade_requisitante, "demandante")
            cnt_fonte2 += 1

        self.stdout.write(f"Fonte 2 (Contrato.arp_origem):   {cnt_fonte2} registros analisados")

        # --- Fonte 3: gestora padrão ---
        if unidade_gestora:
            arps_sem_gestora = AtaRegistroPrecos.objects.exclude(
                vinculos_unidades__papel="gestora"
            ).values_list("pk", flat=True)
            for arp_pk in arps_sem_gestora:
                _adicionar(arp_pk, unidade_gestora, "gestora")

        # --- Relatório do que foi encontrado ---
        total_vinculos = sum(len(v) for v in mapa.values())
        self.stdout.write(f"\nVínculos inferidos: {total_vinculos} em {len(mapa)} ARPs\n")

        if relatorio:
            arps_map = {
                a.pk: a
                for a in AtaRegistroPrecos.objects.filter(pk__in=mapa.keys())
            }
            from apps.core.models import UnidadeRequisitante
            unidades_map = {
                u.pk: u
                for u in UnidadeRequisitante.objects.filter(
                    pk__in={upk for v in mapa.values() for upk in v}
                )
            }
            for arp_pk, unidades in sorted(mapa.items(), key=lambda x: x[0]):
                arp = arps_map.get(arp_pk)
                label = f"ARP {arp.numero_arp}" if arp else f"ARP pk={arp_pk}"
                self.stdout.write(f"\n  {label}")
                for upk, papel in unidades.items():
                    u = unidades_map.get(upk)
                    sigla = u.sigla if u else f"pk={upk}"
                    self.stdout.write(f"    → {sigla:12s}  {papel}")

        if dry_run:
            self.stdout.write(self.style.WARNING("\nDry-run concluído. Nenhum dado salvo."))
            return

        # --- Persistência ---
        criados = 0
        atualizados = 0
        ignorados = 0

        with transaction.atomic():
            for arp_pk, unidades in mapa.items():
                for unidade_pk, papel in unidades.items():
                    existente = VinculoARPUnidade.objects.filter(
                        arp_id=arp_pk, unidade_id=unidade_pk
                    ).first()

                    if existente:
                        if sobrescrever:
                            if existente.papel != papel:
                                existente.papel = papel
                                existente.observacoes = (
                                    (existente.observacoes or "")
                                    + " [atualizado automaticamente]"
                                ).strip()
                                existente.save(update_fields=["papel", "observacoes"])
                                atualizados += 1
                            else:
                                ignorados += 1
                        else:
                            ignorados += 1
                    else:
                        VinculoARPUnidade.objects.create(
                            arp_id=arp_pk,
                            unidade_id=unidade_pk,
                            papel=papel,
                            observacoes="Criado automaticamente por vincular_arps_unidades",
                        )
                        criados += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"\nConcluído: {criados} criado(s), {atualizados} atualizado(s), {ignorados} ignorado(s)."
            )
        )
