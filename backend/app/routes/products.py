from fastapi import APIRouter, HTTPException, status, Depends, Query
from typing import List, Optional
import logging

from app.models import ProductCreate, ProductUpdate, ProductResponse, MessageResponse, ErrorResponse
from app.auth import get_current_active_user
from app.database import execute_query

# Configuración de logging
logger = logging.getLogger(__name__)

# Crear router
router = APIRouter()


# ============================================
# ENDPOINT: LISTAR PRODUCTOS
# ============================================

@router.get(
    "/",
    response_model=List[ProductResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar productos",
    description="Obtiene lista de todos los productos con filtros opcionales",
    responses={
        200: {"description": "Lista de productos"},
        500: {"model": ErrorResponse, "description": "Error del servidor"}
    }
)
async def get_products(
    skip: int = Query(0, ge=0, description="Número de registros a saltar"),
    limit: int = Query(100, ge=1, le=1000, description="Máximo de registros a retornar"),
    category_id: Optional[int] = Query(None, description="Filtrar por categoría"),
    is_active: Optional[bool] = Query(None, description="Filtrar por estado"),
    current_user: dict = Depends(get_current_active_user)
):
    """
    Lista todos los productos con paginación y filtros.
    
    Parámetros de entrada:
        skip (int): Registros a omitir para paginación (default: 0)
        limit (int): Máximo de registros a retornar (default: 100, max: 1000)
        category_id (int, opcional): Filtrar por categoría específica
        is_active (bool, opcional): Filtrar por productos activos/inactivos
        current_user (dict): Usuario autenticado (requerido)
    
    Retorna:
        List[ProductResponse]: Lista de productos
    
    Códigos HTTP:
        200: Lista retornada exitosamente
        401: No autenticado
        500: Error al obtener productos
    
    Autenticación:
        Requiere token JWT válido
    """
    try:
        logger.info(f"Usuario {current_user['username']} listando productos")
        
        # Construir query dinámicamente según filtros
        query = "SELECT * FROM products WHERE 1=1"
        params = []
        
        if category_id is not None:
            query += " AND category_id = %s"
            params.append(category_id)
        
        if is_active is not None:
            query += " AND is_active = %s"
            params.append(is_active)
        
        query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, skip])
        
        # Ejecutar query
        products = execute_query(query, tuple(params), fetch=True)
        
        logger.info(f"✓ {len(products)} productos retornados")
        return products
        
    except Exception as e:
        logger.error(f"Error al listar productos: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener lista de productos"
        )


# ============================================
# ENDPOINT: OBTENER PRODUCTO POR ID
# ============================================

@router.get(
    "/{product_id}",
    response_model=ProductResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener producto",
    description="Obtiene un producto específico por su ID",
    responses={
        200: {"description": "Producto encontrado"},
        404: {"model": ErrorResponse, "description": "Producto no encontrado"},
        500: {"model": ErrorResponse, "description": "Error del servidor"}
    }
)
async def get_product(
    product_id: int,
    current_user: dict = Depends(get_current_active_user)
):
    """
    Obtiene un producto por su ID.
    
    Parámetros de entrada:
        product_id (int): ID del producto a buscar
        current_user (dict): Usuario autenticado
    
    Retorna:
        ProductResponse: Datos del producto
    
    Códigos HTTP:
        200: Producto encontrado
        404: Producto no existe
        500: Error al buscar producto
    """
    try:
        logger.info(f"Buscando producto ID: {product_id}")
        
        query = "SELECT * FROM products WHERE id = %s"
        result = execute_query(query, (product_id,), fetch=True)
        
        if not result:
            logger.warning(f"Producto no encontrado: {product_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Producto con ID {product_id} no encontrado"
            )
        
        logger.info(f"✓ Producto encontrado: {result[0]['name']}")
        return result[0]
        
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"Error al obtener producto: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener producto"
        )


# ============================================
# ENDPOINT: CREAR PRODUCTO
# ============================================

