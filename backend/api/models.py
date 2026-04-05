from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class Article(models.Model):
    title = models.CharField(max_length=255)
    content = models.TextField()
    source_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class Prediction(models.Model):
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="predictions")
    label = models.CharField(max_length=50)
    score = models.FloatField()
    model_version = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)

    def __str__(self):
        return f"{self.label} ({self.score:.2f})"
