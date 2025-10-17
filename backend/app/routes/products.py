from fastapi import APIRouter, HTTPException, status, Depends, Query, UploadFile, File, BackgroundTasks
from fastapi.responses import StreamingResponse
from typing import List, Optional, Dict
import logging
import pandas as pd
import os
from datetime import datetime
import uuid
import io
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading

from app.models import ProductCreate, ProductUpdate, ProductResponse, MessageResponse, ErrorResponse
from app.auth import get_current_active_user
from app.database import execute_query

# Configuración de logging
logger = logging.getLogger(__name__)

# Crear router
router = APIRouter()

# Diccionario para almacenar progreso de uploads (thread-safe)
upload_progress: Dict[str, dict] = {}
progress_lock = threading.Lock()

# Executor para procesamiento concurrente
executor = ThreadPoolExecutor(max_workers=3)  # Máximo 3 archivos simultáneos


# ============================================
# FUNCIONES AUXILIARES PARA CONCURRENCIA
# ============================================

def update_progress(upload_id: str, **kwargs):
    """Actualiza el progreso de forma thread-safe."""
    with progress_lock:
        if upload_id in upload_progress:
            upload_progress[upload_id].update(kwargs)


def process_excel_row(row: pd.Series, index: int, upload_id: str, total_rows: int) -> dict:
    """
    Procesa una fila del Excel de forma aislada.
    Retorna: {"success": bool, "error": str|None, "product_name": str}
    """
    try:
        # Actualizar progreso
        progress_percent = int(((index + 1) / total_rows) * 100)
        update_progress(
            upload_id,
            procesados=index + 1,
            progress=progress_percent,
            message=f"Procesando producto {index + 1} de {total_rows}"
        )
        
        # Extraer datos
        nombre = str(row['Nombre']).strip() if pd.notna(row['Nombre']) else None
        sku = str(row['SKU']).strip() if 'SKU' in row and pd.notna(row['SKU']) else None
        precio = float(row['Precio']) if pd.notna(row['Precio']) else None
        stock = int(row['Stock']) if pd.notna(row['Stock']) else 0
        min_stock = int(row['Min_Stock']) if 'Min_Stock' in row and pd.notna(row['Min_Stock']) else 5
        categoria_id = int(row['Categoría']) if 'Categoría' in row and pd.notna(row['Categoría']) else None
        descripcion = str(row['Descripción']).strip() if 'Descripción' in row and pd.notna(row['Descripción']) else None
        
        # Validaciones
        if not nombre:
            return {"success": False, "error": f"Fila {index + 2}: Nombre vacío", "product_name": ""}
        
        if not precio or precio <= 0:
            return {"success": False, "error": f"Fila {index + 2}: Precio inválido ({precio})", "product_name": nombre}
        
        if stock < 0:
            return {"success": False, "error": f"Fila {index + 2}: Stock negativo ({stock})", "product_name": nombre}
        
        # Verificar SKU duplicado
        if sku:
            check_sku_query = "SELECT id FROM products WHERE sku = %s"
            existing = execute_query(check_sku_query, (sku,), fetch=True)
            
            if existing:
                return {"success": False, "error": f"SKU duplicado: {sku}", "product_name": nombre, "duplicate": True}
        
        # Insertar producto
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
            logger.debug(f"✓ Producto insertado: {nombre}")
            return {"success": True, "error": None, "product_name": nombre}
        else:
            return {"success": False, "error": f"Fila {index + 2}: Error al insertar '{nombre}'", "product_name": nombre}
    
    except Exception as e:
        logger.error(f"Error procesando fila {index + 2}: {e}")
        return {"success": False, "error": f"Fila {index + 2}: {str(e)}", "product_name": ""}


