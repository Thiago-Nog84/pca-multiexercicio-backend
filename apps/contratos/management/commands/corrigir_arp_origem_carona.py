"""
Management command: corrigir_arp_origem_carona
====================================================
Remove o vínculo `Contrato.arp_origem` de contratos que na verdade são
CARONA (adesão) a uma ata de OUTRO órgão, e portanto não deviam consumir
saldo de nenhuma `AtaRegistroPrecos` própria do MPPI.

O modelo já tem `ARPExterna` + `Contrato.arp_externa_origem` para
representar exatamente esse caso — mas cadastrar lá exige dados que ainda
não temos (CNPJ do órgão gerenciador, datas de vigência, quantidade
autorizada). Este comando faz só a parte segura agora: zera o
`arp_origem` errado, tirando o contrato do fluxo de `conciliar_dashboard_srp`
da ARP à qual foi vinculado por engano. O cadastro em `ARPExterna` fica
pendente (ver docs/fracao_quantidades_2026-07-29.md).

Caso confirmado nesta sessão (2026-07-30): contrato `2025NE00141` (pk=159,
REPREMIG REPRESENTAÇÃO E COMÉRCIO DE MINAS GERAIS LTDA) estava com
`arp_origem` apontando para a ARP 00016/2025 (toners MPPI). O objeto real é
"Adesão à Ata de Registro de Preços nº 039/2024, oriunda do Pregão
Eletrônico SGP-e nº PMSC/17517/2023 (Polícia Militar de Santa Catarina)"
para uma "SOLUÇÃO DE VIDEO WALL" — confirmado pelo usuário como carona
externa. Achado via cruzamento do bloco produtos[] da NE 2025NE00141 (SIAFE)
contra o objeto do contrato, durante a investigação de quantidade
fracionária no item 9 da ARP 00016/2025 (fracao_quantidades_2026-07-29.md).

Uso:
  python manage.py corrigir_arp_origem_carona --dry-run
  python manage.py corrigir_arp_origem_carona
"""

from django.core.management.base import BaseCommand

from apps.contratos.models import Contrato

# pk -> (numero_arp_atual_esperada, justificativa)
# Baixo risco: só zera arp_origem, nunca sobrescreve para outra ARP.
# Recusa se o arp_origem atual não for o esperado (alguém já mexeu).
DESVINCULAR = {
    159: (
        "00016/2025",
        "REPREMIG — contrato 2025NE00141 é carona (adesão) à Ata 039/2024 da "
        "Polícia Militar de Santa Catarina (Pregão SGP-e PMSC/17517/2023), "
        "objeto 'SOLUÇÃO DE VIDEO WALL' — confirmado pelo usuário em "
        "2026-07-30. Não tem relação com a ARP 00016/2025 (toners do MPPI). "
        "Pendente: cadastrar em ARPExterna quando houver o documento SEI da "
        "adesão com CNPJ do órgão gerenciador, vigência e quantidade "
        "autorizada.",
    ),
}


class Command(BaseCommand):
    help = "Zera arp_origem de contratos identificados como carona externa vinculada por engano a ARP própria"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        modo = "[DRY-RUN — nada gravado] " if dry_run else ""

        desvinculados = 0
        recusados = 0

        for pk, (numero_arp_esperada, justificativa) in DESVINCULAR.items():
            contrato = Contrato.objects.filter(pk=pk).select_related("arp_origem").first()
            if not contrato:
                self.stdout.write(self.style.ERROR(f"  pk={pk}: contrato não encontrado."))
                continue

            atual = contrato.arp_origem.numero_arp if contrato.arp_origem else None
            if atual != numero_arp_esperada:
                recusados += 1
                self.stdout.write(self.style.ERROR(
                    f"  pk={pk} {contrato.numero_contrato!r}: RECUSADO — arp_origem atual é "
                    f"{atual!r}, mas a correção esperava {numero_arp_esperada!r}. Confira antes "
                    f"de rodar de novo."
                ))
                continue

            self.stdout.write(
                f"  pk={pk} {contrato.numero_contrato!r}: arp_origem {numero_arp_esperada!r} -> (vazio)"
            )
            self.stdout.write(f"      {justificativa}")
            if not dry_run:
                contrato.arp_origem = None
                contrato.save(update_fields=["arp_origem"])
            desvinculados += 1

        self.stdout.write(self.style.SUCCESS(
            f"\n{modo}Desvinculados: {desvinculados} | Recusados: {recusados}"
        ))
        if desvinculados and not dry_run:
            self.stdout.write(self.style.WARNING(
                "\nAgora rode `conciliar_dashboard_srp --arp 00016/2025` de novo — a fração "
                "fantasma no item 9 deve sumir."
            ))
