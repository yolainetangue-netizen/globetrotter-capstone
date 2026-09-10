FROM python:3.11-slim

WORKDIR /app/gateway

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY gateway /app/gateway
COPY templates /app/templates
COPY static /app/static

EXPOSE 5000
CMD ["python", "app.py"]
