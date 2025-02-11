# Use an official Python runtime as a parent image
FROM python:3.11

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.proxy.txt .
RUN pip install --no-cache-dir -r requirements.proxy.txt

# Copy the rest of the application code
COPY . .

# Set environment variables to improve performance and logging
ENV PYTHONUNBUFFERED 1
ENV PYTHONDONTWRITEBYTECODE 1

# Expose the FastAPI port (use the env variable)
EXPOSE $ZSEQUENCER_PROXY_PORT

# Command to run the FastAPI application
CMD ["sh", "-c", "uvicorn batch_aggregator_proxy.proxy_server:app --host ${ZSEQUENCER_PROXY_HOST} --port ${ZSEQUENCER_PROXY_PORT} --workers=${ZSEQUENCER_PROXY_WORKERS_COUNT}"]
