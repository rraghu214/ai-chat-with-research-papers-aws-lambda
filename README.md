# AI Chat with Research Papers

This app ingests a research paper URL (arXiv or any PDF/HTML), summarizes it at **LOW / MEDIUM / HIGH** complexity, and offers a **chat interface** grounded in the paper text.

---

## Running on AWS Lambda (Flask Removed)
The original Flask app has been refactored into a pure AWS Lambda function exposed via API Gateway.

### Key Changes
- `app.py` now exports `lambda_handler(event, context)`.
- No Flask dependency; request parsing and routing handled manually.
- HTML rendered with Jinja2 (`templates/index.html`).
- Static assets served from `/static/*` via Lambda (suitable for low traffic). For higher scale, place `static/` in S3 + CloudFront.
- In‑memory caches (`DOC_CACHE`, `CHAT_HISTORY`) persist per warm Lambda container.
- Gemini API key is fetched from AWS Secrets Manager secret name: `prod/gemini/api_key` (see `llm.py`). If `GEMINI_API_KEY` env var is set, it takes precedence.

### API Paths (same as before)
- `GET /` – form & (optionally) summary/chat UI
- `POST /summarize` – form-encoded body: `paper_url`, `complexity`
- `POST /chat` – JSON body: `{ "paper_url": ..., "message": ... }`
- `GET /static/<file>` – static assets

### Deploy Steps (SAM CLI example)
1. Create a SAM template (`template.yaml`):
```yaml
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31
Description: Research Paper Summarizer
Globals:
  Function:
    Timeout: 60
    MemorySize: 1024
    Runtime: python3.12
Resources:
  WebFunction:
    Type: AWS::Serverless::Function
    Properties:
      Handler: app.lambda_handler
      CodeUri: .
      Policies:
        - AWSSecretsManagerGetSecretValuePolicy:
            SecretArn: arn:aws:secretsmanager:REGION:ACCOUNT_ID:secret:prod/gemini/api_key-*
      Environment:
        Variables:
          GEMINI_MODEL: gemini-2.5-flash
      Events:
        ApiRoot:
          Type: Api
          Properties:
            Path: /{proxy+}
            Method: ANY
```
2. Build & deploy:
```bash
sam build
sam deploy --guided
```
3. After deployment, open the API Gateway URL. (Root path `/` loads UI.)

### Packaging Notes
- Dependencies defined in `pyproject.toml`. SAM will build a layer inside the build folder.
- For smaller cold start, you may prune PDF parsing if not needed (remove `pdfminer.six`).

### Secrets Manager Setup
Store the Gemini API key:
```bash
aws secretsmanager create-secret \
  --name prod/gemini/api_key \
  --secret-string "<GEMINI_KEY>"
```
Ensure the Lambda role has permission (policy included above).

### Local Invocation (SAM)
```bash
sam local start-api
# Open http://127.0.0.1:3000/
```

---

## Local (Legacy) Development Without Lambda
Still possible using a mock event:
```bash
uv run python app.py
```
This only prints a rendered HTML response for `/` (for quick smoke test). For full web behavior, rely on API Gateway.

---

## 1) Local Setup (Original Instructions)
```
# 1. Clone
git clone https://github.com/rraghu214/ai-chat-with-research-papers.git
cd ai-chat-with-research-papers

# 2. Install uv
pip install uv

# 3. Sync deps
uv sync

# 4. (Optional) export GEMINI_API_KEY to bypass Secrets Manager in dev
export GEMINI_API_KEY=<GEMINI-KEY>

# 5. (Lambda style) invoke locally
uv run python app.py
```

## 2) How it Works (Architecture)
```
- Extraction: arXiv/PDF/HTML via requests + pdfminer + BeautifulSoup.
- Summarization: map-reduce chunk summarization -> reduce synthesis.
- Chat: grounded responses using history + truncated document context.
- Caching: in-memory (persists for warm Lambda); replace with DynamoDB or ElastiCache for scale.
```

## 3) Scaling / Production Suggestions
- Move static assets to S3/CloudFront.
- Externalize caches (Redis/DynamoDB) to keep chat state across cold starts.
- Add request validation / WAF if public.
- Consider streaming responses (would require WebSockets or SSE via API Gateway + Lambda or shift to container on Fargate).

## 4) Notes
- Adjust Lambda memory to improve cold start and PDF parse speed.
- Increase function timeout if large PDFs (>10MB).
- Ensure Secrets Manager access policy ARN matches your account/region.