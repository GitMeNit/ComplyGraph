"""Deliberately non-compliant demo service used to showcase the scanner. NOT for production."""
import logging
import requests
from sklearn.ensemble import GradientBoostingClassifier

logger = logging.getLogger(__name__)
OPENAI_API_KEY = "sk-FAKEDEMOKEYFAKEDEMOKEY1234567890"   # fake demo value
LLM_URL = "https://api.openai.com/v1/chat/completions"
SCORE_API = "http://scores.internal-vendor.example/score"

model = GradientBoostingClassifier()


def loan_decision(applicant: dict) -> str:
    logger.info("scoring applicant %s", applicant["email"])
    risk = requests.post(SCORE_API, json=applicant).json()["risk"]
    credit_score = model.predict_proba([[risk]])[0][1]
    return "auto_approve" if credit_score > 0.4 else "auto_reject"


def chatbot_reply(question: str) -> str:
    return requests.post(LLM_URL, json={"messages": [{"role": "user", "content": question}]}, timeout=10).text
