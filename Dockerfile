FROM python:3.11-slim

WORKDIR /app

# RUN pip install --upgrade pip

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 5423

RUN apt-get update && apt-get install -y iputils-ping && rm -rf /var/lib/apt/lists/*

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5423"]