def process_excel_file_sync(file_path: str, upload_id: str, username: str):
    """
    Procesa el archivo Excel de forma síncrona en background.
    Esta función se ejecuta en un thread separado.
    """
    try:
        logger.info(f"[{upload_id}] Iniciando procesamiento en background para {username}")
        
        # Leer Excel
        df = pd.read_excel(file_path)
        total_rows = len(df)
        
        update_progress(
            upload_id,
            total=total_rows,
            status="procesando",
            message=f"Procesando {total_rows} productos..."
        )
        
        exitosos = 0
        errores = 0
        duplicados = 0
        error_details = []
        
        # Procesar cada fila
        for index, row in df.iterrows():
            result = process_excel_row(row, index, upload_id, total_rows)
            
            if result["success"]:
                exitosos += 1
            elif result.get("duplicate"):
                duplicados += 1
            else:
                errores += 1
                if len(error_details) < 10:  # Limitar a 10 errores
                    error_details.append(result["error"])
        
        # Actualizar progreso final
        update_progress(
            upload_id,
            status="completado",
            progress=100,
            exitosos=exitosos,
            errores=errores,
            duplicados=duplicados,
            detalles_errores=error_details,
            message="Procesamiento completado"
        )
        
        logger.info(f"[{upload_id}] ✓ Completado: {exitosos} exitosos, {errores} errores, {duplicados} duplicados")
        
    except Exception as e:
        logger.error(f"[{upload_id}] Error en procesamiento background: {e}")
        update_progress(
            upload_id,
            status="error",
            message=f"Error: {str(e)}"
        )
    
    finally:
        # Limpiar archivo temporal
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.debug(f"[{upload_id}] Archivo temporal eliminado")
        except Exception as e:
            logger.warning(f"[{upload_id}] No se pudo eliminar archivo temporal: {e}")


# ============================================
# ENDPOINT: LISTAR PRODUCTOS
# ============================================

@router.get(
    "/",
    response_model=List[ProductResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar productos",
    description="Obtiene lista de todos los productos con filtros opcionales"
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
        
        query += " ORDER BY id ASC LIMIT %s OFFSET %s"
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
# ENDPOINT: ELIMINAR TODOS LOS PRODUCTOS
# ============================================

@router.delete(
    "/delete-all",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Eliminar todos los productos",
    description="Elimina TODOS los productos del inventario (requiere confirmación)"
)
async def delete_all_products(
    confirm: bool = Query(False, description="Debe ser True para confirmar"),
    current_user: dict = Depends(get_current_active_user)
):
    """
    Elimina TODOS los productos del inventario.
    Requiere confirmación explícita con confirm=true.
    """
    try:
        if not confirm:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Debes confirmar la eliminación masiva con confirm=true"
            )
        
        logger.warning(f"⚠️ Usuario {current_user['username']} solicitó ELIMINAR TODOS los productos")
        
        # Contar productos antes de eliminar
        count_query = "SELECT COUNT(*) as total FROM products"
        result = execute_query(count_query, fetch=True)
        total_products = result[0]['total']
        
        if total_products == 0:
            return {
                "message": "No hay productos para eliminar",
                "detail": "El inventario ya está vacío"
            }
        
        # Eliminar todos
        delete_query = "DELETE FROM products"
        execute_query(delete_query, fetch=False)
        
        logger.warning(f"🗑️ {total_products} productos eliminados por {current_user['username']}")
        
        return {
            "message": f"✅ {total_products} productos eliminados exitosamente",
            "detail": f"Se eliminaron todos los productos del inventario"
        }
        
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"Error al eliminar todos los productos: {e}")
        
        if "foreign key constraint" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se pueden eliminar productos con ventas asociadas. Elimina primero las ventas."
            )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al eliminar productos"
        )
        

# ============================================
# ENDPOINT: OBTENER PRODUCTO POR ID
# ============================================

