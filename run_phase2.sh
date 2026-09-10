#!/bin/sh
python user-service/app.py &
python itinerary-service/app.py &
python destination-service/app.py &
python recommendation-service/app.py &
python gateway/app.py
