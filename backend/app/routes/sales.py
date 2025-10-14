from fastapi import APIRouter, HTTPException, status, Depends, Query
from typing import List, Optional
from decimal import Decimal
import logging

from app.models import SaleCreate, SaleResponse, MessageResponse, ErrorResponse
from app.auth import get_current_active_user
from app.database import get_db_connection, close_db_connection

# Configuración de logging
logger = logging.getLogger(__name__)

# Crear router
router = APIRouter()


# ============================================
# ENDPOINT: CREAR VENTA
# ============================================

@router.post(
    "/",
    response_model=SaleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear venta",
    description="Registra una nueva venta y reduce el stock automáticamente",
    responses={
        201: {"description": "Venta creada"},
        400: {"model": ErrorResponse, "description": "Stock insuficiente o datos inválidos"},
        500: {"model": ErrorResponse, "description": "Error del servidor"}
    }
)
async def create_sale(
    sale: SaleCreate,
    current_user: dict = Depends(get_current_active_user)
):
    """
    
    Parámetros de entrada:
        sale (SaleCreate): Datos de la venta (items, notes)
        current_user (dict): Usuario autenticado que realiza la venta
    
    Retorna:
        SaleResponse: Venta creada con ID asignado
    
    Códigos HTTP:
        201: Venta creada exitosamente
        400: Stock insuficiente o producto inactivo
        404: Producto no encontrado
        500: Error al procesar venta
    
    Validaciones:
        - Todos los productos deben existir
        - Todos los productos deben estar activos
        - Stock debe ser suficiente para cada item
        - Cantidad debe ser mayor a 0
    """
    connection = None
    cursor = None
    
    try:
        logger.info(f"Usuario {current_user['username']} creando venta con {len(sale.items)} items")
        
        # Establecer conexión
        connection = get_db_connection()
        
        if not connection:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error al conectar con la base de datos"
            )
        
        cursor = connection.cursor(dictionary=True)
        
        # ===== PASO 1: VALIDAR PRODUCTOS Y STOCK =====
        
        total_amount = Decimal('0.00')
        validated_items = []
        
        for item in sale.items:
            # Obtener información del producto
            cursor.execute(
                "SELECT id, name, price, stock, is_active FROM products WHERE id = %s",
                (item.product_id,)
            )
            product = cursor.fetchone()
            
            # Validar que el producto existe
            if not product:
                logger.warning(f"Intento de venta con producto inexistente: {item.product_id}")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Producto con ID {item.product_id} no encontrado"
                )
            
            # Validar que el producto está activo
            if not product['is_active']:
                logger.warning(f"Intento de venta con producto inactivo: {product['name']}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"El producto '{product['name']}' no está disponible para venta"
                )
            
            # Validar stock suficiente
            if product['stock'] < item.quantity:
                logger.warning(
                    f"Stock insuficiente para {product['name']}: "
                    f"disponible={product['stock']}, solicitado={item.quantity}"
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Stock insuficiente para '{product['name']}'. "
                           f"Disponible: {product['stock']}, Solicitado: {item.quantity}"
                )
            
            # Calcular subtotal (usar precio del item, no del producto actual)
            subtotal = Decimal(str(item.unit_price)) * Decimal(str(item.quantity))
            total_amount += subtotal
            
            # Guardar item validado
            validated_items.append({
                'product_id': item.product_id,
                'product_name': product['name'],
                'quantity': item.quantity,
                'unit_price': item.unit_price,
                'subtotal': subtotal,
                'current_stock': product['stock']
            })
            
            logger.debug(
                f"Item validado: {product['name']} x{item.quantity} = ${subtotal}"
            )
        
        logger.info(f"✓ Todos los items validados. Total: ${total_amount}")
        
        # ===== PASO 2: CREAR VENTA =====
        
        insert_sale_query = """
            INSERT INTO sales (user_id, total_amount, status, notes)
            VALUES (%s, %s, %s, %s)
        """
        
        cursor.execute(
            insert_sale_query,
            (current_user['id'], float(total_amount), 'completed', sale.notes)
        )
        
        sale_id = cursor.lastrowid
        logger.info(f"✓ Venta creada con ID: {sale_id}")
        
        # ===== PASO 3: CREAR ITEMS DE VENTA =====
        
        insert_item_query = """
            INSERT INTO sale_items (sale_id, product_id, quantity, unit_price, subtotal)
            VALUES (%s, %s, %s, %s, %s)
        """
        
        for item in validated_items:
            cursor.execute(
                insert_item_query,
                (
                    sale_id,
                    item['product_id'],
                    item['quantity'],
                    float(item['unit_price']),
                    float(item['subtotal'])
                )
            )
            logger.debug(f"✓ Item agregado: {item['product_name']}")
        
        # ===== PASO 4: ACTUALIZAR STOCK =====
        
        update_stock_query = """
            UPDATE products 
            SET stock = stock - %s 
            WHERE id = %s
        """
        
        for item in validated_items:
            cursor.execute(
                update_stock_query,
                (item['quantity'], item['product_id'])
            )
            
            new_stock = item['current_stock'] - item['quantity']
            logger.info(
                f"✓ Stock actualizado: {item['product_name']} "
                f"({item['current_stock']} → {new_stock})"
            )
        
        # ===== PASO 5: COMMIT TRANSACCIÓN =====
        
        connection.commit()
        logger.info(f"✓✓✓ Venta {sale_id} procesada exitosamente ✓✓✓")
        
        # ===== PASO 6: RETORNAR VENTA CREADA =====
        
        cursor.execute(
            "SELECT * FROM sales WHERE id = %s",
            (sale_id,)
        )
        created_sale = cursor.fetchone()
        
        return created_sale
        
    except HTTPException:
        # Si es un error HTTP, hacer rollback y re-lanzar
        if connection:
            connection.rollback()
            logger.warning("Rollback ejecutado por validación fallida")
        raise
    
    except Exception as e:
        # Error inesperado: rollback y retornar error 500
        if connection:
            connection.rollback()
            logger.error(f"Rollback ejecutado por error: {e}")
        
        logger.error(f"Error inesperado al crear venta: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al procesar venta"
        )
    
    finally:
        # SIEMPRE cerrar cursor y conexión
        if cursor:
            cursor.close()
            logger.debug("Cursor cerrado")
        
        if connection:
            close_db_connection(connection)


