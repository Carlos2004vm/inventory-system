from fastapi import APIRouter, HTTPException, status, Depends, Query, UploadFile, File, BackgroundTasks
from fastapi.responses import StreamingResponse
from typing import List, Optional, Dict
import logging
import pandas as pd
import os
from datetime import datetime
import uuid
import io

from app.models import ProductCreate, ProductUpdate, ProductResponse, MessageResponse, ErrorResponse
from app.auth import get_current_active_user
from app.database import execute_query

# Configuración de logging
logger = logging.getLogger(__name__)

# Crear router
router = APIRouter()

# Diccionario para almacenar progreso de uploads
upload_progress: Dict[str, dict] = {}


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
    """Lista todos los productos con paginación y filtros."""
    try:
        logger.info(f"Usuario {current_user['username']} listando productos")
        
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
    description="Obtiene un producto específico por su ID"
)
async def get_product(
    product_id: int,
    current_user: dict = Depends(get_current_active_user)
):
    """Obtiene un producto por su ID."""
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
    description="Crea un nuevo producto en el inventario"
)
async def create_product(
    product: ProductCreate,
    current_user: dict = Depends(get_current_active_user)
):
    """Crea un nuevo producto en el inventario."""
    try:
        logger.info(f"Usuario {current_user['username']} creando producto: {product.name}")
        
        if product.sku:
            check_sku_query = "SELECT id FROM products WHERE sku = %s"
            existing_sku = execute_query(check_sku_query, (product.sku,), fetch=True)
            
            if existing_sku:
                logger.warning(f"Intento de crear producto con SKU duplicado: {product.sku}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Ya existe un producto con SKU '{product.sku}'"
                )
        
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
        
        get_product_query = """
            SELECT * FROM products 
            WHERE id = (SELECT LAST_INSERT_ID())
        """
        created_product = execute_query(get_product_query, fetch=True)
        
        logger.info(f"✓ Producto creado exitosamente: ID {created_product[0]['id']}")
        return created_product[0]
        
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
    description="Actualiza un producto existente"
)
async def update_product(
    product_id: int,
    product: ProductUpdate,
    current_user: dict = Depends(get_current_active_user)
):
    """Actualiza un producto existente."""
    try:
        logger.info(f"Usuario {current_user['username']} actualizando producto ID: {product_id}")
        
        check_query = "SELECT id FROM products WHERE id = %s"
        exists = execute_query(check_query, (product_id,), fetch=True)
        
        if not exists:
            logger.warning(f"Intento de actualizar producto inexistente: {product_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Producto con ID {product_id} no encontrado"
            )
        
        update_fields = []
        params = []
        
        if product.name is not None:
            update_fields.append("name = %s")
            params.append(product.name)
        
        if product.description is not None:
            update_fields.append("description = %s")
            params.append(product.description)
        
        if product.sku is not None:
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
        
        update_query = f"UPDATE products SET {', '.join(update_fields)} WHERE id = %s"
        params.append(product_id)
        
        result = execute_query(update_query, tuple(params), fetch=False)
        
        if result <= 0:
            logger.error("Error al actualizar producto")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error al actualizar producto"
            )
        
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
    description="Elimina un producto del inventario"
)
async def delete_product(
    product_id: int,
    current_user: dict = Depends(get_current_active_user)
):
    """Elimina un producto del inventario."""
    try:
        logger.info(f"Usuario {current_user['username']} eliminando producto ID: {product_id}")
        
        check_query = "SELECT name FROM products WHERE id = %s"
        exists = execute_query(check_query, (product_id,), fetch=True)
        
        if not exists:
            logger.warning(f"Intento de eliminar producto inexistente: {product_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Producto con ID {product_id} no encontrado"
            )
        
        product_name = exists[0]['name']
        
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
    description="Lista productos cuyo stock está por debajo del mínimo"
)
async def get_low_stock_products(
    current_user: dict = Depends(get_current_active_user)
):
    """Lista productos con stock bajo."""
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


