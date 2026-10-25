from django.urls import include, path

urlpatterns = [path('', include(('student.urls', 'student'), namespace='student'))]
