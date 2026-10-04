"""Streamlit workbench:  streamlit run src/complygraph/ui.py"""
import json

import streamlit as st

from complygraph.config import Settings
from complygraph.copilot import Copilot
from complygraph.scanner.engine import Finding, ScanResult
from complygraph.scanner.report import to_sarif

st.set_page_config(page_title="ComplyGraph", page_icon="🗎", layout="wide")


@st.cache_resource
def get_copilot():
    return Copilot(Settings.load())


c = get_copilot()
with st.sidebar:
    st.title(" ComplyGraph")
    user = st.text_input("User", "alice")
    st.caption(f"LLM: `{c.llm.name}`  \nRetriever: `{c.crag.retriever.name}`  \nLangGraph: `{__import__('complygraph.graph_runtime', fromlist=['x']).HAS_LANGGRAPH}`")
    st.subheader("Tools (local + MCP)")
    for t in c.toolbox.describe():
        st.markdown(f"- `{t['server']}/{t['name']}`")

tab_ask, tab_appr, tab_audit = st.tabs(["Assess", "Approvals (maker-checker)", "Audit trail"])

with tab_ask:
    q = st.text_area("Question or assessment request", "Run a regulatory gap assessment of this service")
    path = st.text_input("Code path to scan (optional, inside allowed roots)", "examples/credit_scoring_service")
    if st.button("Run", type="primary"):
        r = c.ask(q, user, path or None)
        st.session_state["last"] = r
    r = st.session_state.get("last")
    if r:
        st.subheader(f"Status: {r['status']}")
        st.markdown(r["answer"])
        with st.expander("Agent trace"):
            st.code("\n".join(r["trace"]))
        if r.get("rag"):
            with st.expander("Self-corrective RAG attempts"):
                st.json(r["rag"]["history"])
        if r.get("scan") and "findings" in r["scan"]:
            sc = r["scan"]
            sarif = to_sarif(ScanResult(sc["target"], sc["files_scanned"], sc["rules_evaluated"], [Finding(**f) for f in sc["findings"]]))
            st.download_button("Download SARIF", json.dumps(sarif, indent=2), "complygraph.sarif.json")

with tab_appr:
    pend = c.approvals.pending()
    st.write(f"{len(pend)} pending")
    for a in pend:
        with st.expander(f"{a['id']} - {a['tier'].upper()} - requested by {a['requester']}"):
            st.write(a["reason"]); st.markdown(a["draft"][:3000])
            comment = st.text_input("Comment", key=f"c{a['id']}")
            col1, col2 = st.columns(2)
            for col, label, ok in [(col1, "Approve", True), (col2, "Reject", False)]:
                if col.button(label, key=f"{label}{a['id']}"):
                    try:
                        c.resume(a["id"], user, ok, comment); st.rerun()
                    except PermissionError as e:
                        st.error(str(e))

with tab_audit:
    st.json(c.audit.verify())
    st.dataframe([{k: v for k, v in r.items() if k != "payload"} | {"payload": json.dumps(r["payload"])[:120]}
                  for r in c.audit.records()[-100:]][::-1])
