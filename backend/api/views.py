import re
from datetime import datetime
import io
import os
from urllib.parse import urlparse
import numpy as np
import requests
from django.contrib.auth.models import User
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny as DRFAllowAny

from langdetect import detect, LangDetectException
from textblob import TextBlob
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from rest_framework import status, viewsets
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import Article, Prediction
from .serializers import ArticleSerializer, PredictRequestSerializer, PredictionSerializer


class EmailOrUsernameTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Allow JWT login with either username or email."""

    def validate(self, attrs):
        login_value = (attrs.get(self.username_field) or "").strip()

        if login_value and "@" in login_value:
            try:
                user = User.objects.get(email__iexact=login_value)
                attrs[self.username_field] = user.username
            except User.DoesNotExist:
                pass

        data = super().validate(attrs)
        data["username"] = self.user.username
        return data


class EmailOrUsernameTokenObtainPairView(TokenObtainPairView):
    serializer_class = EmailOrUsernameTokenObtainPairSerializer


def analyze_image(file_obj) -> dict:
    """
    Lightweight heuristic image analysis. This is not deepfake detection,
    but gives a basic real/fake signal using resolution, sharpness and format.
    """
    try:
        from PIL import Image, ImageStat
    except ImportError:
        return {
            "label": "unknown",
            "score": 0.5,
            "model_version": "v1.0.0-image-heuristic",
            "analysis_details": {
                "language": "Image content - N/A",
                "sentiment": "Image content - N/A",
                "authority": "Image source - Unknown",
                "recency": "Not Applicable",
                "links": "N/A",
                "bias": "N/A",
                "social": "N/A",
                "bot": "N/A",
                "image": {
                    "error": "Pillow not installed"
                }
            },
            "confidence": 0.0
        }

    image = Image.open(file_obj)
    width, height = image.size
    fmt = (image.format or "").upper()
    mode = image.mode

    # Sharpness proxy: variance of grayscale
    stat = ImageStat.Stat(image.convert("L"))
    variance = stat.var[0] if stat.var else 0

    # Size in KB if available
    size_kb = None
    if hasattr(file_obj, "size"):
        size_kb = round(file_obj.size / 1024, 1)

    # Heuristic scoring
    score = 50
    if width >= 800 and height >= 600:
        score += 8
    else:
        score -= 5

    if size_kb is not None:
        if size_kb >= 120:
            score += 6
        elif size_kb < 40:
            score -= 8

    if variance >= 2000:
        score += 8  # sharp/detailed
    elif variance < 400:
        score -= 10  # too smooth / low detail

    if fmt in {"JPEG", "PNG", "WEBP"}:
        score += 4
    else:
        score -= 4

    aspect_ratio = round(width / height, 2) if height else 0
    if aspect_ratio < 0.6 or aspect_ratio > 1.9:
        score -= 4  # unusual aspect ratios

    # --- Try OCR to extract text for additional inference ---
    ocr_text = ""
    try:
        import os, pytesseract
        from PIL import ImageOps, ImageFilter, ImageEnhance
        import time
        # Tesseract path configuration
        tpath = os.getenv("TESSERACT_PATH") or r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        pytesseract.pytesseract.tesseract_cmd = tpath
        print(f"[DEBUG] Tesseract path: {tpath}")
        
        # Optimized: Only Hindi + English (most reliable for India)
        ocr_langs = "hin+eng"
        
        # Aggressive preprocessing for dense newspaper text
        img_for_ocr = image.convert("L")  # grayscale
        
        # Enhance contrast significantly
        enhancer = ImageEnhance.Contrast(img_for_ocr)
        img_for_ocr = enhancer.enhance(3.0)  # Strong contrast boost
        
        # Apply multiple filters
        img_for_ocr = ImageOps.autocontrast(img_for_ocr)
        img_for_ocr = img_for_ocr.filter(ImageFilter.SHARPEN)
        img_for_ocr = img_for_ocr.filter(ImageFilter.SHARPEN)  # Double sharpen
        
        # Apply median filter to remove noise
        img_for_ocr = img_for_ocr.filter(ImageFilter.MedianFilter(size=3))
        
        # OCR with multiple PSM attempts
        ocr_text = ""
        ocr_start = time.time()
        psm_modes = ['3', '6', '11']  # Try multiple PSM modes
        
        for psm_idx, psm_mode in enumerate(psm_modes):
            try:
                if ocr_text and len(ocr_text.strip()) > 20:
                    # Already have good text, stop trying
                    print(f"[DEBUG] Got enough text ({len(ocr_text.strip())} chars) with PSM {psm_mode}")
                    break
                
                print(f"[DEBUG] Attempt {psm_idx+1}: Trying OCR with PSM {psm_mode}...")
                ocr_attempt = pytesseract.image_to_string(
                    img_for_ocr, 
                    config=f'--oem 1 --psm {psm_mode}', 
                    lang=ocr_langs, 
                    timeout=20
                )
                
                if ocr_attempt and len(ocr_attempt.strip()) > len(ocr_text.strip()):
                    ocr_text = ocr_attempt  # Keep the best result
                    print(f"[DEBUG] PSM {psm_mode} extracted {len(ocr_text.strip())} chars")
                    
            except Exception as ocr_err:
                print(f"[DEBUG] PSM {psm_mode} error: {str(ocr_err)[:100]}")
                continue
        
        ocr_time = time.time() - ocr_start
        print(f"[DEBUG] OCR completed in {ocr_time:.2f}s, Final text length: {len(ocr_text.strip())}")
        print(f"[DEBUG] OCR Text Length: {len(ocr_text.strip())}, First 100 chars: {ocr_text[:100]}")
    except Exception as e:
        print(f"[ERROR] Tesseract OCR failed: {str(e)}")
        ocr_text = ""

    # Basic advertisement detection from OCR text
    is_advert = False
    ad_signals = []
    if ocr_text:
        lower = ocr_text.lower()
        ad_keywords = [
            "special advertising", "advertising", "advertisement", "sponsored",
            "public gets free tv", "free tv", "no monthly", "no monthly bills",
            "limited", "offer", "deal", "save", "guarantee", "risk-free",
            "call", "order now", "free over the air", "zip codes", "call now",
            "1-888-", "1-800-", "1-877-", "1-866-", "tv channels", "free over the air tv"
        ]
        phone_pattern = r"\b(?:1[-\s]?(?:800|888|877|866|855|844)[-\s]?)?\d{3}[-\s]?\d{3}[-\s]?\d{4}\b"
        if any(k in lower for k in ad_keywords):
            is_advert = True
            ad_signals.extend([k for k in ad_keywords if k in lower])
        phones = re.findall(phone_pattern, lower)
        if phones:
            is_advert = True
            ad_signals.append("phone-number")
        if is_advert:
            # Stronger penalty for clear advertisement signals
            score -= 35

    # Penalty logic for low/no text
    ocr_char_count = len(ocr_text.strip())
    
    # Newspaper layout detection
    # Newspapers typically have: good resolution, standard aspect ratios, decent file size, moderate sharpness
    # Check for newspaper patterns in OCR text too
    looks_like_newspaper = False
    newspaper_keywords = ['समाचार', 'पत्र', 'दैनिक', 'न्यूज', 'news', 'daily', 'times', 'post', 'express', 'tribune']
    has_newspaper_text = any(kw in ocr_text.lower() for kw in newspaper_keywords) if ocr_text else False
    
    # Physical characteristics OR newspaper keywords in text
    if (width >= 800 and height >= 600 and 
        0.7 <= aspect_ratio <= 1.8 and
        size_kb and size_kb >= 100 and
        variance >= 1500) or has_newspaper_text:
        looks_like_newspaper = True
        if ocr_char_count < 20:
            score += 15  # Bonus for newspaper-like layout when OCR failed
    
    if ocr_char_count == 0:
        if not looks_like_newspaper:
            score -= 8  # Strong penalty only if doesn't look like newspaper
    elif ocr_char_count < 20:
        score -= 3  # Small penalty for very little text

    final_score = max(0, min(100, score))
    # Hard rule for ads: if strong ad signals (keywords or phone numbers), cap score
    if is_advert:
        final_score = min(final_score, 25)

    # Optional strict mode: only apply if OCR is truly empty AND doesn't look like newspaper
    try:
        strict_mode = os.getenv("STRICT_IMAGE_MODE", "false").lower() == "true"
    except Exception:
        strict_mode = False
    if strict_mode and ocr_char_count < 5 and not looks_like_newspaper:
        final_score = min(final_score, 45)
    label = "real" if final_score >= 50 else "fake"

    # Analyze OCR text if available (lowered threshold to 5 chars)
    language_detected = "Not enough text"
    sentiment_analysis = "Not enough text"
    detected_authority = "Image source"
    reference_links = "No links detected"
    
    if ocr_text and len(ocr_text.strip()) >= 5:
        # Script detection helper - check what script the text is in
        def detect_script(text):
            """Detect if text is primarily Devanagari (Hindi) or Latin (English)"""
            devanagari_count = sum(1 for c in text if '\u0900' <= c <= '\u097F')
            latin_count = sum(1 for c in text if 'a' <= c.lower() <= 'z')
            total_alpha = devanagari_count + latin_count
            
            if total_alpha < 5:
                return 'unknown'
            
            devanagari_percent = (devanagari_count / total_alpha) * 100
            latin_percent = (latin_count / total_alpha) * 100
            
            print(f"[DEBUG] Script analysis: Devanagari={devanagari_count} chars ({devanagari_percent:.1f}%), Latin={latin_count} chars ({latin_percent:.1f}%)")
            
            # Lowered thresholds for noisy OCR text
            if devanagari_count >= 20 or devanagari_percent > 30:  # Any significant Hindi presence
                return 'devanagari'
            elif latin_count >= 50 and latin_percent > 60:  # Strong English presence
                return 'latin'
            else:
                return 'mixed'
        
        # Simplified Language Detection - Use langid library (better than langdetect)
        try:
            import langid
            langid.set_languages(['en', 'hi', 'bn', 'te', 'ta', 'gu', 'mr', 'kn', 'ml', 'pa'])  # Limit to Indian languages
            
            # Use langid for detection
            detected_lang, confidence = langid.classify(ocr_text)
            
            # Detect script type
            script_type = detect_script(ocr_text)
            
            # Language mapping
            lang_map = {
                'en': 'English', 'hi': 'Hindi', 'bn': 'Bengali',
                'te': 'Telugu', 'ta': 'Tamil', 'gu': 'Gujarati',
                'mr': 'Marathi', 'kn': 'Kannada', 'ml': 'Malayalam', 'pa': 'Punjabi'
            }
            
            print(f"[DEBUG] Langid raw output: lang='{detected_lang}', confidence={confidence:.2f}")
            print(f"[DEBUG] OCR text sample (first 200 chars): {ocr_text[:200]}")
            
            # Map to readable language name
            if detected_lang in lang_map:
                language_detected = lang_map[detected_lang]
            else:
                # Unknown language code - use script detection
                if script_type == 'devanagari':
                    language_detected = 'Hindi'
                    print(f"[DEBUG] Unknown lang code '{detected_lang}' but Devanagari script -> Hindi")
                elif script_type == 'latin':
                    language_detected = 'English'
                    print(f"[DEBUG] Unknown lang code '{detected_lang}' but Latin script -> English")
                else:
                    language_detected = detected_lang.upper() if len(detected_lang) <= 3 else "Mixed"
            
            print(f"[DEBUG] Final language: {language_detected}")
            
            # Override logic: If script and detected language don't match, trust the script
            if script_type == 'latin' and language_detected != 'English':
                language_detected = 'English'
                print(f"[DEBUG] Override: Latin script detected -> forcing English")
            elif script_type == 'devanagari' and language_detected not in ['Hindi', 'Marathi']:
                language_detected = 'Hindi'
                print(f"[DEBUG] Override: Devanagari script detected -> forcing Hindi")
        except Exception as e:
            print(f"[DEBUG] Language detection error: {str(e)}")
            import traceback
            print(f"[DEBUG] Traceback: {traceback.format_exc()}")
            # Fallback: try script detection even on error
            try:
                script_type = detect_script(ocr_text)
                if script_type == 'latin':
                    language_detected = 'English'
                elif script_type == 'devanagari':
                    language_detected = 'Hindi'
                else:
                    language_detected = 'Mixed'
                print(f"[DEBUG] Fallback script detection: {script_type} -> {language_detected}")
            except:
                language_detected = 'Mixed'
        
        # Sentiment Analysis
        try:
            analyzer = SentimentIntensityAnalyzer()
            sentiment_scores = analyzer.polarity_scores(ocr_text)
            compound = sentiment_scores['compound']
            if compound >= 0.05:
                sentiment_analysis = f"Positive ({compound:.2f})"
            elif compound <= -0.05:
                sentiment_analysis = f"Negative ({compound:.2f})"
            else:
                sentiment_analysis = f"Neutral ({compound:.2f})"
        except Exception:
            sentiment_analysis = "Could not analyze"
        
        # Source Authority Detection
        try:
            trusted_keywords = ['bbc', 'reuters', 'hindu', 'ndtv', 'times', 'guardian', 'associated press']
            ocr_lower = ocr_text.lower()
            if any(kw in ocr_lower for kw in trusted_keywords):
                detected_authority = "Trusted Source Detected"
            else:
                detected_authority = "Unknown Source"
        except Exception:
            detected_authority = "Could not analyze"
        
        # Reference Links Detection
        try:
            url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
            urls = re.findall(url_pattern, ocr_text)
            if urls:
                reference_links = f"{len(urls)} link(s) found"
            else:
                reference_links = "No links found"
        except Exception:
            reference_links = "Could not analyze"

    # Determine bot activity based on image characteristics
    bot_activity = "None"
    if is_advert and len(ad_signals) > 2:
        bot_activity = "Potential spam"
    
    # Determine recency (for images, use creation time if available)
    recency_status = "Image - Date Unknown"
    if looks_like_newspaper:
        recency_status = "May be current news"
    elif is_advert:
        recency_status = "Advertisement"
    
    # Debug logging
    print(f"[IMAGE ANALYSIS] OCR Text Length: {len(ocr_text.strip())}, Language: {language_detected}, Sentiment: {sentiment_analysis}")
    
    analysis_details = {
        "language": language_detected,
        "sentiment": sentiment_analysis,
        "authority": detected_authority,
        "recency": recency_status,
        "links": reference_links,
        "bias": ("High" if is_advert else "Low"),
        "social": ("Negative" if is_advert else "Neutral"),
        "bot": bot_activity,
        "image": {
            "resolution": f"{width}x{height}",
            "format": fmt or "Unknown",
            "mode": mode,
            "size_kb": size_kb,
            "sharpness_var": round(variance, 1),
            "aspect_ratio": aspect_ratio,
            "ocr_excerpt": (ocr_text[:250] if ocr_text else ""),
            "ocr_char_count": len(ocr_text.strip()),
            "no_text": (len(ocr_text.strip()) < 5),
            "looks_like_newspaper": looks_like_newspaper,
            "ad_detected": is_advert,
            "ad_signals": ad_signals,
            "strict_mode_active": strict_mode,
        }
    }

    return {
        "label": label,
        "score": round(final_score / 100.0, 2),
        "model_version": "v1.0.0-image-heuristic",
        "analysis_details": analysis_details,
        "confidence": final_score
    }


def advanced_ml_analysis(text: str, title: str = "", source_url: str = "") -> dict:
    """
    Advanced fake news detection using ML models + heuristics.
    Returns: {label, score, model_version, analysis_details}
    """
    
    # ==================== TRUSTED NEWS DOMAINS ====================
    TRUSTED_DOMAINS = {
        # International
        'bbc.com', 'bbc.co.uk', 'reuters.com', 'apnews.com', 'theguardian.com',
        'nytimes.com', 'washingtonpost.com', 'cnn.com', 'bbc.co.in',
        # India
        'thehindu.com', 'ndtv.com', 'theprint.in', 'deccanherald.com',
        'indianexpress.com', 'hindustantimes.com', 'moneycontrol.com',
        'thaindian.com', 'times-of-india.com', 'business-standard.com',
        # Academic/Research
        'nature.com', 'science.org', 'sciencedaily.com', 'plos.org',
        'arxiv.org', 'ieee.org', 'acm.org',
        # Fact-check
        'snopes.com', 'factcheck.org', 'politifact.com', 'fullfact.org',
        'indiatoday.com'
    }
    
    SUSPICIOUS_DOMAINS = {
        'blogspot', 'wordpress.com', 'free', 'xyz', 'click', 'viral',
        'breakingnews', 'newstoday', 'realnews', 'truenews', 'latest',
        'exclusive', 'trending', 'shocking', 'unbelievable'
    }
    
    # Initialize analyzers
    vader = SentimentIntensityAnalyzer()
    combined_text = f"{title} {text}".strip()
    
    # Detect if this is headline-only content
    is_headline_only = len(text.split()) < 15 and len(title) > 0
    
    # Feature extraction
    features = {}
    
    # ==================== FEATURE 1: Content Length & Structure ====================
    word_count = len(combined_text.split())
    sentence_count = len(re.split(r'[.!?]+', combined_text))
    avg_word_length = np.mean([len(w) for w in combined_text.split()]) if word_count > 0 else 0
    
    # For headline-only: be more lenient
    if is_headline_only:
        features['content_length_score'] = 15  # Give benefit of doubt for headlines
    else:
        features['content_length_score'] = min(word_count / 500, 1.0) * 20
    
    features['sentence_structure_score'] = min(sentence_count / 10, 1.0) * 15
    
    # ==================== FEATURE 2: Language Detection ====================
    try:
        language = detect(combined_text)
        lang_map = {
            'en': 'English', 'hi': 'Hindi', 'ur': 'Urdu', 
            'bn': 'Bengali', 'gu': 'Gujarati'
        }
        language_name = lang_map.get(language, language.upper())
    except LangDetectException:
        language_name = "Unknown"
    
    # ==================== FEATURE 3: Sentiment Analysis (VADER + Transformer) ====================
    vader_scores = vader.polarity_scores(combined_text)
    vader_compound = vader_scores['compound']
    
    if vader_compound >= 0.05:
        sentiment = "Positive"
    elif vader_compound <= -0.05:
        sentiment = "Negative"
    else:
        sentiment = "Neutral"
    
    # Extreme sentiment = less credible
    features['sentiment_score'] = (1 - abs(vader_compound)) * 20
    
    # ==================== FEATURE 4: Source Authority (URL Analysis + Domain Extraction) ====================
    authority = "Unknown"
    authority_score = 0
    extracted_domains = []
    has_trusted_source = False
    
    # Check provided source URL
    if source_url:
        domain = urlparse(source_url).netloc.lower()
        if any(td in domain for td in TRUSTED_DOMAINS):
            authority = "High"
            authority_score = 30
            has_trusted_source = True
        elif any(sp in domain for sp in SUSPICIOUS_DOMAINS):
            authority = "Low"
            authority_score = -20
        else:
            authority = "Medium"
            authority_score = 15
    
    # Extract domains mentioned in text (e.g., "according to BBC.com" or "BBC reports")
    domain_extraction_pattern = r'(?:https?://)?(?:www\.)?([a-zA-Z0-9-]+\.(?:com|co\.uk|co\.in|org|net|edu|gov))'
    text_domains = re.findall(domain_extraction_pattern, text.lower())
    extracted_domains = list(set(text_domains))  # unique
    
    if extracted_domains:
        for dom in extracted_domains:
            if any(td in dom for td in TRUSTED_DOMAINS):
                has_trusted_source = True
                authority = "High"
                authority_score = max(authority_score, 30)
                break
    
    features['authority_score'] = authority_score
    
    # ==================== FEATURE 5: Clickbait & Emotional Language ====================
    clickbait_words = [
        'shocking', 'unbelievable', 'amazing', 'secret', 'exposed', 'you won\'t believe',
        'click here', 'must see', 'incredible', 'devastating', 'horrific', 'terrifying',
        'stunning', 'breaking', 'viral', 'trending'
    ]
    
    emotional_intensity = sum(1 for word in clickbait_words if word in combined_text.lower())
    
    if emotional_intensity == 0:
        bias = "Low"
        bias_score = 25
    elif emotional_intensity <= 2:
        bias = "Medium"
        bias_score = 10
    else:
        bias = "High"
        bias_score = -15
    
    features['bias_score'] = bias_score
    
    # ==================== FEATURE 6: URL References ====================
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    urls = re.findall(url_pattern, text)
    links_count = len(urls)
    
    # News articles should have references
    links_status = f"{links_count} Found"
    links_score = min(links_count * 5, 20)  # Max 20 points
    features['links_score'] = links_score

    # ==================== FEATURE 6B: Evidence vs Extraordinary Claims ====================
    lower_text = combined_text.lower()
    claim_phrases = [
        'reportedly', 'allegedly', 'claims', 'study claims', 'experiments',
        'researchers', 'scientists', 'experts say', 'more research is needed',
        'without awareness', 'manipulate', 'control dreams', 'specific frequencies',
        'enter the human brain', 'subconsciously'
    ]
    extraordinary_phrases = [
        'control dreams', 'enter the human brain', 'mind control',
        'alter dream patterns', 'subconsciously manipulate', 'influence dreams'
    ]
    unverified_phrases = [
        'no official', 'no verified', 'unverified', 'not verified',
        'no university', 'no research institute'
    ]
    claim_hits = sum(1 for p in claim_phrases if p in lower_text)
    extraordinary_hits = sum(1 for p in extraordinary_phrases if p in lower_text)
    unverified_hits = sum(1 for p in unverified_phrases if p in lower_text)

    evidence_score = 0
    if (claim_hits + unverified_hits) >= 2 and links_count < 2:
        evidence_score = -25
    elif claim_hits >= 1 and links_count == 0:
        evidence_score = -15
    elif claim_hits >= 1 and links_count >= 2:
        evidence_score = 5
    features['evidence_score'] = evidence_score

    # If scientific/extraordinary claims but no trusted source backing
    if (claim_hits >= 1 or extraordinary_hits >= 1) and not has_trusted_source and links_count < 2:
        authority_score = min(authority_score - 15, -20)
        features['authority_score'] = authority_score

    # Strengthen bias if unverified claims are present
    if (unverified_hits >= 1 and claim_hits >= 1 and links_count < 2) or extraordinary_hits >= 1:
        bias = "High"
        features['bias_score'] = -15
    
    # ==================== FEATURE 7: Bot Activity Detection ====================
    caps_ratio = sum(1 for c in text if c.isupper()) / max(len(text), 1)
    repeated_chars = len(re.findall(r'(.)\1{3,}', text))
    excessive_punctuation = text.count('!') + text.count('?')
    
    bot_activity = "None"
    bot_score = 20
    
    if caps_ratio > 0.3 or repeated_chars > 3 or excessive_punctuation > 10:
        bot_activity = "Detected"
        bot_score = -20
    
    features['bot_score'] = bot_score
    
    # ==================== FEATURE 8: Content Freshness ====================
    recency_words = ['today', 'yesterday', 'breaking', 'just now', 'recently', 'latest', 'new']
    has_recency = any(word in combined_text.lower() for word in recency_words)
    recency = "Recent" if has_recency else "Older"
    recency_score = 5 if has_recency else 0
    features['recency_score'] = recency_score
    
    # ==================== FEATURE 9: ML-Based Content Analysis ====================
    ml_score = 0
    
    # Additional heuristic-based detection (without transformer models)
    # Check for news-like structure
    has_intro = len(text.split()) > 20  # Substantial content
    has_quotes = '"' in text or "'" in text
    has_numbers = bool(re.search(r'\d+', text))
    
    # Fact-heavy content is more credible
    fact_indicators = sum([has_intro, has_quotes, has_numbers])
    ml_score = fact_indicators * 5
    
    features['ml_score'] = ml_score
    
    # ==================== CALCULATE FINAL SCORE ====================
    # Weighted combination of features
    weights = {
        'content_length_score': 1.0,
        'sentence_structure_score': 1.0,
        'sentiment_score': 1.0,
        'authority_score': 2.0,  # Authority is most important
        'bias_score': 2.0,       # Bias detection is crucial
        'links_score': 1.5,
        'evidence_score': 3.0,
        'bot_score': 1.5,
        'recency_score': 0.5,
        'ml_score': 2.0
    }
    
    total_score = 50  # Start at neutral
    total_weight = sum(weights.values())
    
    for feature, weight in weights.items():
        if feature in features:
            total_score += (features[feature] * weight) / total_weight
    
    # Clamp to 0-100
    final_score = max(0, min(100, total_score))

    # Hard rule: extraordinary claims without sufficient references are unlikely
    if (extraordinary_hits >= 1 and links_count < 2) or ((claim_hits + unverified_hits) >= 2 and links_count < 2):
        final_score = min(final_score, 35)
    confidence = final_score / 100.0
    
    # Determine label
    label = "real" if final_score >= 50 else "fake"
    
    # Social signals
    if sentiment == "Positive" and bias == "Low":
        social = "Positive"
    elif sentiment == "Negative" or bias == "High":
        social = "Negative"
    else:
        social = "Mixed"
    
    analysis_details = {
        "language": language_name,
        "sentiment": sentiment,
        "authority": authority,
        "recency": recency,
        "links": links_status,
        "bias": bias,
        "social": social,
        "bot": bot_activity,
        "extracted_domains": extracted_domains,
        "has_trusted_source": has_trusted_source,
        "trusted_sample": list(TRUSTED_DOMAINS)[:10]
    }

    return {
        "label": label,
        "score": round(confidence, 2),
        "model_version": "v2.0.0-ml-trusted-sources",
        "analysis_details": analysis_details,
        "confidence": round(final_score, 1),
        "features": features
    }


def run_model(text: str, title: str = "", source_url: str = "") -> dict:
    """
    Main inference function. Uses advanced ML analysis.
    """
    return advanced_ml_analysis(text, title, source_url)


class PredictView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PredictRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        article = Article.objects.create(
            title=data.get("title") or "",
            content=data["content"],
            source_url=data.get("source_url", ""),
        )

        result = run_model(
            text=article.content,
            title=article.title,
            source_url=article.source_url
        )
        prediction = Prediction.objects.create(
            article=article,
            label=result["label"],
            score=result["score"],
            model_version=result.get("model_version", ""),
            created_by=request.user if request.user.is_authenticated else None,
        )

        response_payload = {
            "article": ArticleSerializer(article).data,
            "prediction": PredictionSerializer(prediction).data,
            "analysis": result.get("analysis_details", {})
        }
        return Response(response_payload, status=status.HTTP_201_CREATED)


class ImagePredictView(APIView):
    # Allow unauthenticated uploads for easier testing of image OCR/ads.
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        uploaded = request.FILES.get("image")
        title = request.data.get("title", "Uploaded Image")

        if not uploaded:
            return Response({"detail": "No image provided"}, status=status.HTTP_400_BAD_REQUEST)

        result = analyze_image(uploaded)

        # Store a minimal Article/Prediction record for history consistency
        article = Article.objects.create(
            title=title,
            content=f"Image upload: {uploaded.name}",
            source_url="",
        )

        prediction = Prediction.objects.create(
            article=article,
            label=result["label"],
            score=result.get("score", 0),
            model_version=result.get("model_version", ""),
            created_by=request.user if request.user.is_authenticated else None,
        )

        response_payload = {
            "article": ArticleSerializer(article).data,
            "prediction": PredictionSerializer(prediction).data,
            "analysis": result.get("analysis_details", {})
        }
        return Response(response_payload, status=status.HTTP_201_CREATED)


class ArticleViewSet(viewsets.ModelViewSet):
    queryset = Article.objects.all().order_by("-created_at")
    serializer_class = ArticleSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]


class PredictionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Prediction.objects.select_related("article").all().order_by("-created_at")
    serializer_class = PredictionSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]


class VerifySourceView(APIView):
    """Verify headline/URL via Google Fact Check Tools API."""
    permission_classes = [AllowAny]
    
    # Domain Reputation Database
    FAKE_NEWS_DOMAINS = {
        # Known fake news sites
        'infowars.com', 'naturalnews.com', 'beforeitsnews.com', 
        'yournewswire.com', 'neonnettle.com', 'worldnewsdailyreport.com',
        'abcnews.com.co', 'nationalreport.net', 'empirenews.net',
        'newslo.com', 'huzlers.com', 'civictribune.com',
        # Add more known fake domains
    }
    
    TRUSTED_DOMAINS = {
        # International trusted sources
        'bbc.com', 'bbc.co.uk', 'reuters.com', 'apnews.com', 
        'nytimes.com', 'theguardian.com', 'washingtonpost.com',
        'cnn.com', 'npr.org', 'pbs.org', 'bloomberg.com',
        'aljazeera.com', 'economist.com', 'time.com',
        # Indian trusted sources
        'thehindu.com', 'indianexpress.com', 'ndtv.com',
        'hindustantimes.com', 'timesofindia.indiatimes.com', 'indiatoday.in', 'livemint.com', 'news18.com', 'thewire.in',
        # Fact-checking organizations
        'factcheck.org', 'snopes.com', 'politifact.com',
        'boomlive.in', 'altnews.in', 'thequint.com',
    }
    
    SATIRE_DOMAINS = {
        'theonion.com', 'clickhole.com', 'thebeaverton.com',
        'fakingnews.com', 'newsthump.com', 'private-eye.co.uk', 'babylonbee.com', 'thedailymash.co.uk',
    }

    def post(self, request):
        from .serializers import VerifyRequestSerializer
        s = VerifyRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        api_key = os.getenv("GOOGLE_FACTCHECK_API_KEY", "")

        query = data.get("headline") or data.get("url")
        lang = data.get("languageCode") or "en"
        
        # Check if input is a URL (domain check)
        domain_check_result = self._check_domain_reputation(query)

        payload = {"claims": []}
        # Google Fact Check Tools API (v1alpha1)
        # https://factchecktools.googleapis.com/v1alpha1/claims:search
        if api_key:
            url = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
            params = {
                "query": query,
                "languageCode": lang,
                "key": api_key,
                "maxAgeDays": 365,
                "pageSize": 10,
            }
            try:
                resp = requests.get(url, params=params, timeout=10)
                resp.raise_for_status()
                payload = resp.json()
            except requests.RequestException as e:
                # If API call fails, proceed with domain-only verdict
                payload = {"error": str(e), "claims": []}

        # Simplify response for UI
        claims = []
        for c in payload.get("claims", []):
            reviews = c.get("claimReview", [])
            claims.append({
                "text": c.get("text"),
                "claimant": c.get("claimant"),
                "claimDate": c.get("claimDate"),
                "reviews": [
                    {
                        "publisher": r.get("publisher", {}).get("name"),
                        "url": r.get("url"),
                        "title": r.get("title"),
                        "textualRating": r.get("textualRating"),
                        "reviewDate": r.get("reviewDate"),
                    } for r in reviews
                ]
            })

        # Verdict mapping based on textualRating across all reviews
        def _bucket(rating: str) -> str:
            if not rating:
                return "neutral"
            t = rating.strip().lower()
            positive = {
                "true", "mostly true", "correct", "accurate", "verified",
                "supported", "partly true", "half true", "mixture"
            }
            negative = {
                "false", "mostly false", "incorrect", "inaccurate",
                "misleading", "pants on fire", "hoax", "fake"
            }
            if t in positive:
                return "positive"
            if t in negative:
                return "negative"
            # fallback: keyword contains
            if any(k in t for k in ["true", "correct", "accurate", "verified"]):
                return "positive"
            if any(k in t for k in ["false", "incorrect", "inaccurate", "misleading", "fake"]):
                return "negative"
            return "neutral"

        pos = neg = neu = 0
        for c in claims:
            for r in c.get("reviews", []):
                bucket = _bucket(r.get("textualRating"))
                if bucket == "positive":
                    pos += 1
                elif bucket == "negative":
                    neg += 1
                else:
                    neu += 1

        total_reviews = pos + neg + neu
        
        # If no fact-checks found, use domain reputation if available
        if total_reviews == 0 and domain_check_result:
            verdict = domain_check_result['verdict']
        elif pos > neg:
            verdict = "likely_real"
        elif neg > pos:
            verdict = "likely_fake"
        else:
            verdict = "mixed"

        response_data = {
            "query": query,
            "languageCode": lang,
            "claimsFound": len(claims),
            "summary": {
                "positive": pos,
                "negative": neg,
                "neutral": neu,
                "totalReviews": total_reviews,
                "verdict": verdict,
            },
            "claims": claims
        }
        
        # Add domain check info if available
        if domain_check_result:
            response_data['domainCheck'] = domain_check_result
        else:
            response_data['domainCheck'] = {
                'domain': None,
                'reputation': 'unknown',
                'verdict': 'insufficient_evidence' if total_reviews == 0 else verdict,
                'confidence': 0.5,
                'reason': 'No domain reputation and limited fact-check data'
            }

        # Debug info to help diagnose classification
        try:
            parsed = urlparse(query) if (query.startswith('http://') or query.startswith('https://')) else None
            dbg_domain = (parsed.netloc.lower() if parsed else query.lower())
        except Exception:
            dbg_domain = query
        response_data['debug'] = {
            'parsedDomain': dbg_domain,
            'apiKeyPresent': bool(api_key),
            'reviewCounts': {'pos': pos, 'neg': neg, 'neu': neu},
        }
        
        return Response(response_data, status=status.HTTP_200_OK)

    def get(self, request):
        """GET variant: verify using query parameters (?url=...&headline=...)"""
        from .serializers import VerifyRequestSerializer
        data = {
            "url": request.query_params.get("url", ""),
            "headline": request.query_params.get("headline", ""),
            "languageCode": request.query_params.get("languageCode", "en"),
        }
        s = VerifyRequestSerializer(data=data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        api_key = os.getenv("GOOGLE_FACTCHECK_API_KEY", "")

        query = data.get("headline") or data.get("url")
        lang = data.get("languageCode") or "en"

        # Check if input is a URL (domain check)
        domain_check_result = self._check_domain_reputation(query)

        payload = {"claims": []}
        # Google Fact Check Tools API (v1alpha1)
        # https://factchecktools.googleapis.com/v1alpha1/claims:search
        if api_key:
            url = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
            params = {
                "query": query,
                "languageCode": lang,
                "key": api_key,
                "maxAgeDays": 365,
                "pageSize": 10,
            }
            try:
                resp = requests.get(url, params=params, timeout=10)
                resp.raise_for_status()
                payload = resp.json()
            except requests.RequestException as e:
                payload = {"error": str(e), "claims": []}

        # Simplify response for UI
        claims = []
        for c in payload.get("claims", []):
            reviews = c.get("claimReview", [])
            claims.append({
                "text": c.get("text"),
                "claimant": c.get("claimant"),
                "claimDate": c.get("claimDate"),
                "reviews": [
                    {
                        "publisher": r.get("publisher", {}).get("name"),
                        "url": r.get("url"),
                        "title": r.get("title"),
                        "textualRating": r.get("textualRating"),
                        "reviewDate": r.get("reviewDate"),
                    } for r in reviews
                ]
            })

        # Verdict mapping based on textualRating across all reviews
        def _bucket(rating: str) -> str:
            if not rating:
                return "neutral"
            t = rating.strip().lower()
            positive = {
                "true", "mostly true", "correct", "accurate", "verified",
                "supported", "partly true", "half true", "mixture"
            }
            negative = {
                "false", "mostly false", "incorrect", "inaccurate",
                "misleading", "pants on fire", "hoax", "fake"
            }
            if t in positive:
                return "positive"
            if t in negative:
                return "negative"
            if any(k in t for k in ["true", "correct", "accurate", "verified"]):
                return "positive"
            if any(k in t for k in ["false", "incorrect", "inaccurate", "misleading", "fake"]):
                return "negative"
            return "neutral"

        pos = neg = neu = 0
        for c in claims:
            for r in c.get("reviews", []):
                bucket = _bucket(r.get("textualRating"))
                if bucket == "positive":
                    pos += 1
                elif bucket == "negative":
                    neg += 1
                else:
                    neu += 1

        total_reviews = pos + neg + neu

        # If no fact-checks found, use domain reputation if available
        if total_reviews == 0 and domain_check_result:
            verdict = domain_check_result['verdict']
        elif pos > neg:
            verdict = "likely_real"
        elif neg > pos:
            verdict = "likely_fake"
        else:
            verdict = "mixed"

        response_data = {
            "query": query,
            "languageCode": lang,
            "claimsFound": len(claims),
            "summary": {
                "positive": pos,
                "negative": neg,
                "neutral": neu,
                "totalReviews": total_reviews,
                "verdict": verdict,
            },
            "claims": claims
        }

        # Add domain check info if available
        if domain_check_result:
            response_data['domainCheck'] = domain_check_result
        else:
            response_data['domainCheck'] = {
                'domain': None,
                'reputation': 'unknown',
                'verdict': 'insufficient_evidence' if total_reviews == 0 else verdict,
                'confidence': 0.5,
                'reason': 'No domain reputation and limited fact-check data'
            }

        # Debug info to help diagnose classification
        try:
            parsed = urlparse(query) if (query.startswith('http://') or query.startswith('https://')) else None
            dbg_domain = (parsed.netloc.lower() if parsed else query.lower())
        except Exception:
            dbg_domain = query
        response_data['debug'] = {
            'parsedDomain': dbg_domain,
            'apiKeyPresent': bool(api_key),
            'reviewCounts': {'pos': pos, 'neg': neg, 'neu': neu},
        }

        return Response(response_data, status=status.HTTP_200_OK)
    
    def _check_domain_reputation(self, query: str):
        """Check if query is a URL and return domain reputation."""
        try:
            # Try to extract domain from query
            domain = None
            original = query
            common_prefixes = ('www.', 'm.', 'amp.', 'mobile.', 'beta.')
            
            # Check if it's a URL
            if query.startswith('http://') or query.startswith('https://'):
                parsed = urlparse(query)
                domain = parsed.netloc.lower()
                # Strip credentials if any
                if '@' in domain:
                    domain = domain.split('@')[-1]
                # Normalize common prefixes like www./m./amp.
                for p in common_prefixes:
                    if domain.startswith(p):
                        domain = domain[len(p):]
            elif '.' in query and ' ' not in query and len(query.split('.')) >= 2:
                # Might be a domain like "infowars.com"
                domain = query.lower()
                for p in common_prefixes:
                    if domain.startswith(p):
                        domain = domain[len(p):]
                # Only keep the domain part (remove path)
                if '/' in domain:
                    domain = domain.split('/')[0]
            
            if not domain:
                return None
            
            # Remove port if present
            if ':' in domain:
                domain = domain.split(':')[0]

            # Reduce to registrable base (handle some multi-TLDs)
            def _base(d: str) -> str:
                parts = d.split('.')
                if len(parts) <= 2:
                    return d
                multi_suffixes = {
                    'co.uk', 'com.au', 'co.in', 'com.br', 'com.mx', 'com.ar',
                    'com.tr', 'co.jp', 'gov.in', 'org.uk'
                }
                last_two = '.'.join(parts[-2:])
                last_three = '.'.join(parts[-3:])
                if last_two in multi_suffixes:
                    return '.'.join(parts[-3:])
                if last_three in multi_suffixes:
                    return '.'.join(parts[-4:]) if len(parts) >= 4 else last_three
                return '.'.join(parts[-2:])

            base = _base(domain)
            
            # Check against reputation databases
            if base in self.FAKE_NEWS_DOMAINS or domain in self.FAKE_NEWS_DOMAINS:
                return {
                    'domain': base,
                    'reputation': 'fake_news',
                    'verdict': 'likely_fake',
                    'confidence': 0.9,
                    'reason': 'Domain is known for spreading misinformation'
                }
            elif base in self.SATIRE_DOMAINS or domain in self.SATIRE_DOMAINS:
                return {
                    'domain': base,
                    'reputation': 'satire',
                    'verdict': 'satire_site',
                    'confidence': 0.95,
                    'reason': 'Domain publishes satirical/parody content for entertainment'
                }
            elif base in self.TRUSTED_DOMAINS or domain in self.TRUSTED_DOMAINS:
                return {
                    'domain': base,
                    'reputation': 'trusted',
                    'verdict': 'likely_real',
                    'confidence': 0.85,
                    'reason': 'Domain is a recognized trusted news source'
                }
            else:
                # Heuristic: suspicious TLDs, long/complex domains
                suspicious_tlds = {
                    'info', 'top', 'xyz', 'click', 'work', 'loan', 'gq', 'tk', 'ml'
                }
                tld = base.split('.')[-1] if '.' in base else ''
                hyphens = base.count('-')
                digits = sum(ch.isdigit() for ch in base)
                long_domain = len(base) > 30
                if tld in suspicious_tlds or hyphens >= 3 or digits >= 4 or long_domain:
                    return {
                        'domain': base,
                        'reputation': 'low_reputation',
                        'verdict': 'likely_fake',
                        'confidence': 0.65,
                        'reason': 'Heuristic flags: suspicious TLD or domain pattern'
                    }
                return {
                    'domain': base,
                    'reputation': 'unknown',
                    'verdict': 'insufficient_evidence',
                    'confidence': 0.5,
                    'reason': 'Domain not in reputation database'
                }
        except Exception as e:
            return None


class SearchAndVerifyView(APIView):
    """Search the web (Google Custom Search) and verify each result's domain reputation."""
    permission_classes = [AllowAny]

    def get(self, request):
        query = request.query_params.get('q', '').strip()
        lang = request.query_params.get('languageCode', 'en')
        num = int(request.query_params.get('num', '5'))
        if not query:
            return Response({"error": "Missing 'q' query parameter"}, status=status.HTTP_400_BAD_REQUEST)

        api_key = os.getenv('GOOGLE_CSE_API_KEY', '')
        cx = os.getenv('GOOGLE_CSE_CX', '')
        if not api_key or not cx:
            return Response({
                "error": "Google Custom Search not configured",
                "how_to": "Set GOOGLE_CSE_API_KEY and GOOGLE_CSE_CX in backend/.env"
            }, status=status.HTTP_400_BAD_REQUEST)

        # Call Google Custom Search
        try:
            params = {
                'key': api_key,
                'cx': cx,
                'q': query,
                'num': max(1, min(num, 10)),
                'hl': lang,
                'safe': 'active'
            }
            resp = requests.get('https://www.googleapis.com/customsearch/v1', params=params, timeout=10)
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as e:
            return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)

        # Reuse VerifySourceView's domain reputation logic
        verifier = VerifySourceView()

        results = []
        items = payload.get('items', [])
        trusted = fake = satire = neutral = 0
        for it in items:
            url = it.get('link') or it.get('formattedUrl') or ''
            title = it.get('title') or ''
            snippet = it.get('snippet') or ''
            rep = verifier._check_domain_reputation(url)
            verdict = rep['verdict'] if rep else 'insufficient_evidence'
            reputation = rep['reputation'] if rep else 'unknown'
            if verdict == 'likely_real':
                trusted += 1
            elif verdict == 'likely_fake':
                fake += 1
            elif verdict == 'satire_site':
                satire += 1
            else:
                neutral += 1

            results.append({
                'title': title,
                'url': url,
                'snippet': snippet,
                'domainCheck': rep or {
                    'domain': None,
                    'reputation': reputation,
                    'verdict': verdict,
                    'confidence': 0.5,
                    'reason': 'No domain reputation match'
                }
            })

        return Response({
            'query': query,
            'languageCode': lang,
            'counts': {
                'trusted': trusted,
                'fake': fake,
                'satire': satire,
                'neutral': neutral,
                'total': len(results)
            },
            'results': results
        }, status=status.HTTP_200_OK)

