@echo off
start "User Service" cmd /k python user-service\app.py
start "Itinerary Service" cmd /k python itinerary-service\app.py
start "Destination Service" cmd /k python destination-service\app.py
start "Recommendation Service" cmd /k python recommendation-service\app.py
start "API Gateway" cmd /k python gateway\app.py