# ============================================
# ENDPOINT: LISTAR VENTAS
# ============================================

@router.get(
    "/",
    response_model=List[SaleResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar ventas",
    description="Obtiene lista de todas las ventas con paginación",
    responses={
        200: {"description": "Lista de ventas"},
        500: {"model": ErrorResponse, "description": "Error del servidor"}
    }
)
async def get_sales(
    skip: int = Query(0, ge=0, description="Registros a saltar"),
    limit: int = Query(100, ge=1, le=1000, description="Máximo de registros"),
    status_filter: Optional[str] = Query(None, description="Filtrar por estado"),
    current_user: dict = Depends(get_current_active_user)
):
    """
    Lista todas las ventas con paginación.
    
    Parámetros de entrada:
        skip (int): Registros a omitir (default: 0)
        limit (int): Máximo de registros (default: 100)
        status_filter (str, opcional): Filtrar por estado (completed, cancelled, pending)
        current_user (dict): Usuario autenticado
    
    Retorna:
        List[SaleResponse]: Lista de ventas
    
    Códigos HTTP:
        200: Lista retornada
        500: Error al obtener ventas
    """
    connection = None
    cursor = None
    
    try:
        logger.info(f"Usuario {current_user['username']} listando ventas")
        
        connection = get_db_connection()
        if not connection:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error al conectar con la base de datos"
            )
        
        cursor = connection.cursor(dictionary=True)
        
        # Construir query con filtros
        query = "SELECT * FROM sales WHERE 1=1"
        params = []
        
        if status_filter:
            query += " AND status = %s"
            params.append(status_filter)
        
        query += " ORDER BY sale_date DESC LIMIT %s OFFSET %s"
        params.extend([limit, skip])
        
        cursor.execute(query, tuple(params))
        sales = cursor.fetchall()
        
        logger.info(f"✓ {len(sales)} ventas retornadas")
        return sales
        
    except Exception as e:
        logger.error(f"Error al listar ventas: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener lista de ventas"
        )
    
    finally:
        if cursor:
            cursor.close()
        if connection:
            close_db_connection(connection)


# ============================================
# ENDPOINT: OBTENER VENTA POR ID
# ============================================

