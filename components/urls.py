
from django.urls import path

from .views import ComponentViewSet, ComponentNodeTemplateViewSet


component_list_view = ComponentViewSet.as_view({"get": "list"})
component_template_list_view = ComponentNodeTemplateViewSet.as_view({"get": "list", "post": "create"})
component_template_detail_view = ComponentNodeTemplateViewSet.as_view(
    {"patch": "partial_update", "delete": "destroy", "get": "retrieve"}
)

urlpatterns = [
    path("templates/", component_template_list_view),
    path("templates/<int:pk>/", component_template_detail_view),
    path("", component_list_view),
]