@router.get(
    "/{product_id}",
    response_model=ProductResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener producto"
)
async def get_product(
    product_id: int,
    current_user: dict = Depends(get_current_active_user)
):
    """Obtiene un producto por su ID."""
    try:
        query = "SELECT * FROM products WHERE id = %s"
        result = execute_query(query, (product_id,), fetch=True)
        
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Producto con ID {product_id} no encontrado"
            )
        
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
    summary="Crear producto"
)
async def create_product(
    product: ProductCreate,
    current_user: dict = Depends(get_current_active_user)
):
    """Crea un nuevo producto en el inventario."""
    try:
        if product.sku:
            check_sku_query = "SELECT id FROM products WHERE sku = %s"
            existing_sku = execute_query(check_sku_query, (product.sku,), fetch=True)
            
            if existing_sku:
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
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error al crear producto"
            )
        
        # Obtener el producto recién creado
        get_product_query = "SELECT * FROM products ORDER BY id DESC LIMIT 1"
        created_product = execute_query(get_product_query, fetch=True)
        
        if not created_product or len(created_product) == 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Producto creado pero no se pudo recuperar"
            )
        
        logger.info(f"✓ Producto creado: {created_product[0]['name']}")
        return created_product[0]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al crear producto: {e}")
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
    summary="Actualizar producto"
)
async def update_product(
    product_id: int,
    product: ProductUpdate,
    current_user: dict = Depends(get_current_active_user)
):
    """Actualiza un producto existente."""
    try:
        check_query = "SELECT id FROM products WHERE id = %s"
        exists = execute_query(check_query, (product_id,), fetch=True)
        
        if not exists:
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
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se proporcionaron campos para actualizar"
            )
        
        update_query = f"UPDATE products SET {', '.join(update_fields)} WHERE id = %s"
        params.append(product_id)
        
        execute_query(update_query, tuple(params), fetch=False)
        
        get_query = "SELECT * FROM products WHERE id = %s"
        updated_product = execute_query(get_query, (product_id,), fetch=True)
        
        return updated_product[0]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al actualizar producto: {e}")
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
    summary="Eliminar producto"
)
async def delete_product(
    product_id: int,
    current_user: dict = Depends(get_current_active_user)
):
    """Elimina un producto del inventario."""
    try:
        check_query = "SELECT name FROM products WHERE id = %s"
        exists = execute_query(check_query, (product_id,), fetch=True)
        
        if not exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Producto con ID {product_id} no encontrado"
            )
        
        product_name = exists[0]['name']
        
        delete_query = "DELETE FROM products WHERE id = %s"
        execute_query(delete_query, (product_id,), fetch=False)
        
        return {
            "message": "Producto eliminado exitosamente",
            "detail": f"El producto '{product_name}' ha sido eliminado"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al eliminar producto: {e}")
        
        if "foreign key constraint" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se puede eliminar el producto porque tiene ventas asociadas"
            )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al eliminar producto"
        )


# ============================================
# ENDPOINT: PRODUCTOS CON STOCK BAJO
# ============================================

@router.get(
    "/alerts/low-stock",
    response_model=List[ProductResponse],
    status_code=status.HTTP_200_OK,
    summary="Productos con stock bajo"
)
async def get_low_stock_products(
    current_user: dict = Depends(get_current_active_user)
):
    """Lista productos con stock bajo."""
    try:
        query = """
            SELECT * FROM products 
            WHERE stock <= min_stock AND is_active = TRUE
            ORDER BY stock ASC
        """
        
        products = execute_query(query, fetch=True)
        return products
        
    except Exception as e:
        logger.error(f"Error al consultar stock bajo: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al consultar productos con stock bajo"
        )


# ============================================
# ENDPOINT: CARGAR PRODUCTOS DESDE EXCEL (MEJORADO CON CONCURRENCIA)
# ============================================

