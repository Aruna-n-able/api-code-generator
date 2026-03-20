# N-Central API Code Generator

A tool that reads an **N-Central WSDL file** and generates a complete REST API implementation in either **Java (Spring Boot 3)** or **Python (FastAPI)**.

![API Code Generator UI](https://github.com/user-attachments/assets/e1f713fc-f8de-41d8-b7dd-a1805f30d815)

---

## ⚡ Quick Start — Simple Deployment (Python)

**No Node.js, no build step, no npm required.**

```bash
# 1. Clone
git clone https://github.com/Aruna-n-able/api-code-generator.git
cd api-code-generator

# 2. Install (Python 3.9+ required)
pip install -r requirements.txt

# 3. Run
python app.py

# 4. Open
# http://localhost:5000
```

That's it. The app is fully self-contained — the UI is served as a single static HTML file and all WSDL parsing and code generation runs in Python.

Change the port if needed:

```bash
PORT=8080 python app.py
```

---

## What it does

1. **Upload or paste** an N-Central WSDL file (sidebar)
2. **Select** one of the discovered operations
3. **Choose** your target language — ☕ Java (Spring Boot) or 🐍 Python (FastAPI)
4. Click **Implement REST API** — six files are generated instantly
5. Optionally **refine** the code via AI chat (requires an OpenAI API key in ⚙ Settings)
6. Click **"I'm satisfied"** to unlock test generation
7. **Generate Tests** — JUnit 5 / pytest unit tests + Robot Framework acceptance tests
8. **Copy or download** each file individually

### Generated files (per operation)

| Tab             | Java file                      | Python file                    |
|-----------------|--------------------------------|--------------------------------|
| Controller      | `{Op}Controller.java`          | `{op}_router.py`               |
| Service         | `{Op}Service.java` (interface) | `{op}_service_base.py` (ABC)   |
| ServiceImpl     | `{Op}ServiceImpl.java`         | `{op}_service.py`              |
| Transformer     | `{Op}Transformer.java`         | `{op}_transformer.py`          |
| RequestDTO      | `{Op}Request.java`             | `{op}_request.py`              |
| ResponseDTO     | `{Op}Response.java`            | `{op}_response.py`             |

---

## Deploy

### Option A — Python / Flask (simplest, recommended)

```bash
pip install -r requirements.txt
python app.py
# → http://localhost:5000
```

**Production with Gunicorn:**

```bash
pip install gunicorn
gunicorn app:app --bind 0.0.0.0:8080 --workers 4
```

**Docker:**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
COPY static/ static/
EXPOSE 5000
CMD ["python", "app.py"]
```

```bash
docker build -t api-code-generator .
docker run -p 5000:5000 api-code-generator
```

---

### Option B — Node.js / Vite (original, feature-identical)

Requires Node.js ≥ 18.

```bash
npm install
npm run dev        # development with hot-reload → http://localhost:5173
npm run build      # build to ./dist/
npm run preview    # preview production build → http://localhost:4173
```

Deploy the `dist/` folder to Vercel, Netlify, GitHub Pages, or any static host.

---

## Testing

### Test the generator UI

```bash
# Python version — no extra dependencies
python app.py
# Open http://localhost:5000 and paste a WSDL file

# Node.js version
npm run lint    # ESLint
npm run build   # TypeScript + Vite (fails on errors)
```

### Test generated Java code

```bash
# Copy generated files into a Spring Boot project, then:
./mvnw test                              # run all tests
./mvnw test -Dtest=GetDeviceInfoServiceImplTest  # single class

# Robot Framework acceptance tests (app must be running)
pip install robotframework robotframework-requests
robot tests/GetDeviceInfoTests.robot
```

### Test generated Python code

```bash
# Install test dependencies
pip install pytest pytest-asyncio httpx

# Run unit tests
pytest tests/ -v
pytest tests/ --cov=operations

# Robot Framework acceptance tests (uvicorn must be running)
pip install robotframework robotframework-requests
robot tests/GetDeviceInfoTests.robot
```

---

## Using generated Java code

See [`DEPLOYMENT.md`](DEPLOYMENT.md) for full step-by-step instructions including:

- Spring Boot project setup (`pom.xml` snippets)
- File layout and package structure
- SOAP client skeleton
- Build, run, and test commands
- Docker + systemd deployment

---

## Using generated Python code

See [`DEPLOYMENT.md`](DEPLOYMENT.md) for full step-by-step instructions including:

- Virtual environment setup and dependencies
- `main.py`, `dependencies.py`, `soap/client.py` skeletons
- `uvicorn` run commands
- Docker + systemd deployment
- pytest and Robot Framework test commands

---

## Configuration

| Environment variable | Default | Purpose |
|----------------------|---------|---------|
| `PORT` | `5000` | HTTP port for the Flask server |
| `FLASK_DEBUG` | `0` | Set to `1` to enable debug/hot-reload mode |

No API key is required to use the generator. The OpenAI API key (for AI refinement) is entered by the user at runtime via the Settings panel and is never stored on disk.

---

## Project structure

```
api-code-generator/
├── app.py              # Flask backend — WSDL parser + Java/Python generators + OpenAI proxy
├── requirements.txt    # Python dependencies (Flask, openai)
├── static/
│   └── index.html      # Complete single-file frontend (vanilla HTML + CSS + JS)
├── src/                # Original TypeScript/React source (Node.js build, same features)
│   ├── services/
│   │   ├── wsdlParser.ts
│   │   ├── codeGenerator.ts      # Java generator
│   │   └── pythonCodeGenerator.ts
│   └── components/
├── DEPLOYMENT.md       # Detailed deploy/test guide for generated Java and Python code
└── README.md
```
