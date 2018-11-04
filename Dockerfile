FROM python:2

WORKDIR /usr/src/app

EXPOSE 9000 5005

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./