"""
Management command: listar_nes_sem_contrato_local
====================================================
SOMENTE LEITURA. Lista, de uma vez, todas as Notas de Empenho do SIAFE que
o `importar_empenhos_siafe` reporta como "NEs sem contrato local" — ou seja,
NEs que TÊM um `codContrato` preenchido no SIAFE, mas cujo código não bate
com nenhum `Contrato.codigo_siafe` cadastrado aqui.

Separa em dois grupos, que exigem tratamento diferente:

  (A) NE COM codContrato preenchido, mas sem par local
      -> provável CONTRATO FALTANDO no cadastro. Mesmo caso do contrato
         13/2026/PGJ (Laís G de Sousa), achado em 2026-07-29: o contrato
         existia no SEI/SIAFE mas nunca tinha sido cadastrado. Resolver com
         `cadastrar_contrato_manual` depois de confirmar no documento fonte.

  (B) NE com codContrato zerado ('00000000' / vazio)
      -> COMPRA DIRETA, sem instrumento contratual. NÃO é erro e NÃO tem
         correção: o modelo `Empenho` exige FK obrigatória para `Contrato`,
         então esse tipo de despesa não é registrável aqui por design.
         Caso real confirmado: NE 2026NE00818 (ZENITE, R$5.568,00).
      Este grupo só é listado com --incluir-avulsas (são centenas: folha,
      diárias, etc.) — por padrão fica de fora para não poluir a saída.

Agrupa por `codContrato` para mostrar quantas NEs (e quanto valor) cada
contrato faltante representa — os de maior valor são os mais urgentes.

Uso:
  python manage.py listar_nes_sem_contrato_local --exercicio 2026 --saida arquivo.txt
  python manage.py listar_nes_sem_contrato_local --exercicio 2026 --incluir-avulsas
"""

import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.contratos.models import Contrato
from apps.siafe.client import SiafeAPIError, SiafeClient

UGS_MPPI = ["250101", "250102", "250104"]
CODIGOS_CONTRATO_VAZIOS = {"", "0", "00000000"}


def parse_valor(v):
    if v is None:
        return Decimal("0")
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    s = re.sub(r"[R$\s]", "", str(v)).replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal("0")


