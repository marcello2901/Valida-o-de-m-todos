"""Testes de fumaça do painel administrativo.

Existem por causa de uma falha real: um mixin de permissão repassava um
argumento a mais para ``ModelAdmin.has_add_permission``, que só aceita
``request``. O erro não aparecia na tela do estudo — aparecia em **toda** página
do painel, porque o menu lateral chama ``get_model_perms`` de cada admin
registrado. Nenhum teste pegava, porque não havia nenhum teste de painel.

O que estes testes fazem é simples e cobre a classe inteira do problema: abrem a
listagem e a tela de edição de cada modelo registrado. Qualquer assinatura
errada, campo inexistente num ``fieldsets`` ou inline mal configurado aparece
como 500 aqui, e não no navegador do laboratório.
"""

from django.contrib import admin
from django.test import TestCase
from django.urls import reverse

from contas.models import Usuario
from estudos.models import Estudo

from .tests import montar_estudo, montar_laboratorio


class TestPainelAdministrativo(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        cls.dono = Usuario.objects.create_user(
            username="dono", password="senha-longa-de-teste", laboratorio=cls.laboratorio
        )
        cls.estudo = montar_estudo(cls.laboratorio, cls.dono)
        cls.equipe = Usuario.objects.create_superuser(
            username="suporte", password="senha-longa-de-teste", email="suporte@exemplo.com"
        )

    def setUp(self):
        self.client.force_login(self.equipe)

    def test_o_indice_do_painel_abre(self):
        # É aqui que a falha se manifestava: o índice monta a lista de todos os
        # modelos registrados e pergunta as permissões de cada um.
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)

    def test_todas_as_listagens_abrem(self):
        for modelo, _ in admin.site._registry.items():
            rotulo = modelo._meta.app_label
            nome = modelo._meta.model_name
            with self.subTest(modelo=f"{rotulo}.{nome}"):
                url = reverse(f"admin:{rotulo}_{nome}_changelist")

                self.assertEqual(self.client.get(url).status_code, 200)

    def test_todas_as_telas_de_edicao_abrem(self):
        for modelo, opcoes in admin.site._registry.items():
            objeto = modelo.objects.first()
            if objeto is None:
                continue
            rotulo = modelo._meta.app_label
            nome = modelo._meta.model_name
            with self.subTest(modelo=f"{rotulo}.{nome}"):
                url = reverse(f"admin:{rotulo}_{nome}_change", args=[objeto.pk])
                resposta = self.client.get(url)

                # Veredito é somente leitura: o painel redireciona para a lista.
                self.assertIn(resposta.status_code, (200, 302))

    def test_as_telas_de_cadastro_novo_abrem(self):
        for modelo, opcoes in admin.site._registry.items():
            if not opcoes.has_add_permission(self._pedido()):
                continue
            rotulo = modelo._meta.app_label
            nome = modelo._meta.model_name
            with self.subTest(modelo=f"{rotulo}.{nome}"):
                url = reverse(f"admin:{rotulo}_{nome}_add")

                self.assertEqual(self.client.get(url).status_code, 200)

    def test_estudo_liberado_abre_em_somente_leitura(self):
        # O caminho que o mixin protege: nenhum campo editável, e sem erro.
        self.estudo.situacao = Estudo.LIBERADO
        self.estudo.save(update_fields=["situacao"])
        url = reverse("admin:estudos_estudo_change", args=[self.estudo.pk])

        resposta = self.client.get(url)

        self.assertEqual(resposta.status_code, 200)
        self.assertNotContains(resposta, 'name="identificacao"')

    def _pedido(self):
        """Uma requisição autenticada, para perguntar permissões fora da view."""
        from django.test import RequestFactory

        pedido = RequestFactory().get("/admin/")
        pedido.user = self.equipe
        return pedido
