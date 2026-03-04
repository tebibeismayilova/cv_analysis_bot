# CV Screener — AI Recruitment Bot

An AI-powered CV screening system using **Ollama** (local LLM) + **Flask** backend + beautiful web UI.

## How it works

1. **Upload** job requirements + PDF/DOCX resumes
2. AI **extracts** About / Skills / Experience from each resume
3. AI **scores** each resume against requirements (0–100%)
4. Resumes with score ≥ threshold (default 80%) are **accepted**
5. Results shown in UI with match breakdown, strengths & gaps

## Setup

### 1. Install Ollama
```bash
# macOS/Linux
curl -fsSL https://ollama.com/install.sh | sh

# Pull a model (choose one)
ollama pull llama3        # Recommended
ollama pull mistral       # Alternative
ollama pull phi3          # Lighter/faster

# Start Ollama
ollama serve
```

### 2. Install Python dependencies
```bash
pip install flask python-docx pymupdf requests
# or without PyMuPDF (uses pypdf as fallback):
pip install flask python-docx pypdf requests
```

### 3. Run the app
```bash
cd cv_screener
python app.py
```

### 4. Open the UI
Visit: **http://localhost:5000**

## Project Structure
```
cv_screener/
├── app.py              # Flask backend
├── static/
│   └── index.html      # Frontend UI
└── README.md
```

## Configuration (in app.py)

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_MODEL` | `llama3` | Ollama model to use (overridable in UI) |
| `THRESHOLD` | `80` | Default acceptance score % (overridable in UI) |
| `OLLAMA_URL` | `localhost:11434` | Ollama server URL |

## Notes
- **Privacy**: Candidate name & email are extracted for routing only, NOT used in scoring
- **Bias prevention**: The AI prompt scores only on skills, experience & domain fit
- **Supported formats**: PDF (.pdf) and Word (.docx, .doc)
- Borderline cases (70–79%) can be manually reviewed before next step (n8n email integration)
