FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=7860
ENV USE_SIMULATOR=0
ENV RUN_IN_PAPER=1

EXPOSE 7860

CMD ["python", "app.py"]
