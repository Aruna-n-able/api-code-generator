# Deployment & Testing Guide

This document provides step-by-step instructions for:

1. [Deploying the generator UI](#1-deploying-the-generator-ui)
2. [Deploying generated Java (Spring Boot) code](#2-deploying-generated-java-spring-boot-code)
3. [Deploying generated Python (FastAPI) code](#3-deploying-generated-python-fastapi-code)
4. [Testing — UI, Java, and Python](#4-testing)
5. [CI/CD pipeline examples](#5-cicd-pipeline-examples)
6. [Troubleshooting](#6-troubleshooting)

---

## 1. Deploying the generator UI

The generator is a static single-page application (SPA). The build output is a folder of plain HTML, CSS, and JavaScript — no server-side code needed.

### 1.1 Build

```bash
# From the repository root
npm install        # install dependencies (first time only)
npm run build      # produces ./dist/
```

The `dist/` folder contains everything needed to host the app.

### 1.2 Local preview (verify the build before deploying)

```bash
npm run preview
# → http://localhost:4173
```

### 1.3 Vercel

```bash
# One-time CLI setup
npm install -g vercel
vercel login

# Deploy (run from the project root)
vercel --prod
```

Vercel auto-detects Vite. It uses `npm run build` and serves from `dist/`.

Alternatively, connect your GitHub repository to the Vercel dashboard — every push to `main` triggers a new deployment.

**Environment variables on Vercel:** none are required; the OpenAI key is entered by the user in the browser.

### 1.4 Netlify

```bash
npm install -g netlify-cli
netlify login
npm run build
netlify deploy --prod --dir dist
```

Add `netlify.toml` to the project root to handle page refreshes:

```toml
[[redirects]]
  from = "/*"
  to = "/index.html"
  status = 200
```

### 1.5 GitHub Pages

```bash
# Install the gh-pages helper
npm install --save-dev gh-pages

# Add to package.json → scripts:
#   "deploy": "gh-pages -d dist"

npm run build
npm run deploy
```

Your site will be live at `https://<your-org>.github.io/api-code-generator/`.

> If serving from a sub-path, set `base` in `vite.config.ts`:
>
> ```ts
> export default defineConfig({
>   base: '/api-code-generator/',
>   ...
> })
> ```

### 1.6 Docker (Nginx)

**`Dockerfile`** (create at the project root if it doesn't exist):

```dockerfile
# Stage 1 – build the React app
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci --frozen-lockfile
COPY . .
RUN npm run build

# Stage 2 – serve with Nginx
FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

**`nginx.conf`** (create at the project root):

```nginx
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    # Required for SPA client-side routing
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Cache static assets aggressively
    location ~* \.(js|css|png|svg|ico|woff2)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```

```bash
# Build and run
docker build -t api-code-generator:latest .
docker run -d -p 8080:80 --name api-code-generator api-code-generator:latest

# Verify
curl -I http://localhost:8080
# Open http://localhost:8080 in a browser
```

---

## 2. Deploying generated Java (Spring Boot) code

The Java generator produces six files targeting Spring Boot 3 / Jakarta EE. Follow these steps to integrate them into a working project.

### 2.1 Create a Spring Boot project

Use [start.spring.io](https://start.spring.io) with these settings:

| Setting | Value |
|---------|-------|
| Project | Maven (or Gradle) |
| Language | Java |
| Spring Boot | 3.3.x |
| Packaging | Jar |
| Java | 21 |
| Dependencies | Spring Web, Validation, Lombok, Spring Boot Actuator |

Download and unzip (or generate via CLI):

```bash
curl -o starter.zip \
  "https://start.spring.io/starter.zip?type=maven-project&language=java&bootVersion=3.3.5&javaVersion=21&dependencies=web,validation,lombok,actuator"
unzip starter.zip -d my-ncentral-api
cd my-ncentral-api
```

### 2.2 Add additional dependencies

In `pom.xml`, add inside `<dependencies>`:

```xml
<!-- SpringDoc OpenAPI / Swagger UI -->
<dependency>
    <groupId>org.springdoc</groupId>
    <artifactId>springdoc-openapi-starter-webmvc-ui</artifactId>
    <version>2.5.0</version>
</dependency>

<!-- Apache CXF for SOAP client (calls N-Central) -->
<dependency>
    <groupId>org.apache.cxf</groupId>
    <artifactId>cxf-spring-boot-starter-jaxws</artifactId>
    <version>4.0.5</version>
</dependency>
```

### 2.3 Copy generated files

For a generated operation named `getDeviceInfo` with package `com.ncentral.api`:

```
src/main/java/com/ncentral/api/
├── controller/
│   └── GetDeviceInfoController.java   ← paste from UI
├── dto/
│   ├── GetDeviceInfoRequest.java      ← paste from UI
│   └── GetDeviceInfoResponse.java     ← paste from UI
├── service/
│   └── GetDeviceInfoService.java      ← paste from UI (interface)
├── service/impl/
│   └── GetDeviceInfoServiceImpl.java  ← paste from UI
└── transformer/
    └── GetDeviceInfoTransformer.java  ← paste from UI
```

You also need to provide a SOAP client bean. Create:

```
src/main/java/com/ncentral/api/soap/
├── NCentralSoapClient.java   ← implement with Apache CXF stubs
```

Minimal skeleton:

```java
package com.ncentral.api.soap;

import org.springframework.stereotype.Component;

@Component
public class NCentralSoapClient {
    // Inject Apache CXF-generated service here, e.g.:
    // @Autowired private com.ncentral.ServerEI2 serverEI2;

    public GetDeviceInfoSoapResponse getDeviceInfo(GetDeviceInfoSoapRequest req) {
        // TODO: call the real SOAP endpoint
        throw new UnsupportedOperationException("Implement SOAP call");
    }
}
```

### 2.4 Run locally

```bash
./mvnw spring-boot:run
```

```
Started application at http://localhost:8080
Swagger UI: http://localhost:8080/swagger-ui.html
Actuator:   http://localhost:8080/actuator/health
```

Test the endpoint manually:

```bash
# GET operation example
curl -X GET "http://localhost:8080/api/v1/get-device-info" \
     -H "Accept: application/json"

# POST / PUT operation example
curl -X POST "http://localhost:8080/api/v1/update-device" \
     -H "Content-Type: application/json" \
     -d '{"deviceId": 123, "deviceName": "MyDevice"}'
```

### 2.5 Build a deployable JAR

```bash
./mvnw clean package -DskipTests
java -jar target/my-ncentral-api-0.0.1-SNAPSHOT.jar
```

### 2.6 Deploy to a server

```bash
# Copy the JAR to the server
scp target/my-ncentral-api.jar user@server:/opt/ncentral/

# Run as a background service (systemd example)
ssh user@server << 'EOF'
sudo tee /etc/systemd/system/ncentral-api.service > /dev/null << UNIT
[Unit]
Description=N-Central REST API
After=network.target

[Service]
ExecStart=/usr/bin/java -jar /opt/ncentral/my-ncentral-api.jar
User=ncentral
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now ncentral-api
EOF
```

### 2.7 Dockerize the Java app

```dockerfile
FROM eclipse-temurin:21-jdk-alpine AS build
WORKDIR /app
COPY . .
RUN ./mvnw clean package -DskipTests

FROM eclipse-temurin:21-jre-alpine
COPY --from=build /app/target/*.jar /app/app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
```

```bash
docker build -t ncentral-java-api:latest .
docker run -d -p 8080:8080 ncentral-java-api:latest
```

---

## 3. Deploying generated Python (FastAPI) code

### 3.1 Set up the project

```bash
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# Install runtime dependencies
pip install fastapi "uvicorn[standard]" pydantic zeep

# Save for reproducibility
pip freeze > requirements.txt
```

### 3.2 Lay out generated files

```
my_ncentral_api/
├── main.py                    ← you create: FastAPI app + router registration
├── dependencies.py            ← you create: dependency injection
├── soap/
│   ├── __init__.py
│   ├── client.py              ← you create: zeep SOAP client
│   └── models.py              ← you create: SOAP dataclasses
└── operations/
    └── get_device_info/
        ├── __init__.py
        ├── schemas.py         ← paste {op}_request.py + {op}_response.py
        ├── service_base.py    ← paste {op}_service_base.py
        ├── service.py         ← paste {op}_service.py
        ├── transformer.py     ← paste {op}_transformer.py
        └── router.py          ← paste {op}_router.py
```

**`main.py`:**

```python
from fastapi import FastAPI
from operations.get_device_info.router import router as get_device_info_router

app = FastAPI(
    title="N-Central REST API",
    version="1.0.0",
    description="REST wrapper for N-Central SOAP/WSDL operations",
)

app.include_router(get_device_info_router)

@app.get("/health", tags=["Health"])
def health() -> dict:
    return {"status": "ok"}
```

**`soap/client.py`:**

```python
import zeep
from dataclasses import dataclass

NCENTRAL_WSDL = "https://your-ncentral-server/dms/services/ServerEI2?wsdl"

class NCentralSoapClient:
    def __init__(self) -> None:
        self._client = zeep.Client(wsdl=NCENTRAL_WSDL)

    def get_device_info(self, soap_request):
        return self._client.service.getDeviceInfo(**vars(soap_request))
```

**`dependencies.py`:**

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

### 3.3 Run locally

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

```
Application:   http://localhost:8000
Swagger UI:    http://localhost:8000/docs
ReDoc:         http://localhost:8000/redoc
Health check:  http://localhost:8000/health
```

Test manually:

```bash
# GET endpoint
curl -X GET "http://localhost:8000/api/v1/get-device-info" \
     -H "Accept: application/json"

# PUT endpoint
curl -X PUT "http://localhost:8000/api/v1/update-device" \
     -H "Content-Type: application/json" \
     -d '{"device_id": 123, "device_name": "MyDevice"}'
```

### 3.4 Deploy to a server (systemd + uvicorn)

```bash
# On the server:
pip install fastapi "uvicorn[standard]" pydantic zeep
pip install -r requirements.txt

sudo tee /etc/systemd/system/ncentral-api.service > /dev/null << 'EOF'
[Unit]
Description=N-Central FastAPI
After=network.target

[Service]
WorkingDirectory=/opt/ncentral-api
ExecStart=/opt/ncentral-api/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
Restart=on-failure
User=ncentral

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now ncentral-api
```

### 3.5 Dockerize the Python app

**`Dockerfile`:**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

```bash
docker build -t ncentral-python-api:latest .
docker run -d -p 8000:8000 ncentral-python-api:latest

# Check
curl http://localhost:8000/health
```

---

## 4. Testing

### 4.1 Testing the generator UI

```bash
# Type-check + build (catches TypeScript errors)
npm run build

# Lint (ESLint)
npm run lint
```

There are no UI automated test files in the repository. To add them:

```bash
npm install --save-dev vitest @testing-library/react @testing-library/jest-dom jsdom
```

Then add to `vite.config.ts`:

```ts
test: {
  environment: 'jsdom',
  globals: true,
  setupFiles: './src/test/setup.ts',
}
```

### 4.2 Testing generated Java code

**Unit tests (JUnit 5 + Mockito)**

Copy `{Op}ServiceImplTest.java` from the **Test Generation** panel into:
`src/test/java/com/ncentral/api/service/impl/`

```bash
# Run all tests
./mvnw test

# Run a specific test class
./mvnw test -Dtest=GetDeviceInfoServiceImplTest

# Run with coverage (JaCoCo)
./mvnw test jacoco:report
# Report: target/site/jacoco/index.html
```

**Integration tests (Spring MockMvc)**

The `{Op}ControllerTest.java` template is included (commented out) in the unit test output. Uncomment and place in the test sources:

```bash
./mvnw test -Dtest=GetDeviceInfoControllerTest
```

**Robot Framework acceptance tests**

```bash
# Install dependencies
pip install robotframework robotframework-requests

# Start the Spring Boot app first, then:
robot tests/GetDeviceInfoTests.robot

# Run against a specific environment
robot --variable BASE_URL:http://staging-server:8080 tests/GetDeviceInfoTests.robot

# Generate a formatted HTML report
robot --outputdir reports tests/
open reports/report.html
```

### 4.3 Testing generated Python code

**pytest unit tests**

Copy `test_{op}_service.py` from the **Test Generation** panel into `tests/`:

```bash
# Install test dependencies
pip install pytest pytest-asyncio httpx

# Run all tests
pytest tests/ -v

# Run a specific file
pytest tests/test_get_device_info_service.py -v

# With coverage
pip install pytest-cov
pytest tests/ --cov=operations --cov-report=term-missing --cov-report=html
open htmlcov/index.html
```

**FastAPI endpoint tests (httpx)**

```python
# tests/test_get_device_info_router.py
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from main import app
from operations.get_device_info.service import GetDeviceInfoService
from operations.get_device_info.schemas import GetDeviceInfoResponse
from dependencies import get_get_device_info_service

def test_get_device_info_returns_200():
    mock_service = MagicMock(spec=GetDeviceInfoService)
    mock_service.get_device_info.return_value = GetDeviceInfoResponse(
        device_id=1, device_name="TestDevice", status="active"
    )
    app.dependency_overrides[get_get_device_info_service] = lambda: mock_service
    client = TestClient(app)

    response = client.get("/api/v1/get-device-info")

    assert response.status_code == 200
    assert response.json()["device_name"] == "TestDevice"
    app.dependency_overrides.clear()
```

**Robot Framework acceptance tests**

```bash
# The Python API must be running first
uvicorn main:app --port 8000 &

robot tests/GetDeviceInfoTests.robot

# Run with a custom base URL
robot --variable BASE_URL:http://localhost:8000 tests/GetDeviceInfoTests.robot

# HTML report
robot --outputdir reports tests/
open reports/report.html
```

**Lint (Python)**

```bash
pip install ruff mypy
ruff check .
mypy operations/ --strict
```

---

## 5. CI/CD pipeline examples

### GitHub Actions — UI build + lint

Create `.github/workflows/ui.yml`:

```yaml
name: UI – build & lint

on:
  push:
    branches: [main]
  pull_request:

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
      - run: npm ci
      - run: npm run lint
      - run: npm run build
      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/
```

### GitHub Actions — Java tests

Create `.github/workflows/java.yml`:

```yaml
name: Java – test

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with:
          java-version: 21
          distribution: temurin
          cache: maven
      - run: ./mvnw verify
```

### GitHub Actions — Python tests

Create `.github/workflows/python.yml`:

```yaml
name: Python – test

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r requirements.txt pytest pytest-asyncio httpx pytest-cov
      - run: pytest tests/ -v --cov=operations
```

---

## 6. Troubleshooting

### UI / build issues

| Symptom | Fix |
|---------|-----|
| `npm run build` fails with type errors | Run `npm install` then retry; ensure Node.js ≥ 18 |
| Blank page after deploy | Ensure your web server falls back to `index.html` for all routes |
| WSDL parse fails | Check the WSDL is valid XML; try pasting just the `<wsdl:definitions>` block |

### Java issues

| Symptom | Fix |
|---------|-----|
| `Cannot find symbol: NCentralSoapClient` | Create the SOAP client class (see section 2.3) |
| Lombok annotations not working | Ensure annotation processing is enabled in your IDE; add the Lombok Maven plugin |
| Port 8080 already in use | `lsof -i:8080` to find the process; or set `server.port=9090` in `application.properties` |

### Python issues

| Symptom | Fix |
|---------|-----|
| `ImportError: No module named 'fastapi'` | Activate your venv: `source .venv/bin/activate` |
| `zeep.exceptions.Fault` | Check the N-Central WSDL URL and network connectivity |
| `422 Unprocessable Entity` | The request body doesn't match the Pydantic schema — check field names (snake_case) |
| Port 8000 already in use | `lsof -i:8000` or change port: `uvicorn main:app --port 8001` |
