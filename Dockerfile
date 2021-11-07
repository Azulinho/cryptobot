FROM bitnami/minideb:bullseye AS builder
RUN install_packages \
	make \
	build-essential \
	libssl-dev \
	zlib1g-dev \
	libbz2-dev \
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
	ca-certificates

RUN useradd -d /cryptobot -u 1001 -ms /bin/bash cryptobot
USER cryptobot
ENV HOME /cryptobot
WORKDIR /cryptobot
RUN curl https://pyenv.run | bash
ENV PYENV_ROOT="$HOME/.pyenv"
ENV PATH="$PYENV_ROOT/bin:$PYENV_ROOT/shims/:$PATH"
ADD .python-version .
RUN CONFIGURE_OPTS=--enable-shared pyenv install
ADD requirements.txt .
RUN pip install -r requirements.txt
ADD app.py .

FROM bitnami/minideb:bullseye AS cryptobot
RUN useradd -d /cryptobot -u 1001 -ms /bin/bash cryptobot
USER cryptobot
ENV HOME /cryptobot
WORKDIR /cryptobot
ENV PYENV_ROOT="$HOME/.pyenv"
ENV PATH="$PYENV_ROOT/bin:$PYENV_ROOT/shims/:$PATH"
COPY --from=builder /cryptobot/.python-version /cryptobot/
COPY --from=builder /cryptobot/app.py /cryptobot/
COPY --from=builder /cryptobot/.pyenv/ /cryptobot/.pyenv/
CMD python -u app.py
