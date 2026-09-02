"""Rotas do sistema.

Hoje só existem o painel administrativo e a tela de resultado do estudo. As
telas de digitação de dados do laboratório entram aqui conforme forem prontas.
"""

from django.contrib import admin
from django.urls import path

from estudos import views as estudos_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("estudos/<int:estudo_id>/resultado/", estudos_views.resultado, name="resultado_estudo"),
]
