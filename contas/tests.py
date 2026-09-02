"""Testes da liberação de módulos contratados.

Estes testes guardam a regra comercial do produto: o que cada plano libera, e o
fato de que o pacote completo cobre os módulos isolados sem precisar de três
assinaturas separadas.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

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
