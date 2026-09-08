FROM python:3.10-slim

WORKDIR /app

# Instalar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código
COPY src/ ./src/

# Crear usuario no root
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Exponer puerto
EXPOSE 8083

# Ejecutar la aplicación
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8083"]