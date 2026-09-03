"""Testes da ficha de analito — a fonte dos limites que toda validação herda."""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from contas.models import Laboratorio, Usuario

from .models import EspecificacaoQualidade, LimiteImprecisao, Mensurando


def montar_ficha(**campos) -> EspecificacaoQualidade:
    # get_or_create para o mesmo teste poder montar várias fichas sem esbarrar
    # na unicidade do CNPJ.
    laboratorio, _ = Laboratorio.objects.get_or_create(
        cnpj="11.111.111/0001-11", defaults={"razao_social": "Lab A"}
    )
    mensurando, _ = Mensurando.objects.get_or_create(
        laboratorio=laboratorio, nome="FT4", material_biologico="soro",
        defaults={"unidade_medida": "ng/dL"},
    )
    padrao = {
        "laboratorio": laboratorio,
        "mensurando": mensurando,
        "nome": "FT4 — ControlLab 2026",
        "erro_total_maximo_pct": Decimal("12.00"),
        "fonte": EspecificacaoQualidade.PROFICIENCIA,
        "fonte_descricao": "provedor de ensaio de proficiência ControlLab",
    }
    return EspecificacaoQualidade.objects.create(**{**padrao, **campos})


class TestHerancaDaFicha(TestCase):
    def test_a_fonte_escreve_a_justificativa_do_erro_total(self):
        # É o que o usuário não quer digitar, e o que o auditor cobra.
        ficha = montar_ficha()

        self.assertEqual(
            ficha.erro_total_referencia,
            "Limite de aceitabilidade do provedor de ensaio de proficiência ControlLab",
        )

    def test_o_bias_nasce_como_metade_do_erro_total(self):
        ficha = montar_ficha()

        self.assertEqual(ficha.bias_maximo_pct, Decimal("6.00"))
        self.assertTrue(ficha.bias_referencia.startswith("50% do limite de aceitabilidade"))

    def test_mudar_o_erro_total_arrasta_o_bias(self):
        ficha = montar_ficha()

        ficha.erro_total_maximo_pct = Decimal("20.00")
        ficha.save()

        self.assertEqual(ficha.bias_maximo_pct, Decimal("10.00"))

    def test_bias_desvinculado_permanece_como_foi_digitado(self):
        # Um valor que o laboratório digitou é dele; a derivação não o atropela.
        ficha = montar_ficha(bias_derivado=False, bias_maximo_pct=Decimal("3.00"))

        ficha.erro_total_maximo_pct = Decimal("20.00")
        ficha.save()

        self.assertEqual(ficha.bias_maximo_pct, Decimal("3.00"))

    def test_a_imprecisao_derivada_se_espalha_pelos_niveis(self):
        ficha = montar_ficha()
        for nivel in (1, 2, 3):
            LimiteImprecisao.objects.create(
                especificacao=ficha, nivel=nivel, maximo_pct=Decimal("0.00"), referencia=""
            )

        ficha.sincronizar_imprecisao()

        limites = list(ficha.limites_imprecisao.order_by("nivel"))
        self.assertEqual([limite.maximo_pct for limite in limites], [Decimal("3.00")] * 3)
        self.assertTrue(all(limite.referencia.startswith("1/4 do limite") for limite in limites))

    def test_fonte_manual_nao_escreve_justificativa(self):
        # Quem escolhe "manual" assume escrever a própria justificativa.
        ficha = montar_ficha(fonte=EspecificacaoQualidade.MANUAL, fonte_descricao="")

        self.assertEqual(ficha.erro_total_referencia, "")

    def test_variacao_biologica_redige_diferente(self):
        ficha = montar_ficha(
            fonte=EspecificacaoQualidade.VARIACAO_BIOLOGICA, fonte_descricao="base EFLM"
        )

        self.assertIn("variação biológica", ficha.erro_total_referencia)


