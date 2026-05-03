FROM python:3.12-alpine
WORKDIR /app
COPY run.py /app/run.py
RUN adduser -D -u 1000 tool
USER tool
ENTRYPOINT ["python", "/app/run.py"]
