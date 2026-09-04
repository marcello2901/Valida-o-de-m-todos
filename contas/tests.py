"""Testes da liberação de módulos contratados.

Estes testes guardam a regra comercial do produto: o que cada plano libera, e o
fato de que o pacote completo cobre os módulos isolados sem precisar de três
assinaturas separadas.
"""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from catalogo.models import Mensurando, Reagente, SistemaAnalitico

from .models import Assinatura, Laboratorio, Usuario


def criar_laboratorio(**campos):
    padrao = {"razao_social": "Laboratório Exemplo Ltda", "cnpj": "00.000.000/0001-00"}
    return Laboratorio.objects.create(**{**padrao, **campos})


class TestLiberacaoDeModulos(TestCase):
    def setUp(self):
        self.laboratorio = criar_laboratorio()

    def test_sem_assinatura_nada_e_liberado(self):
        self.assertFalse(self.laboratorio.pode_usar(Assinatura.PRECISAO))
        self.assertFalse(self.laboratorio.pode_usar(Assinatura.COMPARABILIDADE))
        self.assertFalse(self.laboratorio.pode_usar(Assinatura.COMPLETO))

    def test_assinatura_isolada_libera_apenas_o_proprio_modulo(self):
        Assinatura.objects.create(laboratorio=self.laboratorio, modulo=Assinatura.PRECISAO)

        self.assertTrue(self.laboratorio.pode_usar(Assinatura.PRECISAO))
        self.assertFalse(self.laboratorio.pode_usar(Assinatura.COMPARABILIDADE))

    def test_pacote_completo_cobre_os_modulos_isolados(self):
        # Quem compra o pacote não precisa de três assinaturas.
        Assinatura.objects.create(laboratorio=self.laboratorio, modulo=Assinatura.COMPLETO)

        self.assertTrue(self.laboratorio.pode_usar(Assinatura.PRECISAO))
        self.assertTrue(self.laboratorio.pode_usar(Assinatura.COMPARABILIDADE))
        self.assertTrue(self.laboratorio.pode_usar(Assinatura.COMPLETO))

    def test_assinatura_vencida_nao_libera(self):
        ontem = timezone.localdate() - timedelta(days=1)
        Assinatura.objects.create(
            laboratorio=self.laboratorio,
            modulo=Assinatura.COMPLETO,
            inicio=ontem - timedelta(days=30),
            fim=ontem,
        )

        self.assertFalse(self.laboratorio.pode_usar(Assinatura.COMPLETO))

    def test_assinatura_futura_ainda_nao_libera(self):
        amanha = timezone.localdate() + timedelta(days=1)
        Assinatura.objects.create(
            laboratorio=self.laboratorio, modulo=Assinatura.PRECISAO, inicio=amanha
        )

        self.assertFalse(self.laboratorio.pode_usar(Assinatura.PRECISAO))

    def test_assinatura_sem_prazo_final_permanece_vigente(self):
        Assinatura.objects.create(
            laboratorio=self.laboratorio, modulo=Assinatura.PRECISAO, fim=None
        )

        self.assertTrue(self.laboratorio.pode_usar(Assinatura.PRECISAO))


class TestUsuario(TestCase):
    def setUp(self):
        self.laboratorio = criar_laboratorio()

    def test_apenas_responsavel_tecnico_assina_relatorio(self):
        analista = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste", laboratorio=self.laboratorio
        )
        responsavel = Usuario.objects.create_user(
            username="responsavel",
            password="senha-longa-de-teste",
            laboratorio=self.laboratorio,
            funcao=Usuario.RESPONSAVEL,
        )

        self.assertFalse(analista.pode_assinar_relatorio())
        self.assertTrue(responsavel.pode_assinar_relatorio())

    def test_usuario_novo_entra_como_analista(self):
        # Permissão de assinar é concedida, nunca presumida.
        usuario = Usuario.objects.create_user(
            username="novo", password="senha-longa-de-teste", laboratorio=self.laboratorio
        )

        self.assertEqual(usuario.funcao, Usuario.ANALISTA)


class TestConfiguracoes(TestCase):
    """A tela de configurações: mesmo cartão do resto do programa."""

    def setUp(self):
        self.laboratorio = Laboratorio.objects.create(
            razao_social="Lab A", cnpj="11.111.111/0001-11", responsavel_tecnico="Dra. Fulana"
        )
        Assinatura.objects.create(laboratorio=self.laboratorio, modulo=Assinatura.COMPLETO)
        self.usuario = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.RESPONSAVEL,
        )
        self.sistema = SistemaAnalitico.objects.create(
            laboratorio=self.laboratorio, papel=SistemaAnalitico.TESTE,
            equipamento="Atellica", numero_serie="IH00715", metodologia="Quimioluminescência",
        )
        self.url = reverse("configuracoes")
        self.client.force_login(self.usuario)

    def test_mostra_laboratorio_equipe_e_equipamento(self):
        resposta = self.client.get(self.url)

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Lab A")
        self.assertContains(resposta, "Dra. Fulana")
        self.assertContains(resposta, "IH00715")

    def test_nomeia_o_papel_do_sistema_por_extenso_curto(self):
        # O rótulo longo truncado virava "Sistema ...", que não distingue o
        # sistema em teste do de comparação.
        resposta = self.client.get(self.url)

        self.assertContains(resposta, "S.A. em teste")

    def test_insumo_vencido_aparece_marcado(self):
        Reagente.objects.create(
            sistema=self.sistema, nome="Reagente velho", lote="L1",
            validade=timezone.localdate() - timedelta(days=1),
        )

        resposta = self.client.get(self.url)

        self.assertContains(resposta, "vencido")

    def test_insumo_proximo_do_vencimento_avisa_com_antecedencia(self):
        Reagente.objects.create(
            sistema=self.sistema, nome="Reagente a vencer", lote="L2",
            validade=timezone.localdate() + timedelta(days=10),
        )

        resposta = self.client.get(self.url)

        self.assertContains(resposta, "vence em 10 d")

    def test_analito_sem_intervalo_de_referencia_e_sinalizado(self):
        Mensurando.objects.create(
            laboratorio=self.laboratorio, nome="Ferritina",
            unidade_medida="ng/mL", material_biologico="soro",
        )

        resposta = self.client.get(self.url)

        self.assertContains(resposta, "concordância clínica não é calculada")

    def test_laboratorio_alheio_nao_aparece(self):
        outro = Laboratorio.objects.create(razao_social="Lab B", cnpj="22.222.222/0001-22")
        SistemaAnalitico.objects.create(
            laboratorio=outro, papel=SistemaAnalitico.TESTE,
            equipamento="Cobas", numero_serie="ZZ99999", metodologia="Eletroquimioluminescência",
        )

        resposta = self.client.get(self.url)

        self.assertNotContains(resposta, "ZZ99999")

    def test_visitante_vai_para_o_login(self):
        self.client.logout()

        self.assertEqual(self.client.get(self.url).status_code, 302)
