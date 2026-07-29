"""
Management command: auditar_empenhos_manuais
====================================================
SOMENTE LEITURA. Confere cada `Empenho` com `importado_siafe=False` (ou
seja, cadastrado manualmente / pelo antigo `vincular_empenhos_siafe` com o
dict EMPENHOS_CONHECIDOS hardcoded) contra a fonte real no SIAFE-PI.

Motivação (achado de 2026-07-29): o Empenho pk=26 estava registrado como
NE 2026NE00010, credor SORELLE (36.045.363/0001-90), no contrato
10/2026/FPDC. Mas a NE 2026NE00010 real, comprovada por documento SIAFE
(NL 2026NL00135 / OB 2026OB00362), é do credor L H C HAIDAR SOUSA
(42.489.485/0001-79), UG 250102 (FMMP, não FEPDC), contrato SIAFE 26100660
(projetos de prevenção e combate a incêndio, não bebedouros). Registro
manual completamente equivocado — inflava o empenhado do SORELLE em
R$25.132,47 e quebrava a conciliação com o TCE.

Para cada empenho manual, busca a NE de mesmo número no SIAFE (todas as
UGs do MPPI no exercício) e classifica:

  OK               — número, credor (CNPJ) e contrato batem.
  CREDOR DIFERENTE — a NE existe no SIAFE, mas em nome de outro credor.
                     O registro local está errado (caso do pk=26).
  CONTRATO DIFERENTE — credor bate, mas o codContrato da NE aponta para
                     outro contrato que não o vinculado localmente.
  NAO ENCONTRADA   — nenhuma NE com esse número nas UGs/exercício
                     consultados. Pode ser NE de outro exercício, de UG
                     fora do MPPI, ou número inventado.

Nunca altera nada — a decisão de apagar/corrigir cada registro é manual.

Uso:
  python manage.py auditar_empenhos_manuais --exercicio 2026 --saida arquivo.txt
  python manage.py auditar_empenhos_manuais --exercicio 2025 --saida arquivo.txt
"""

import re

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.contratos.models import Empenho
from apps.siafe.client import SiafeAPIError, SiafeClient

UGS_MPPI = ["250101", "250102", "250104"]


def _digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


class Command(BaseCommand):
    help = "Confere Empenhos manuais (importado_siafe=False) contra o SIAFE e aponta divergências (somente leitura)"

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

        manuais = list(
            Empenho.objects.filter(importado_siafe=False, ano_exercicio=exercicio)
            .select_related("contrato")
            .order_by("numero_empenho")
        )
        if not manuais:
            self.stdout.write(self.style.SUCCESS(
                f"Nenhum Empenho manual (importado_siafe=False) no exercício {exercicio}."
            ))
            if arquivo_saida:
                arquivo_saida.close()
            return

        self.stdout.write(f"{len(manuais)} empenho(s) manual(is) no exercício {exercicio}.\n")

        # Índice de NEs do SIAFE por número
        nes_siafe = {}
        for ug in options["ug"]:
            self.stdout.write(f"Buscando NEs da UG {ug}...")
            try:
                nes = client.nota_empenho_por_ug(exercicio, ug)
            except SiafeAPIError as exc:
                self.stdout.write(self.style.ERROR(f"  [ERRO] UG {ug}: {exc}"))
                continue
            self.stdout.write(f"  {len(nes)} NEs recebidas")
            for ne in nes:
                numero = (ne.get("codigo") or "").strip()
                if numero:
                    nes_siafe.setdefault(numero, []).append((ug, ne))

        contagem = {"ok": 0, "credor": 0, "contrato": 0, "nao_encontrada": 0}

        self.stdout.write("")
        for e in manuais:
            numero = (e.numero_empenho or "").strip()
            cnpj_local = _digitos(e.cnpj_favorecido)
            cod_local = (e.contrato.codigo_siafe or "").strip()

            ocorrencias = nes_siafe.get(numero, [])
            if not ocorrencias:
                contagem["nao_encontrada"] += 1
                self.stdout.write(self.style.WARNING(
                    f"  [NAO ENCONTRADA] pk={e.pk} NE={numero!r} R$ {e.valor_empenhado:,.2f} "
                    f"— contrato {e.contrato.numero_contrato!r} (pk={e.contrato_id}), "
                    f"credor local {cnpj_local} {e.nome_favorecido[:40]}"
                ))
                continue

            # Se houver mais de uma UG com o mesmo número de NE, tenta achar a do credor local
            match = None
            for ug, ne in ocorrencias:
                cnpj_ne = _digitos(ne.get("cnpjCredor") or ne.get("cpfCredor"))
                if cnpj_ne and cnpj_ne == cnpj_local:
                    match = (ug, ne)
                    break

            if match:
                ug, ne = match
                cod_ne = (ne.get("codContrato") or "").strip()
                if cod_local and cod_ne and cod_ne != cod_local:
                    contagem["contrato"] += 1
                    self.stdout.write(self.style.ERROR(
                        f"  [CONTRATO DIFERENTE] pk={e.pk} NE={numero!r}: credor bate, mas SIAFE diz "
                        f"codContrato={cod_ne!r} e o contrato local {e.contrato.numero_contrato!r} "
                        f"tem codigo_siafe={cod_local!r}"
                    ))
                else:
                    contagem["ok"] += 1
                continue

            # Nenhuma ocorrência com o CNPJ local → credor errado
            contagem["credor"] += 1
            ug, ne = ocorrencias[0]
            cnpj_real = _digitos(ne.get("cnpjCredor") or ne.get("cpfCredor"))
            self.stdout.write(self.style.ERROR(
                f"  [CREDOR DIFERENTE] pk={e.pk} NE={numero!r} R$ {e.valor_empenhado:,.2f}"
            ))
            self.stdout.write(
                f"      local : credor {cnpj_local} {e.nome_favorecido[:45]} | "
                f"contrato {e.contrato.numero_contrato!r} (pk={e.contrato_id})"
            )
            self.stdout.write(
                f"      SIAFE : credor {cnpj_real} {(ne.get('nomeCredor') or '')[:45]} | "
                f"UG {ug} | codContrato={(ne.get('codContrato') or '').strip()!r} | "
                f"valor={ne.get('valor')}"
            )
            obs = (ne.get("observacao") or "").strip()
            if obs:
                self.stdout.write(f"      obs SIAFE: {obs[:160]}")

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== Resumo ==="))
        self.stdout.write(
            f"  OK: {contagem['ok']} | CREDOR DIFERENTE: {contagem['credor']} | "
            f"CONTRATO DIFERENTE: {contagem['contrato']} | NAO ENCONTRADA: {contagem['nao_encontrada']}"
        )
        self.stdout.write(self.style.WARNING(
            "\nSomente leitura. Registros com CREDOR DIFERENTE são dados manuais equivocados — "
            "conferir no documento fonte e, confirmado o erro, remover (eles inflam o empenhado "
            "do credor errado e quebram a conciliação com o TCE)."
        ))

        if arquivo_saida:
            arquivo_saida.close()
