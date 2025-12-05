FROM python:3.11-slim

WORKDIR /app

# 1. Upgrade pip to the latest version (Fixes the warning)
RUN pip install --upgrade pip

# 2. Copy and install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]