"""
Management command: corrigir_codigo_siafe_manual
====================================================
Preenche (ou corrige) `Contrato.codigo_siafe` para contratos onde o vínculo
com o SIAFE foi confirmado manualmente — normalmente a partir do
`sugerir_vinculo_ne_contrato`, quando o valor E o objeto da NE batem
exatamente com um contrato local.

Duas listas separadas por nível de risco:

  PREENCHER_VAZIO — contratos com `codigo_siafe` VAZIO. Baixo risco: só
  preenche o que está em branco. Se o campo já tiver qualquer valor, o
  comando NÃO mexe e avisa (evita sobrescrever correção manual).

  SUBSTITUIR — contratos com `codigo_siafe` PREENCHIDO mas comprovadamente
  ERRADO. Alto risco: sobrescreve dado existente. Só roda com --force, e
  cada entrada declara o valor antigo esperado (`de`); se o valor atual no
  banco não for o esperado, o comando recusa (alguém já mexeu no meio do
  caminho — melhor abortar que sobrescrever às cegas).

Depois de rodar, execute `importar_empenhos_siafe --exercicio <ano>` para
as NEs correspondentes entrarem como `Empenho`.

Uso:
  python manage.py corrigir_codigo_siafe_manual --dry-run
  python manage.py corrigir_codigo_siafe_manual
  python manage.py corrigir_codigo_siafe_manual --force   # inclui SUBSTITUIR
"""

from django.core.management.base import BaseCommand

from apps.contratos.models import Contrato

# pk -> (codigo_siafe, justificativa)
# Fonte: sugerir_vinculo_ne_contrato, exercício 2026, rodado em 2026-07-29.
# Critério de confiança: valor da NE == valor_inicial do contrato E objeto
# da observação da NE == objeto do contrato.
PREENCHER_VAZIO = {
    268: (
        "26000337",
        "DOMINI TELECOM — NE 2026NE00037 R$42.940,40 == valor_inicial do "
        "contrato 43/2026/FMMPPI; objeto idêntico (conectores RJ-45 EZ Crimp CAT6).",
    ),
    264: (
        "26100631",
        "NORDESTE COMERCIO — NE 2026NE00005 R$31.860,00 == valor_inicial do "
        "contrato 07/2026/FMMPPI; objeto idêntico (manutenção preventiva/corretiva "
        "de plataformas).",
    ),
    263: (
        "26100643",
        "NTSEC — NE 2026NE00146 R$1.553.207,77; único contrato local do CNPJ "
        "09.137.728/0002-15 sem codigo_siafe, objeto idêntico (solução integrada de "
        "segurança de perímetro). Resolve a pendência registrada na memória do "
        "projeto: '05/2026/PGJ (NTSEC) NÃO foi preenchido — numeração interna do "
        "MPPI não corresponde 1:1 à sequência SIASG'.",
    ),
}

# pk -> (de, para, justificativa)
SUBSTITUIR = {
    176: (
        "25017404",
        "26100669",
        "SORELLE — contrato 10/2026/FPDC (exercício 2026) estava apontando para um "
        "codigo_siafe de 2025 ('25017404'). O SIAFE mostra a NE 2026NE00022 "
        "R$10.957,23 (== valor_inicial do contrato, objeto idêntico: bebedouros e "
        "purificadores) sob codContrato 26100669. Mesmo padrão de vínculo errado já "
        "corrigido em outros contratos nesta sessão.",
    ),
}


class Command(BaseCommand):
    help = "Preenche/corrige codigo_siafe de contratos com vínculo confirmado manualmente"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--force", action="store_true",
            help="Também aplica a lista SUBSTITUIR (sobrescreve codigo_siafe existente).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        force = options["force"]
        modo = "[DRY-RUN — nada gravado] " if dry_run else ""

        preenchidos = 0
        pulados = 0
        substituidos = 0
        recusados = 0

        self.stdout.write(self.style.MIGRATE_HEADING("=== PREENCHER (codigo_siafe vazio) ==="))
        for pk, (codigo, justificativa) in PREENCHER_VAZIO.items():
            contrato = Contrato.objects.filter(pk=pk).first()
            if not contrato:
                self.stdout.write(self.style.ERROR(f"  pk={pk}: contrato não encontrado."))
                continue

            atual = (contrato.codigo_siafe or "").strip()
            if atual:
                pulados += 1
                self.stdout.write(self.style.WARNING(
                    f"  pk={pk} {contrato.numero_contrato!r}: JÁ tem codigo_siafe={atual!r} "
                    f"— não mexido (esperado vazio)."
                ))
                continue

            self.stdout.write(
                f"  pk={pk} {contrato.numero_contrato!r}: (vazio) -> {codigo!r}"
            )
            self.stdout.write(f"      {justificativa}")
            if not dry_run:
                contrato.codigo_siafe = codigo
                contrato.save(update_fields=["codigo_siafe"])
            preenchidos += 1

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== SUBSTITUIR (codigo_siafe errado) ==="))
        if not force:
            self.stdout.write(self.style.WARNING(
                f"  {len(SUBSTITUIR)} caso(s) pendente(s) — rode com --force para aplicar."
            ))
            for pk, (de, para, justificativa) in SUBSTITUIR.items():
                self.stdout.write(f"    pk={pk}: {de!r} -> {para!r}")
        else:
            for pk, (de, para, justificativa) in SUBSTITUIR.items():
                contrato = Contrato.objects.filter(pk=pk).first()
                if not contrato:
                    self.stdout.write(self.style.ERROR(f"  pk={pk}: contrato não encontrado."))
                    continue

                atual = (contrato.codigo_siafe or "").strip()
                if atual != de:
                    recusados += 1
                    self.stdout.write(self.style.ERROR(
                        f"  pk={pk} {contrato.numero_contrato!r}: RECUSADO — codigo_siafe atual é "
                        f"{atual!r}, mas a correção esperava {de!r}. Alguém já alterou; "
                        f"confira antes de forçar."
                    ))
                    continue

                self.stdout.write(
                    f"  pk={pk} {contrato.numero_contrato!r}: {de!r} -> {para!r}"
                )
                self.stdout.write(f"      {justificativa}")
                if not dry_run:
                    contrato.codigo_siafe = para
                    contrato.save(update_fields=["codigo_siafe"])
                substituidos += 1

        self.stdout.write(self.style.SUCCESS(
            f"\n{modo}Preenchidos: {preenchidos} | Pulados (já tinham valor): {pulados} | "
            f"Substituídos: {substituidos} | Recusados (valor atual inesperado): {recusados}"
        ))
        if (preenchidos or substituidos) and not dry_run:
            self.stdout.write(self.style.WARNING(
                "\nAgora rode `importar_empenhos_siafe --exercicio 2026` para as NEs "
                "correspondentes entrarem como Empenho."
            ))
