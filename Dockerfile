# Använd en lättviktig Python-image
FROM python:3.11-slim

# Sätt arbetskatalog
WORKDIR /app

# Kopiera beroenden och installera
COPY requirements.txt .
# Installera gcc om det behövs för vissa python-paket (behövs oftast sällan för flask/openpyxl men bra att ha)
# RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

# Kopiera källkoden till containern
COPY . .

# Exponera port (Cloud Run använder port 8080 default via env var PORT)
# Flask körs internt på 5000 eller via gunicorn
ENV PORT=8080

# Kommando för att starta appen med Gunicorn
# Vi binder till 0.0.0.0 och den port som miljön anger
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app:app
