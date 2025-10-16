import mysql.connector
from mysql.connector import Error
import os
import logging
from typing import Optional

# Configuración del sistema de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_db_connection():
    """
    Establece y retorna una conexión a la base de datos MySQL.
    
    Parámetros de entrada:
        Ninguno (usa variables de entorno)
    
    Retorna:
        mysql.connector.connection.MySQLConnection: Objeto de conexión activa
        None: Si la conexión falla
    
    Variables de entorno requeridas:
        - DB_HOST: Host del servidor MySQL
        - DB_PORT: Puerto de MySQL (default: 3306)
        - DB_USER: Usuario de la base de datos
        - DB_PASSWORD: Contraseña del usuario
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
            'autocommit': False  # Control manual de transacciones
        }
        
        # Intenta establecer la conexión
        logger.info(f"Intentando conectar a MySQL en {db_config['host']}:{db_config['port']}")
        connection = mysql.connector.connect(**db_config)
        
        if connection.is_connected():
            db_info = connection.get_server_info()
            logger.info(f"Conexión exitosa a MySQL Server versión {db_info}")
            return connection
            
    except Error as e:
        logger.error(f"Error al conectar a MySQL: {e}")
        return None
    
    except Exception as e:
        logger.error(f"Error inesperado al conectar a la base de datos: {e}")
        return None


def close_db_connection(connection):
    """
    Cierra de forma segura una conexión a la base de datos.
    
    Parámetros de entrada:
        connection (mysql.connector.connection.MySQLConnection): Conexión a cerrar
    
    Retorna:
        None
    """
    try:
        if connection:
            if connection.is_connected():
                connection.close()
                logger.info("Conexión a MySQL cerrada correctamente")
            else:
                logger.warning("La conexión ya estaba cerrada")
        else:
            logger.warning("No hay conexión para cerrar")
            
    except Error as e:
        logger.error(f"Error al cerrar la conexión: {e}")
    
    except Exception as e:
        logger.error(f"Error inesperado al cerrar la conexión: {e}")


def execute_query(query: str, params: Optional[tuple] = None, fetch: bool = False):
    """
    Ejecuta una consulta SQL con manejo completo de errores.
   
    Parámetros de entrada:
        query (str): Consulta SQL a ejecutar (puede usar placeholders %s)
        params (tuple, opcional): Parámetros para la consulta (previene SQL injection)
        fetch (bool): True para SELECT (devuelve datos), False para INSERT/UPDATE/DELETE
    
    Retorna:
        - Si fetch=True: Lista de resultados o lista vacía si falla
        - Si fetch=False: Número de filas afectadas o -1 si falla
    """
    connection = None
    cursor = None
    
    try:
        # Establece la conexión
        connection = get_db_connection()
        
        if not connection:
            logger.error("No se pudo establecer conexión con la base de datos")
            return [] if fetch else -1
        
        # Crear cursor
        cursor = connection.cursor(dictionary=True)  # Retorna diccionarios
        
        # Ejecutar consulta
        logger.info(f"Ejecutando query: {query[:100]}...")  # Toma solo los primeros 100 caracteres de la variable query
        cursor.execute(query, params or ())
        
        if fetch:
            # Consulta SELECT - retornar resultados
            results = cursor.fetchall()
            logger.info(f"Query ejecutado exitosamente. Filas retornadas: {len(results)}")
            return results
        else:
            # Consulta INSERT/UPDATE/DELETE - hacer commit
            connection.commit()
            rows_affected = cursor.rowcount
            logger.info(f"Query ejecutado exitosamente. Filas afectadas: {rows_affected}")
            return rows_affected
            
    except Error as e:
        logger.error(f"Error de MySQL al ejecutar query: {e}")
        if connection:
            connection.rollback()  # Revertir cambios en caso de error
            logger.info("Rollback ejecutado")
        return [] if fetch else -1
    
    except Exception as e:
        logger.error(f"Error inesperado al ejecutar query: {e}")
        if connection:
            connection.rollback()
        return [] if fetch else -1
    
    finally:
        # Cierra cursor y conexión 
        if cursor:
            cursor.close()
            logger.debug("Cursor cerrado")
        
        if connection:
            close_db_connection(connection)


def test_connection():
    """
    Prueba la conexión a la base de datos.
    
    Parámetros de entrada: 
        Ninguno
    
    Retorna:
        bool: True si la conexión es exitosa, False en caso contrario
    """
    connection = None
    
    try:
        connection = get_db_connection()
        
        if connection and connection.is_connected():
            logger.info("✓ Test de conexión exitoso")
            return True
        else:
            logger.error("✗ Test de conexión fallido")
            return False
            
    except Exception as e:
        logger.error(f"✗ Error en test de conexión: {e}")
        return False
    
    finally:
        if connection:
            close_db_connection(connection)