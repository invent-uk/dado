FROM python:3.8-slim-buster

RUN apt-get update && apt-get install -y ffmpeg

RUN cp /usr/share/zoneinfo/Europe/London /etc/localtime

COPY ./requirements.txt /requirements.txt
WORKDIR /
RUN pip3 install -r requirements.txt

COPY . /
ENTRYPOINT [ "/dado.sh" ]
