from fastapi import APIRouter, HTTPException, status, Depends
from datetime import timedelta
import logging

from app.models import UserCreate, UserLogin, UserResponse, Token, MessageResponse, ErrorResponse
from app.auth import (
    get_password_hash,
    authenticate_user,
    create_access_token,
    get_current_active_user,
    ACCESS_TOKEN_EXPIRE_MINUTES
)
from app.database import execute_query

# Configuración de logging
logger = logging.getLogger(__name__)

# Crear router
router = APIRouter()


# ============================================
# ENDPOINT: REGISTRAR USUARIO
# ============================================

@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar nuevo usuario",
    description="Crea una cuenta de usuario nueva en el sistema",
    responses={
        201: {"description": "Usuario creado exitosamente"},
        400: {"model": ErrorResponse, "description": "Usuario ya existe"},
        500: {"model": ErrorResponse, "description": "Error del servidor"}
    }
)
async def register_user(user: UserCreate):
    """
    Parámetros de entrada:
        user (UserCreate): Datos del usuario (username, email, password, full_name)
    
    Retorna:
        UserResponse: Datos del usuario creado (sin contraseña)
        
    Códigos HTTP:
        201: Usuario creado exitosamente
        400: Usuario o email ya existe
        500: Error al crear usuario
    """
    connection = None
    
    try:
        logger.info(f"Intentando registrar usuario: {user.username}")
        
        # Verificar si el username ya existe
        check_username_query = "SELECT id FROM users WHERE username = %s"
        existing_username = execute_query(check_username_query, (user.username,), fetch=True)
        
        if existing_username:
            logger.warning(f"Intento de registro con username existente: {user.username}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"El usuario '{user.username}' ya existe"
            )
        
        # Verificar si el email ya existe
        check_email_query = "SELECT id FROM users WHERE email = %s"
        existing_email = execute_query(check_email_query, (user.email,), fetch=True)
        
        if existing_email:
            logger.warning(f"Intento de registro con email existente: {user.email}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"El email '{user.email}' ya está registrado"
            )
        
        # Hashear la contraseña
        hashed_password = get_password_hash(user.password)
        
        # Insertar usuario en la base de datos
        insert_query = """
            INSERT INTO users (username, email, hashed_password, full_name)
            VALUES (%s, %s, %s, %s)
        """
        
        result = execute_query(
            insert_query,
            (user.username, user.email, hashed_password, user.full_name),
            fetch=False
        )
        
        if result <= 0:
            logger.error(f"Error al insertar usuario: {user.username}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error al crear usuario"
            )
        
        # Obtener el usuario recién creado
        get_user_query = """
            SELECT id, username, email, full_name, is_active, created_at
            FROM users
            WHERE username = %s
        """
        
        new_user = execute_query(get_user_query, (user.username,), fetch=True)
        
        if not new_user:
            logger.error(f"Usuario creado pero no se pudo recuperar: {user.username}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error al recuperar usuario creado"
            )
        
        logger.info(f"✓ Usuario registrado exitosamente: {user.username}")
        return new_user[0]
        
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"Error inesperado al registrar usuario: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al crear usuario"
        )


# ============================================
# ENDPOINT: LOGIN
# ============================================

@router.post(
    "/login",
    response_model=Token,
    status_code=status.HTTP_200_OK,
    summary="Iniciar sesión",
    description="Autentica un usuario y retorna un token JWT",
    responses={
        200: {"description": "Login exitoso"},
        401: {"model": ErrorResponse, "description": "Credenciales incorrectas"},
        500: {"model": ErrorResponse, "description": "Error del servidor"}
    }
)
async def login(credentials: UserLogin):
    """
    Autentica un usuario y genera un token JWT.
    
    Parámetros de entrada:
        credentials (UserLogin): Username y password
    
    Retorna:
        Token: access_token (JWT) y token_type ("bearer")
        
    Códigos HTTP:
        200: Login exitoso, token generado
        401: Credenciales incorrectas
        500: Error al procesar login
    """
    try:
        logger.info(f"Intento de login para usuario: {credentials.username}")
        
        # Autenticar usuario
        user = authenticate_user(credentials.username, credentials.password)
        
        if not user:
            logger.warning(f"Login fallido para usuario: {credentials.username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Usuario o contraseña incorrectos",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Crear token JWT
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": user['username']},
            expires_delta=access_token_expires
        )
        
        logger.info(f"✓ Login exitoso para usuario: {credentials.username}")
        
        return {
            "access_token": access_token,
            "token_type": "bearer"
        }
        
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"Error inesperado en login: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al procesar login"
        )


# ============================================
# ENDPOINT: OBTENER USUARIO ACTUAL
# ============================================

@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener usuario actual",
    description="Retorna información del usuario autenticado",
    responses={
        200: {"description": "Datos del usuario"},
        401: {"model": ErrorResponse, "description": "No autenticado"}
    }
)
async def get_me(current_user: dict = Depends(get_current_active_user)):
    """
    Obtiene información del usuario autenticado.
    
    Parámetros de entrada:
        current_user (dict): Usuario obtenido del token JWT (inyectado automáticamente)
    
    Retorna:
        UserResponse: Datos del usuario autenticado
    
    Códigos HTTP:
        200: Datos del usuario retornados
        401: Token inválido o expirado
    """
    try:
        logger.info(f"Usuario consultando su propia información: {current_user.get('username')}")
        return current_user
        
    except Exception as e:
        logger.error(f"Error al obtener usuario actual: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener información del usuario"
        )