@router.post(
    "/upload/excel",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Cargar productos desde Excel (Async)",
    description="Carga masiva ASÍNCRONA de productos con procesamiento en background"
)
async def upload_excel_async(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_active_user)
):
    """
    Carga productos masivamente de forma ASÍNCRONA.
    El archivo se procesa en background y puedes consultar el progreso.
    """
    
    upload_id = str(uuid.uuid4())
    
    # Inicializar progreso
    with progress_lock:
        upload_progress[upload_id] = {
            "upload_id": upload_id,
            "status": "iniciando",
            "progress": 0,
            "total": 0,
            "procesados": 0,
            "exitosos": 0,
            "errores": 0,
            "duplicados": 0,
            "detalles_errores": [],
            "message": "Iniciando carga...",
            "started_at": datetime.now().isoformat(),
            "username": current_user['username']
        }
    
    try:
        logger.info(f"[{upload_id}] Usuario {current_user['username']} iniciando carga async")
        
        # Validar formato
        if not file.filename.endswith(('.xlsx', '.xls')):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El archivo debe ser formato Excel (.xlsx o .xls)"
            )
        
        # Guardar archivo temporal
        upload_dir = "/tmp/uploads"
        os.makedirs(upload_dir, exist_ok=True)
        
        file_path = f"{upload_dir}/{upload_id}_{file.filename}"
        
        # Guardar archivo
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        logger.info(f"[{upload_id}] Archivo guardado: {file_path}")
        
        # Validar Excel rápidamente
        try:
            df = pd.read_excel(file_path)
            required_columns = ['Nombre', 'Precio', 'Stock']
            missing_columns = [col for col in required_columns if col not in df.columns]
            
            if missing_columns:
                os.remove(file_path)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Columnas faltantes: {', '.join(missing_columns)}"
                )
            
            logger.info(f"[{upload_id}] Excel validado: {len(df)} filas")
            
        except Exception as e:
            if os.path.exists(file_path):
                os.remove(file_path)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Error al leer Excel: {str(e)}"
            )
        
        # Procesar en background usando ThreadPoolExecutor
        loop = asyncio.get_event_loop()
        loop.run_in_executor(
            executor,
            process_excel_file_sync,
            file_path,
            upload_id,
            current_user['username']
        )
        
        logger.info(f"[{upload_id}] Procesamiento iniciado en background")
        
        # Retornar inmediatamente con el upload_id
        return {
            "upload_id": upload_id,
            "message": "Archivo recibido. Procesando en segundo plano...",
            "status": "processing",
            "check_progress_url": f"/api/products/upload/progress/{upload_id}"
        }
        
    except HTTPException:
        with progress_lock:
            if upload_id in upload_progress:
                upload_progress[upload_id]["status"] = "error"
        raise
    
    except Exception as e:
        logger.error(f"[{upload_id}] Error: {e}")
        with progress_lock:
            if upload_id in upload_progress:
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
    
    with progress_lock:
        if upload_id not in upload_progress:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Upload no encontrado o expirado"
            )
        
        return upload_progress[upload_id].copy()


# ============================================
# ENDPOINT: LISTAR TODOS LOS UPLOADS ACTIVOS
# ============================================

@router.get(
    "/upload/list",
    status_code=status.HTTP_200_OK,
    summary="Listar uploads activos",
    description="Lista todos los uploads en progreso o completados recientemente"
)
async def list_uploads(
    current_user: dict = Depends(get_current_active_user)
):
    """Lista todos los uploads activos."""
    
    with progress_lock:
        return {
            "uploads": list(upload_progress.values()),
            "total": len(upload_progress)
        }


# ============================================
# ENDPOINT: DESCARGAR PLANTILLA EXCEL
# ============================================

@router.get(
    "/download/template",
    status_code=status.HTTP_200_OK,
    summary="Descargar plantilla Excel"
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


# ============================================
# ENDPOINT: REINICIAR SECUENCIA DE IDs
# ============================================

@router.post(
    "/reset-sequence",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Reiniciar secuencia de IDs"
)
async def reset_product_sequence(
    current_user: dict = Depends(get_current_active_user)
):
    """Reinicia la secuencia de IDs de productos."""
    try:
        check_query = "SELECT COUNT(*) as total FROM products"
        result = execute_query(check_query, fetch=True)
        
        if result[0]['total'] > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se puede reiniciar la secuencia mientras existan productos. Elimina todos los productos primero."
            )
        
        reset_query = "ALTER TABLE products AUTO_INCREMENT = 1"
        execute_query(reset_query, fetch=False)
        
        logger.info(f"✓ Secuencia reiniciada por {current_user['username']}")
        
        return {
            "message": "Secuencia reiniciada exitosamente",
            "detail": "El próximo producto creado tendrá ID = 1"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al reiniciar secuencia: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al reiniciar secuencia"
        )


