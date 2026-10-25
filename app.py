"""Alteryx Migration Analyzer: web app.

Run from the project folder:   streamlit run app.py
"""
import base64
import hashlib
import html as htmllib
import os
import sys
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).parent
os.chdir(APP_DIR)  # rules, templates and samples are found relative to the app, wherever it's launched from
sys.path.insert(0, str(APP_DIR / "src"))

from pipeline import WorkflowError, analyze, load_all_rules, render_report  # noqa: E402
from report import BANDS, group_gotchas, score_level  # noqa: E402

SAMPLES = Path("tests/workflows")
# Samples offered in the app, first one is the default. WF1 and WF2 stay in tests/ for evaluation.
APP_SAMPLES = ["wf4_savings_report.yxmd", "wf3_monthly_trend.yxmd"]
SAVED_AI = Path("outputs/ai")
# Online demo: set DEMO_MODE = "true" in the hosting service's secrets. Live AI is off;
# samples show their saved AI summaries instead, so the demo never spends API credits.
DEMO = os.getenv("DEMO_MODE", "").strip().lower() in ("1", "true", "yes")
COLORS = {"low": "#2e7d4f", "medium": "#c99a1a", "high": "#b02a37"}

st.set_page_config(page_title="Alteryx-to-Redshift Workflow Analyzer", page_icon="🔎", layout="wide")


@st.cache_resource
def rules():
    return load_all_rules()


def score_bar(score, level):
    cells = "".join(
        f'<div style="height:12px;border:1px solid {COLORS[level] if i <= score else "#d9dee7"};'
        f'background:{COLORS[level] if i <= score else "transparent"}"></div>' for i in range(1, 11))
    return f'<div style="display:grid;grid-template-columns:repeat(10,1fr);gap:3px;max-width:420px">{cells}</div>'


def isolated(html):
    """Embed HTML as a data: URL, so it runs in its own origin, sealed off from the app.

    The report contains text from the uploaded file and from the AI. It's escaped already,
    but isolating it means even a missed edge case can't reach the app itself.
    """
    return "data:text/html;charset=utf-8;base64," + base64.b64encode(html.encode("utf-8")).decode("ascii")


def mermaid_html(code):
    return f"""<meta charset="utf-8"><pre class="mermaid">{htmllib.escape(code)}</pre>
<script type="module">
  import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
  mermaid.initialize({{ startOnLoad: true, theme: "base" }});
</script>"""


def run_ai(result):
    """Call Claude for this workflow. Returns (summary, error message)."""
    from dotenv import load_dotenv
    from ai_summary import DEFAULT_MODEL, ask_claude, build_facts_from, check_citations, parse_reply

    load_dotenv()
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None, "No API key found. Add ANTHROPIC_API_KEY to the .env file in the project folder."
    model = os.getenv("CLAUDE_MODEL", DEFAULT_MODEL)
    facts = build_facts_from(result["parsed"], result["score"], result["gotchas"])
    try:
        text, usage = ask_claude(facts, model)
        ai = parse_reply(text)
    except Exception as exc:  # network, authentication, or a reply that isn't JSON
        return None, f"The AI summary failed: {type(exc).__name__}. The rule-based results above are unaffected."
    ai["_check"] = {"model": model, "usage": usage,
                    "uncited_or_invented_tool_ids": check_citations(ai, facts)}
    return ai, None


# ---------- page ----------

st.title("Alteryx-to-Redshift Workflow Analyzer")
st.caption("Scores how hard an Alteryx workflow is to rebuild in Amazon Redshift SQL, flags the logic "
           "that won't translate cleanly, and explains it in plain English.")

with st.sidebar:
    st.header("How it works")
    st.markdown(
        "1. **Code reads the workflow file:** every tool, setting, and connection.\n"
        "2. **Rules score each tool** (`rules/tool_rules.yaml`) and **check formulas and settings** "
        "for known migration issues (`rules/formula_gotchas.yaml`).\n"
        "3. **AI explains the facts**, only when you ask. Every tool it cites is checked "
        "against the workflow.\n\n"
        "The score comes from the rules, not the AI. "
        + ("In this online demo, files are processed on the hosting server and live AI is off."
           if DEMO else
           "The workflow file stays on this computer; only a summary of facts (file names, no paths) "
           "is sent if you request the AI explanation."))

if DEMO:
    st.info("**Online demo.** Try the sample workflows. Uploaded files are processed on a hosted server, "
            "so please don't upload confidential workflows. To analyze your own files privately, "
            "[run it on your computer](https://github.com/FaizaLag/alteryx-migration-analyzer#run-it).")

source = st.radio("Workflow", ["Upload a file", "Try a sample"], horizontal=True)
data = name = None
from_sample = False
if source == "Upload a file":
    up = st.file_uploader("Alteryx workflow or macro", type=["yxmd", "yxmc"])
    if up:
        data, name = up.getvalue(), up.name
