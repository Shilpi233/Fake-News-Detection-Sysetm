from django.contrib import admin

from .models import Article, Prediction


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "source_url", "created_at")
    search_fields = ("title", "content")
    list_filter = ("created_at",)


@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display = ("id", "article", "label", "score", "model_version", "created_at")
    list_filter = ("label", "model_version", "created_at")
    search_fields = ("article__title", "label")
