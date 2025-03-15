# Dockerfile.api

FROM python:3.8-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN apt-get update && apt-get install -y firejail

# Copy all application files
COPY . .

# Get wait-for-it script
ADD https://raw.githubusercontent.com/vishnubob/wait-for-it/master/wait-for-it.sh /app/wait-for-it.sh

# Copy and make entrypoint executable
COPY entrypoint.sh .
RUN chmod +x /app/wait-for-it.sh entrypoint.sh

EXPOSE 9000

# Use entrypoint as command
CMD ["./entities_entrypoint.sh"]