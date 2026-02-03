FROM python:3.11-slim

WORKDIR /app

# System deps for Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg ca-certificates \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 libpango-1.0-0 libcairo2 libatspi2.0-0 \
    libgtk-3-0 libx11-xcb1 libxcb1 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium for Playwright
RUN playwright install chromium && playwright install-deps chromium

COPY *.py ./

CMD ["python", "main.py"]
