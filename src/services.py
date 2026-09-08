"""
Servicios de MS4 - Consumo de ms1, ms2, ms3
"""

import httpx
import logging
from typing import List, Dict, Any
from fastapi import HTTPException

from src.models import CheckoutRequest, CheckoutResponse, ItemCarritoResponse
from src.config import settings

logger = logging.getLogger(__name__)

class CheckoutService:
    """Servicio que orquesta el checkout"""

    def __init__(self):
        self.ms1_url = settings.MS1_URL
        self.ms2_url = settings.MS2_URL
        self.ms3_url = settings.MS3_URL
        self.timeout = settings.TIMEOUT

    async def procesar(self, request: CheckoutRequest) -> CheckoutResponse:
        """Procesa el checkout completo"""

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # ===== PASO 1: Validar cliente (ms2) =====
            logger.info("Paso 1: Validando cliente")
            try:
                cliente_resp = await client.get(
                    f"{self.ms2_url}/cliente/{request.cliente_id}"
                )
                cliente_resp.raise_for_status()
                cliente = cliente_resp.json()
                logger.info(f"Cliente validado: {cliente.get('nombre')}")
            except httpx.HTTPError as e:
                raise HTTPException(404, f"Cliente no encontrado: {str(e)}")

            # ===== PASO 2: Obtener carrito (ms3) =====
            logger.info("Paso 2: Obteniendo carrito")
            try:
                carrito_resp = await client.get(
                    f"{self.ms3_url}/carrito/{request.cliente_id}"
                )
                carrito_resp.raise_for_status()
                carrito = carrito_resp.json()
                items = carrito.get("items", [])
                if not items:
                    raise HTTPException(400, "El carrito está vacío")
                logger.info(f"Carrito tiene {len(items)} items")
            except httpx.HTTPError as e:
                raise HTTPException(503, f"Error al leer carrito: {str(e)}")

            # ===== PASO 3: Validar stock (ms1) =====
            logger.info("Paso 3: Validando stock")
            productos_validados = []
            for item in items:
                producto_id = item["producto_id"]
                cantidad = item["cantidad"]

                try:
                    # Validar stock
                    stock_resp = await client.get(
                        f"{self.ms1_url}/inventario/stock/{producto_id}"
                    )
                    stock_resp.raise_for_status()
                    stock_data = stock_resp.json()
                    stock_disponible = stock_data.get("stock_disponible", 0)
                    if stock_disponible < cantidad:
                        raise HTTPException(
                            400,
                            f"Stock insuficiente para producto {producto_id}"
                        )

                    # Obtener precio
                    prod_resp = await client.get(
                        f"{self.ms1_url}/productos/{producto_id}"
                    )
                    prod_resp.raise_for_status()
                    prod_data = prod_resp.json()

                    productos_validados.append({
                        "producto_id": producto_id,
                        "cantidad": cantidad,
                        "precio_unitario": float(prod_data.get("price", 0)),
                        "producto_nombre": prod_data.get("nombre", "Producto")
                    })
                except httpx.HTTPError as e:
                    raise HTTPException(503, f"Error al validar producto {producto_id}: {str(e)}")

            # ===== PASO 4: Reservar stock (ms1) =====
            logger.info("Paso 4: Reservando stock")
            try:
                for item in productos_validados:
                    reservar_resp = await client.patch(
                        f"{self.ms1_url}/inventario/stock/reservar",
                        json={
                            "producto_id": item["producto_id"],
                            "cantidad_reservar": item["cantidad"]
                        }
                    )
                    reservar_resp.raise_for_status()
                    reservar_data = reservar_resp.json()
                    if not reservar_data.get("exito", False):
                        raise HTTPException(
                            400,
                            f"No se pudo reservar stock para producto {item['producto_id']}"
                        )
                logger.info("Stock reservado exitosamente")
            except httpx.HTTPError as e:
                raise HTTPException(503, f"Error al reservar stock: {str(e)}")

            # ===== PASO 5: Calcular total =====
            subtotal = sum(item["precio_unitario"] * item["cantidad"]
                           for item in productos_validados)
            impuestos = subtotal * 0.18
            total = subtotal + impuestos

            # ===== PASO 6: Crear pedido (ms2) =====
            logger.info("Paso 5: Creando pedido")
            try:
                pedido_data = {
                    "cliente_id": request.cliente_id,
                    "items": productos_validados,
                    "subtotal": subtotal,
                    "impuestos": impuestos,
                    "total": total,
                    "direccion_envio": request.direccion_envio,
                    "metodo_pago": request.metodo_pago.value
                }
                pedido_resp = await client.post(
                    f"{self.ms2_url}/pedidos",
                    json=pedido_data
                )
                pedido_resp.raise_for_status()
                pedido = pedido_resp.json()
                pedido_id = pedido.get("pedido_id")
                logger.info(f"Pedido creado: {pedido_id}")
            except httpx.HTTPError as e:
                raise HTTPException(503, f"Error al crear pedido: {str(e)}")

            # ===== PASO 7: Registrar pago (ms2) =====
            logger.info("Paso 6: Registrando pago")
            try:
                pago_data = {
                    "pedido_id": pedido_id,
                    "monto": total,
                    "metodo_pago": request.metodo_pago.value,
                    "estado_pago": "aprobado"
                }
                pago_resp = await client.post(
                    f"{self.ms2_url}/pagos",
                    json=pago_data
                )
                pago_resp.raise_for_status()
                pago = pago_resp.json()
                pago_id = pago.get("pago_id")
                logger.info(f"Pago registrado: {pago_id}")
            except httpx.HTTPError as e:
                raise HTTPException(503, f"Error al registrar pago: {str(e)}")

            # ===== PASO 8: Vaciar carrito (ms3) =====
            logger.info("Paso 7: Vaciando carrito")
            try:
                await client.delete(
                    f"{self.ms3_url}/carrito/{request.cliente_id}"
                )
                logger.info("Carrito vaciado exitosamente")
            except httpx.HTTPError as e:
                logger.warning(f"No se pudo vaciar carrito: {str(e)}")

            # ===== RESPUESTA =====
            return CheckoutResponse(
                mensaje="Checkout completado exitosamente",
                pedido_id=pedido_id,
                pago_id=pago_id,
                total=total,
                items=[
                    ItemCarritoResponse(
                        producto_id=item["producto_id"],
                        cantidad=item["cantidad"],
                        precio_unitario=item["precio_unitario"],
                        producto_nombre=item["producto_nombre"]
                    )
                    for item in productos_validados
                ],
                estado_pedido="pendiente"
            )

    async def obtener_estado(self, pedido_id: int) -> Dict[str, Any]:
        """Obtiene el estado de un pedido"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.get(
                    f"{self.ms2_url}/pedidos/{pedido_id}"
                )
                resp.raise_for_status()
                data = resp.json()
                return {
                    "pedido_id": pedido_id,
                    "estado": data.get("estado"),
                    "fecha_pedido": data.get("fecha_pedido"),
                    "total": data.get("total")
                }
            except httpx.HTTPError as e:
                raise HTTPException(404, f"Pedido no encontrado: {str(e)}")

    async def obtener_historial(self, cliente_id: int) -> List[Dict[str, Any]]:
        """Obtiene el historial de pedidos de un cliente"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.get(
                    f"{self.ms2_url}/pedidos/cliente/{cliente_id}"
                )
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPError as e:
                raise HTTPException(503, f"Error al obtener historial: {str(e)}")