from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path
from rest_framework_simplejwt.views import TokenRefreshView
from api.views import EmailOrUsernameTokenObtainPairView

def root(_request):
    return redirect("/static/index.html")

urlpatterns = [
    path("", root),
    path("admin/", admin.site.urls),
    path("api/auth/login/", EmailOrUsernameTokenObtainPairView.as_view(), name="token_login_compat"),
    path("api/auth/token/", EmailOrUsernameTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("auth/", include("social_django.urls", namespace="social")),
    path("api/", include("api.urls")),
]

if settings.DEBUG:
    # Serve frontend assets from <workspace>/frontend
    urlpatterns += static(settings.STATIC_URL, document_root=settings.BASE_DIR.parent / "frontend")
