from datetime import datetime, timedelta
from typing import Optional
import os
import logging

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.database import execute_query

# Configuración de logging
logger = logging.getLogger(__name__)

# Configuración de seguridad
security = HTTPBearer()

# Contexto para encriptación de contraseñas (bcrypt)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Configuración JWT desde variables de entorno
SECRET_KEY = os.getenv("JWT_SECRET", "tu_clave_secreta_super_segura_cambiar_en_produccion_12345")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30"))


# ============================================
# FUNCIONES DE HASH DE CONTRASEÑAS
# ============================================

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifica si una contraseña coincide con su hash.
    
    Parámetros de entrada:
        plain_password (str): Contraseña en texto plano
        hashed_password (str): Contraseña hasheada almacenada en BD
    
    Retorna:
        bool: True si coinciden, False si no
    """
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        logger.error(f"Error al verificar contraseña: {e}")
        return False


def get_password_hash(password: str) -> str:
    """
    Hashea una contraseña usando bcrypt.
    
    Parámetros de entrada:
        password (str): Contraseña en texto plano
    
    Retorna:
        str: Contraseña hasheada (bcrypt)
    """
    try:
        return pwd_context.hash(password)
    except Exception as e:
        logger.error(f"Error al hashear contraseña: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al procesar contraseña"
        )


# ============================================
# FUNCIONES JWT (JSON Web Tokens)
# ============================================

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Crea un token JWT para autenticación.
    
    Parámetros de entrada:
        data (dict): Datos a incluir en el token (ej: {"sub": "username"})
        expires_delta (timedelta, opcional): Tiempo de expiración personalizado
    
    Retorna:
        str: Token JWT firmado
    
    Estructura del token:
        - sub: Subject (username del usuario)
        - exp: Expiration time (cuándo expira)
        - iat: Issued at (cuándo se creó)
    """
    try:
        to_encode = data.copy()
        
        # Definir tiempo de expiración
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        
        # Agregar campos estándar JWT
        to_encode.update({
            "exp": expire,
            "iat": datetime.utcnow()
        })
        
        # Crear y firmar el token
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        
        logger.info(f"Token JWT creado para usuario: {data.get('sub', 'unknown')}")
        return encoded_jwt
        
    except Exception as e:
        logger.error(f"Error al crear token JWT: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al generar token de autenticación"
        )


def decode_access_token(token: str) -> Optional[dict]:
    """
    Decodifica y verifica un token JWT.
    
    Parámetros de entrada:
        token (str): Token JWT a decodificar
    
    Retorna:
        dict: Payload del token si es válido
        None: Si el token es inválido o expirado
    
    Excepciones manejadas:
        - JWTError: Token inválido o expirado
        - Exception: Otros errores
    """
    try:
        # Decodificar y verificar el token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        
        if username is None:
            logger.warning("Token sin campo 'sub'")
            return None
        
        logger.debug(f"Token decodificado exitosamente para: {username}")
        return payload
        
    except JWTError as e:
        logger.warning(f"Token JWT inválido o expirado: {e}")
        return None
    
    except Exception as e:
        logger.error(f"Error inesperado al decodificar token: {e}")
        return None


# ============================================
# FUNCIONES DE AUTENTICACIÓN
# ============================================

def authenticate_user(username: str, password: str) -> Optional[dict]:
    """
    Autentica un usuario verificando sus credenciales.
    
    Parámetros de entrada:
        username (str): Nombre de usuario
        password (str): Contraseña en texto plano
    
    Retorna:
        dict: Datos del usuario si la autenticación es exitosa
        None: Si las credenciales son incorrectas
    """
    connection = None
    
    try:
        # Buscar usuario en la base de datos
        query = """
            SELECT id, username, email, full_name, hashed_password, is_active, created_at
            FROM users
            WHERE username = %s
        """
        
        results = execute_query(query, (username,), fetch=True)
        
        if not results:
            logger.warning(f"Intento de login con usuario inexistente: {username}")
            return None
        
        user = results[0]
        
        # Verificar que el usuario esté activo
        if not user['is_active']:
            logger.warning(f"Intento de login con usuario inactivo: {username}")
            return None
        
        # Verificar contraseña
        if not verify_password(password, user['hashed_password']):
            logger.warning(f"Contraseña incorrecta para usuario: {username}")
            return None
        
        # Autenticación exitosa - remover contraseña del resultado
        user.pop('hashed_password')
        logger.info(f"Autenticación exitosa para usuario: {username}")
        
        return user
        
    except Exception as e:
        logger.error(f"Error al autenticar usuario: {e}")
        return None


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """
    Obtiene el usuario actual desde el token JWT.
  
    Parámetros de entrada:
        credentials (HTTPAuthorizationCredentials): Credenciales del header
    
    Retorna:
        dict: Datos del usuario autenticado
    
    Excepciones:
        HTTPException 401: Si el token es inválido o el usuario no existe
    
    Uso en endpoints:
        @app.get("/protected")
        def protected_route(current_user: dict = Depends(get_current_user)):
            return {"user": current_user}
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudo validar las credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # Obtener token del header
        token = credentials.credentials
        
        # Decodificar token
        payload = decode_access_token(token)
        
        if payload is None:
            logger.warning("Token inválido en request")
            raise credentials_exception
        
        username: str = payload.get("sub")
        
        if username is None:
            logger.warning("Token sin username")
            raise credentials_exception
        
        # Buscar usuario en la base de datos
        query = """
            SELECT id, username, email, full_name, is_active, created_at
            FROM users
            WHERE username = %s AND is_active = TRUE
        """
        
        results = execute_query(query, (username,), fetch=True)
        
        if not results:
            logger.warning(f"Usuario no encontrado o inactivo: {username}")
            raise credentials_exception
        
        user = results[0]
        logger.debug(f"Usuario autenticado: {username}")
        
        return user
        
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"Error al obtener usuario actual: {e}")
        raise credentials_exception


def get_current_active_user(current_user: dict = Depends(get_current_user)) -> dict:
    """
    Verifica que el usuario actual esté activo.
    
    Parámetros de entrada:
        current_user (dict): Usuario obtenido de get_current_user
    
    Retorna:
        dict: Usuario activo
    
    Excepciones:
        HTTPException 400: Si el usuario está inactivo
    """
    if not current_user.get('is_active', False):
        logger.warning(f"Usuario inactivo intentó acceder: {current_user.get('username')}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuario inactivo"
        )
    
    return current_user