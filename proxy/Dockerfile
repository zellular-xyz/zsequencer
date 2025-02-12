# Use an official Python runtime as a parent image
FROM python:3.11


# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Set environment variables to improve performance and logging
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Expose the port
EXPOSE 80

# Command to run the FastAPI application
CMD ["sh", "-c", "uvicorn proxy_server:app --host 0.0.0.0 --port 80 --workers=$ZSEQUENCER_PROXY_WORKERS_COUNT"]
