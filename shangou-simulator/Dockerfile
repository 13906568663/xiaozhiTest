FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SIM_HOST=0.0.0.0 \
    SIM_PORT=18100

WORKDIR /app

RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn>=0.30" "mcp>=1.9"

COPY main.py ./
COPY shangou_sim/ shangou_sim/

EXPOSE 18100

CMD ["python", "main.py"]