else:
    samples = [n for n in APP_SAMPLES if (SAMPLES / n).exists()]
    if samples:
        name = st.selectbox("Sample workflow", samples)
        data = (SAMPLES / name).read_bytes()
        from_sample = True
    else:
        st.info("No sample workflows found in tests/workflows.")

if data is None:
    st.stop()

key = hashlib.sha256(data).hexdigest()
try:
    result = analyze(data, name, rules())
except WorkflowError as exc:
    st.error(str(exc))
    st.stop()

parsed, score, gotchas = result["parsed"], result["score"], result["gotchas"]
level = score_level(score["score"])
counts = gotchas["counts"]

# ---------- headline ----------
left, mid, right = st.columns([2, 1, 1])
with left:
    st.subheader(parsed["file_name"])
    st.markdown(f"### {score['score']}/10 · {BANDS[score['score']]}")
    st.html(score_bar(score["score"], level))
with mid:
    st.metric("Tools", parsed["tool_count"])
    st.metric("Difficulty points", score["total_points"])
with right:
    st.metric("Gotchas", len(gotchas["findings"]))
    st.caption(f"{counts['high']} high · {counts['medium']} medium · {counts['low']} low")

for m in parsed["macros_used"]:
    st.info(f"This workflow calls the macro **{m['file']}**. Its logic is in a separate file; "
            "upload it to assess it too.")
if score["unknown_tools"]:
    st.warning("Tools not in the rules yet (scored conservatively, review by hand): "
               + ", ".join(sorted(set(score["unknown_tools"]))))

tab_risks, tab_flow, tab_tools, tab_ai, tab_report = st.tabs(
    ["Gotchas", "Data flow", "Tools", "AI explanation", "Full report"])

with tab_risks:
    st.caption("Logic that doesn't translate cleanly to Redshift, most severe first.")
    st.dataframe(
        [{"Severity": g["severity"], "Issue": g["message"], "Tools": ", ".join(g["tools"]),
          "What to do in Redshift": g["redshift"]} for g in group_gotchas(gotchas["findings"])],
        width="stretch", hide_index=True)

with tab_flow:
    st.caption("Colors show migration difficulty: red high, yellow medium, green low, grey nothing to migrate. "
               "Needs an internet connection to draw.")
    height = 1400 if parsed["tool_count"] > 10 else 450
    st.iframe(isolated(mermaid_html(result["mermaid"])), height=height)

with tab_tools:
    st.dataframe(
        [{"ID": t["tool_id"], "Tool": t["name"], "Difficulty": t["difficulty"], "Points": t["points"],
          "In Redshift": t.get("redshift") or ""} for t in score["tools"] if not t.get("interface")],
        width="stretch", hide_index=True)

def show_ai(ai):
    bad = ai["_check"]["uncited_or_invented_tool_ids"]
    if bad:
        st.warning(f"The AI cited tools that aren't in this workflow: {', '.join(bad)}. Treat its text with care.")
    else:
        st.success("Citation check passed: every tool the AI mentions exists in the workflow.")
    st.markdown(ai["summary"])
    st.markdown("**Main risks**")
    for r in ai["risks"]:
        st.markdown(f"- **{r['title']}** ({r['severity']}): {r['detail']}")
    st.markdown("**Next steps**")
    for i, s in enumerate(ai["next_steps"], 1):
        st.markdown(f"{i}. {s}")


ai_store = st.session_state.setdefault("ai", {})
saved = SAVED_AI / f"{Path(name).stem}.json"
if DEMO and from_sample and saved.exists() and key not in ai_store:
    import json
    ai_store[key] = json.loads(saved.read_text(encoding="utf-8"))

with tab_ai:
    if DEMO:
        if key in ai_store:
            st.caption(f"Generated earlier by {ai_store[key]['_check']['model']} for this sample. "
                       "Live AI explanations are turned off in the online demo.")
        else:
            st.info("Live AI explanations are turned off in the online demo. Run the app on your own "
                    "computer with your own API key to explain uploaded workflows.")
    else:
        st.caption("Plain-English summary, risks, and next steps, written by AI from the facts above. "
                   "Each click uses API credits.")
        if key not in ai_store and st.button("Explain with AI"):
            with st.spinner("Asking Claude..."):
                ai, err = run_ai(result)
            if err:
                st.error(err)
            else:
                ai_store[key] = ai  # kept for this session, so switching tabs doesn't call the API again
                st.rerun()
    if key in ai_store:
        show_ai(ai_store[key])

with tab_report:
    html, md = render_report(result, ai_store.get(key), rules())
    st.caption("The same report as the command-line tool"
               + (", including the AI summary." if key in ai_store else ". Run the AI explanation to include its summary."))
    stem = Path(parsed["file_name"]).stem
    c1, c2 = st.columns(2)
    c1.download_button("Download HTML report", html, file_name=f"{stem}.html", mime="text/html")
    c2.download_button("Download Markdown report", md, file_name=f"{stem}.md", mime="text/markdown")
    st.iframe(isolated(html), height=1600)