from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging
import os

from app.database import test_connection
from app.routes import auth, products, sales

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================
# INICIALIZACIÓN DE LA APLICACIÓN
# ============================================

app = FastAPI(
    title="Sistema de Gestión de Inventario y Ventas",
    description="""
    API RESTful para gestionar inventario de productos y ventas.
    
    **Características principales:**
    - Autenticación con JWT
    - CRUD completo de productos
    - Gestión de ventas con control de stock
    - Registro de usuarios
    - Documentación interactiva (Swagger)
    
    **Tecnologías:**
    - FastAPI (Python)
    - MySQL
    - Docker
    - JWT para autenticación
    """,
    version="1.0.0",
    docs_url="/docs",  # Swagger UI
    redoc_url="/redoc",  # ReDoc
    contact={
        "name": "Soporte Técnico",
        "email": "soporte@inventario.com"
    }
)

# ============================================
# CONFIGURACIÓN DE CORS
# ============================================

# Lista de orígenes permitidos (frontend)
origins = [
    "http://localhost",
    "http://localhost:3000",  # React default
    "http://localhost:4200",  # Angular default
    "http://localhost:8080",  # Vue default
    "http://127.0.0.1:5500",  # Live Server
    "*"  # Permitir todos (solo para desarrollo)
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # Orígenes permitidos
    allow_credentials=True,  # Permite cookies
    allow_methods=["*"],  # Permite todos los métodos (GET, POST, PUT, DELETE)
    allow_headers=["*"],  # Permite todos los headers
)

logger.info("CORS configurado correctamente")

# ============================================
# REGISTRO DE RUTAS (ROUTERS)
# ============================================

# Incluir routers de cada módulo
app.include_router(
    auth.router,
    prefix="/api/auth",
    tags=["Autenticación"]
)

app.include_router(
    products.router,
    prefix="/api/products",
    tags=["Productos"]
)

app.include_router(
    sales.router,
    prefix="/api/sales",
    tags=["Ventas"]
)

logger.info("Rutas registradas correctamente")

# ============================================
# EVENTOS DE CICLO DE VIDA
# ============================================

@app.on_event("startup")
async def startup_event():
    """
    Evento que se ejecuta al iniciar la aplicación.
    
    Parámetros de entrada:
        Ninguno
    
    Retorna:
        None
    """
    logger.info("=" * 50)
    logger.info("Iniciando Sistema de Inventario")
    logger.info("=" * 50)
    
    # Verificar variables de entorno críticas
    required_env_vars = ["DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME", "JWT_SECRET"]
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Variables de entorno faltantes: {', '.join(missing_vars)}")
        logger.error("La aplicación puede no funcionar correctamente")
    else:
        logger.info("Variables de entorno cargadas correctamente")
    
    # Probar conexión a base de datos
    if test_connection():
        logger.info("Conexión a MySQL exitosa")
    else:
        logger.error("Error al conectar con MySQL")
        logger.error("Verifica que el contenedor de MySQL esté corriendo")
    
    logger.info("=" * 50)
    logger.info("Documentación disponible en: http://localhost:8000/docs")
    logger.info("=" * 50)


@app.on_event("shutdown")
async def shutdown_event():
    """
    Evento que se ejecuta al cerrar la aplicación.
    
    Parámetros de entrada:
        Ninguno
    
    Retorna:
        None
    """
    logger.info("=" * 50)
    logger.info("Cerrando Sistema de Inventario")
    logger.info("=" * 50)
    logger.info("Recursos liberados correctamente")


# ============================================
# ENDPOINTS RAÍZ Y HEALTH CHECK
# ============================================

@app.get(
    "/",
    status_code=status.HTTP_200_OK,
    summary="Endpoint raíz",
    description="Retorna información básica de la API"
)
async def root():
    """
    Endpoint raíz de la API.
    
    Parámetros de entrada:
        Ninguno
    
    Retorna:
        dict: Información de la API
    
    Códigos de respuesta:
        200: API funcionando correctamente
    """
    return {
        "message": "API de Sistema de Inventario y Ventas",
        "version": "1.0.0",
        "status": "online",
        "docs": "/docs",
        "redoc": "/redoc"
    }


@app.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="Health check",
    description="Verifica el estado de la API y sus dependencias"
)
async def health_check():
    """
    Endpoint de verificación de salud.
    
    Parámetros de entrada:
        Ninguno
    
    Retorna:
        dict: Estado de la API y dependencias
    
    Códigos de respuesta:
        200: Todo funcionando correctamente
        503: Algún servicio no disponible
    """
    # Verificar conexión a base de datos
    db_status = test_connection()
    
    health_status = {
        "status": "healthy" if db_status else "unhealthy",
        "api": "online",
        "database": "connected" if db_status else "disconnected",
        "timestamp": "2025-01-05T00:00:00Z"
    }
    
    if not db_status:
        logger.warning("Health check falló: Base de datos no disponible")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=health_status
        )
    
    return health_status


# ============================================
# MANEJADOR DE ERRORES GLOBAL
# ============================================

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """
    Manejador global de excepciones no capturadas.
   
    Parámetros de entrada:
        request: Request HTTP
        exc (Exception): Excepción capturada
    
    Retorna:
        JSONResponse: Respuesta de error estructurada
    
    Códigos de respuesta:
        500: Error interno del servidor
    """
    logger.error(f"Error no manejado: {exc}", exc_info=True)
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal Server Error",
            "message": "Ha ocurrido un error inesperado",
            "detail": str(exc) if os.getenv("DEBUG") == "True" else None
        }
    )


# ============================================
# INFORMACIÓN ADICIONAL
# ============================================

if __name__ == "__main__":
    """
    Este bloque NO se ejecuta en producción.
    Solo para desarrollo local sin Docker.
    """
    import uvicorn
    
    logger.info("Ejecutando en modo desarrollo")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )