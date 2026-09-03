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
from contas.models import Assinatura, Laboratorio, RegistroAuditoria, Usuario
from estudos.models import (
    VERSAO_MOTOR,
    AmostraComparacao,
    Estudo,
    NivelEstudo,
    Replica,
    Veredito,
)
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

    def test_traz_as_faixas_do_estudo(self):
        # A rastreabilidade deixou de ser uma seção única e virou três faixas
        # condensáveis, cada uma resumida numa linha quando resolvida.
        for faixa in [
            "Analito e limites",
            "Sistemas analíticos",
            "Insumos e controles",
            "Precisão",
            "Comparabilidade",
            "Veredito por nível",
        ]:
            self.assertContains(self.resposta, faixa)

    def test_as_faixas_resolvidas_nascem_fechadas(self):
        # Só a etapa corrente abre sozinha: é isso que faz a tela caber num olhar.
        corpo = self.resposta.content.decode()
        assert corpo.count("<details class=\"cartao faixa\">") >= 3, "faixas de rastreabilidade deveriam nascer condensadas"
        assert "<details class=\"cartao faixa\" open>" in corpo, "a etapa corrente deveria nascer aberta"

    def test_traz_as_medidas_pedidas(self):
        for medida in [
            "Erro sistemático médio",
            "Regressão de Deming",
            "Passing-Bablok",
            "Concordância de Lin",
            "Concordância analítica",
            "Concordância clínica",
        ]:
            self.assertContains(self.resposta, medida)

    def test_desenha_os_graficos(self):
        # Os gráficos são SVG embutido; sem biblioteca externa, sem JavaScript.
        self.assertContains(self.resposta, "<svg")
        self.assertContains(self.resposta, "Levey-Jennings")

    def test_mostra_a_referencia_cientifica_de_cada_limite(self):
        self.assertContains(self.resposta, "ControlLab")

    def test_distingue_previa_de_veredito_congelado(self):
        # O estudo do fixture não foi concluído: o cabeçalho tem de dizer que o
        # resultado é prévia, não decisão assinada.
        self.assertContains(self.resposta, "Prévia")
        self.assertNotContains(self.resposta, "Congelado em")

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


class TestQuadro(TestCase):
    """O quadro precisa colocar cada estudo na coluna certa e dizer o que falta."""

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.dono = Usuario.objects.create_user(
            username="dono", password="senha-longa-de-teste", laboratorio=self.laboratorio
        )
        self.estudo = montar_estudo(self.laboratorio, self.dono)
        self.url = reverse("quadro")

    def test_o_estudo_aparece_no_quadro(self):
        self.client.force_login(self.dono)

        resposta = self.client.get(self.url)

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "FT4")

    def test_estudo_com_dados_parciais_fica_em_coletando(self):
        # 25 réplicas de 25 e 10 amostras de 40: começou, não terminou.
        self.assertEqual(self.estudo.coluna_quadro(), Estudo.COLUNA_COLETANDO)

    def test_estudo_sem_dado_nenhum_fica_em_rascunho(self):
        self.estudo.amostras_comparacao.all().delete()
        Replica.objects.filter(nivel__estudo=self.estudo).delete()

        self.assertEqual(self.estudo.coluna_quadro(), Estudo.COLUNA_RASCUNHO)

    def test_estudo_liberado_fica_na_ultima_coluna(self):
        self.estudo.situacao = Estudo.LIBERADO

        self.assertEqual(self.estudo.coluna_quadro(), Estudo.COLUNA_LIBERADO)

    def test_a_proxima_acao_diz_quantas_amostras_faltam(self):
        # A precisão está completa; o que trava é a comparabilidade.
        self.assertEqual(self.estudo.proxima_acao(), "Faltam 30 amostras")

    def test_a_proxima_acao_aponta_a_replica_seguinte(self):
        Replica.objects.filter(nivel__estudo=self.estudo, corrida__gte=4).delete()

        self.assertEqual(self.estudo.proxima_acao(), "Nível 1, réplica 16")

    def test_estudo_de_outro_laboratorio_nao_aparece(self):
        outro = montar_laboratorio("Lab B", "22.222.222/0001-22")
        intruso = Usuario.objects.create_user(
            username="intruso", password="senha-longa-de-teste", laboratorio=outro
        )
        self.client.force_login(intruso)

        self.assertNotContains(self.client.get(self.url), "FT4")

    def test_visitante_vai_para_o_login(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)


class TestCalcularELiberar(TestCase):
    """As duas ações que movem o estudo pelo quadro.

    São o ponto em que um cálculo vira registro de qualidade, então o que se
    testa aqui é sobretudo o que elas *recusam* fazer.
    """

    def setUp(self):
        self.laboratorio = montar_laboratorio("Lab A", "11.111.111/0001-11")
        self.responsavel = Usuario.objects.create_user(
            username="responsavel", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.RESPONSAVEL,
        )
        self.analista = Usuario.objects.create_user(
            username="analista", password="senha-longa-de-teste",
            laboratorio=self.laboratorio, funcao=Usuario.ANALISTA,
        )
        self.estudo = montar_estudo(self.laboratorio, self.responsavel)
        self.calcular_url = reverse("concluir_estudo", args=[self.estudo.pk])
        self.liberar_url = reverse("liberar_estudo", args=[self.estudo.pk])

    def test_calcular_congela_o_retrato_e_move_o_estudo(self):
        self.client.force_login(self.analista)

        self.client.post(self.calcular_url)

        self.estudo.refresh_from_db()
        self.assertEqual(self.estudo.situacao, Estudo.CONCLUIDO)
        self.assertEqual(self.estudo.coluna_quadro(), Estudo.COLUNA_CALCULADO)
        veredito = self.estudo.veredito
        self.assertEqual(veredito.versao_motor, VERSAO_MOTOR)
        self.assertIn("precisao", veredito.detalhamento)

    def test_o_retrato_guarda_os_limites_vigentes_no_momento(self):
        # É o que permite defender o número numa auditoria: a ficha pode mudar
        # depois, mas o relatório mostra contra o que se decidiu na época.
        self.client.force_login(self.analista)

        self.client.post(self.calcular_url)

        limites = self.estudo.veredito.detalhamento["especificacao"]
        self.assertEqual(limites["erro_total"]["valor_pct"], 12.0)
        self.assertEqual(limites["erro_total"]["referencia"], "ControlLab")

    def test_calcular_registra_na_trilha_de_auditoria(self):
        self.client.force_login(self.analista)

        self.client.post(self.calcular_url)

        registro = RegistroAuditoria.objects.get(acao="calculou o estudo")
        self.assertEqual(registro.usuario, self.analista)
        self.assertEqual(registro.laboratorio, self.laboratorio)

    def test_estudo_sem_dado_nenhum_nao_calcula(self):
        self.estudo.amostras_comparacao.all().delete()
        Replica.objects.filter(nivel__estudo=self.estudo).delete()
        self.client.force_login(self.analista)

        self.client.post(self.calcular_url)

        self.estudo.refresh_from_db()
        self.assertEqual(self.estudo.situacao, Estudo.RASCUNHO)
        self.assertFalse(hasattr(self.estudo, "veredito"))

    def test_recalcular_substitui_o_retrato_anterior(self):
        self.client.force_login(self.analista)
        self.client.post(self.calcular_url)

        self.client.post(self.calcular_url)

        self.assertEqual(Veredito.objects.filter(estudo=self.estudo).count(), 1)
        self.assertTrue(RegistroAuditoria.objects.filter(acao="recalculou o estudo").exists())

    def test_get_nao_calcula(self):
        # Mudança de estado por GET seria disparada por um simples recarregar.
        self.client.force_login(self.analista)

        resposta = self.client.get(self.calcular_url)

        self.assertEqual(resposta.status_code, 405)
        self.assertFalse(Veredito.objects.exists())

    def test_laboratorio_alheio_nao_calcula(self):
        outro = montar_laboratorio("Lab B", "22.222.222/0001-22")
        intruso = Usuario.objects.create_user(
            username="intruso", password="senha-longa-de-teste", laboratorio=outro
        )
        self.client.force_login(intruso)

        self.assertEqual(self.client.post(self.calcular_url).status_code, 404)
        self.assertFalse(Veredito.objects.exists())

    def test_analista_nao_libera(self):
        # Assinar relatório de validação é ato do responsável técnico.
        self.client.force_login(self.analista)
        self.client.post(self.calcular_url)

        self.client.post(self.liberar_url)

        self.estudo.refresh_from_db()
        self.assertEqual(self.estudo.situacao, Estudo.CONCLUIDO)

    def test_responsavel_libera_e_assina(self):
        self.client.force_login(self.responsavel)
        self.client.post(self.calcular_url)

        self.client.post(self.liberar_url)

        self.estudo.refresh_from_db()
        self.assertEqual(self.estudo.situacao, Estudo.LIBERADO)
        self.assertEqual(self.estudo.veredito.liberado_por, self.responsavel)
        self.assertIsNotNone(self.estudo.veredito.liberado_em)

    def test_nao_libera_sem_calcular_antes(self):
        self.client.force_login(self.responsavel)

        self.client.post(self.liberar_url)

        self.estudo.refresh_from_db()
        self.assertEqual(self.estudo.situacao, Estudo.RASCUNHO)

    def test_estudo_liberado_nao_recalcula(self):
        # Recalcular um relatório assinado descolaria o número do que se assinou.
        self.client.force_login(self.responsavel)
        self.client.post(self.calcular_url)
        self.client.post(self.liberar_url)
        congelado_em = self.estudo.veredito.calculado_em

        self.client.post(self.calcular_url)

        self.estudo.refresh_from_db()
        self.assertEqual(self.estudo.situacao, Estudo.LIBERADO)
        self.assertEqual(self.estudo.veredito.calculado_em, congelado_em)

    def test_a_tela_avisa_quando_o_recalculo_diverge_do_assinado(self):
        # A ficha do analito apertou depois da assinatura: a tela recalcula ao
        # vivo, o relatório mantém o número assinado, e o usuário precisa ver
        # que os dois deixaram de bater.
        self.client.force_login(self.responsavel)
        self.client.post(self.calcular_url)
        self.assertEqual(self.estudo.veredito.resultado, Veredito.APROVADO)

        ficha = self.estudo.especificacao
        ficha.erro_total_maximo_pct = Decimal("1.00")
        ficha.save()
        ficha.limites_imprecisao.update(maximo_pct=Decimal("0.25"))

        resposta = self.client.get(reverse("resultado_estudo", args=[self.estudo.pk]))

        self.assertContains(resposta, "não bate com o veredito congelado")