@api_view(['POST'])
@authentication_classes([])
@permission_classes([DRFAllowAny])
def register(request):
    """User registration endpoint with enhanced security"""
    try:
        username = request.data.get('username', '').strip()
        email = request.data.get('email', '').strip()
        password = request.data.get('password', '').strip()
        confirm_password = request.data.get('confirm', '').strip()
        
        print(f"[DEBUG] Register request: username={username}, email={email}")
        
        # Validate username format (3-30 chars, alphanumeric + dots, hyphens, underscores)
        if username and not re.match(r'^[a-zA-Z0-9_.-]{3,30}$', username):
            return Response(
                {"error": "Username must be 3-30 characters, containing only letters, numbers, dots, hyphens, or underscores"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validation
        if not all([username, email, password, confirm_password]):
            print(f"[DEBUG] Missing fields - username:{bool(username)}, email:{bool(email)}, password:{bool(password)}, confirm:{bool(confirm_password)}")
            return Response(
                {"error": "All fields are required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if password != confirm_password:
            return Response(
                {"error": "Passwords do not match"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Improved password validation
        if len(password) < 12:
            return Response(
                {"error": "Password must be at least 12 characters"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check password strength
        has_upper = any(c.isupper() for c in password)
        has_lower = any(c.islower() for c in password)
        has_digit = any(c.isdigit() for c in password)
        has_special = any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password)
        
        if not (has_upper and has_lower and has_digit and has_special):
            return Response(
                {"error": "Password must contain uppercase, lowercase, numbers, and special characters"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check password is not too common
        common_passwords = ['password', '12345678', 'qwerty', 'abc123', '123456', 'password123']
        if password.lower() in common_passwords:
            return Response(
                {"error": "Password is too common. Please choose a stronger password"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if User.objects.filter(username=username).exists():
            return Response(
                {"error": "Username already exists"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if User.objects.filter(email=email).exists():
            return Response(
                {"error": "Email already registered"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create user
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password
        )
        user.is_active = True  # Ensure user is active
        user.save()
        
        print(f"[DEBUG] ✅ User created successfully: {username} (ID: {user.id}, is_active: {user.is_active})")
        
        return Response(
            {
                "message": "Registration successful",
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email
                }
            },
            status=status.HTTP_201_CREATED
        )
    
    except Exception as e:
        print(f"[ERROR] Registration error: {str(e)}")
        # Don't expose detailed error messages to users
        return Response(
            {"error": "Registration failed. Please try again."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
