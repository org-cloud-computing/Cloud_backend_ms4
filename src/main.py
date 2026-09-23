from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx
import logging
from datetime import datetime

from src.models import (
    CheckoutRequest, CheckoutResponse, HealthResponse,
    ReservarStockRequest, ReservarStockResponse,
    CrearPedidoRequest, CrearPagoRequest
)
from src.services import CheckoutService
from src.config import settings

# ========== CONFIGURACION ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========== APLICACION ==========
# Igual que hizo ms1 con /ms1 (main.py: docs_url="/ms1/docs", etc.), acá se
# prefija todo con /ms4 para mantener el mismo estándar entre microservicios.
app = FastAPI(
    title="MS4 - Orquestador",
    description="Orquesta el checkout entre ms1, ms2 y ms3",
    version="1.0.0",
    docs_url="/ms4/docs",
    redoc_url="/ms4/redoc",
    openapi_url="/ms4/openapi.json"
)

# CORS para permitir peticiones desde el frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== SERVICIOS ==========
checkout_service = CheckoutService()

# ========== ROUTER CON PREFIJO /ms4 ==========
# Usar un APIRouter con prefix en vez de repetir "/ms4" en cada decorador evita
# que alguien agregue un endpoint nuevo y se olvide de anteponer el prefijo.
router = APIRouter(prefix="/ms4")


# ========== ENDPOINTS ==========

@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Verifica que el servicio esté operativo"""
    return HealthResponse(
        status="ok",
        service="ms4-orquestador",
        timestamp=datetime.now().isoformat()
    )


@router.post("/checkout", response_model=CheckoutResponse)
async def procesar_checkout(request: CheckoutRequest):
    """
    Procesa el checkout completo:
    1. Valida el cliente (ms2)
    2. Lee el carrito (ms3)
    3. Valida stock (ms1)
    4. Reserva stock (ms1)
    5. Crea pedido (ms2)
    6. Registra pago (ms2)
    7. Vacía carrito (ms3)
    """
    logger.info(f"Iniciando checkout para cliente {request.cliente_id}")

    try:
        resultado = await checkout_service.procesar(request)
        logger.info(f"Checkout completado. Pedido: {resultado.pedido_id}")
        return resultado
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en checkout: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/checkout/{pedido_id}/estado")
async def obtener_estado_pedido(pedido_id: int):
    """Obtiene el estado de un pedido"""
    try:
        estado = await checkout_service.obtener_estado(pedido_id)
        return estado
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/checkout/usuario/{cliente_id}/pedidos")
async def obtener_historial_cliente(cliente_id: int):
    """Obtiene el historial de pedidos de un cliente"""
    try:
        historial = await checkout_service.obtener_historial(cliente_id)
        return historial
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== ENDPOINTS PROXY: stock / pedidos / pagos ==========
# Estos 3 endpoints exponen, de forma directa e independiente del flujo de
# /checkout, las mismas operaciones que CheckoutService ya usa internamente
# contra ms1 y ms2. No hacen orquestación ni rollback: son proxies puntuales.

@router.patch("/stock/reservar", response_model=ReservarStockResponse)
async def reservar_stock(request: ReservarStockRequest):
    """Reserva stock de un producto para un cliente (proxy a ms1: PATCH /ms1/stock/reservar)"""
    logger.info(
        f"Reservando stock: producto {request.producto_id}, "
        f"cliente {request.cliente_id}, cantidad {request.cantidad}"
    )
    try:
        return await checkout_service.reservar_stock(request)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al reservar stock: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pedidos", status_code=201)
async def crear_pedido(request: CrearPedidoRequest):
    """Crea un pedido (proxy a ms2: POST /ms2/pedidos)"""
    logger.info(f"Creando pedido para cliente {request.cliente_id}")
    try:
        return await checkout_service.crear_pedido(request)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al crear pedido: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pagos", status_code=201)
async def registrar_pago(request: CrearPagoRequest):
    """Registra un pago (proxy a ms2: POST /ms2/pagos)"""
    logger.info(f"Registrando pago para pedido {request.pedido_id}")
    try:
        return await checkout_service.registrar_pago(request)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al registrar pago: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Registrar el router (con prefijo /ms4 ya aplicado) en la app
app.include_router(router)
