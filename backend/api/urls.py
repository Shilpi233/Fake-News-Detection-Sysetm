from django.urls import include, path
from rest_framework import routers

from .views import ArticleViewSet, PredictView, PredictionViewSet, ImagePredictView, VerifySourceView, register, SearchAndVerifyView

router = routers.DefaultRouter()
router.register(r"articles", ArticleViewSet, basename="article")
router.register(r"predictions", PredictionViewSet, basename="prediction")

urlpatterns = [
    path("register/", register, name="register"),
    path("predict/", PredictView.as_view(), name="predict"),
    path("predict-image/", ImagePredictView.as_view(), name="predict-image"),
    path("verify-source/", VerifySourceView.as_view(), name="verify-source"),
    path("search-and-verify/", SearchAndVerifyView.as_view(), name="search-and-verify"),
    path("", include(router.urls)),
]
