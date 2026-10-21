FROM jenkins/jenkins:lts-jdk17
USER root
RUN apt-get update && apt-get install -y --no-install-recommends docker.io python3 python3-venv python3-pip curl \
    && rm -rf /var/lib/apt/lists/*
