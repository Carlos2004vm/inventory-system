from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional
from datetime import datetime
from decimal import Decimal


# ============================================
# MODELOS DE USUARIO (Authentication)
# ============================================

class UserBase(BaseModel):
    """
    Modelo base de usuario.
    
    Atributos:
        username (str): Nombre de usuario único (3-50 caracteres)
        email (EmailStr): Email válido
        full_name (str, opcional): Nombre completo del usuario
    """
    username: str = Field(..., min_length=3, max_length=50, 
                         description="Nombre de usuario único")
    email: EmailStr = Field(..., description="Correo electrónico válido")
    full_name: Optional[str] = Field(None, max_length=100,
                                    description="Nombre completo")


class UserCreate(UserBase):
    """
    Modelo para crear un nuevo usuario.
   
    Parámetros de entrada (además de UserBase):
        password (str): Contraseña (mínimo 8 caracteres)
    
    Validaciones:
        - Password debe tener al menos 8 caracteres
        - Email debe ser válido (validado por EmailStr)
        - Username debe ser único (validado en la base de datos)
    """
    password: str = Field(..., min_length=8, max_length=100,
                         description="Contraseña (mínimo 8 caracteres)")
    
    @validator('password')
    def password_strength(cls, v):
        """
        Valida la fortaleza de la contraseña.
        
        Parámetros:
            v (str): Contraseña a validar
        
        Retorna:
            str: Contraseña validada
        
        Excepciones:
            ValueError: Si la contraseña no cumple requisitos
        """
        if len(v) < 8:
            raise ValueError('La contraseña debe tener al menos 8 caracteres')
        return v


class UserLogin(BaseModel):
    """
    Modelo para login de usuario.
    
    Atributos:
        username (str): Nombre de usuario
        password (str): Contraseña
    """
    username: str = Field(..., description="Nombre de usuario")
    password: str = Field(..., description="Contraseña")


class UserResponse(UserBase):
    """
    Modelo de respuesta de usuario (sin contraseña).
    
    Atributos adicionales:
        id (int): ID del usuario
        is_active (bool): Estado del usuario
        created_at (datetime): Fecha de creación
    """
    id: int
    is_active: bool = True
    created_at: datetime
    
    class Config:
        from_attributes = True  # Permite crear desde ORM objects


class Token(BaseModel):
    """
    Modelo de respuesta de token JWT.
    
    Atributos:
        access_token (str): Token JWT generado
        token_type (str): Tipo de token (siempre "bearer")
    """
    access_token: str = Field(..., description="Token JWT")
    token_type: str = Field(default="bearer", description="Tipo de token")


# ============================================
# MODELOS DE CATEGORÍA
# ============================================

class CategoryBase(BaseModel):
    """
    Modelo base de categoría.
    
    Atributos:
        name (str): Nombre de la categoría (único, 1-100 caracteres)
        description (str, opcional): Descripción de la categoría
    """
    name: str = Field(..., min_length=1, max_length=100,
                     description="Nombre de la categoría")
    description: Optional[str] = Field(None, description="Descripción")


class CategoryCreate(CategoryBase):
    """
    Modelo para crear categoría.
    
    """
    pass


class CategoryResponse(CategoryBase):
    """
    Modelo de respuesta de categoría.
    
    Atributos adicionales:
        id (int): ID de la categoría
        created_at (datetime): Fecha de creación
    """
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True


# ============================================
# MODELOS DE PRODUCTO
# ============================================

class ProductBase(BaseModel):
    """
    Modelo base de producto.
    
    Atributos:
        name (str): Nombre del producto
        description (str, opcional): Descripción detallada
        sku (str, opcional): Código único del producto
        price (Decimal): Precio (debe ser positivo)
        stock (int): Cantidad en inventario (no negativo)
        min_stock (int): Stock mínimo para alertas
        category_id (int, opcional): ID de la categoría
        is_active (bool): Si el producto está activo
    """
    name: str = Field(..., min_length=1, max_length=200,
                     description="Nombre del producto")
    description: Optional[str] = Field(None, description="Descripción")
    sku: Optional[str] = Field(None, max_length=50,
                              description="Código SKU único")
    price: Decimal = Field(..., gt=0, description="Precio (debe ser > 0)")
    stock: int = Field(default=0, ge=0, description="Stock disponible")
    min_stock: int = Field(default=5, ge=0, description="Stock mínimo")
    category_id: Optional[int] = Field(None, description="ID de categoría")
    is_active: bool = Field(default=True, description="Producto activo")
    
    @validator('price')
    def price_must_be_positive(cls, v):
        """
        Valida que el precio sea positivo.
        
        Parámetros:
            v (Decimal): Precio a validar
        
        Retorna:
            Decimal: Precio validado
        
        Excepciones:
            ValueError: Si el precio es negativo o cero
        """
        if v <= 0:
            raise ValueError('El precio debe ser mayor a 0')
        return v
    
    @validator('stock', 'min_stock')
    def stock_must_be_non_negative(cls, v):
        """
        Valida que el stock no sea negativo.
        
        Parámetros:
            v (int): Stock a validar
        
        Retorna:
            int: Stock validado
        """
        if v < 0:
            raise ValueError('El stock no puede ser negativo')
        return v


