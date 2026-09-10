FROM python:3.11-slim

WORKDIR /app/user-service

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY user-service /app/user-service

EXPOSE 5001
CMD ["python", "app.py"]
