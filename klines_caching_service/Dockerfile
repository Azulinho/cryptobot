FROM ubuntu:focal
RUN apt-get update &&  \
  DEBIAN_FRONTEND=noninteractive apt-get install -yq \
  python3 \
  python3-venv \
  python3-pip && \
  apt-get clean autoclean && \
  apt-get autoremove --yes && \
  rm -rf /var/lib/apt/lists/*

RUN useradd -d /cryptobot -u 1001 -ms /bin/bash cryptobot
USER cryptobot
ENV HOME /cryptobot
WORKDIR /cryptobot
RUN python3 -m venv /cryptobot/.venv
ADD requirements.txt .
RUN /cryptobot/.venv/bin/pip install wheel
RUN /cryptobot/.venv/bin/pip install -r requirements.txt
EXPOSE 8999
ADD klines_caching_service.py .
CMD ["/cryptobot/.venv/bin/gunicorn", "--preload", "--workers=4", "--worker-class=egg:meinheld#gunicorn_worker", "--bind", "0.0.0.0:8999", "klines_caching_service:app"]
