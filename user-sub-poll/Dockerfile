FROM python:2

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY config/* ./config/
COPY user-sub-poll/* ./
COPY gimgur/* ./gimgur/
