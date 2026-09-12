FROM python:3.12-slim AS evaluator

RUN groupadd -r evaluator && useradd -r -g evaluator -d /home/evaluator -s /sbin/nologin evaluator \
    && mkdir -p /home/evaluator /workspace /result /data \
    && chown -R evaluator:evaluator /home/evaluator /workspace /result /data

COPY entrypoint.py /entrypoint.py

USER evaluator

ENTRYPOINT ["python", "/entrypoint.py"]
