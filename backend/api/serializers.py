from rest_framework import serializers

from .models import Article, Prediction


class ArticleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Article
        fields = ["id", "title", "content", "source_url", "created_at"]


class PredictionSerializer(serializers.ModelSerializer):
    article = ArticleSerializer(read_only=True)

    class Meta:
        model = Prediction
        fields = ["id", "article", "label", "score", "model_version", "created_at"]


class PredictRequestSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255, required=False, allow_blank=True)
    content = serializers.CharField()
    source_url = serializers.URLField(required=False, allow_blank=True)


class VerifyRequestSerializer(serializers.Serializer):
    headline = serializers.CharField(max_length=512, required=False, allow_blank=True)
    url = serializers.URLField(required=False, allow_blank=True)
    languageCode = serializers.CharField(max_length=10, required=False, allow_blank=True)

    def validate(self, attrs):
        if not attrs.get("headline") and not attrs.get("url"):
            raise serializers.ValidationError("Provide either 'headline' or 'url'.")
        return attrs
