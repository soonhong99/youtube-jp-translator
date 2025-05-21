# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set the working directory in the container
WORKDIR /app/translation_service

# Install system dependencies that might be needed by Python packages
# (e.g., for kafka-python, although typically not many for slim images)
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     # any system libs if needed \
#     && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY src/ ./src/

# Expose the port the app runs on (optional if no HTTP interface is actively used for ingress,
# but good for consistency and potential health checks)
EXPOSE 80

# Define the command to run the application
# The default port for Uvicorn is 8000. If your app (e.g. health check) is on a different port,
# make sure it matches. Here, we map to port 80 as per common practice for web services.
# Ensure your main:app is correctly located. If main.py is in src/, then it's src.main:app
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "80"]
