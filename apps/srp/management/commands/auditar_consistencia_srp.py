"""
Management command: auditar_consistencia_srp
===============================================
Bateria de verificações de consistência entre ARPs, itens e contratos.
SOMENTE LEITURA — nunca altera nada, só reporta.

Nasceu da sessão de 2026-07-29, em que consultas ad-hoc encontraram, de uma
vez: 1 substituição de detentor por cadastro de reserva não registrada,
1 contrato de dispensa pendurado numa ARP e 1 registro duplicado com número
trocado. Consolidado aqui para poder rodar periodicamente.

Uso:
  python manage.py auditar_consistencia_srp
  python manage.py auditar_consistencia_srp --checagem cnpj
  python manage.py auditar_consistencia_srp --csv auditoria.csv
"""

import csv
import re
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.contratos.models import Contrato
from apps.srp.models import AtaRegistroPrecos, ContratacaoDecorrente, ItemARP


def _digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


class Command(BaseCommand):
    help = "Audita consistência entre ARPs, itens e contratos (somente leitura)"

    CHECAGENS = [
        "cnpj", "duplicados", "saldo_negativo", "rescindidos",
        "datas", "valor_zero", "sem_pncp", "vigencia", "fracao",
    ]

    def add_arguments(self, parser):
        parser.add_argument(
            "--checagem", choices=self.CHECAGENS,
            help="Roda apenas uma das checagens (padrão: todas)",
        )
        parser.add_argument(
            "--csv", dest="csv_path",
            help="Grava os achados num CSV além de exibir na tela",
        )

    def handle(self, *args, **options):
        so = options.get("checagem")
        achados = []  # (checagem, severidade, identificador, detalhe)

        def add(check, sev, ident, detalhe):
            achados.append((check, sev, ident, detalhe))

        # ------------------------------------------------------------------
        # 1. CNPJ do contrato ≠ CNPJ do detentor da ata
        # ------------------------------------------------------------------
        if not so or so == "cnpj":
            self.stdout.write(self.style.MIGRATE_HEADING(
                "\n[cnpj] Contratos cujo CNPJ difere do detentor da ARP de origem"
            ))
            n = 0
            for c in Contrato.objects.exclude(arp_origem=None).select_related("arp_origem"):
                arp = c.arp_origem
                cnpj_arp, cnpj_c = _digitos(arp.fornecedor_cnpj_cpf), _digitos(c.contratado_cnpj_cpf)
                if not cnpj_arp or not cnpj_c or cnpj_arp == cnpj_c:
                    continue
                # Esperado quando houve troca de detentor: contratos assinados
                # pelo detentor ORIGINAL continuam válidos na ata.
                if getattr(arp, "substituido_por_cadastro_reserva", False):
                    cnpj_orig = _digitos(getattr(arp, "fornecedor_original_cnpj_cpf", ""))
                    if cnpj_orig and cnpj_c == cnpj_orig:
                        continue  # é o vencedor original — legítimo, não reportar
                n += 1
                detalhe = (
                    f"ARP {arp.numero_arp} detentor={arp.fornecedor_razao_social[:30]} ({cnpj_arp}) "
                    f"× contrato {(c.contratado_razao_social or '')[:30]} ({cnpj_c})"
                )
                add("cnpj", "ALTO", c.numero_contrato, detalhe)
                self.stdout.write(f"  ⚠ {c.numero_contrato}: {detalhe}")
            if not n:
                self.stdout.write("  nenhum")

        # ------------------------------------------------------------------
        # 2. Contratos duplicados (mesmo CNPJ + mesmo valor, números diferentes)
        # ------------------------------------------------------------------
        if not so or so == "duplicados":
            self.stdout.write(self.style.MIGRATE_HEADING(
                "\n[duplicados] Possíveis registros duplicados (mesmo CNPJ + mesmo valor)"
            ))
            grupos = {}
            for c in Contrato.objects.all():
                cnpj = _digitos(c.contratado_cnpj_cpf)
                if not cnpj or not c.valor_inicial:
                    continue
                grupos.setdefault((cnpj, c.valor_inicial), []).append(c)
            n = 0
            for (cnpj, valor), lista in sorted(grupos.items()):
                if len(lista) < 2:
                    continue
                n += 1
                nums = ", ".join(f"{x.numero_contrato} (sei={x.numero_sei or '—'})" for x in lista)
                detalhe = f"CNPJ {cnpj} · R$ {valor:,.2f} → {nums}"
                add("duplicados", "ALTO", nums, detalhe)
                self.stdout.write(f"  ⚠ {detalhe}")
            if not n:
                self.stdout.write("  nenhum")

        # ------------------------------------------------------------------
        # 3. Itens com saldo negativo (contratado + carona > registrado)
        # ------------------------------------------------------------------
        if not so or so == "saldo_negativo":
            self.stdout.write(self.style.MIGRATE_HEADING(
                "\n[saldo_negativo] Itens de ARP consumidos além do registrado"
            ))
            n = 0
            for i in ItemARP.objects.select_related("arp"):
                consumido = (i.quantidade_contratada or 0) + (i.quantidade_cedida_carona or 0)
                if consumido > (i.quantidade_registrada or 0) + Decimal("0.0001"):
                    n += 1
                    detalhe = (
                        f"ARP {i.arp.numero_arp} item {i.numero_item}: "
                        f"registrado={i.quantidade_registrada} consumido={consumido}"
                    )
                    add("saldo_negativo", "ALTO", f"{i.arp.numero_arp}#{i.numero_item}", detalhe)
                    self.stdout.write(f"  ⚠ {detalhe}")
            if not n:
                self.stdout.write("  nenhum")

        # ------------------------------------------------------------------
        # 4. Contratos rescindidos que ainda geram contratação decorrente
        # ------------------------------------------------------------------
        if not so or so == "rescindidos":
            self.stdout.write(self.style.MIGRATE_HEADING(
                "\n[rescindidos] Contratos rescindidos ainda consumindo saldo de ARP"
            ))
            numeros = set(
                Contrato.objects.filter(status="rescindido").values_list("numero_contrato", flat=True)
            )
            n = 0
            if numeros:
                for cd in ContratacaoDecorrente.objects.filter(numero_pedido__in=numeros).select_related("arp"):
                    n += 1
                    detalhe = (
                        f"ARP {cd.arp.numero_arp}: contratação {cd.numero_pedido} "
                        f"(qtd={cd.quantidade}) vem de contrato RESCINDIDO — rodar conciliar_dashboard_srp"
                    )
                    add("rescindidos", "MEDIO", cd.numero_pedido, detalhe)
                    self.stdout.write(f"  ⚠ {detalhe}")
            if not n:
                self.stdout.write("  nenhum")

        # ------------------------------------------------------------------
        # 5. Datas suspeitas (placeholder 01/01 ou vigência antes da assinatura)
        # ------------------------------------------------------------------
        if not so or so == "datas":
            self.stdout.write(self.style.MIGRATE_HEADING(
                "\n[datas] Datas provavelmente placeholder ou incoerentes"
            ))
            n = 0
            for c in Contrato.objects.all():
                problemas = []
                ini, ass = c.data_inicio_vigencia, c.data_assinatura
                # 01/01 é o fallback usado por importar_contratos_siafe_api
                if ini and ini.month == 1 and ini.day == 1:
                    problemas.append(f"início 01/01 (fallback do import SIAFE?): {ini}")
                if ass and ass.month == 1 and ass.day == 1:
                    problemas.append(f"assinatura 01/01 (fallback): {ass}")
                if ini and ass and ini < ass:
                    problemas.append(f"vigência ({ini}) começa antes da assinatura ({ass})")
                if c.data_fim_vigencia and ini and c.data_fim_vigencia < ini:
                    problemas.append(f"fim ({c.data_fim_vigencia}) antes do início ({ini})")
                if problemas:
                    n += 1
                    detalhe = "; ".join(problemas)
                    add("datas", "BAIXO", c.numero_contrato, detalhe)
                    self.stdout.write(f"  · {c.numero_contrato}: {detalhe}")
            if not n:
                self.stdout.write("  nenhum")

        # ------------------------------------------------------------------
        # 6. Contratos vigentes com valor zerado
        # ------------------------------------------------------------------
        if not so or so == "valor_zero":
            self.stdout.write(self.style.MIGRATE_HEADING(
                "\n[valor_zero] Contratos vigentes com valor_inicial zerado"
            ))
            qs = Contrato.objects.filter(status="vigente", valor_inicial__lte=0)
            for c in qs:
                detalhe = f"{(c.contratado_razao_social or '')[:40]} · {(c.objeto or '')[:50]}"
                add("valor_zero", "MEDIO", c.numero_contrato, detalhe)
                self.stdout.write(f"  ⚠ {c.numero_contrato}: {detalhe}")
            if not qs.exists():
                self.stdout.write("  nenhum")

        # ------------------------------------------------------------------
        # 7. ARPs sem número de controle PNCP (bloqueia automações)
        # ------------------------------------------------------------------
        if not so or so == "sem_pncp":
            self.stdout.write(self.style.MIGRATE_HEADING(
                "\n[sem_pncp] ARPs sem numero_controle_pncp_ata (impede busca automática no PNCP)"
            ))
            qs = AtaRegistroPrecos.objects.filter(numero_controle_pncp_ata="")
            for a in qs.order_by("numero_arp"):
                add("sem_pncp", "MEDIO", a.numero_arp, (a.objeto or "")[:60])
                self.stdout.write(f"  · {a.numero_arp}: {(a.objeto or '')[:60]}")
            if not qs.exists():
                self.stdout.write("  nenhuma")

        # ------------------------------------------------------------------
        # 8. ARPs vencidas ainda marcadas como vigentes
        # ------------------------------------------------------------------
        if not so or so == "vigencia":
            from datetime import date
            self.stdout.write(self.style.MIGRATE_HEADING(
                "\n[vigencia] ARPs com status 'vigente' mas vigência expirada"
            ))
            qs = AtaRegistroPrecos.objects.filter(status="vigente", data_fim_vigencia__lt=date.today())
            for a in qs.order_by("data_fim_vigencia"):
                detalhe = f"venceu em {a.data_fim_vigencia}"
                add("vigencia", "BAIXO", a.numero_arp, detalhe)
                self.stdout.write(f"  · {a.numero_arp}: {detalhe}")
            if not qs.exists():
                self.stdout.write("  nenhuma")

        # ------------------------------------------------------------------
        # 9. Quantidade fracionária em item de unidade física
        # ------------------------------------------------------------------
        if not so or so == "fracao":
            self.stdout.write(self.style.MIGRATE_HEADING(
                "\n[fracao] Contratações com quantidade fracionária em item de unidade física"
            ))
            n = 0
            for cd in ContratacaoDecorrente.objects.select_related("arp", "item_arp"):
                item = cd.item_arp
                if not item or cd.quantidade is None:
                    continue
                # "Lote de valor" (qtd registrada = 1, sem unidade) aceita fração
                eh_lote = (
                    not (item.unidade_fornecimento or "").strip()
                    and abs(float(item.quantidade_registrada) - 1.0) < 0.0001
                )
                if eh_lote:
                    continue
                if abs(float(cd.quantidade) - round(float(cd.quantidade))) > 0.0001:
                    n += 1
                    detalhe = (
                        f"ARP {cd.arp.numero_arp} item {item.numero_item} "
                        f"({(item.descricao or '')[:30]}): qtd={cd.quantidade} em '{cd.numero_pedido}'"
                    )
                    add("fracao", "MEDIO", cd.numero_pedido, detalhe)
                    self.stdout.write(f"  ⚠ {detalhe}")
            if not n:
                self.stdout.write("  nenhuma")

        # ------------------------------------------------------------------
        # Resumo + CSV
        # ------------------------------------------------------------------
        self.stdout.write("\n" + "=" * 70)
        if not achados:
            self.stdout.write(self.style.SUCCESS("Nenhuma inconsistência encontrada."))
            return

        por_sev = {}
        for check, sev, _ident, _d in achados:
            por_sev.setdefault(sev, []).append(check)
        resumo = " | ".join(f"{sev}: {len(v)}" for sev, v in sorted(por_sev.items()))
        self.stdout.write(self.style.WARNING(f"{len(achados)} achado(s) — {resumo}"))

        csv_path = options.get("csv_path")
        if csv_path:
            with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(["checagem", "severidade", "identificador", "detalhe"])
                w.writerows(achados)
            self.stdout.write(self.style.SUCCESS(f"CSV gravado em {csv_path}"))
