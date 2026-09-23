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
    PENDIENTE = "pendiente"
    PAGADO = "pagado"
    ENVIADO = "enviado"
    CANCELADO = "cancelado"

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