class TestTensaoEntreOsLimites(TestCase):
    def test_os_limites_derivados_nunca_estouram_o_teto(self):
        """A partição derivada tem de ser aritmeticamente coerente.

        Este teste existe porque a primeira versão não era: com bias em 1/2 e
        imprecisão em 1/3 do erro total, o alerta disparava em toda ficha
        derivada — 1,05 vezes o teto, sempre. Um alerta que acende sempre não
        informa nada e desmoraliza o caso em que a contradição é real.
        """
        for teto in ("6.00", "8.00", "12.00", "20.00", "33.00"):
            with self.subTest(erro_total=teto):
                ficha = montar_ficha(
                    nome=f"FT4 — teto {teto}", erro_total_maximo_pct=Decimal(teto)
                )
                LimiteImprecisao.objects.create(
                    especificacao=ficha, nivel=1, maximo_pct=Decimal("0.00"), referencia=""
                )
                ficha.sincronizar_imprecisao()

                self.assertFalse(
                    ficha.sub_limites_excedem_o_erro_total(),
                    f"limites derivados de {teto}% estouraram o próprio teto",
                )

    def test_os_sub_limites_digitados_a_mao_podem_estourar_o_erro_total(self):
        # Um laboratório que digita bias 6% e CV 4% cria uma contradição: um
        # método parado nos dois limites daria 12,6%, acima do máximo de 12% que
        # ele mesmo declarou. A ficha mostra isso em vez de esconder.
        ficha = montar_ficha(imprecisao_derivada=False)
        LimiteImprecisao.objects.create(
            especificacao=ficha, nivel=1, maximo_pct=Decimal("4.00"), referencia="digitada"
        )

        self.assertEqual(ficha.erro_total_implicito(), Decimal("12.60"))
        self.assertTrue(ficha.sub_limites_excedem_o_erro_total())

    def test_sem_imprecisao_cadastrada_nao_ha_o_que_comparar(self):
        ficha = montar_ficha()

        self.assertIsNone(ficha.erro_total_implicito())
        self.assertFalse(ficha.sub_limites_excedem_o_erro_total())

    def test_limites_folgados_nao_disparam_o_alerta(self):
        ficha = montar_ficha(bias_derivado=False, bias_maximo_pct=Decimal("2.00"))
        LimiteImprecisao.objects.create(
            especificacao=ficha, nivel=1, maximo_pct=Decimal("2.00"), referencia="manual"
        )

        self.assertFalse(ficha.sub_limites_excedem_o_erro_total())


class TestBiblioteca(TestCase):
    def setUp(self):
        self.ficha = montar_ficha()
        LimiteImprecisao.objects.create(
            especificacao=self.ficha, nivel=1, maximo_pct=Decimal("4.00"), referencia="1/3 do limite"
        )
        self.usuario = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste", laboratorio=self.ficha.laboratorio
        )

    def test_a_grade_mostra_a_ficha_do_laboratorio(self):
        self.client.force_login(self.usuario)

        resposta = self.client.get(reverse("biblioteca"))

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "FT4")
        self.assertContains(resposta, "12,00")

    def test_ficha_de_outro_laboratorio_nao_aparece(self):
        outro = Laboratorio.objects.create(razao_social="Lab B", cnpj="22.222.222/0001-22")
        intruso = Usuario.objects.create_user(
            username="intruso", password="senha-longa-de-teste", laboratorio=outro
        )
        self.client.force_login(intruso)

        resposta = self.client.get(reverse("biblioteca"))

        self.assertNotContains(resposta, "FT4")

    def test_visitante_vai_para_o_login(self):
        self.assertEqual(self.client.get(reverse("biblioteca")).status_code, 302)

    def test_ficha_incompleta_aparece_como_pendencia(self):
        # Sem imprecisão definida a ficha não sustenta veredito, e a grade avisa
        # antes de o laboratório descobrir isso no fim do estudo.
        self.ficha.limites_imprecisao.all().delete()
        self.client.force_login(self.usuario)

        resposta = self.client.get(reverse("biblioteca"))

        self.assertContains(resposta, "Com pendência")
