# Use Python 3.12 slim for smaller image size
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PYTHONPATH /app

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends 
    build-essential 
    libssl-dev 
    sqlite3 
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create directory for SQLite database
RUN mkdir -p /app/data && chown -R 1000:1000 /app/data

# Switch to non-root user for security (if possible)
# USER 1000

# Entrypoint to run migrations and then the bot
CMD ["sh", "-c", "python -m src.db.migrate && python -m src.bot.app"]
