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


class TestFormularioDoEstudoNoPainel(TestCase):
    """O cadastro do estudo pede só o que se decide no cadastro.

    A média interlaboratorial e o nome do programa saíram do formulário do
    estudo: quem os preenche é quem tem o boletim do programa na mão, na hora de
    digitar as réplicas daquele lote. Aqui ficavam em branco.
    """

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.suporte = Usuario.objects.create_user(
            username="suporte", password="senha-longa-de-teste",
            is_staff=True, is_superuser=True,
        )
        self.estudo = montar_estudo(self.laboratorio, self.suporte)
        self.client.force_login(self.suporte)

    def test_o_nivel_pede_so_numero_e_material(self):
        from estudos.admin import NivelEstudoInline

        self.assertEqual(NivelEstudoInline.fields, ["numero", "controle"])

    def test_a_tela_do_estudo_nao_pede_concentracao_nem_media(self):
        resposta = self.client.get(
            reverse("admin:estudos_estudo_change", args=[self.estudo.pk])
        )

        corpo = resposta.content.decode()
        self.assertNotIn("Concentração declarada", corpo)
        self.assertNotIn("niveis-0-media_interlaboratorial", corpo)
        self.assertNotIn("niveis-0-provedor_interlaboratorial", corpo)
        self.assertIn("niveis-0-controle", corpo)


class TestExplicacaoDeAcessoNoPainel(TestCase):
    """O formulário de usuário diz qual mecanismo controla o quê.

    O programa tem dois sistemas de acesso paralelos: a *função* governa as
    telas do laboratório e o par ``is_staff`` + grupos governa só este painel.
    Quem monta um grupo com todas as permissões e não marca "membro da equipe"
    não abre nada — e passa uma tarde procurando o motivo. O formulário precisa
    dizer isso onde a decisão é tomada.
    """

    def setUp(self):
        self.suporte = Usuario.objects.create_user(
            username="suporte", password="senha-longa-de-teste",
            is_staff=True, is_superuser=True,
        )
        self.client.force_login(self.suporte)

    def test_o_formulario_avisa_que_grupo_sozinho_nao_abre_o_painel(self):
        resposta = self.client.get(
            reverse("admin:contas_usuario_change", args=[self.suporte.pk])
        )

        self.assertContains(resposta, "membro da equipe")
        self.assertContains(resposta, "nem grupo nem permissão individual")

    def test_o_formulario_diz_que_o_programa_usa_a_funcao(self):
        resposta = self.client.get(
            reverse("admin:contas_usuario_change", args=[self.suporte.pk])
        )

        self.assertContains(resposta, "governadas pela")
        self.assertContains(resposta, "sem depender de grupo")

    def test_a_lista_mostra_quem_acessa_o_painel(self):
        resposta = self.client.get(reverse("admin:contas_usuario_changelist"))

        self.assertContains(resposta, "Acessa cadastros")

    def test_permissao_de_grupo_chega_ao_usuario(self):
        # Guarda o que foi medido: o mecanismo do Django funciona. Se um dia
        # deixar de funcionar — backend de autenticação trocado, campo groups
        # redefinido — este teste falha antes de o cliente descobrir.
        from django.contrib.auth.models import Group, Permission

        permissao = Permission.objects.get(codename="change_estudo")
        grupo = Group.objects.create(name="Analista")
        grupo.permissions.add(permissao)

        pessoa = Usuario.objects.create_user(
            username="alcindo", password="senha-longa-de-teste", is_staff=True
        )
        pessoa.groups.add(grupo)

        pessoa = Usuario.objects.get(pk=pessoa.pk)
        self.assertTrue(pessoa.has_perm("estudos.change_estudo"))

    def test_sem_membro_da_equipe_nem_o_superusuario_entra_no_painel(self):
        # A trava que confundia: as permissões estão todas lá, e o painel
        # devolve a tela de login mesmo assim.
        pessoa = Usuario.objects.create_user(
            username="sasha", password="senha-longa-de-teste", is_superuser=True
        )
        self.client.force_login(pessoa)

        resposta = self.client.get(reverse("admin:index"), follow=True)

        self.assertEqual(resposta.redirect_chain[0][0], "/admin/login/?next=/admin/")


class TestAtalhosParaAsGradesDeLancamento(TestCase):
    """O cadastro do estudo leva às telas de lançamento.

    O caminho até as grades passava obrigatoriamente pela tela de resultado:
    quem chega com a planilha pronta — que é o caso comum, o laboratório roda o
    estudo primeiro e digita depois — tinha de criar o estudo, sair do cadastro,
    abrir o resultado e voltar, sem que nada na tela dissesse que a grade
    existia.
    """

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.suporte = Usuario.objects.create_user(
            username="suporte", password="senha-longa-de-teste",
            is_staff=True, is_superuser=True,
        )
        self.estudo = montar_estudo(self.laboratorio, self.suporte)
        self.client.force_login(self.suporte)
        self.url = reverse("admin:estudos_estudo_change", args=[self.estudo.pk])

    def test_a_secao_de_replicas_fica_abaixo_dos_niveis(self):
        resposta = self.client.get(self.url)

        corpo = resposta.content.decode()
        niveis = corpo.index("Níveis do estudo")
        replicas = corpo.index("Lançar réplicas de controle")
        amostras = corpo.index("Lançar amostras pareadas")
        self.assertLess(niveis, replicas)
        self.assertLess(replicas, amostras)

    def test_leva_para_as_tres_grades(self):
        resposta = self.client.get(self.url)

        for rota in ("replicas_estudo", "amostras_estudo", "qualitativas_estudo"):
            self.assertContains(resposta, reverse(rota, args=[self.estudo.pk]))

    def test_no_formulario_de_criacao_o_botao_da_lugar_a_um_recado(self):
        # Sem estudo salvo não há para onde ir, e um link quebrado seria pior
        # do que a ausência dele.
        resposta = self.client.get(reverse("admin:estudos_estudo_add"))

        self.assertContains(resposta, "Réplicas")
        self.assertContains(resposta, "Salve o estudo primeiro")
        self.assertNotContains(resposta, "Lançar réplicas de controle")

    def test_o_titulo_da_secao_de_replicas_e_o_pedido(self):
        resposta = self.client.get(self.url)

        self.assertContains(resposta, "<h2>Réplicas</h2>", html=True)
