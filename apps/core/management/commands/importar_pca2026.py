"""
Importa dados do PCA 2026 (schema Supabase antigo) para o novo modelo Django.

Mapeamento:
  unidades          → UnidadeRequisitante (vinculadas ao Orgão MPPI)
  exercicios        → PlanoContratacaoAnual (um PCA por exercício)
  itens_pca         → DocumentoFormalizacaoDemanda + ItemPCA
                      (um DFD por unidade/exercício, itens dentro de cada DFD)

Uso:
  python manage.py importar_pca2026
  python manage.py importar_pca2026 --dry-run   # apenas mostra o que seria importado
  python manage.py importar_pca2026 --limpar    # apaga dados existentes antes de importar
"""

import psycopg2
from decouple import config
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.models import Orgao, UnidadeRequisitante
from apps.pca.models import DocumentoFormalizacaoDemanda, ItemPCA, PlanoContratacaoAnual

User = get_user_model()

# Mapeamento de modalidade (schema antigo → novo)
MODALIDADE_MAP = {
    "licitacao": "licitacao",
    "dispensa": "dispensa",
    "inexigibilidade": "inexigibilidade",
    None: "licitacao",
}

# Mapeamento de tipo_objeto (schema antigo → categoria novo)
TIPO_OBJETO_MAP = {
    "tic": "solucao_ti",
    "nao_tic": "servico",
    None: "servico",
}


