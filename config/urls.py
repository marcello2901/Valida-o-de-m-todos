"""Rotas do sistema.

O quadro é a porta de entrada: é dele que o laboratório enxerga o que está
parado e o que depende de um gesto para andar. O painel administrativo continua
respondendo pelos cadastros e pela digitação de dados brutos.
"""

from django.contrib import admin
from django.urls import path
from django.views.generic import RedirectView

from catalogo import views as catalogo_views
from estudos import views as estudos_views

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="quadro", permanent=False)),
    path("quadro/", estudos_views.quadro, name="quadro"),
    path("analitos/", catalogo_views.biblioteca, name="biblioteca"),
    path("estudos/<int:estudo_id>/resultado/", estudos_views.resultado, name="resultado_estudo"),
    path("admin/", admin.site.urls),
]
