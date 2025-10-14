import mysql.connector
from mysql.connector import Error
import os
import logging
from typing import Optional

# Configuración del sistema logging
logging.bassicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_db_connection():
      """
    Establece y retorna una conexión a la base de datos MySQL.
    
    Propósito:
        Crear una conexión segura a MySQL usando variables de entorno.
        Implementa manejo de errores robusto.
    
    Parámetros de entrada:
        Ninguno (usa variables de entorno)
    
    Retorna:
        mysql.connector.connection.MySQLConnection: Objeto de conexión activa
        None: Si la conexión falla
    
    Variables de entorno requeridas:
        - DB_HOST: Host del servidor MySQL
        - DB_PORT: Puerto de MySQL (default: 3306)
        - DB_USER: Usuario de la base de datos
        - DB_PASSWORD: Contraseña del usuariosudo apt update
sudo apt install mysql-server -y

        - DB_NAME: Nombre de la base de datos
    
    Excepciones:
        - Error de MySQL si las credenciales son incorrectas
        - Error de conexión si el servidor no está disponible
    """
    connection = None

    try:
        # Obtener variables de entorno
        db_config = {
            'host': os.getenv('DB_HOST', 'mysql'),
            'port': int(os.getenv('DB_PORT', 3306)),
            'user': os.getenv('DB_USER', 'inventory_user'),
            'password': os.getenv('DB_PASSWORD'),
            'database': os.getenv('DB_NAME', 'inventory_db'),
            'charset': 'utf8mb4',
            'collation': 'utf8mb4_unicode_ci',
            'autocommit': False # Control manual de transacciones
        }

        # Intentar establecer conexion
        logger.info(f"Intentando conectar a MySQL en {db_config['host']}:{db_config['port']}")
        connection = mysql.connector.connect(**db_config)

        if connection.is_connected():
             db_info = connection.get_server_info()
             logger.info(f"Conexión exitosa a MySQL server verisión {db_info}")
             return connection
        
    except Error as e:
        logger.error(f"Error al conectar a MySQL: {e}")
        return None

    except Exception as e:
        logger.error(f"Error al conectar a la base de datos: {e}")
        return None

def