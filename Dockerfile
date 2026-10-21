FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p static/uploads
EXPOSE 5000
# app.py starts the no-show scheduler and seeds the super admin from its main block
CMD ["python", "app.py"]
