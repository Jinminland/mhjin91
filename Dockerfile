FROM python:3.11

# potrace 설치
RUN apt-get update && apt-get install -y potrace

WORKDIR /app

COPY . .

RUN pip install -r requirements.txt

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "10000"]