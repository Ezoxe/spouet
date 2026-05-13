FROM python:3.12-alpine
WORKDIR /app
RUN pip install --no-cache-dir httpx==0.27.*
COPY run.py /app/run.py
RUN adduser -D -u 1000 tool
USER tool
ENTRYPOINT ["python", "/app/run.py"]
