"""
Management command: sugerir_vinculo_ne_contrato
====================================================
SOMENTE LEITURA. Complemento do `listar_nes_sem_contrato_local`: para cada
`codContrato` do SIAFE sem par local, procura no banco contratos do MESMO
CNPJ e sugere qual é o caso:

  (1) CONTRATO EXISTE, SÓ FALTA O codigo_siafe
      Há contrato(s) local(is) do mesmo CNPJ com `codigo_siafe` VAZIO.
      Provável: é só preencher o codigo_siafe no contrato certo — não
      precisa cadastrar nada novo. Caso típico: apostilamento/aditivo de
      contrato antigo (ex: NE da EASWELL cita "APOSTILAMENTO Nº 01 AO
      CONTRATO Nº 29/2024/PGJ", que já está cadastrado).

  (2) CONTRATO PROVAVELMENTE FALTANDO
      Nenhum contrato local desse CNPJ, ou todos já têm outro codigo_siafe
      preenchido. Provável: contrato genuinamente não cadastrado — mesmo
      caso do 13/2026/PGJ (Laís G de Sousa), resolvido em 2026-07-29 via
      `cadastrar_contrato_manual`.

Em ambos os casos a decisão é MANUAL e exige conferir o documento fonte
(SEI/PNCP) — o comando só organiza a evidência, nunca altera nada.

Uso:
  python manage.py sugerir_vinculo_ne_contrato --exercicio 2026 --saida arquivo.txt
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


def _digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


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
    help = "Para cada codContrato do SIAFE sem par local, sugere se falta só o codigo_siafe ou o contrato inteiro (somente leitura)"

    def add_arguments(self, parser):
        parser.add_argument("--exercicio", type=int, default=timezone.now().year)
        parser.add_argument("--ug", type=str, nargs="+", default=UGS_MPPI)
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

        # Índice de contratos locais por CNPJ (dígitos)
        por_cnpj = defaultdict(list)
        for c in Contrato.objects.all():
            d = _digitos(c.contratado_cnpj_cpf)
            if d:
                por_cnpj[d].append(c)

        faltantes = defaultdict(list)
        for ug in options["ug"]:
            try:
                nes = client.nota_empenho_por_ug(exercicio, ug)
            except SiafeAPIError as exc:
                self.stdout.write(self.style.ERROR(f"[ERRO] UG {ug}: {exc}"))
                continue
            for ne in nes:
                cod = (ne.get("codContrato") or "").strip()
                if cod in CODIGOS_CONTRATO_VAZIOS or cod in codigos_locais:
                    continue
                faltantes[cod].append((ug, ne))

        caso_1 = []  # (cod, total, cnpj, nome, [contratos sem codigo_siafe])
        caso_2 = []  # (cod, total, cnpj, nome, [contratos com outro codigo_siafe])

        for cod, lista in faltantes.items():
            total = sum(parse_valor(ne.get("valor")) for _, ne in lista)
            cnpjs = {
                _digitos(ne.get("cnpjCredor") or ne.get("cpfCredor")) for _, ne in lista
            }
            cnpj = next(iter(cnpjs)) if len(cnpjs) == 1 else None
            nome = next(((ne.get("nomeCredor") or "").strip() for _, ne in lista), "")

            locais = por_cnpj.get(cnpj, []) if cnpj else []
            sem_codigo = [c for c in locais if not (c.codigo_siafe or "").strip()]

            if sem_codigo:
                caso_1.append((cod, total, cnpj, nome, sem_codigo, lista))
            else:
                caso_2.append((cod, total, cnpj, nome, locais, lista))

        # ------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n=== (1) CONTRATO EXISTE, provavelmente só falta o codigo_siafe — {len(caso_1)} caso(s) ==="
        ))
        for cod, total, cnpj, nome, candidatos, lista in sorted(caso_1, key=lambda x: -x[1]):
            self.stdout.write(self.style.WARNING(
                f"\n  codContrato={cod!r} | R$ {total:,.2f} | {nome} (CNPJ {cnpj})"
            ))
            for _, ne in lista:
                obs = (ne.get("observacao") or "").strip()
                self.stdout.write(f"    NE={(ne.get('codigo') or '').strip()!r}: {obs[:180]}")
            self.stdout.write("    Contrato(s) local(is) do mesmo CNPJ SEM codigo_siafe (candidatos):")
            for c in candidatos:
                self.stdout.write(
                    f"      pk={c.pk} | {c.numero_contrato!r} | R$ {c.valor_inicial:,.2f} | "
                    f"assinatura={c.data_assinatura} | {(c.objeto or '')[:70]}"
                )

        # ------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n=== (2) CONTRATO PROVAVELMENTE FALTANDO no cadastro — {len(caso_2)} caso(s) ==="
        ))
        for cod, total, cnpj, nome, locais, lista in sorted(caso_2, key=lambda x: -x[1]):
            self.stdout.write(self.style.ERROR(
                f"\n  codContrato={cod!r} | R$ {total:,.2f} | {nome} (CNPJ {cnpj})"
            ))
            for _, ne in lista:
                obs = (ne.get("observacao") or "").strip()
                self.stdout.write(f"    NE={(ne.get('codigo') or '').strip()!r}: {obs[:180]}")
            if locais:
                self.stdout.write("    Contratos locais do mesmo CNPJ (todos JÁ com outro codigo_siafe):")
                for c in locais:
                    self.stdout.write(
                        f"      pk={c.pk} | {c.numero_contrato!r} | codigo_siafe={c.codigo_siafe!r} | "
                        f"R$ {c.valor_inicial:,.2f} | {(c.objeto or '')[:60]}"
                    )
            else:
                self.stdout.write("    Nenhum contrato local com esse CNPJ.")

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== Resumo ==="))
        self.stdout.write(
            f"  (1) só falta codigo_siafe: {len(caso_1)} | (2) contrato faltando: {len(caso_2)}"
        )
        self.stdout.write(self.style.WARNING(
            "\nSomente leitura. Caso (1): conferir qual candidato é o certo e preencher codigo_siafe. "
            "Caso (2): confirmar no SEI/PNCP e usar `cadastrar_contrato_manual`."
        ))

        if arquivo_saida:
            arquivo_saida.close()
