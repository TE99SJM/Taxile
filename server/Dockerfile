FROM python:3.12-slim
WORKDIR /app
COPY app.py /app/app.py
ENV PYTHONUNBUFFERED=1 TAXILE_DB=/data/taxile.sqlite3
EXPOSE 8098
CMD ["python", "/app/app.py"]
