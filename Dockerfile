# Use the official Ubuntu 24.04 image as the base image
FROM ubuntu:24.04

# Set environment variables to avoid writing .pyc files and ensure stdout/stderr is flushed
ENV PYTHONUNBUFFERED 1
ENV PYTHONDONTWRITEBYTECODE 1

# Install necessary packages and dependencies
RUN apt-get update && \
    apt-get install -y python3 python3-pip python3-dev libgmp3-dev wget unzip cmake build-essential && \
    rm -rf /var/lib/apt/lists/*

# Download and install mcl
RUN wget https://github.com/herumi/mcl/archive/refs/tags/v1.93.zip && \
    unzip v1.93.zip && \
    cd mcl-1.93 && \
    mkdir build && \
    cd build && \
    cmake .. && \
    make && \
    make install && \
    cd ../.. && \
    rm -rf mcl-1.93 v1.93.zip

# Create and set the working directory
WORKDIR /app

# Copy the requirements file to the working directory
COPY requirements.txt /app/

# Install the Python dependencies
RUN pip3 install --break-system-packages -r requirements.txt

# Copy the required project files to the working directory
COPY node /app/zsequencer/node
COPY sequencer /app/zsequencer/sequencer
COPY common /app/zsequencer/common
COPY utils /app/zsequencer/utils
COPY schema.py /app/zsequencer/schema.py
COPY config.py /app/zsequencer/config.py
COPY run.py /app/zsequencer/run.py


# Command to run the application
CMD ["python3", "zsequencer/run.py"]