@router.get(
    "/{sale_id}",
    response_model=SaleResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener venta",
    description="Obtiene detalles de una venta específica",
    responses={
        200: {"description": "Venta encontrada"},
        404: {"model": ErrorResponse, "description": "Venta no encontrada"},
        500: {"model": ErrorResponse, "description": "Error del servidor"}
    }
)
async def get_sale(
    sale_id: int,
    current_user: dict = Depends(get_current_active_user)
):
    """
    Obtiene una venta por su ID.
    
    Parámetros de entrada:
        sale_id (int): ID de la venta
        current_user (dict): Usuario autenticado
    
    Retorna:
        SaleResponse: Datos de la venta
    
    Códigos HTTP:
        200: Venta encontrada
        404: Venta no existe
        500: Error al buscar
    """
    connection = None
    cursor = None
    
    try:
        logger.info(f"Buscando venta ID: {sale_id}")
        
        connection = get_db_connection()
        if not connection:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error al conectar con la base de datos"
            )
        
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM sales WHERE id = %s", (sale_id,))
        sale = cursor.fetchone()
        
        if not sale:
            logger.warning(f"Venta no encontrada: {sale_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Venta con ID {sale_id} no encontrada"
            )
        
        logger.info(f"✓ Venta encontrada: ${sale['total_amount']}")
        return sale
        
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"Error al obtener venta: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener venta"
        )
    
    finally:
        if cursor:
            cursor.close()
        if connection:
            close_db_connection(connection)


# ============================================
# ENDPOINT: OBTENER ITEMS DE VENTA
# ============================================

@router.get(
    "/{sale_id}/items",
    status_code=status.HTTP_200_OK,
    summary="Obtener items de venta",
    description="Lista todos los items (productos) de una venta específica",
    responses={
        200: {"description": "Items de la venta"},
        404: {"model": ErrorResponse, "description": "Venta no encontrada"},
        500: {"model": ErrorResponse, "description": "Error del servidor"}
    }
)
async def get_sale_items(
    sale_id: int,
    current_user: dict = Depends(get_current_active_user)
):
    """
    Obtiene los items de una venta.
    
    Parámetros de entrada:
        sale_id (int): ID de la venta
        current_user (dict): Usuario autenticado
    
    Retorna:
        list: Items de la venta con información del producto
    
    Códigos HTTP:
        200: Items retornados
        404: Venta no existe
        500: Error al consultar
    """
    connection = None
    cursor = None
    
    try:
        logger.info(f"Obteniendo items de venta ID: {sale_id}")
        
        connection = get_db_connection()
        if not connection:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error al conectar con la base de datos"
            )
        
        cursor = connection.cursor(dictionary=True)
        
        # Verificar que la venta existe
        cursor.execute("SELECT id FROM sales WHERE id = %s", (sale_id,))
        if not cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Venta con ID {sale_id} no encontrada"
            )
        
        # Obtener items con información del producto
        query = """
            SELECT 
                si.*,
                p.name as product_name,
                p.sku as product_sku
            FROM sale_items si
            JOIN products p ON si.product_id = p.id
            WHERE si.sale_id = %s
            ORDER BY si.id
        """
        
        cursor.execute(query, (sale_id,))
        items = cursor.fetchall()
        
        logger.info(f"✓ {len(items)} items retornados")
        return items
        
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"Error al obtener items de venta: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener items de venta"
        )
    
    finally:
        if cursor:
            cursor.close()
        if connection:
            close_db_connection(connection)


# ============================================
# ENDPOINT: CANCELAR VENTA
# ============================================