# ============================================
# ENDPOINT: CARGAR PRODUCTOS DESDE EXCEL
# ============================================

@router.post(
    "/upload/excel",
    status_code=status.HTTP_200_OK,
    summary="Cargar productos desde Excel",
    description="Carga masiva de productos desde archivo Excel (.xlsx, .xls)",
    responses={
        200: {"description": "Archivo procesado"},
        400: {"model": ErrorResponse, "description": "Archivo inválido"},
        500: {"model": ErrorResponse, "description": "Error del servidor"}
    }
)
async def upload_excel(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_active_user)
):
    """
    Carga productos masivamente desde archivo Excel.
    
    Formato esperado del Excel:
        | Nombre | SKU | Precio | Stock | Min_Stock | Categoría | Descripción |
    
    Retorna:
        dict: Resultado del procesamiento con estadísticas
    """
    
    upload_id = str(uuid.uuid4())
    
    upload_progress[upload_id] = {
        "status": "iniciando",
        "progress": 0,
        "total": 0,
        "procesados": 0,
        "exitosos": 0,
        "errores": 0,
        "duplicados": 0,
        "message": "Iniciando carga..."
    }
    
    try:
        logger.info(f"Usuario {current_user['username']} iniciando carga de Excel")
        
        if not file.filename.endswith(('.xlsx', '.xls')):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El archivo debe ser formato Excel (.xlsx o .xls)"
            )
        
        upload_dir = "/tmp/uploads"
        os.makedirs(upload_dir, exist_ok=True)
        
        file_path = f"{upload_dir}/{upload_id}_{file.filename}"
        
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        logger.info(f"Archivo guardado: {file_path}")
        
        try:
            df = pd.read_excel(file_path)
            logger.info(f"Excel leído: {len(df)} filas encontradas")
        except Exception as e:
            logger.error(f"Error al leer Excel: {e}")
            os.remove(file_path)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Error al leer archivo Excel: {str(e)}"
            )
        
        required_columns = ['Nombre', 'Precio', 'Stock']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            os.remove(file_path)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Columnas faltantes en el Excel: {', '.join(missing_columns)}. "
                       f"Columnas requeridas: {', '.join(required_columns)}"
            )
        
        total_rows = len(df)
        upload_progress[upload_id]["total"] = total_rows
        upload_progress[upload_id]["status"] = "procesando"
        
        exitosos = 0
        errores = 0
        duplicados = 0
        error_details = []
        
        for index, row in df.iterrows():
            try:
                upload_progress[upload_id]["procesados"] = index + 1
                upload_progress[upload_id]["progress"] = int(((index + 1) / total_rows) * 100)
                upload_progress[upload_id]["message"] = f"Procesando producto {index + 1} de {total_rows}"
                
                nombre = str(row['Nombre']).strip() if pd.notna(row['Nombre']) else None
                sku = str(row['SKU']).strip() if 'SKU' in row and pd.notna(row['SKU']) else None
                precio = float(row['Precio']) if pd.notna(row['Precio']) else None
                stock = int(row['Stock']) if pd.notna(row['Stock']) else 0
                min_stock = int(row['Min_Stock']) if 'Min_Stock' in row and pd.notna(row['Min_Stock']) else 5
                categoria_id = int(row['Categoría']) if 'Categoría' in row and pd.notna(row['Categoría']) else None
                descripcion = str(row['Descripción']).strip() if 'Descripción' in row and pd.notna(row['Descripción']) else None
                
                if not nombre:
                    errores += 1
                    error_details.append(f"Fila {index + 2}: Nombre vacío")
                    continue
                
                if not precio or precio <= 0:
                    errores += 1
                    error_details.append(f"Fila {index + 2}: Precio inválido ({precio})")
                    continue
                
                if stock < 0:
                    errores += 1
                    error_details.append(f"Fila {index + 2}: Stock negativo ({stock})")
                    continue
                
                if sku:
                    check_sku_query = "SELECT id FROM products WHERE sku = %s"
                    existing = execute_query(check_sku_query, (sku,), fetch=True)
                    
                    if existing:
                        duplicados += 1
                        logger.warning(f"SKU duplicado: {sku}")
                        continue
                
                insert_query = """
                    INSERT INTO products 
                    (name, description, sku, price, stock, min_stock, category_id, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """
                
                result = execute_query(
                    insert_query,
                    (nombre, descripcion, sku, precio, stock, min_stock, categoria_id, True),
                    fetch=False
                )
                
                if result > 0:
                    exitosos += 1
                    logger.debug(f"Producto insertado: {nombre}")
                else:
                    errores += 1
                    error_details.append(f"Fila {index + 2}: Error al insertar '{nombre}'")
                
            except Exception as e:
                errores += 1
                error_details.append(f"Fila {index + 2}: {str(e)}")
                logger.error(f"Error procesando fila {index + 2}: {e}")
        
        try:
            os.remove(file_path)
        except:
            pass
        
        upload_progress[upload_id]["status"] = "completado"
        upload_progress[upload_id]["progress"] = 100
        upload_progress[upload_id]["exitosos"] = exitosos
        upload_progress[upload_id]["errores"] = errores
        upload_progress[upload_id]["duplicados"] = duplicados
        upload_progress[upload_id]["message"] = "Procesamiento completado"
        
        response = {
            "upload_id": upload_id,
            "total_procesados": total_rows,
            "exitosos": exitosos,
            "errores": errores,
            "duplicados": duplicados,
            "detalles_errores": error_details[:10] if error_details else []
        }
        
        logger.info(f"✓ Carga completada: {exitosos} exitosos, {errores} errores, {duplicados} duplicados")
        
        return response
        
    except HTTPException:
        upload_progress[upload_id]["status"] = "error"
        raise
    
    except Exception as e:
        logger.error(f"Error inesperado en carga de Excel: {e}")
        upload_progress[upload_id]["status"] = "error"
        upload_progress[upload_id]["message"] = str(e)
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al procesar archivo: {str(e)}"
        )


