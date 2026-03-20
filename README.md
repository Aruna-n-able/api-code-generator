# N-Central API Code Generator

A browser-based tool that reads an **N-Central WSDL file** and generates a complete REST API implementation in either **Java (Spring Boot 3)** or **Python (FastAPI)**.

The UI is built with **React + TypeScript** (compiled to plain JS/HTML/CSS via Vite), so no backend or server is required to run the generator itself.

---

## Table of Contents

1. [What it does](#what-it-does)
2. [Prerequisites](#prerequisites)
3. [Quick start — run locally](#quick-start--run-locally)
4. [Deploy the UI](#deploy-the-ui)
   - [Vercel](#vercel-recommended)
   - [Netlify](#netlify)
   - [Static file server / Nginx](#static-file-server--nginx)
   - [Docker](#docker)
5. [Using the generated Java code](#using-the-generated-java-code)
   - [Project setup](#java-project-setup)
   - [Run & test](#java-run--test)
6. [Using the generated Python code](#using-the-generated-python-code)
   - [Project setup](#python-project-setup)
   - [Run & test](#python-run--test)
7. [Development — contributing to the generator](#development--contributing-to-the-generator)

---

## What it does

1. **Upload or paste** an N-Central WSDL file.
2. **Select** one of the discovered operations.
3. **Choose** your target language — Java ☕ or Python 🐍.
4. Click **Implement REST API** — six files are generated instantly in the browser.
5. Optionally **refine** the code with an AI chat (requires an OpenAI API key).
6. **Generate tests** — JUnit 5 / Mockito unit tests + Robot Framework acceptance tests (Java) or pytest + Robot Framework (Python).
7. **Copy or download** each file individually.

### Generated files

| UI tab | Java file | Python file |
|--------|-----------|-------------|
| Controller | `{Op}Controller.java` | `{op}_router.py` |
| Service | `{Op}Service.java` | `{op}_service_base.py` |
| ServiceImpl | `{Op}ServiceImpl.java` | `{op}_service.py` |
| Transformer | `{Op}Transformer.java` | `{op}_transformer.py` |
| RequestDTO | `{Op}Request.java` | `{op}_request.py` |
| ResponseDTO | `{Op}Response.java` | `{op}_response.py` |

---

## Prerequisites

### To run the generator UI

| Requirement | Version |
|-------------|---------|
| Node.js | ≥ 18 |
| npm | ≥ 9 (bundled with Node.js) |

### To use the generated Java code

| Requirement | Version |
|-------------|---------|
| Java JDK | 17 or 21 (LTS) |
| Maven | 3.9+ **or** Gradle 8+ |

### To use the generated Python code

| Requirement | Version |
|-------------|---------|
| Python | 3.11+ |
| pip | latest |

---

## Quick start — run locally

```bash
# 1. Clone the repository
git clone https://github.com/Aruna-n-able/api-code-generator.git
cd api-code-generator

# 2. Install dependencies
npm install

# 3. Start the development server (hot-reload)
npm run dev
```

Open <http://localhost:5173> in your browser.

> **Optional:** To enable AI-powered code refinement, click **Settings** in the top-right corner and paste your [OpenAI API key](https://platform.openai.com/api-keys). The key is stored only in memory and never sent anywhere except the OpenAI API.

---

## Deploy the UI

The UI compiles to a static bundle of HTML, JS, and CSS — it can be hosted anywhere.

### Build the production bundle

```bash
npm run build
# Output is written to ./dist/
```

Preview the production build locally:

```bash
npm run preview
# Opens http://localhost:4173
```

---

### Vercel (recommended)

1. Push the repository to GitHub (or fork it).
2. Go to <https://vercel.com> → **New Project** → import the repo.
3. Framework preset: **Vite** (auto-detected).
4. Build command: `npm run build` | Output directory: `dist`
5. Click **Deploy**.

Every push to `main` triggers an automatic re-deploy.

---

### Netlify

```bash
# Install the Netlify CLI (once)
npm install -g netlify-cli

# Build and deploy
npm run build
netlify deploy --prod --dir dist
```

Or connect the GitHub repo to Netlify's dashboard for continuous deployment.

> Add a `netlify.toml` at the project root to handle client-side routing:
>
> ```toml
> [[redirects]]
>   from = "/*"
>   to = "/index.html"
>   status = 200
> ```

---

### Static file server / Nginx

```bash
npm run build
# Copy ./dist/ to your web server's document root

# Example with Python's built-in server (for quick testing only)
cd dist
python3 -m http.server 8080
# Open http://localhost:8080
```

Nginx snippet:

```nginx
server {
    listen 80;
    root /var/www/api-code-generator/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

---

### Docker

Create a `Dockerfile` at the project root (not included in the repo — add it if needed):

```dockerfile
# Stage 1 – build
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Stage 2 – serve
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

`nginx.conf`:

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

```bash
docker build -t api-code-generator .
docker run -p 8080:80 api-code-generator
# Open http://localhost:8080
```

---

## Using the generated Java code

The Java generator targets **Spring Boot 3** with Lombok, Jakarta EE, and SpringDoc OpenAPI.

### Java project setup

1. Create a new Spring Boot project via [start.spring.io](https://start.spring.io) with these dependencies:
   - **Spring Web**
   - **Lombok**
   - **Spring Boot Actuator** (optional but recommended)
   - **Validation** (Bean Validation)

   Or add the following to an existing `pom.xml`:

   ```xml
   <dependencies>
       <!-- Spring Web -->
       <dependency>
           <groupId>org.springframework.boot</groupId>
           <artifactId>spring-boot-starter-web</artifactId>
       </dependency>
       <!-- Bean Validation -->
       <dependency>
           <groupId>org.springframework.boot</groupId>
           <artifactId>spring-boot-starter-validation</artifactId>
       </dependency>
       <!-- Lombok -->
       <dependency>
           <groupId>org.projectlombok</groupId>
           <artifactId>lombok</artifactId>
           <optional>true</optional>
       </dependency>
       <!-- SOAP client (Apache CXF or zeep equivalent) -->
       <dependency>
           <groupId>org.apache.cxf</groupId>
           <artifactId>cxf-spring-boot-starter-jaxws</artifactId>
           <version>4.0.5</version>
       </dependency>
       <!-- SpringDoc OpenAPI (Swagger UI) -->
       <dependency>
           <groupId>org.springdoc</groupId>
           <artifactId>springdoc-openapi-starter-webmvc-ui</artifactId>
           <version>2.5.0</version>
       </dependency>
   </dependencies>
   ```

2. Copy the six generated `.java` files into the correct package structure:

   ```
   src/main/java/com/ncentral/api/
   ├── controller/   ← {Op}Controller.java
   ├── dto/          ← {Op}Request.java, {Op}Response.java
   ├── service/      ← {Op}Service.java (interface)
   ├── service/impl/ ← {Op}ServiceImpl.java
   └── transformer/  ← {Op}Transformer.java
   ```

3. Implement the `NCentralSoapClient` class (the SOAP stub that calls the real N-Central endpoint). The generated code references this class but does not generate it, because it depends on the WSDL binding you choose.

### Java run & test

```bash
# Run the application
./mvnw spring-boot:run
# or: java -jar target/your-app.jar

# Application starts at http://localhost:8080
# Swagger UI: http://localhost:8080/swagger-ui.html
```

**Run unit tests**

Copy the generated `{Op}ServiceImplTest.java` into `src/test/java/.../service/impl/` and run:

```bash
./mvnw test
# or: ./mvnw test -Dtest=GetDeviceInfoServiceImplTest
```

**Run Robot Framework acceptance tests**

```bash
# Install Robot Framework and RequestsLibrary
pip install robotframework robotframework-requests

# Run the .robot test file (app must be running first)
robot tests/GetDeviceInfoTests.robot
```

**Lint**

```bash
# With Checkstyle (if configured)
./mvnw checkstyle:check

# With SpotBugs
./mvnw spotbugs:check
```

---

## Using the generated Python code

The Python generator targets **FastAPI** with Pydantic v2 and the `zeep` SOAP client.

### Python project setup

1. Create a virtual environment and install dependencies:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate          # Windows: .venv\Scripts\activate

   pip install fastapi "uvicorn[standard]" pydantic zeep
   # For tests:
   pip install pytest pytest-asyncio httpx
   # For Robot Framework tests:
   pip install robotframework robotframework-requests
   ```

2. Lay out your project:

   ```
   my_api/
   ├── main.py                  ← FastAPI app entry point (you create this)
   ├── dependencies.py          ← Dependency injection helpers (you create this)
   ├── soap/
   │   ├── client.py            ← NCentralSoapClient using zeep (you create this)
   │   └── models.py            ← SOAP request/response dataclasses (you create this)
   └── operations/
       └── get_device_info/     ← one folder per operation
           ├── schemas.py       ← paste {op}_request.py + {op}_response.py here
           ├── service_base.py  ← paste {op}_service_base.py here
           ├── service.py       ← paste {op}_service.py here
           ├── transformer.py   ← paste {op}_transformer.py here
           └── router.py        ← paste {op}_router.py here
   ```

   **`main.py` example:**

   ```python
   from fastapi import FastAPI
   from operations.get_device_info.router import router as get_device_info_router

   app = FastAPI(title="N-Central REST API", version="1.0.0")
   app.include_router(get_device_info_router)
   ```

   **`soap/client.py` skeleton:**

   ```python
   import zeep

   NCENTRAL_WSDL = "https://your-ncentral-server/dms/services/ServerEI2?wsdl"

   class NCentralSoapClient:
       def __init__(self):
           self._client = zeep.Client(wsdl=NCENTRAL_WSDL)

       def get_device_info(self, soap_request):
           return self._client.service.getDeviceInfo(**vars(soap_request))
   ```

   **`dependencies.py` skeleton:**

   ```python
   from soap.client import NCentralSoapClient
   from operations.get_device_info.transformer import GetDeviceInfoTransformer
   from operations.get_device_info.service import GetDeviceInfoService

   def get_get_device_info_service() -> GetDeviceInfoService:
       return GetDeviceInfoService(
           soap_client=NCentralSoapClient(),
           transformer=GetDeviceInfoTransformer(),
       )
   ```

### Python run & test

```bash
# Start the API server (development, auto-reload)
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Application starts at http://localhost:8000
# Swagger UI:  http://localhost:8000/docs
# ReDoc:       http://localhost:8000/redoc
```

**Run pytest unit tests**

Copy the generated `test_{op}_service.py` into a `tests/` folder:

```bash
pytest tests/ -v
# Run a single test file
pytest tests/test_get_device_info_service.py -v
# With coverage
pip install pytest-cov
pytest tests/ --cov=operations --cov-report=term-missing
```

**Run Robot Framework acceptance tests**

```bash
# The app must be running first (uvicorn main:app --port 8000)
robot tests/GetDeviceInfoTests.robot

# Run with a custom base URL
robot --variable BASE_URL:http://my-server:8000 tests/GetDeviceInfoTests.robot

# Generate HTML report
robot --outputdir reports tests/
```

**Lint**

```bash
pip install ruff mypy
ruff check .
mypy operations/
```

---

## Development — contributing to the generator

These commands apply to the generator UI itself (this repository).

```bash
# Install dependencies
npm install

# Start development server with hot-reload
npm run dev

# Type-check + build for production
npm run build

# Lint TypeScript/React source
npm run lint

# Preview production build
npm run preview
```

### Project structure

```
src/
├── components/          # React UI components
│   ├── ApiKeyInput.tsx
│   ├── ChatInterface.tsx
│   ├── GeneratedCode.tsx
│   ├── LanguageSelector.tsx
│   ├── OperationDetail.tsx
│   ├── OperationsList.tsx
│   ├── TestGenerator.tsx
│   └── WsdlUploader.tsx
├── services/            # Code generation logic (pure TypeScript, no browser APIs)
│   ├── codeGenerator.ts       # Java / Spring Boot generator
│   ├── pythonCodeGenerator.ts # Python / FastAPI generator
│   ├── openaiService.ts       # OpenAI API integration
│   └── wsdlParser.ts          # WSDL XML → structured data
├── types/
│   └── index.ts         # Shared TypeScript interfaces & types
├── App.tsx              # Root component & application state
└── main.tsx             # React entry point
```

### Environment variables

No environment variables are required. The OpenAI API key is entered by the user at runtime and never persisted.

---

## License

See [LICENSE](LICENSE) if present, or check with the repository owner.