class Command(BaseCommand):
    help = "Lista as NEs do SIAFE cujo codContrato não bate com nenhum Contrato local (somente leitura)"

    def add_arguments(self, parser):
        parser.add_argument("--exercicio", type=int, default=timezone.now().year)
        parser.add_argument("--ug", type=str, nargs="+", default=UGS_MPPI)
        parser.add_argument(
            "--incluir-avulsas", action="store_true",
            help="Também lista NEs com codContrato zerado (compras diretas — não corrigíveis).",
        )
        parser.add_argument("--saida", type=str, default=None)

    def handle(self, *args, **options):
        arquivo_saida = None
        if options.get("saida"):
            arquivo_saida = open(options["saida"], "w", encoding="utf-8")
            escrever_original = self.stdout.write

            def escrever_e_gravar(msg="", *a, **kw):
                escrever_original(msg, *a, **kw)
                arquivo_saida.write(str(msg) + "\n")

            self.stdout.write = escrever_e_gravar

        exercicio = options["exercicio"]
        client = SiafeClient()

        codigos_locais = {
            c.codigo_siafe.strip()
            for c in Contrato.objects.exclude(codigo_siafe="").exclude(codigo_siafe__isnull=True)
        }
        self.stdout.write(f"{len(codigos_locais)} contrato(s) local(is) com codigo_siafe.\n")

        # codContrato -> lista de NEs
        faltantes = defaultdict(list)
        avulsas = []
        total_nes = 0

        for ug in options["ug"]:
            self.stdout.write(f"Buscando NEs da UG {ug} — exercício {exercicio}...")
            try:
                nes = client.nota_empenho_por_ug(exercicio, ug)
            except SiafeAPIError as exc:
                self.stdout.write(self.style.ERROR(f"  [ERRO] UG {ug}: {exc}"))
                continue
            self.stdout.write(f"  {len(nes)} NEs recebidas")
            total_nes += len(nes)

            for ne in nes:
                cod_contrato = (ne.get("codContrato") or "").strip()
                if cod_contrato in CODIGOS_CONTRATO_VAZIOS:
                    avulsas.append((ug, ne))
                    continue
                if cod_contrato in codigos_locais:
                    continue  # já tem par local, tudo certo
                faltantes[cod_contrato].append((ug, ne))

        # ------------------------------------------------------------------
        # Grupo A — contrato provavelmente faltando no cadastro
        # ------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n=== (A) codContrato preenchido no SIAFE, SEM par local — "
            f"{len(faltantes)} contrato(s) distinto(s) ==="
        ))
        if not faltantes:
            self.stdout.write("  Nenhum. Todos os codContrato do SIAFE têm contrato local correspondente.")
        else:
            ordenados = sorted(
                faltantes.items(),
                key=lambda kv: sum(parse_valor(ne.get("valor")) for _, ne in kv[1]),
                reverse=True,
            )
            for cod_contrato, lista in ordenados:
                total = sum(parse_valor(ne.get("valor")) for _, ne in lista)
                credores = {
                    (
                        re.sub(r"\D", "", str(ne.get("cnpjCredor") or ne.get("cpfCredor") or "")),
                        (ne.get("nomeCredor") or "").strip(),
                    )
                    for _, ne in lista
                }
                self.stdout.write(self.style.ERROR(
                    f"\n  codContrato={cod_contrato!r} | {len(lista)} NE(s) | total R$ {total:,.2f}"
                ))
                for cnpj, nome in sorted(credores):
                    self.stdout.write(f"    credor: {cnpj} — {nome}")
                for ug, ne in sorted(lista, key=lambda x: (x[1].get("codigo") or "")):
                    tipo_alt = (ne.get("tipoAlteracaoNE") or "NENHUMA").upper()
                    self.stdout.write(
                        f"    UG {ug} | NE={(ne.get('codigo') or '').strip()!r} | "
                        f"R$ {parse_valor(ne.get('valor')):>14,.2f} | tipo={tipo_alt} | "
                        f"emissão={ne.get('dataEmissao')}"
                    )
                    obs = (ne.get("observacao") or "").strip()
                    if obs:
                        self.stdout.write(f"      obs: {obs[:200]}")

        # ------------------------------------------------------------------
        # Grupo B — compras diretas (sem contrato), não corrigíveis
        # ------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n=== (B) codContrato zerado — compra direta, sem instrumento contratual: "
            f"{len(avulsas)} NE(s) ==="
        ))
        self.stdout.write(
            "  Não é erro e não tem correção: o modelo Empenho exige FK obrigatória para Contrato, "
            "então NE sem contrato não é registrável localmente por design."
        )
        if options["incluir_avulsas"]:
            total_avulsas = sum(parse_valor(ne.get("valor")) for _, ne in avulsas)
            self.stdout.write(f"  Total das avulsas: R$ {total_avulsas:,.2f}\n")
            for ug, ne in sorted(avulsas, key=lambda x: -parse_valor(x[1].get("valor"))):
                self.stdout.write(
                    f"    UG {ug} | NE={(ne.get('codigo') or '').strip()!r} | "
                    f"R$ {parse_valor(ne.get('valor')):>14,.2f} | "
                    f"{(ne.get('nomeCredor') or '').strip()[:50]}"
                )
        else:
            self.stdout.write("  (use --incluir-avulsas para listar todas)")

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== Resumo ==="))
        self.stdout.write(
            f"  {total_nes} NEs lidas | (A) {len(faltantes)} contrato(s) faltando cadastrar | "
            f"(B) {len(avulsas)} NE(s) de compra direta (esperado)"
        )
        self.stdout.write(self.style.WARNING(
            "\nSomente leitura. Para os do grupo (A): confirmar cada contrato no documento fonte "
            "(SEI/PNCP) e cadastrar via `cadastrar_contrato_manual`, depois rodar "
            "`importar_empenhos_siafe` de novo para as NEs entrarem automaticamente."
        ))

        if arquivo_saida:
            arquivo_saida.close()