@router.post(
    "/",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear producto",
    description="Crea un nuevo producto en el inventario",
    responses={
        201: {"description": "Producto creado"},
        400: {"model": ErrorResponse, "description": "Datos inválidos o SKU duplicado"},
        500: {"model": ErrorResponse, "description": "Error del servidor"}
    }
)
async def create_product(
    product: ProductCreate,
    current_user: dict = Depends(get_current_active_user)
):
    """
    Crea un nuevo producto en el inventario.
    
    Parámetros de entrada:
        product (ProductCreate): Datos del producto
        current_user (dict): Usuario autenticado
    
    Retorna:
        ProductResponse: Producto creado con ID asignado
    
    Códigos HTTP:
        201: Producto creado exitosamente
        400: SKU duplicado o datos inválidos
        500: Error al crear producto
    """
    try:
        logger.info(f"Usuario {current_user['username']} creando producto: {product.name}")
        
        # Verificar SKU único si se proporciona
        if product.sku:
            check_sku_query = "SELECT id FROM products WHERE sku = %s"
            existing_sku = execute_query(check_sku_query, (product.sku,), fetch=True)
            
            if existing_sku:
                logger.warning(f"Intento de crear producto con SKU duplicado: {product.sku}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Ya existe un producto con SKU '{product.sku}'"
                )
        
        # Insertar producto
        insert_query = """
            INSERT INTO products 
            (name, description, sku, price, stock, min_stock, category_id, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        result = execute_query(
            insert_query,
            (
                product.name,
                product.description,
                product.sku,
                float(product.price),
                product.stock,
                product.min_stock,
                product.category_id,
                product.is_active
            ),
            fetch=False
        )
        
        if result <= 0:
            logger.error("Error al insertar producto")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error al crear producto"
            )
        
        # Obtener producto recién creado
        get_product_query = """
            SELECT * FROM products 
            WHERE sku = %s OR (name = %s AND sku IS NULL)
            ORDER BY id DESC LIMIT 1
        """
        
        new_product = execute_query(
            get_product_query,
            (product.sku, product.name),
            fetch=True
        )
        
        if not new_product:
            logger.error("Producto creado pero no se pudo recuperar")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error al recuperar producto creado"
            )
        
        logger.info(f"Producto creado exitosamente: ID {new_product[0]['id']}")
        return new_product[0]
        
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"Error inesperado al crear producto: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al crear producto"
        )


# ============================================
# ENDPOINT: ACTUALIZAR PRODUCTO
# ============================================

@router.put(
    "/{product_id}",
    response_model=ProductResponse,
    status_code=status.HTTP_200_OK,
    summary="Actualizar producto",
    description="Actualiza un producto existente",
    responses={
        200: {"description": "Producto actualizado"},
        404: {"model": ErrorResponse, "description": "Producto no encontrado"},
        400: {"model": ErrorResponse, "description": "Datos inválidos"},
        500: {"model": ErrorResponse, "description": "Error del servidor"}
    }
)
async def update_product(
    product_id: int,
    product: ProductUpdate,
    current_user: dict = Depends(get_current_active_user)
):
    """
    Actualiza un producto existente.
    
    Parámetros de entrada:
        product_id (int): ID del producto a actualizar
        product (ProductUpdate): Campos a actualizar (todos opcionales)
        current_user (dict): Usuario autenticado
    
    Retorna:
        ProductResponse: Producto actualizado
    
    Códigos HTTP:
        200: Producto actualizado exitosamente
        404: Producto no existe
        400: Datos inválidos o SKU duplicado
        500: Error al actualizar
    """
    try:
        logger.info(f"Usuario {current_user['username']} actualizando producto ID: {product_id}")
        
        # Verificar que el producto existe
        check_query = "SELECT id FROM products WHERE id = %s"
        exists = execute_query(check_query, (product_id,), fetch=True)
        
        if not exists:
            logger.warning(f"Intento de actualizar producto inexistente: {product_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Producto con ID {product_id} no encontrado"
            )
        
        # Construir query de actualización dinámicamente
        update_fields = []
        params = []
        
        if product.name is not None:
            update_fields.append("name = %s")
            params.append(product.name)
        
        if product.description is not None:
            update_fields.append("description = %s")
            params.append(product.description)
        
        if product.sku is not None:
            # Verificar SKU único
            check_sku = "SELECT id FROM products WHERE sku = %s AND id != %s"
            sku_exists = execute_query(check_sku, (product.sku, product_id), fetch=True)
            if sku_exists:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Ya existe otro producto con SKU '{product.sku}'"
                )
            update_fields.append("sku = %s")
            params.append(product.sku)
        
        if product.price is not None:
            update_fields.append("price = %s")
            params.append(float(product.price))
        
        if product.stock is not None:
            update_fields.append("stock = %s")
            params.append(product.stock)
        
        if product.min_stock is not None:
            update_fields.append("min_stock = %s")
            params.append(product.min_stock)
        
        if product.category_id is not None:
            update_fields.append("category_id = %s")
            params.append(product.category_id)
        
        if product.is_active is not None:
            update_fields.append("is_active = %s")
            params.append(product.is_active)
        
        if not update_fields:
            logger.warning("Intento de actualización sin campos")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se proporcionaron campos para actualizar"
            )
        
        # Ejecutar actualización
        update_query = f"UPDATE products SET {', '.join(update_fields)} WHERE id = %s"
        params.append(product_id)
        
        result = execute_query(update_query, tuple(params), fetch=False)
        
        if result <= 0:
            logger.error("Error al actualizar producto")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error al actualizar producto"
            )
        
        # Obtener producto actualizado
        get_query = "SELECT * FROM products WHERE id = %s"
        updated_product = execute_query(get_query, (product_id,), fetch=True)
        
        logger.info(f"✓ Producto actualizado exitosamente: ID {product_id}")
        return updated_product[0]
        
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"Error inesperado al actualizar producto: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al actualizar producto"
        )


# ============================================
# ENDPOINT: ELIMINAR PRODUCTO
# ============================================

@router.delete(
    "/{product_id}",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Eliminar producto",
    description="Elimina un producto del inventario",
    responses={
        200: {"description": "Producto eliminado"},
        404: {"model": ErrorResponse, "description": "Producto no encontrado"},
        500: {"model": ErrorResponse, "description": "Error del servidor"}
    }
)
async def delete_product(
    product_id: int,
    current_user: dict = Depends(get_current_active_user)
):
    """
    Elimina un producto del inventario.
   
    Parámetros de entrada:
        product_id (int): ID del producto a eliminar
        current_user (dict): Usuario autenticado
    
    Retorna:
        MessageResponse: Confirmación de eliminación
    
    Códigos HTTP:
        200: Producto eliminado exitosamente
        404: Producto no existe
        400: No se puede eliminar (tiene ventas asociadas)
        500: Error al eliminar
    """
    try:
        logger.info(f"Usuario {current_user['username']} eliminando producto ID: {product_id}")
        
        # Verificar que el producto existe
        check_query = "SELECT name FROM products WHERE id = %s"
        exists = execute_query(check_query, (product_id,), fetch=True)
        
        if not exists:
            logger.warning(f"Intento de eliminar producto inexistente: {product_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Producto con ID {product_id} no encontrado"
            )
        
        product_name = exists[0]['name']
        
        # Intentar eliminar producto
        delete_query = "DELETE FROM products WHERE id = %s"
        result = execute_query(delete_query, (product_id,), fetch=False)
        
        if result <= 0:
            logger.error(f"Error al eliminar producto: {product_id}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error al eliminar producto"
            )
        
        logger.info(f"✓ Producto eliminado: {product_name}")
        return {
            "message": "Producto eliminado exitosamente",
            "detail": f"El producto '{product_name}' ha sido eliminado del inventario"
        }
        
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"Error inesperado al eliminar producto: {e}")
        
        # Si el error es por integridad referencial
        if "foreign key constraint" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se puede eliminar el producto porque tiene ventas asociadas"
            )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al eliminar producto"
        )


# ============================================
# ENDPOINT: PRODUCTOS CON STOCK BAJO
# ============================================

@router.get(
    "/alerts/low-stock",
    response_model=List[ProductResponse],
    status_code=status.HTTP_200_OK,
    summary="Productos con stock bajo",
    description="Lista productos cuyo stock está por debajo del mínimo",
    responses={
        200: {"description": "Lista de productos con stock bajo"},
        500: {"model": ErrorResponse, "description": "Error del servidor"}
    }
)
async def get_low_stock_products(
    current_user: dict = Depends(get_current_active_user)
):
    """
    Lista productos con stock bajo.
    
    Parámetros de entrada:
        current_user (dict): Usuario autenticado
    
    Retorna:
        List[ProductResponse]: Productos con stock <= min_stock
    
    Códigos HTTP:
        200: Lista retornada
        500: Error al consultar
    """
    try:
        logger.info(f"Consultando productos con stock bajo")
        
        query = """
            SELECT * FROM products 
            WHERE stock <= min_stock AND is_active = TRUE
            ORDER BY stock ASC
        """
        
        products = execute_query(query, fetch=True)
        
        logger.info(f"✓ {len(products)} productos con stock bajo")
        return products
        
    except Exception as e:
        logger.error(f"Error al consultar stock bajo: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al consultar productos con stock bajo"
        )