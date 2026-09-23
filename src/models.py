"""
Modelos de datos para MS4
"""

from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum

# ========== ENUMS ==========

class MetodoPago(str, Enum):
    # OJO: estos valores deben coincidir EXACTO con el ENUM de Pago.js en ms2
    # (Sequelize: ENUM("tarjeta_credito", "debito", "paypal") -> guion bajo, no guion medio)
    TARJETA_CREDITO = "tarjeta_credito"
    DEBITO = "debito"
    PAYPAL = "paypal"

class EstadoPedido(str, Enum):
    # Alineado con el ENUM real de Pedido.js en ms2 (Sequelize):
    # ENUM("procesando", "pendiente", "pagado", "cancelado")
    PROCESANDO = "procesando"
    PENDIENTE = "pendiente"
    PAGADO = "pagado"
    CANCELADO = "cancelado"

class EstadoPago(str, Enum):
    # Alineado con el ENUM real de Pago.js en ms2 (Sequelize):
    # ENUM("aprobado", "rechazado", "en_proceso")
    APROBADO = "aprobado"
    RECHAZADO = "rechazado"
    EN_PROCESO = "en_proceso"

# ========== REQUEST MODELS ==========

class ItemCarritoRequest(BaseModel):
    producto_id: int
    cantidad: int

class CheckoutRequest(BaseModel):
    cliente_id: int = Field(..., description="ID del cliente")
    direccion_envio: str = Field(..., description="Direccion de envio")
    metodo_pago: MetodoPago = Field(..., description="Metodo de pago")

# ========== RESPONSE MODELS ==========

class ItemCarritoResponse(BaseModel):
    producto_id: int
    cantidad: int
    precio_unitario: float
    producto_nombre: str

class CheckoutResponse(BaseModel):
    mensaje: str
    pedido_id: int
    pago_id: int
    total: float
    items: List[ItemCarritoResponse]
    estado_pedido: str

class HealthResponse(BaseModel):
    status: str
    service: str
    timestamp: str

class EstadoPedidoResponse(BaseModel):
    pedido_id: int
    estado: str
    fecha_pedido: str
    total: float

# ========== MODELS PARA ENDPOINTS PROXY (stock / pedidos / pagos) ==========
# Estos son los 3 endpoints propios que expone MS4 además de /checkout,
# para reservar stock, crear un pedido o registrar un pago de forma directa
# (sin correr todo el flujo orquestado de checkout).

class ReservarStockRequest(BaseModel):
    """Body que recibe MS4. Se traduce internamente al formato que espera ms1
    (product_id, client_id, cantidad) — ver CheckoutService.reservar_stock."""
    producto_id: int = Field(..., description="ID del producto")
    cliente_id: int = Field(..., description="ID del cliente")
    cantidad: int = Field(..., gt=0, description="Cantidad a reservar")

class ReservarStockResponse(BaseModel):
    # Mismo shape que schemas.ReservarStockResponse en ms1
    exito: bool
    product_id: int
    available_stock: int

class CrearPedidoRequest(BaseModel):
    """Body que recibe MS4 para crear un pedido directamente (proxy a ms2).
    Mismos campos que ya arma CheckoutService.procesar() al llamar a
    POST {ms2}/ms2/pedidos."""
    cliente_id: int = Field(..., description="ID del cliente")
    subtotal: float = Field(..., ge=0)
    impuestos: float = Field(..., ge=0)
    total: float = Field(..., ge=0)
    direccion_envio: str = Field(..., description="Direccion de envio")
    metodo_pago: MetodoPago = Field(..., description="Metodo de pago")

class CrearPagoRequest(BaseModel):
    """Body que recibe MS4 para registrar un pago directamente (proxy a ms2).
    Mismos campos que ya arma CheckoutService.procesar() al llamar a
    POST {ms2}/ms2/pagos."""
    pedido_id: int = Field(..., description="ID del pedido asociado")
    monto: float = Field(..., ge=0)
    metodo_pago: MetodoPago = Field(..., description="Metodo de pago")
    estado_pago: EstadoPago = Field(default=EstadoPago.APROBADO)