# ============================================
# ENDPOINT: OBTENER PROGRESO DE UPLOAD
# ============================================

@router.get(
    "/upload/progress/{upload_id}",
    status_code=status.HTTP_200_OK,
    summary="Obtener progreso de carga",
    description="Consulta el progreso de una carga de Excel en curso"
)
async def get_upload_progress(
    upload_id: str,
    current_user: dict = Depends(get_current_active_user)
):
    """Obtiene el progreso actual de una carga de Excel."""
    
    if upload_id not in upload_progress:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload no encontrado o expirado"
        )
    
    return upload_progress[upload_id]


# ============================================
# ENDPOINT: DESCARGAR PLANTILLA EXCEL
# ============================================

@router.get(
    "/download/template",
    status_code=status.HTTP_200_OK,
    summary="Descargar plantilla Excel",
    description="Descarga una plantilla de Excel de ejemplo para carga masiva"
)
async def download_excel_template(
    current_user: dict = Depends(get_current_active_user)
):
    """Genera y descarga una plantilla Excel de ejemplo."""
    
    try:
        data = {
            'Nombre': ['Laptop HP Pavilion', 'Mouse Logitech G502', 'Teclado Mecánico RGB'],
            'SKU': ['LP-001', 'MS-002', 'KB-003'],
            'Precio': [850.00, 45.99, 120.50],
            'Stock': [15, 50, 30],
            'Min_Stock': [5, 10, 8],
            'Categoría': [1, 1, 1],
            'Descripción': [
                'Laptop gamer 16GB RAM',
                'Mouse gaming RGB',
                'Teclado mecánico switches azules'
            ]
        }
        
        df = pd.DataFrame(data)
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Productos')
        
        output.seek(0)
        
        return StreamingResponse(
            output,
            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={
                'Content-Disposition': 'attachment; filename=plantilla_productos.xlsx'
            }
        )
        
    except Exception as e:
        logger.error(f"Error al generar plantilla: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al generar plantilla"
        )