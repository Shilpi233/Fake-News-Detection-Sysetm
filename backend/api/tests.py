from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Article


class PredictViewTests(APITestCase):
    def test_predict_creates_article_and_prediction(self):
        payload = {"title": "Test", "content": "Sample content"}
        response = self.client.post(reverse("predict"), payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Article.objects.count(), 1)
        self.assertIn("prediction", response.data)
a