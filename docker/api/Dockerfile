FROM python:3.8-slim

WORKDIR /app

COPY requirements.txt .  
RUN pip install --no-cache-dir -r requirements.txt  

RUN apt-get update && apt-get install -y firejail  

# Copy all application files
COPY . .  

# Get wait-for-it script
ADD https://raw.githubusercontent.com/vishnubob/wait-for-it/master/wait-for-it.sh /app/wait-for-it.sh  

# Copy the correct entrypoint script
COPY docker/api/entities_entrypoint.sh /app/

# Ensure scripts are executable
RUN chmod +x /app/wait-for-it.sh /app/entities_entrypoint.sh  

EXPOSE 9000  

# Use the corrected entrypoint path
CMD ["/app/entities_entrypoint.sh"]
