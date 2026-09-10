FROM python:3.11-slim

WORKDIR /app/itinerary-service

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY itinerary-service /app/itinerary-service

EXPOSE 5002
CMD ["python", "app.py"]
