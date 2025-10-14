# Usa una imagen base ligera de Python
FROM python:3.11-slim

# Establece el directorio de trabajo dentro del contenedor
WORKDIR /app

# Instala dependencias del sistema necesarias para mysqlclient
RUN apt-get update && apt-get install -y \
    default-libmysqlclient-dev \
    build-essential \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*
# rm -rf limpia cache para mantener imagen ligera

# Copia el archivo de dependencias primero
# (Esto optimiza el cache de Docker: si requirements no cambia, no reinstala)
COPY requirements.txt .

# Instala las dependencias de Python
RUN pip install --no-cache-dir -r requirements.txt
# --no-cache-dir: no guarda cache, reduce tamaño de imagen

# Copia todo el código de la aplicación
COPY . .

# Expone el puerto 8000 (donde corre FastAPI)
EXPOSE 8000

# Comando para ejecutar la aplicación
# uvicorn: servidor ASGI para FastAPI
# --host 0.0.0.0: acepta conexiones desde cualquier IP (necesario para Docker)
# --reload: recarga automática al detectar cambios (solo para desarrollo)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]