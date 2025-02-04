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

# Expose the FastAPI default port
EXPOSE 8000

# Command to run the FastAPI application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
