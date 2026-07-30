"""
Management command: mesclar_contrato_duplicado
====================================================
Mescla um `Contrato` DUPLICADO (que na verdade é a mesma contratação real de
outro `Contrato` já existente, só que fatiada por NE de elemento de despesa
diferente no SIAFE) no contrato principal: move os `Empenho` do duplicado
para o principal, recalcula `valor_empenhado` dos dois, e apaga o duplicado.

Caso confirmado nesta sessão (2026-07-30), a partir do Termo de Contrato
120/2025-FMMP/PI (SEI 19.21.0016.0043009/2025-75, PDF fornecido pelo
usuário): o contrato tem 4 itens (equipamento + instalação + migração +
treinamento, R$1.526.000,00 total) pagos por DUAS notas de empenho citadas
na própria cláusula de dotação orçamentária — 2025NE00082 e 2025NE00083.
`2025NE00083` (equipamento, R$1.447.000,00) já importava certo sob o
contrato `120/2025` (pk=134, ARP 00048/2025). `2025NE00082` (migração
R$47.000 + treinamento R$32.000 = R$79.000,00 — bate exato) tinha um
`codContrato` diferente no SIAFE e por isso nunca bateu com o
`codigo_siafe` de 120/2025 — alguém cadastrou um Contrato avulso
`25018988` só para capturar essa NE, em vez de ligá-la ao contrato real.

LIMITAÇÃO ESTRUTURAL: o modelo `Contrato` só guarda um `codigo_siafe`. Um
contrato cujo SIAFE usa `codContrato` diferentes por elemento de despesa
(bens vs. serviços) não cabe inteiro em um único código — por isso a NE
migrada aqui não vai "resolver sozinha" numa reimportação futura; ela fica
estável no contrato principal porque `importar_empenhos_siafe` só cria
Empenho para NEs cujo codContrato bate com algum `codigo_siafe` do índice
— como o `codigo_siafe` do duplicado deixa de existir, a NE simplesmente
cai no bucket "sem contrato local" e não duplica nem sobrescreve nada.

Uso:
  python manage.py mesclar_contrato_duplicado --dry-run
  python manage.py mesclar_contrato_duplicado
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.contratos.models import Contrato, Empenho

# pk_duplicado -> (pk_principal, numero_duplicado_esperado, numero_principal_esperado, justificativa)
MESCLAGENS = [
    (
        135, 134, "25018988", "120/2025",
        "Contrato 120/2025-FMMP/PI (SEI 19.21.0016.0043009/2025-75): 4 itens "
        "(equipamento R$1.400.000 + instalação R$47.000 + migração R$47.000 + "
        "treinamento R$32.000 = R$1.526.000,00), pago por 2025NE00082 e "
        "2025NE00083 (cláusula 15.1.5 do Termo de Contrato, PDF fornecido pelo "
        "usuário em 2026-07-30). NE00083 (equipamento) já batia com "
        "codigo_siafe de 120/2025; NE00082 (migração+treinamento, "
        "R$47.000+R$32.000=R$79.000,00 — bate exato) tinha codContrato "
        "diferente e virou o contrato avulso fabricado '25018988'.",
    ),
    (
        273, 274, "AE 1029968/2025-FMMP", "41/2025/FMMP/PI",
        "Mesma contratação MULTPAR (CNPJ 22.561.863/0001-70, ARP 00012/2025, "
        "SEI 19.21.0431.0015069/2025-69, codigo_siafe 25015651, R$27.841,71). "
        "O registro fabricado 'AE 1029968/2025-FMMP' capturou as NEs 2025NE00027 "
        "(R$27.841,71) e 2025NE00063 (anulação R$8.549,81) = R$19.291,90, "
        "deixando o contrato formal 41/2025/FMMP/PI com empenho 0. Como AMBOS "
        "têm o mesmo codigo_siafe, apagar o duplicado deixa 41/2025 dono único "
        "do código — reimportações futuras passam a linkar certo (2026-07-30).",
    ),
]


class Command(BaseCommand):
    help = "Mescla Contrato duplicado (mesma contratação real, NE de elemento diferente) no contrato principal"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        modo = "[DRY-RUN — nada gravado] " if dry_run else ""

        mesclados = 0
        recusados = 0

        for pk_dup, pk_principal, numero_dup_esp, numero_principal_esp, justificativa in MESCLAGENS:
            dup = Contrato.objects.filter(pk=pk_dup).first()
            principal = Contrato.objects.filter(pk=pk_principal).first()

            if not dup or not principal:
                recusados += 1
                self.stdout.write(self.style.ERROR(
                    f"  pk={pk_dup} ou pk={pk_principal}: contrato não encontrado."
                ))
                continue

            if dup.numero_contrato != numero_dup_esp or principal.numero_contrato != numero_principal_esp:
                recusados += 1
                self.stdout.write(self.style.ERROR(
                    f"  RECUSADO — esperava dup.numero_contrato={numero_dup_esp!r} "
                    f"(achou {dup.numero_contrato!r}) e principal.numero_contrato="
                    f"{numero_principal_esp!r} (achou {principal.numero_contrato!r}). "
                    f"Confira antes de rodar de novo."
                ))
                continue

            empenhos = list(Empenho.objects.filter(contrato=dup))
            self.stdout.write(
                f"  Contrato pk={pk_dup} {dup.numero_contrato!r} -> mesclar em "
                f"pk={pk_principal} {principal.numero_contrato!r} "
                f"({len(empenhos)} empenho(s) a mover)"
            )
            for e in empenhos:
                self.stdout.write(
                    f"      Empenho pk={e.pk} NE={e.numero_empenho!r} R$ {e.valor_empenhado:,.2f}"
                )
            self.stdout.write(f"      {justificativa}")

            if dry_run:
                mesclados += 1
                continue

            with transaction.atomic():
                for e in empenhos:
                    e.contrato = principal
                    e.save(update_fields=["contrato"])

                for c in (dup, principal):
                    total = Decimal("0")
                    for emp in Empenho.objects.filter(contrato=c):
                        total += -emp.valor_empenhado if emp.tipo == "anulacao" else emp.valor_empenhado
                    c.valor_empenhado = total
                    c.save(update_fields=["valor_empenhado"])

                Contrato.objects.filter(pk=pk_dup).delete()

            mesclados += 1

        self.stdout.write(self.style.SUCCESS(
            f"\n{modo}Mesclados: {mesclados} | Recusados: {recusados}"
        ))
        if mesclados and not dry_run:
            self.stdout.write(self.style.WARNING(
                "\nAgora rode `conciliar_dashboard_srp --arp 00018/2025 00048/2025` "
                "e `conciliar_tcepi --exercicio 2025 --orgao fmmp` para conferir o resultado."
            ))
