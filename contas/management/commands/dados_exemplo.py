"""Preenche o sistema com um laboratório de demonstração.

Reproduz a planilha de validação de FT4 usada como referência do projeto:
equipamento Atellica, reagente e calibrador com lote e validade, especificação
de qualidade do provedor ControlLab e um estudo com dados brutos.

Serve para ver o sistema funcionando sem digitar trinta cadastros à mão, e para
conferir se o modelo de dados representa mesmo a planilha.

Uso:  python manage.py dados_exemplo
"""

from datetime import date, datetime, timedelta

from django.utils import timezone
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalogo.models import (
    Calibrador,
    Controle,
    EspecificacaoQualidade,
    LimiteImprecisao,
    Mensurando,
    Reagente,
    SistemaAnalitico,
)
from contas.models import Assinatura, Laboratorio, Usuario
from estudos.models import AmostraComparacao, Estudo, NivelEstudo, Replica, Veredito
from estudos import servicos
from motor import precisao

SENHA_DEMONSTRACAO = "demonstracao-2026"


class Command(BaseCommand):
    help = "Cria um laboratório de demonstração com os dados da planilha de FT4."

    def handle(self, *args, **opcoes):
        # O comando cria um usuário com senha conhecida. Isso é aceitável numa
        # máquina de desenvolvimento e inaceitável em produção.
        if not settings.DEBUG:
            raise CommandError(
                "Este comando cria um usuário com senha conhecida e só roda em "
                "desenvolvimento (DEBUG ligado). Em produção, cadastre pelo painel."
            )

        with transaction.atomic():
            laboratorio = self._laboratorio()
            usuario = self._usuario(laboratorio)
            mensurando = self._mensurando(laboratorio)
            teste, comparacao = self._sistemas(laboratorio)
            self._insumos(teste, comparacao)
            especificacao = self._especificacao(laboratorio, mensurando)
            estudo = self._estudo(laboratorio, usuario, mensurando, teste, comparacao, especificacao)
            self._dados_brutos(estudo, teste)
            self._outras_colunas(laboratorio, usuario, teste, comparacao)

        self.stdout.write(self.style.SUCCESS("\nDados de exemplo criados.\n"))
        self.stdout.write(f"  Laboratório: {laboratorio}")
        self.stdout.write(f"  Estudo:      {estudo.identificacao}")
        self.stdout.write(f"  Usuário:     {usuario.username}   senha: {SENHA_DEMONSTRACAO}")
        self.stdout.write(
            "\nAbra http://localhost:8000/admin/ e navegue por "
            "Laboratórios, Sistemas analíticos e Estudos de validação.\n"
        )

    def _laboratorio(self) -> Laboratorio:
        laboratorio, _ = Laboratorio.objects.get_or_create(
            cnpj="12.345.678/0001-90",
            defaults={
                "razao_social": "Laboratório de Demonstração Ltda",
                "nome_fantasia": "Lab Demonstração",
                "cidade": "São Paulo",
                "uf": "SP",
                "responsavel_tecnico": "Dra. Responsável Técnica",
            },
        )
        Assinatura.objects.get_or_create(
            laboratorio=laboratorio,
            modulo=Assinatura.COMPLETO,
            defaults={"observacao": "Assinatura de demonstração"},
        )
        return laboratorio

    def _usuario(self, laboratorio: Laboratorio) -> Usuario:
        usuario, criado = Usuario.objects.get_or_create(
            username="analista.demo",
            defaults={
                "first_name": "Analista",
                "last_name": "de Demonstração",
                "laboratorio": laboratorio,
                "funcao": Usuario.RESPONSAVEL,
                "conselho_profissional": "CRF-SP 00000",
            },
        )
        if criado:
            usuario.set_password(SENHA_DEMONSTRACAO)
            usuario.save()
        return usuario

    def _mensurando(self, laboratorio: Laboratorio) -> Mensurando:
        mensurando, _ = Mensurando.objects.get_or_create(
            laboratorio=laboratorio,
            nome="FT4",
            material_biologico="soro",
            defaults={
                "unidade_medida": "ng/dL",
                # Intervalo de referência usual de T4 livre em adultos.
                "referencia_inferior": Decimal("0.8000"),
                "referencia_superior": Decimal("1.8000"),
            },
        )
        return mensurando

    def _sistemas(self, laboratorio: Laboratorio):
        teste, _ = SistemaAnalitico.objects.get_or_create(
            laboratorio=laboratorio,
            numero_serie="IH00715",
            defaults={
                "papel": SistemaAnalitico.TESTE,
                "equipamento": "Atellica",
                "metodologia": "Quimioluminescência",
                "intervalo_analitico_minimo": Decimal("0.1000"),
                "intervalo_analitico_maximo": Decimal("12.0000"),
            },
        )
        comparacao, _ = SistemaAnalitico.objects.get_or_create(
            laboratorio=laboratorio,
            numero_serie="CE04412",
            defaults={
                "papel": SistemaAnalitico.COMPARACAO,
                "equipamento": "Centaur XP",
                "metodologia": "Quimioluminescência",
                "intervalo_analitico_minimo": Decimal("0.1000"),
                "intervalo_analitico_maximo": Decimal("12.0000"),
            },
        )
        return teste, comparacao

    def _insumos(self, teste: SistemaAnalitico, comparacao: SistemaAnalitico):
        Reagente.objects.get_or_create(
            sistema=teste,
            lote="34351224",
            defaults={"nome": "Atellica IM T4 Livre", "validade": date(2026, 8, 25)},
        )
        Calibrador.objects.get_or_create(
            sistema=teste,
            lote="13591A32",
            defaults={"nome": "Atellica IM Cal A", "validade": date(2026, 6, 18)},
        )
        Reagente.objects.get_or_create(
            sistema=comparacao,
            lote="88120455",
            defaults={"nome": "Centaur FT4", "validade": date(2026, 11, 30)},
        )

        for nivel, (nome, lote, alvo) in enumerate(
            [
                ("Controle Imuno Nível 1", "CT1-2026A", "0.6000"),
                ("Controle Imuno Nível 2", "CT2-2026A", "1.3000"),
                ("Controle Imuno Nível 3", "CT3-2026A", "3.2000"),
            ],
            start=1,
        ):
            Controle.objects.get_or_create(
                sistema=teste,
                nivel=nivel,
                lote=lote,
                defaults={
                    "nome": nome,
                    "validade": date(2027, 3, 31),
                    "valor_alvo": Decimal(alvo),
                },
            )

    def _especificacao(self, laboratorio, mensurando) -> EspecificacaoQualidade:
        """Cria a ficha declarando a FONTE — os limites derivados vêm dela.

        É a demonstração da ideia central: o laboratório informa o erro total e
        de onde ele veio; bias, imprecisão e as três justificativas nascem daí.
        """
        especificacao, criada = EspecificacaoQualidade.objects.get_or_create(
            laboratorio=laboratorio,
            mensurando=mensurando,
            nome="FT4 — ControlLab 2026",
            defaults={
                "erro_total_maximo_pct": Decimal("12.00"),
                "fonte": EspecificacaoQualidade.PROFICIENCIA,
                "fonte_descricao": "provedor de ensaio de proficiência ControlLab",
                "nivel_significancia": Decimal("0.050"),
            },
        )
        if criada:
            for nivel in (1, 2, 3):
                LimiteImprecisao.objects.create(
                    especificacao=especificacao, nivel=nivel,
                    maximo_pct=Decimal("0.00"), referencia="",
                )
            especificacao.sincronizar_imprecisao()
        return especificacao

    def _estudo(self, laboratorio, usuario, mensurando, teste, comparacao, especificacao) -> Estudo:
        estudo, _ = Estudo.objects.get_or_create(
            laboratorio=laboratorio,
            identificacao="Validação FT4 — Atellica IH00715 — 2026",
            defaults={
                "tipo": Estudo.QUANTITATIVO,
                "modulo": Assinatura.COMPLETO,
                "desenho_precisao": precisao.DESENHO_MULTIPLAS_CORRIDAS,
                "mensurando": mensurando,
                "sistema_teste": teste,
                "sistema_comparacao": comparacao,
                "especificacao": especificacao,
                "data_inicio": date.today() - timedelta(days=7),
                "criado_por": usuario,
                "observacoes": "Estudo de demonstração gerado pelo comando dados_exemplo.",
            },
        )
        return estudo

    def _dados_brutos(self, estudo: Estudo, teste: SistemaAnalitico):
        # Precisão: 3 níveis × 5 corridas × 5 réplicas, o desenho de referência.
        # Cada corrida traz um pequeno deslocamento próprio, como acontece na
        # rotina após recalibração ou troca de frasco. É essa variação entre dias
        # que separa a repetibilidade da precisão intermediária — sem ela, os
        # dois números sairiam iguais e o desenho de 5 dias pareceria inútil.
        replicas_por_nivel = {
            1: [
                [0.580, 0.593, 0.585, 0.598, 0.585],
                [0.596, 0.609, 0.601, 0.614, 0.601],
                [0.602, 0.615, 0.607, 0.620, 0.607],
                [0.586, 0.599, 0.591, 0.604, 0.591],
                [0.600, 0.613, 0.605, 0.618, 0.605],
            ],
            2: [
                [1.271, 1.289, 1.278, 1.295, 1.278],
                [1.294, 1.312, 1.301, 1.318, 1.301],
                [1.302, 1.320, 1.309, 1.326, 1.309],
                [1.281, 1.299, 1.288, 1.305, 1.288],
                [1.299, 1.317, 1.306, 1.323, 1.306],
            ],
            3: [
                [3.152, 3.181, 3.163, 3.192, 3.163],
                [3.190, 3.219, 3.201, 3.230, 3.201],
                [3.204, 3.233, 3.215, 3.244, 3.215],
                [3.168, 3.197, 3.179, 3.208, 3.179],
                [3.198, 3.227, 3.209, 3.238, 3.209],
            ],
        }

        for numero, corridas in replicas_por_nivel.items():
            controle = Controle.objects.get(sistema=teste, nivel=numero)
            nivel, criado = NivelEstudo.objects.get_or_create(
                estudo=estudo,
                numero=numero,
                defaults={"controle": controle, "concentracao_declarada": controle.valor_alvo},
            )
            if not criado:
                continue
            for indice_corrida, valores in enumerate(corridas, start=1):
                for sequencia, valor in enumerate(valores, start=1):
                    Replica.objects.create(
                        nivel=nivel,
                        corrida=indice_corrida,
                        sequencia=sequencia,
                        valor=Decimal(str(valor)),
                    )

        # Comparabilidade: 40 amostras cobrindo a faixa analítica, com um erro
        # proporcional leve (o método novo lê cerca de 6% acima) para o estudo
        # ter algo a mostrar.
        if not estudo.amostras_comparacao.exists():
            base = [
                0.32, 0.45, 0.58, 0.71, 0.84, 0.92, 1.05, 1.18, 1.26, 1.34,
                1.47, 1.55, 1.68, 1.79, 1.92, 2.10, 2.35, 2.58, 2.84, 3.05,
                3.32, 3.61, 3.95, 4.28, 4.62, 5.05, 5.48, 5.92, 6.35, 6.81,
                7.24, 7.68, 8.12, 8.55, 9.02, 9.48, 9.95, 10.42, 10.88, 11.35,
            ]
            desvios = [
                0.02, -0.01, 0.03, 0.00, 0.02, -0.02, 0.01, 0.03, -0.01, 0.02,
                0.00, 0.03, -0.02, 0.01, 0.02, -0.01, 0.04, 0.02, -0.03, 0.01,
                0.03, -0.02, 0.05, 0.01, -0.04, 0.02, 0.06, -0.03, 0.02, 0.04,
                -0.05, 0.03, 0.07, -0.02, 0.04, -0.06, 0.03, 0.05, -0.04, 0.02,
            ]
            for indice, (valor, desvio) in enumerate(zip(base, desvios), start=1):
                AmostraComparacao.objects.create(
                    estudo=estudo,
                    identificacao=f"AM-{indice:03d}",
                    valor_comparacao=Decimal(str(round(valor, 4))),
                    valor_teste=Decimal(str(round(valor * 1.06 + 0.02 + desvio, 4))),
                )

    def _outras_colunas(self, laboratorio, usuario, teste, comparacao):
        """Mais três validações, uma por coluna do quadro.

        Com um estudo só o quadro não demonstra nada. Estas três mostram o
        caminho inteiro: rascunho sem dado, coleta em andamento e um estudo já
        liberado — inclusive uma ficha com pendência, que a biblioteca sinaliza.
        """
        # 1. Rascunho — ficha incompleta de propósito: falta a imprecisão.
        ferritina, _ = Mensurando.objects.get_or_create(
            laboratorio=laboratorio, nome="Ferritina", material_biologico="soro",
            defaults={"unidade_medida": "ng/mL"},
        )
        ficha_ferritina, _ = EspecificacaoQualidade.objects.get_or_create(
            laboratorio=laboratorio, mensurando=ferritina, nome="Ferritina — ControlLab 2026",
            defaults={
                "erro_total_maximo_pct": Decimal("20.00"),
                "fonte": EspecificacaoQualidade.PROFICIENCIA,
                "fonte_descricao": "provedor de ensaio de proficiência ControlLab",
            },
        )
        Estudo.objects.get_or_create(
            laboratorio=laboratorio, identificacao="Validação Ferritina — a definir",
            defaults={
                "modulo": Assinatura.COMPLETO, "mensurando": ferritina,
                "sistema_teste": teste, "sistema_comparacao": comparacao,
                "especificacao": ficha_ferritina, "criado_por": usuario,
            },
        )

        # 2. Coletando dados — corrida única, metade das réplicas lançadas.
        hba1c, _ = Mensurando.objects.get_or_create(
            laboratorio=laboratorio, nome="HbA1c", material_biologico="sangue total",
            defaults={"unidade_medida": "%"},
        )
        ficha_hba1c, criada = EspecificacaoQualidade.objects.get_or_create(
            laboratorio=laboratorio, mensurando=hba1c, nome="HbA1c — estado da arte",
            defaults={
                "erro_total_maximo_pct": Decimal("6.00"),
                "fonte": EspecificacaoQualidade.ESTADO_DA_ARTE,
                "fonte_descricao": "desempenho do grupo de pares no método",
            },
        )
        if criada:
            LimiteImprecisao.objects.create(
                especificacao=ficha_hba1c, nivel=1, maximo_pct=Decimal("0.00"), referencia=""
            )
            ficha_hba1c.sincronizar_imprecisao()

        controle_hba1c, _ = Controle.objects.get_or_create(
            sistema=teste, nivel=1, lote="A1C-2026B",
            defaults={"nome": "Controle HbA1c Nível 1", "validade": date(2027, 6, 30),
                      "valor_alvo": Decimal("5.6000")},
        )
        em_coleta, criado = Estudo.objects.get_or_create(
            laboratorio=laboratorio, identificacao="Validação HbA1c — Atellica IH00715",
            defaults={
                "modulo": Assinatura.PRECISAO, "mensurando": hba1c,
                "desenho_precisao": precisao.DESENHO_CORRIDA_UNICA,
                "sistema_teste": teste, "especificacao": ficha_hba1c, "criado_por": usuario,
            },
        )
        if criado:
            nivel = NivelEstudo.objects.create(
                estudo=em_coleta, numero=1, controle=controle_hba1c,
                concentracao_declarada=Decimal("5.6000"),
            )
            for sequencia, valor in enumerate(
                ["5.58", "5.62", "5.59", "5.61", "5.57", "5.63"], start=1
            ):
                Replica.objects.create(nivel=nivel, corrida=1, sequencia=sequencia, valor=Decimal(valor))

        # 3. Liberado — veredito congelado, como fica depois da assinatura.
        glicose, _ = Mensurando.objects.get_or_create(
            laboratorio=laboratorio, nome="Glicose", material_biologico="plasma",
            defaults={"unidade_medida": "mg/dL"},
        )
        ficha_glicose, criada = EspecificacaoQualidade.objects.get_or_create(
            laboratorio=laboratorio, mensurando=glicose, nome="Glicose — ControlLab 2026",
            defaults={
                "erro_total_maximo_pct": Decimal("8.00"),
                "fonte": EspecificacaoQualidade.PROFICIENCIA,
                "fonte_descricao": "provedor de ensaio de proficiência ControlLab",
            },
        )
        if criada:
            LimiteImprecisao.objects.create(
                especificacao=ficha_glicose, nivel=1, maximo_pct=Decimal("0.00"), referencia=""
            )
            ficha_glicose.sincronizar_imprecisao()

        controle_glicose, _ = Controle.objects.get_or_create(
            sistema=teste, nivel=1, lote="GLI-2025C",
            defaults={"nome": "Controle Química Nível 1", "validade": date(2026, 12, 31),
                      "valor_alvo": Decimal("95.0000")},
        )

        liberado, criado = Estudo.objects.get_or_create(
            laboratorio=laboratorio, identificacao="Validação Glicose — Atellica IH00715 — 2025",
            defaults={
                "modulo": Assinatura.COMPLETO, "mensurando": glicose,
                "sistema_teste": teste, "sistema_comparacao": comparacao,
                "especificacao": ficha_glicose, "criado_por": usuario,
                "situacao": Estudo.LIBERADO,
                "data_inicio": date(2025, 11, 3),
                "data_conclusao": date(2025, 11, 21),
            },
        )
        if criado:
            # Estudo completo de verdade, não uma casca: é dele que sai o retrato
            # congelado. Um veredito de demonstração com detalhamento vazio faria
            # a tela mostrar campo em branco onde deveria haver número assinado.
            nivel = NivelEstudo.objects.create(
                estudo=liberado, numero=1, controle=controle_glicose,
                concentracao_declarada=Decimal("95.0000"),
            )
            corridas = [
                ["94.2", "95.1", "94.7", "95.4", "94.6"],
                ["95.0", "95.9", "95.5", "96.2", "95.4"],
                ["94.6", "95.5", "95.1", "95.8", "95.0"],
                ["95.3", "96.2", "95.8", "96.5", "95.7"],
                ["94.9", "95.8", "95.4", "96.1", "95.3"],
            ]
            for numero_corrida, valores in enumerate(corridas, start=1):
                for sequencia, valor in enumerate(valores, start=1):
                    Replica.objects.create(
                        nivel=nivel, corrida=numero_corrida,
                        sequencia=sequencia, valor=Decimal(valor),
                    )

            # 40 amostras pareadas: o mínimo do CLSI EP09, cobrindo do
            # hipoglicêmico ao diabético descompensado. O método novo lê 1%
            # acima do antigo mais 0,5 mg/dL — um viés pequeno e constante.
            for indice in range(40):
                referencia = Decimal("58") + Decimal("7.4") * indice
                desvio = Decimal("0.6") if indice % 3 == 0 else Decimal("-0.4")
                AmostraComparacao.objects.create(
                    estudo=liberado, identificacao=f"GLI-{indice + 1:03d}",
                    valor_comparacao=referencia,
                    valor_teste=(referencia * Decimal("1.01") + Decimal("0.5") + desvio).quantize(
                        Decimal("0.01")
                    ),
                )

            resultado = servicos.retrato(liberado)
            Veredito.objects.create(
                estudo=liberado, resultado=resultado["veredito"]["status"],
                detalhamento=resultado,
                liberado_por=usuario,
                # A liberação acompanha a conclusão do estudo. Com timezone.now()
                # a demonstração mostrava um estudo concluído em 2025 e liberado
                # no ano seguinte — incoerência que salta aos olhos no card.
                liberado_em=timezone.make_aware(datetime(2025, 11, 21, 15, 40)),
            )