@router.put(
    "/{sale_id}/cancel",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancelar venta",
    description="Cancela una venta y restaura el stock de los productos",
    responses={
        200: {"description": "Venta cancelada"},
        400: {"model": ErrorResponse, "description": "Venta ya cancelada"},
        404: {"model": ErrorResponse, "description": "Venta no encontrada"},
        500: {"model": ErrorResponse, "description": "Error del servidor"}
    }
)
async def cancel_sale(
    sale_id: int,
    current_user: dict = Depends(get_current_active_user)
):
    """
    Cancela una venta y restaura el stock.
    
    Parámetros de entrada:
        sale_id (int): ID de la venta a cancelar
        current_user (dict): Usuario autenticado
    
    Retorna:
        MessageResponse: Confirmación de cancelación
    
    Códigos HTTP:
        200: Venta cancelada exitosamente
        400: Venta ya estaba cancelada
        404: Venta no existe
        500: Error al cancelar
    """
    connection = None
    cursor = None
    
    try:
        logger.info(f"Usuario {current_user['username']} cancelando venta ID: {sale_id}")
        
        connection = get_db_connection()
        if not connection:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error al conectar con la base de datos"
            )
        
        cursor = connection.cursor(dictionary=True)
        
        # ===== PASO 1: VERIFICAR VENTA =====
        
        cursor.execute("SELECT * FROM sales WHERE id = %s", (sale_id,))
        sale = cursor.fetchone()
        
        if not sale:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Venta con ID {sale_id} no encontrada"
            )
        
        if sale['status'] == 'cancelled':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La venta ya está cancelada"
            )
        
        # ===== PASO 2: OBTENER ITEMS =====
        
        cursor.execute(
            "SELECT product_id, quantity FROM sale_items WHERE sale_id = %s",
            (sale_id,)
        )
        items = cursor.fetchall()
        
        # ===== PASO 3: RESTAURAR STOCK =====
        
        for item in items:
            cursor.execute(
                "UPDATE products SET stock = stock + %s WHERE id = %s",
                (item['quantity'], item['product_id'])
            )
            logger.debug(f"Stock restaurado: producto {item['product_id']} +{item['quantity']}")
        
        # ===== PASO 4: CANCELAR VENTA =====
        
        cursor.execute(
            "UPDATE sales SET status = 'cancelled' WHERE id = %s",
            (sale_id,)
        )
        
        # ===== PASO 5: COMMIT =====
        
        connection.commit()
        logger.info(f"✓ Venta {sale_id} cancelada exitosamente")
        
        return {
            "message": "Venta cancelada exitosamente",
            "detail": f"Venta #{sale_id} cancelada. Stock restaurado para {len(items)} productos."
        }
        
    except HTTPException:
        if connection:
            connection.rollback()
        raise
    
    except Exception as e:
        if connection:
            connection.rollback()
        logger.error(f"Error al cancelar venta: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al cancelar venta"
        )
    
    finally:
        if cursor:
            cursor.close()
        if connection:
            close_db_connection(connection)


# ============================================
# ENDPOINT: ESTADÍSTICAS DE VENTAS
# ============================================

@router.get(
    "/stats/summary",
    status_code=status.HTTP_200_OK,
    summary="Estadísticas de ventas",
    description="Retorna un resumen de estadísticas de ventas",
    responses={
        200: {"description": "Estadísticas calculadas"},
        500: {"model": ErrorResponse, "description": "Error del servidor"}
    }
)
async def get_sales_summary(
    current_user: dict = Depends(get_current_active_user)
):
    """
    Obtiene estadísticas resumidas de ventas.
    
    Parámetros de entrada:
        current_user (dict): Usuario autenticado
    
    Retorna:
        dict: Estadísticas (total_sales, total_amount, avg_sale, etc.)
    
    Códigos HTTP:
        200: Estadísticas calculadas
        500: Error al calcular
    """
    connection = None
    cursor = None
    
    try:
        logger.info("Calculando estadísticas de ventas")
        
        connection = get_db_connection()
        if not connection:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error al conectar con la base de datos"
            )
        
        cursor = connection.cursor(dictionary=True)
        
        # Estadísticas generales
        cursor.execute("""
            SELECT 
                COUNT(*) as total_sales,
                SUM(total_amount) as total_amount,
                AVG(total_amount) as avg_sale_amount,
                MAX(total_amount) as max_sale,
                MIN(total_amount) as min_sale
            FROM sales
            WHERE status = 'completed'
        """)
        
        stats = cursor.fetchone()
        
        # Productos más vendidos
        cursor.execute("""
            SELECT 
                p.name,
                SUM(si.quantity) as total_quantity
            FROM sale_items si
            JOIN products p ON si.product_id = p.id
            JOIN sales s ON si.sale_id = s.id
            WHERE s.status = 'completed'
            GROUP BY p.id, p.name
            ORDER BY total_quantity DESC
            LIMIT 5
        """)
        
        top_products = cursor.fetchall()
        
        logger.info("✓ Estadísticas calculadas")
        
        return {
            "summary": stats,
            "top_products": top_products
        }
        
    except Exception as e:
        logger.error(f"Error al calcular estadísticas: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al calcular estadísticas"
        )
    
    finally:
        if cursor:
            cursor.close()
        if connection:
            close_db_connection(connection)