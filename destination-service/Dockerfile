FROM python:3.11-slim

WORKDIR /app/destination-service

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY destination-service /app/destination-service
COPY static /app/static

EXPOSE 5003
CMD ["python", "app.py"]
