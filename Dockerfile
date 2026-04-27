FROM python:3.11-slim

# ── Timezone ──────────────────────────────────────────────────────────────────
ENV TZ=Asia/Kolkata

# System packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    ffmpeg \
    tesseract-ocr \
    tesseract-ocr-tam \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Download Tamil font
RUN python download_fonts.py

# Render uses port 10000
EXPOSE 10000

CMD ["python", "main.py"]