class Command(BaseCommand):
    help = "Importa dados do PCA 2026 (schema Supabase legado) para o novo modelo Django"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Apenas exibe o que seria importado, sem gravar",
        )
        parser.add_argument(
            "--limpar",
            action="store_true",
            help="Remove PCAs/DFDs/Itens existentes antes de importar",
        )
        parser.add_argument(
            "--orgao-sigla",
            default="MPPI",
            help="Sigla do órgão a usar/criar (padrão: MPPI)",
        )
        parser.add_argument(
            "--admin-username",
            default="admin",
            help="Username do superusuário para definir como criador (padrão: admin)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        limpar = options["limpar"]
        orgao_sigla = options["orgao_sigla"]
        admin_username = options["admin_username"]

        if dry_run:
            self.stdout.write(self.style.WARNING("=== MODO DRY-RUN — nada será gravado ===\n"))

        # ── Conecta ao banco legado (mesmo Supabase) ─────────────────────────
        conn = psycopg2.connect(
            dbname=config("DB_NAME", default="postgres"),
            user=config("DB_USER"),
            password=config("DB_PASSWORD"),
            host=config("DB_HOST"),
            port=config("DB_PORT", default="6543"),
            options="-c search_path=public",
        )
        cur = conn.cursor()

        try:
            # ── Lê dados do schema legado ────────────────────────────────────

            # Verifica se as tabelas antigas existem
            cur.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name IN ('unidades', 'exercicios', 'itens_pca')
            """)
            tabelas = {row[0] for row in cur.fetchall()}
            faltando = {"unidades", "exercicios", "itens_pca"} - tabelas
            if faltando:
                self.stdout.write(self.style.ERROR(
                    f"Tabelas não encontradas no banco: {faltando}\n"
                    "Verifique se o schema legado ainda existe no Supabase."
                ))
                return

            cur.execute("SELECT id, nome, sigla, ativo FROM unidades WHERE ativo = true ORDER BY nome")
            unidades_rows = cur.fetchall()

            cur.execute("SELECT id, ano, status FROM exercicios ORDER BY ano")
            exercicios_rows = cur.fetchall()

            cur.execute("""
                SELECT
                    id, exercicio_id, unidade_id, descricao, categoria,
                    valor_estimado, tipo_objeto, modalidade_contratacao, status
                FROM itens_pca
                ORDER BY exercicio_id, unidade_id
            """)
            itens_rows = cur.fetchall()

        finally:
            cur.close()
            conn.close()

        self.stdout.write(f"Encontrado no schema legado:")
        self.stdout.write(f"  {len(unidades_rows)} unidades")
        self.stdout.write(f"  {len(exercicios_rows)} exercícios")
        self.stdout.write(f"  {len(itens_rows)} itens do PCA\n")

        if not unidades_rows and not exercicios_rows:
            self.stdout.write(self.style.WARNING("Nenhum dado encontrado no schema legado. Nada a importar."))
            return

        if dry_run:
            for row in unidades_rows:
                self.stdout.write(f"  Unidade: {row[2] or row[1]} — {row[1]}")
            for row in exercicios_rows:
                self.stdout.write(f"  Exercício: {row[1]} ({row[2]})")
            self.stdout.write(f"\n  Total de itens a importar: {len(itens_rows)}")
            return

        # ── Grava no novo schema ─────────────────────────────────────────────
        with transaction.atomic():
            # Admin user
            try:
                admin = User.objects.get(username=admin_username)
            except User.DoesNotExist:
                admin = User.objects.filter(is_superuser=True).first()
                if not admin:
                    self.stdout.write(self.style.WARNING("Nenhum superusuário encontrado — criador ficará em branco"))
                    admin = None

            # Limpar dados existentes
            if limpar:
                self.stdout.write(self.style.WARNING("Removendo dados existentes..."))
                ItemPCA.objects.all().delete()
                DocumentoFormalizacaoDemanda.objects.all().delete()
                PlanoContratacaoAnual.objects.all().delete()

            # Órgão
            orgao, criado = Orgao.objects.get_or_create(
                sigla=orgao_sigla,
                defaults={
                    "nome": "Ministério Público do Estado do Piauí",
                    "uf": "PI",
                    "esfera": "estadual",
                    "ativo": True,
                },
            )
            if criado:
                self.stdout.write(self.style.SUCCESS(f"Órgão criado: {orgao}"))
            else:
                self.stdout.write(f"Órgão já existia: {orgao}")

            # Unidades (uuid legado → objeto novo)
            uuid_to_unidade = {}
            for uid, nome, sigla, ativo in unidades_rows:
                unidade, criada = UnidadeRequisitante.objects.get_or_create(
                    orgao=orgao,
                    sigla=sigla or nome[:10],
                    defaults={
                        "nome": nome,
                        "ativo": ativo,
                    },
                )
                uuid_to_unidade[str(uid)] = unidade
                status_txt = "criada" if criada else "já existia"
                self.stdout.write(f"  Unidade {status_txt}: {unidade.sigla} — {unidade.nome}")

            # PCAs (um por exercício)
            uuid_to_pca = {}
            for eid, ano, status_legado in exercicios_rows:
                # Mapeia status legado → novo
                status_novo = "coleta"
                if status_legado == "aprovado":
                    status_novo = "aprovado"
                elif status_legado == "encerrado":
                    status_novo = "publicado_pncp"

                pca, criado = PlanoContratacaoAnual.objects.get_or_create(
                    orgao=orgao,
                    exercicio=ano,
                    defaults={"status": status_novo},
                )
                uuid_to_pca[str(eid)] = pca
                status_txt = "criado" if criado else "já existia"
                self.stdout.write(self.style.SUCCESS(f"  PCA {status_txt}: {pca}"))

            # Itens → DFDs agrupados por (exercicio, unidade) + ItemPCA
            # Agrupa itens por (exercicio_id, unidade_id)
            from collections import defaultdict
            grupos: dict = defaultdict(list)
            for row in itens_rows:
                iid, eid, uid, desc, cat, valor, tipo_obj, modalidade, status_item = row
                grupos[(str(eid), str(uid))].append(row)

            dfd_count = 0
            item_count = 0

            for (eid, uid), itens_grupo in grupos.items():
                pca = uuid_to_pca.get(eid)
                unidade = uuid_to_unidade.get(uid)
                if not pca or not unidade:
                    self.stdout.write(self.style.WARNING(
                        f"  Pulando grupo (exercício={eid}, unidade={uid}) — PCA ou unidade não encontrados"
                    ))
                    continue

                # Um DFD por (pca, unidade)
                dfd, dfd_criado = DocumentoFormalizacaoDemanda.objects.get_or_create(
                    pca=pca,
                    unidade=unidade,
                    defaults={
                        "descricao_objeto": f"Demandas de {unidade.nome} — PCA {pca.exercicio}",
                        "justificativa": "Importado do PCA 2026 (sistema legado).",
                        "prazo_necessidade": f"{pca.exercicio}-12-31",
                        "grau_prioridade": "medio",
                        "status": "rascunho",
                        "requisitante": admin,
                    },
                )
                if dfd_criado:
                    dfd_count += 1

                # Itens do DFD
                numero = ItemPCA.objects.filter(dfd=dfd).count() + 1
                for row in itens_grupo:
                    iid, eid2, uid2, desc, cat, valor, tipo_obj, modalidade, status_item = row

                    categoria = TIPO_OBJETO_MAP.get(tipo_obj, "servico")
                    tipo_cont = MODALIDADE_MAP.get(modalidade, "licitacao")
                    valor_unit = float(valor) if valor else 0.0

                    item, item_criado = ItemPCA.objects.get_or_create(
                        dfd=dfd,
                        numero_item=numero,
                        defaults={
                            "categoria": categoria,
                            "descricao": desc or "Sem descrição",
                            "unidade_fornecimento": "UN",
                            "quantidade_estimada": 1,
                            "valor_unitario_estimado": valor_unit,
                            "valor_total_estimado": valor_unit,
                            "tipo_contratacao": tipo_cont,
                            "observacoes": f"Categoria original: {cat or '—'} | Status original: {status_item}",
                        },
                    )
                    if item_criado:
                        item_count += 1
                        numero += 1

            self.stdout.write(self.style.SUCCESS(
                f"\nImportação concluída!\n"
                f"  Órgão:    1\n"
                f"  Unidades: {len(uuid_to_unidade)}\n"
                f"  PCAs:     {len(uuid_to_pca)}\n"
                f"  DFDs:     {dfd_count}\n"
                f"  Itens:    {item_count}"
            ))