class ProductCreate(ProductBase):
    """
    Modelo para crear producto.
    
    """
    pass


class ProductUpdate(BaseModel):
    """
    Modelo para actualizar producto (todos los campos opcionales).
   
    """
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    sku: Optional[str] = Field(None, max_length=50)
    price: Optional[Decimal] = Field(None, gt=0)
    stock: Optional[int] = Field(None, ge=0)
    min_stock: Optional[int] = Field(None, ge=0)
    category_id: Optional[int] = None
    is_active: Optional[bool] = None


class ProductResponse(ProductBase):
    """
    Modelo de respuesta de producto.
    
    Atributos adicionales:
        id (int): ID del producto
        created_at (datetime): Fecha de creación
        updated_at (datetime): Última actualización
    """
    id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# ============================================
# MODELOS DE VENTA
# ============================================

class SaleItemBase(BaseModel):
    """
    Modelo de item individual en una venta.
    
    Atributos:
        product_id (int): ID del producto vendido
        quantity (int): Cantidad vendida (debe ser > 0)
        unit_price (Decimal): Precio unitario al momento de venta
    """
    product_id: int = Field(..., description="ID del producto")
    quantity: int = Field(..., gt=0, description="Cantidad (debe ser > 0)")
    unit_price: Decimal = Field(..., gt=0, description="Precio unitario")
    
    @validator('quantity')
    def quantity_must_be_positive(cls, v):
        """Valida que la cantidad sea positiva."""
        if v <= 0:
            raise ValueError('La cantidad debe ser mayor a 0')
        return v


class SaleCreate(BaseModel):
    """
    Modelo para crear una venta.
    
    Atributos:
        items (list): Lista de items a vender
        notes (str, opcional): Notas adicionales
    
    Validaciones:
        - Debe tener al menos 1 item
        - Cada item debe tener stock suficiente (validado en endpoint)
    """
    items: list[SaleItemBase] = Field(..., min_length=1,
                                     description="Items de la venta")
    notes: Optional[str] = Field(None, description="Notas adicionales")
    
    @validator('items')
    def items_not_empty(cls, v):
        """Valida que la venta tenga al menos un item."""
        if not v:
            raise ValueError('La venta debe tener al menos un item')
        return v


class SaleResponse(BaseModel):
    """
    Modelo de respuesta de venta.
    
    Atributos:
        id (int): ID de la venta
        user_id (int): ID del usuario que realizó la venta
        total_amount (Decimal): Monto total
        sale_date (datetime): Fecha de la venta
        status (str): Estado (completed, cancelled, pending)
        notes (str, opcional): Notas
    """
    id: int
    user_id: int
    total_amount: Decimal
    sale_date: datetime
    status: str
    notes: Optional[str]
    
    class Config:
        from_attributes = True


# ============================================
# MODELOS DE RESPUESTA GENÉRICOS
# ============================================

class MessageResponse(BaseModel):
    """
    Modelo de respuesta con mensaje simple.
   
    Atributos:
        message (str): Mensaje descriptivo
        detail (str, opcional): Detalles adicionales
    """
    message: str = Field(..., description="Mensaje de respuesta")
    detail: Optional[str] = Field(None, description="Detalles adicionales")


class ErrorResponse(BaseModel):
    """
    Modelo de respuesta de error.
   
    Atributos:
        error (str): Tipo de error
        message (str): Descripción del error
        detail (str, opcional): Información adicional
    """
    error: str = Field(..., description="Tipo de error")
    message: str = Field(..., description="Mensaje de error")
    detail: Optional[str] = Field(None, description="Detalles del error")
    