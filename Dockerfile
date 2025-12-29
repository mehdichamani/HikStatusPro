FROM python:3.11-slim

WORKDIR /app

# RUN pip install --upgrade pip

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 5423

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5423"]