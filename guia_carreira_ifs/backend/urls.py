from django.urls import path
from backend.core import views
urlpatterns=[path('',views.student_page),path('gestao/',views.management_page),path('api/register/',views.register),path('api/login/',views.login),path('api/me/',views.me),path('api/catalogo/',views.catalog),path('api/recomendar/',views.recommend),path('api/historico/',views.history),path('api/gestao/resumo/',views.summary)]
urlpatterns += [path('api/gestao/analise/',views.management_analysis)]



urlpatterns += [path("api/gestao/alunos/",views.management_students)]

urlpatterns += [path('api/ia/metadata/', views.ia_metadata), path('api/ia/recomendar/', views.ia_recommend)]
