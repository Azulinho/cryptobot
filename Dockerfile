FROM ubuntu:focal
ENV DEBIAN_FRONTEND noninteractive
RUN apt-get update &&  \
  apt-get install -yq eatmydata
RUN eatmydata apt-get install -yq \
  make \
  build-essential \
  libssl-dev \
  zlib1g-dev \
  libbz2-dev \
  libisal-dev \
  libisal2 \
  libreadline-dev \
  libsqlite3-dev \
  wget \
  curl \
  llvm \
  libncursesw5-dev \
  xz-utils \
  tk-dev \
  libxml2-dev \
  libxmlsec1-dev \
  libffi-dev \
  liblzma-dev \
  git \
  ca-certificates \
  cargo \
  gzip \
  pigz \
  bzip2 \
  pbzip2 \
  autoconf \
  automake \
  shtool \
  coreutils \
  autogen \
  libtool \
  shtool \
  nasm && \
  apt-get clean autoclean && \
  apt-get autoremove --yes && \
  rm -rf /var/lib/apt/lists/*


RUN useradd -d /cryptobot -u 1001 -ms /bin/bash cryptobot
RUN cd /tmp \
  && eatmydata wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz \
  && eatmydata tar xf ta-lib-0.4.0-src.tar.gz \
  && cd ta-lib \
  && eatmydata ./configure --prefix=/usr \
  && eatmydata make \
  && eatmydata make install \
  && rm -rf /tmp/ta-lib*
USER cryptobot
ENV HOME /cryptobot
WORKDIR /cryptobot
ADD .python-version .
RUN curl https://pyenv.run | eatmydata bash
ENV PYENV_ROOT="$HOME/.pyenv"
ENV PATH="$PYENV_ROOT/bin:$PYENV_ROOT/shims/:$PATH"
RUN CONFIGURE_OPTS="--enable-shared --enable-optimizations --with-lto --with-pgo" eatmydata pyenv install \
  && rm -f /tmp/python-build*.log
RUN eatmydata python -m venv /cryptobot/.venv
ADD requirements.txt .
RUN eatmydata /cryptobot/.venv/bin/pip install --upgrade pip setuptools wheel
# pyenv is failling to compile isal without setting C_INCLUDE_PATH
RUN eatmydata /cryptobot/.venv/bin/pip install -r requirements.txt && \
  rm -rf /tmp/*

ADD lib/ lib/
ADD utils/automated-backtesting.py utils/automated-backtesting.py
ADD utils/automated-backtesting.sh utils/automated-backtesting.sh
ADD utils/prove-backtesting.py utils/prove-backtesting.py
ADD utils/prove-backtesting.sh utils/prove-backtesting.sh
ADD utils/pull_klines.py utils/pull_klines.py
ADD utils/config-endpoint-service.py utils/config-endpoint-service.py
ADD utils/config-endpoint-service.sh utils/config-endpoint-service.sh
ADD klines_caching_service.py klines_caching_service.py
ADD price_log_service.py price_log_service.py
ADD app.py .

