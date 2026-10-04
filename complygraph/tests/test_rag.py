from complygraph.config import Settings
from complygraph.llm import OfflineLLM
from complygraph.rag.corrective import CorrectiveRAG
from complygraph.rag.retriever import get_retriever

S = Settings.load()


def crag():
    return CorrectiveRAG(get_retriever(S), OfflineLLM(), S.crag_threshold, S.crag_max_attempts)


def test_direct_hit_no_rewrite():
    r = crag().run("How long do we have to report a personal data breach?")
    assert r["attempts"] == 1 and not r["abstained"] and "72" in r["answer"] or "[R1]" in r["answer"]
    assert r["refs"][0]["section"].startswith("Article 33")


def test_self_correction_triggers_and_improves():
    r = crag().run("What must we do if our payments platform has an outage?")
    assert r["attempts"] >= 2
    assert r["history"][-1]["confidence"] > r["history"][0]["confidence"]
    assert "Articles 17 to 19" in r["refs"][0]["section"]


def test_abstains_when_out_of_corpus():
    r = crag().run("What is the best pizza topping?")
    assert r["abstained"] and r["attempts"] == S.crag_max_attempts and "Insufficient evidence" in r["answer"]
