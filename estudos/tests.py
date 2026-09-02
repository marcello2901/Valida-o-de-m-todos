"""Testes da tela de resultado e do isolamento entre laboratórios.

O primeiro bloco guarda uma propriedade de segurança: um laboratório nunca pode
ver o estudo de outro. É o tipo de falha que não aparece no uso normal — só
quando alguém troca o número na barra de endereço — e por isso precisa de teste.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from catalogo.models import (
    Controle,
    EspecificacaoQualidade,
    LimiteImprecisao,
    Mensurando,
    SistemaAnalitico,
)
from contas.models import Assinatura, Laboratorio, Usuario
from estudos.models import AmostraComparacao, Estudo, NivelEstudo, Replica
from motor import precisao


def montar_laboratorio(nome: str, cnpj: str) -> Laboratorio:
    laboratorio = Laboratorio.objects.create(razao_social=nome, cnpj=cnpj)
    Assinatura.objects.create(laboratorio=laboratorio, modulo=Assinatura.COMPLETO)
    return laboratorio


def montar_estudo(laboratorio: Laboratorio, usuario: Usuario) -> Estudo:
    mensurando = Mensurando.objects.create(
        laboratorio=laboratorio,
        nome="FT4",
        unidade_medida="ng/dL",
        material_biologico="soro",
        referencia_inferior=Decimal("0.8"),
        referencia_superior=Decimal("1.8"),
    )
    teste = SistemaAnalitico.objects.create(
        laboratorio=laboratorio, papel=SistemaAnalitico.TESTE,
        equipamento="Atellica", numero_serie="IH00715", metodologia="Quimioluminescência",
    )
    comparacao = SistemaAnalitico.objects.create(
        laboratorio=laboratorio, papel=SistemaAnalitico.COMPARACAO,
        equipamento="Centaur", numero_serie="CE04412", metodologia="Quimioluminescência",
    )
    controle = Controle.objects.create(
        sistema=teste, nivel=1, nome="Controle 1", lote="L1",
        validade=date(2027, 1, 1), valor_alvo=Decimal("1.3"),
    )
    especificacao = EspecificacaoQualidade.objects.create(
        laboratorio=laboratorio, mensurando=mensurando, nome="FT4 — ControlLab",
        erro_total_maximo_pct=Decimal("12.00"), erro_total_referencia="ControlLab",
        bias_maximo_pct=Decimal("6.00"), bias_referencia="50% do ControlLab",
    )
    LimiteImprecisao.objects.create(
        especificacao=especificacao, nivel=1, maximo_pct=Decimal("4.00"), referencia="1/3 do ControlLab"
    )

    estudo = Estudo.objects.create(
        laboratorio=laboratorio,
        identificacao="Validação FT4",
        modulo=Assinatura.COMPLETO,
        desenho_precisao=precisao.DESENHO_MULTIPLAS_CORRIDAS,
        mensurando=mensurando,
        sistema_teste=teste,
        sistema_comparacao=comparacao,
        especificacao=especificacao,
        criado_por=usuario,
    )

    nivel = NivelEstudo.objects.create(
        estudo=estudo, numero=1, controle=controle, concentracao_declarada=Decimal("1.3")
    )
    for corrida in range(1, 6):
        for sequencia, valor in enumerate(["1.28", "1.30", "1.32", "1.29", "1.31"], start=1):
            Replica.objects.create(
                nivel=nivel, corrida=corrida, sequencia=sequencia,
                valor=Decimal(valor) + Decimal("0.005") * corrida,
            )
    for indice in range(1, 11):
        base = Decimal("0.5") * indice
        AmostraComparacao.objects.create(
            estudo=estudo, identificacao=f"AM-{indice:03d}",
            valor_comparacao=base, valor_teste=base * Decimal("1.02"),
        )
    return estudo


class TestIsolamentoEntreLaboratorios(TestCase):
    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.dono = Usuario.objects.create_user(
            username="dono", password="senha-longa-de-teste", laboratorio=self.laboratorio
        )
        self.estudo = montar_estudo(self.laboratorio, self.dono)
        self.url = reverse("resultado_estudo", args=[self.estudo.pk])

    def test_dono_do_estudo_ve_o_resultado(self):
        self.client.force_login(self.dono)

        resposta = self.client.get(self.url)

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Validação FT4")

    def test_outro_laboratorio_nao_ve_o_estudo(self):
        # Trocar o número na barra de endereço não pode revelar dado alheio.
        outro = montar_laboratorio("Lab B", "22.222.222/0001-22")
        intruso = Usuario.objects.create_user(
            username="intruso", password="senha-longa-de-teste", laboratorio=outro
        )
        self.client.force_login(intruso)

        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_usuario_sem_laboratorio_nao_ve_o_estudo(self):
        avulso = Usuario.objects.create_user(username="avulso", password="senha-longa-de-teste")
        self.client.force_login(avulso)

        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_equipe_interna_ve_qualquer_estudo(self):
        # Suporte da plataforma precisa enxergar para atender o cliente.
        suporte = Usuario.objects.create_user(
            username="suporte", password="senha-longa-de-teste", is_staff=True
        )
        self.client.force_login(suporte)

        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_visitante_nao_autenticado_e_mandado_para_o_login(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)


class TestConteudoDoResultado(TestCase):
    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.dono = Usuario.objects.create_user(
            username="dono", password="senha-longa-de-teste", laboratorio=self.laboratorio
        )
        self.estudo = montar_estudo(self.laboratorio, self.dono)
        self.client.force_login(self.dono)
        self.resposta = self.client.get(reverse("resultado_estudo", args=[self.estudo.pk]))

    def test_traz_as_secoes_de_calculo(self):
        for secao in ["Precisão", "Comparabilidade", "Veredito por nível", "Rastreabilidade"]:
            self.assertContains(self.resposta, secao)

    def test_traz_as_medidas_pedidas(self):
        for medida in [
            "Erro sistemático médio",
            "Regressão de Deming",
            "Passing-Bablok",
            "Concordância de Lin",
            "Grau de concordância",
        ]:
            self.assertContains(self.resposta, medida)

    def test_desenha_os_graficos(self):
        # Os gráficos são SVG embutido; sem biblioteca externa, sem JavaScript.
        self.assertContains(self.resposta, "<svg")
        self.assertContains(self.resposta, "Levey-Jennings")

    def test_mostra_a_referencia_cientifica_de_cada_limite(self):
        self.assertContains(self.resposta, "ControlLab")

    def test_avisa_quando_faltam_amostras_para_o_ep09(self):
        # O estudo tem 10 amostras; o EP09 pede 40.
        self.assertContains(self.resposta, "CLSI EP09")

    def test_nao_vaza_o_estudo_no_titulo_de_erro(self):
        outro = montar_laboratorio("Lab B", "22.222.222/0001-22")
        intruso = Usuario.objects.create_user(
            username="intruso", password="senha-longa-de-teste", laboratorio=outro
        )
        self.client.force_login(intruso)

        resposta = self.client.get(reverse("resultado_estudo", args=[self.estudo.pk]))

        self.assertNotContains(resposta, "Validação FT4", status_code=404)
