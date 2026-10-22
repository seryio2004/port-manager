FROM python:3.12-alpine

RUN apk add --no-cache iproute2
WORKDIR /app
COPY collect.py ./collect.py

ENV PYTHONUNBUFFERED=1
CMD ["python", "/app/collect.py"]
