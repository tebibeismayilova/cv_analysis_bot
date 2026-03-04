import os
import re
import json
import math
import tempfile
import requests
from flask import Flask, request, jsonify, send_from_directory
from docx import Document

app = Flask(__name__, static_folder="static")

OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3"  # Change to your installed model e.g. "mistral", "phi3"
THRESHOLD = 80  # Similarity score threshold (%)

# ─── File Parsing ────────────────────────────────────────────────────────────

def parse_pdf(file_bytes: bytes) -> str:
    """Extract text from PDF using PyMuPDF if available, else basic fallback."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
        return text
    except ImportError:
        # Fallback: try pdfplumber or pypdf
        try:
            import io
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            return "\n".join(p.extract_text() or "" for p in reader.pages)
        except ImportError:
            return ""

def parse_docx(file_bytes: bytes) -> str:
    """Extract text from DOCX."""
    import io
    doc = Document(io.BytesIO(file_bytes))
    return "\n".join(p.text for p in doc.paragraphs)

def extract_text(filename: str, file_bytes: bytes) -> str:
    ext = filename.lower().rsplit(".", 1)[-1]
    if ext == "pdf":
        return parse_pdf(file_bytes)
    elif ext in ("docx", "doc"):
        return parse_docx(file_bytes)
    return ""

# ─── Ollama Integration ───────────────────────────────────────────────────────

def call_ollama(prompt: str) -> str:
    """Send a prompt to Ollama and return the response text."""
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=120
        )
        resp.raise_for_status()
        return resp.json().get("response", "")
    except requests.exceptions.ConnectionError:
        raise RuntimeError("Cannot connect to Ollama. Make sure Ollama is running: `ollama serve`")
    except Exception as e:
        raise RuntimeError(f"Ollama error: {e}")

def check_ollama() -> dict:
    """Check if Ollama is running and model is available."""
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        models = [m["name"] for m in resp.json().get("models", [])]
        return {"running": True, "models": models}
    except Exception:
        return {"running": False, "models": []}

# ─── CV Processing Logic ──────────────────────────────────────────────────────

EXTRACT_PROMPT = """You are a CV parser. Extract ONLY the following sections from the CV text below:
1. About / Summary / Objective
2. Skills / Technologies
3. Experience / Work History

Return a JSON object with exactly these keys: "about", "skills", "experience", "name", "email"
- "name": candidate's full name (or "Unknown" if not found)
- "email": candidate's email address (or "" if not found)  
- "about": the about/summary/objective section text
- "skills": the skills/technologies section text
- "experience": the experience/work history section text

If a section is not found, return an empty string for that key.
Return ONLY the JSON object, no other text, no markdown, no explanation.

CV TEXT:
{cv_text}
"""

SCORE_PROMPT = """You are an expert HR screener. Score how well a candidate's profile matches the job requirements.

JOB REQUIREMENTS:
{requirements}

CANDIDATE PROFILE:
About: {about}
Skills: {skills}
Experience: {experience}

Analyze the match carefully. Consider:
- Skill overlap (required skills vs candidate skills)
- Experience relevance and years
- Domain/industry fit
- Overall suitability

Return a JSON object with exactly these keys:
- "score": integer from 0 to 100 (overall match percentage)
- "skill_match": integer 0-100 (how well skills match)
- "experience_match": integer 0-100 (how well experience matches)
- "strengths": list of 2-3 short strings describing strong matches
- "gaps": list of 1-3 short strings describing missing requirements
- "summary": one sentence explaining the score

Return ONLY the JSON object, no markdown, no explanation.
"""

def extract_sections(cv_text: str) -> dict:
    prompt = EXTRACT_PROMPT.format(cv_text=cv_text[:4000])  # Limit context
    raw = call_ollama(prompt)
    try:
        # Strip any markdown code fences
        clean = re.sub(r"```json|```", "", raw).strip()
        return json.loads(clean)
    except Exception:
        # Fallback: return raw text in about field
        return {"about": cv_text[:500], "skills": "", "experience": "", "name": "Unknown", "email": ""}

def score_candidate(requirements: str, sections: dict) -> dict:
    prompt = SCORE_PROMPT.format(
        requirements=requirements,
        about=sections.get("about", ""),
        skills=sections.get("skills", ""),
        experience=sections.get("experience", "")
    )
    raw = call_ollama(prompt)
    try:
        clean = re.sub(r"```json|```", "", raw).strip()
        return json.loads(clean)
    except Exception:
        return {"score": 0, "skill_match": 0, "experience_match": 0,
                "strengths": [], "gaps": ["Could not parse AI response"], "summary": "Error in scoring"}

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "cvindex.html")

@app.route("/api/status")
def status():
    info = check_ollama()
    return jsonify(info)

@app.route("/api/models")
def models():
    info = check_ollama()
    return jsonify({"models": info.get("models", [])})

@app.route("/api/screen", methods=["POST"])
def screen():
    global OLLAMA_MODEL
    requirements = request.form.get("requirements", "").strip()
    threshold = int(request.form.get("threshold", THRESHOLD))
    model = request.form.get("model", OLLAMA_MODEL)
    OLLAMA_MODEL = model

    if not requirements:
        return jsonify({"error": "Job requirements are required"}), 400

    files = request.files.getlist("resumes")
    if not files:
        return jsonify({"error": "No resume files uploaded"}), 400

    results = []

    for f in files:
        filename = f.filename
        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

        if ext not in ("pdf", "docx", "doc"):
            results.append({
                "filename": filename,
                "error": "Unsupported file type. Only PDF and DOCX allowed.",
                "status": "error"
            })
            continue

        try:
            file_bytes = f.read()

            # Step 2: Read file
            cv_text = extract_text(filename, file_bytes)
            if not cv_text.strip():
                results.append({"filename": filename, "error": "Could not extract text from file.", "status": "error"})
                continue

            # Step 3: Extract sections
            sections = extract_sections(cv_text)

            # Step 4: Score
            scoring = score_candidate(requirements, sections)
            score = scoring.get("score", 0)

            # Step 5: Determine status
            status_val = "accepted" if score >= threshold else "rejected"

            results.append({
                "filename": filename,
                "name": sections.get("name", "Unknown"),
                "email": sections.get("email", ""),
                "score": score,
                "skill_match": scoring.get("skill_match", 0),
                "experience_match": scoring.get("experience_match", 0),
                "strengths": scoring.get("strengths", []),
                "gaps": scoring.get("gaps", []),
                "summary": scoring.get("summary", ""),
                "about": sections.get("about", ""),
                "skills": sections.get("skills", ""),
                "experience": sections.get("experience", ""),
                "status": status_val,
                "threshold": threshold
            })

        except RuntimeError as e:
            return jsonify({"error": str(e)}), 503
        except Exception as e:
            results.append({"filename": filename, "error": str(e), "status": "error"})

    accepted = [r for r in results if r.get("status") == "accepted"]
    rejected = [r for r in results if r.get("status") == "rejected"]
    errors = [r for r in results if r.get("status") == "error"]

    return jsonify({
        "total": len(files),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "error_count": len(errors),
        "threshold": threshold,
        "results": sorted(results, key=lambda x: x.get("score", -1), reverse=True)
    })

if __name__ == "__main__":
    os.makedirs("static", exist_ok=True)
    print("🚀 CV Screener running at http://localhost:5000")
    print("📋 Make sure Ollama is running: ollama serve")
    app.run(debug=True, port=5000)