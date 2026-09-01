FROM python:3.12-slim

WORKDIR /workspace

ADD requirements.txt ./

# We can split image into more layers by just extracting installed packages into new clean image
# resulting docker image size is smaller but image has more build layers
RUN python3 -m venv /app/env && \
    /app/env/bin/pip install --upgrade pip && \
    /app/env/bin/pip install -U -r requirements.txt

ADD boarding_pass_service ./boarding_pass_service

ADD conf /app/conf/


EXPOSE 8000

CMD ["/app/env/bin/gunicorn", \
    "--config", "/app/conf/gunicorn.conf.py", \
    "boarding_pass_service.main:app" \
    ]
