"""
Servicios de MS4 - Consumo de ms1, ms2, ms3
"""

import httpx
import logging
from typing import List, Dict, Any
from fastapi import HTTPException

from src.models import (
    CheckoutRequest, CheckoutResponse, ItemCarritoResponse,
    ReservarStockRequest, CrearPedidoRequest, CrearPagoRequest
)
from src.config import settings

logger = logging.getLogger(__name__)

class CheckoutService:
    """Servicio que orquesta el checkout"""

    def __init__(self):
        self.ms1_url = settings.MS1_URL
        self.ms2_url = settings.MS2_URL
        self.ms3_url = settings.MS3_URL
        self.timeout = settings.TIMEOUT

    async def _liberar_stock(self, client: httpx.AsyncClient, cliente_id: int,
                              items_reservados: List[Dict[str, Any]]) -> None:
        """Compensación: libera el stock ya reservado si un paso posterior falla."""
        for item in items_reservados:
            try:
                resp = await client.patch(
                    f"{self.ms1_url}/ms1/stock/liberar",
                    json={
                        "product_id": item["producto_id"],
                        "client_id": cliente_id,
                        "cantidad": item["cantidad"]
                    }
                )
                resp.raise_for_status()
            except httpx.HTTPError as e:
                # No relanzamos: estamos en medio de un rollback, solo logueamos
                # para que quede evidencia y alguien revise stock manualmente.
                logger.error(
                    f"ROLLBACK FALLIDO: no se pudo liberar stock de producto "
                    f"{item['producto_id']} (cantidad {item['cantidad']}): {str(e)}"
                )

    async def _cancelar_pedido(self, client: httpx.AsyncClient, pedido_id: int) -> None:
        """Compensación: marca el pedido como cancelado si el pago falla."""
        try:
            resp = await client.put(
                f"{self.ms2_url}/ms2/pedidos/{pedido_id}",
                json={"estado": "cancelado"}
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(f"ROLLBACK FALLIDO: no se pudo cancelar pedido {pedido_id}: {str(e)}")

    async def procesar(self, request: CheckoutRequest) -> CheckoutResponse:
        """Procesa el checkout completo"""

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # ===== PASO 1: Validar cliente (ms2) =====
            logger.info("Paso 1: Validando cliente")
            try:
                cliente_resp = await client.get(
                    f"{self.ms2_url}/ms2/clientes/{request.cliente_id}"
                )
                cliente_resp.raise_for_status()
                cliente = cliente_resp.json()
                logger.info(f"Cliente validado: {cliente.get('nombre')}")
            except httpx.HTTPError as e:
                raise HTTPException(404, f"Cliente no encontrado: {str(e)}")

            # ===== PASO 2: Obtener carrito (ms3) =====
            # Ruta real: GET /api/carritos/cliente/{clienteId} (CarritoController.java)
            # Confirmado por Carrito.java: el campo del id del carrito es "id" (String, Mongo ObjectId).
            logger.info("Paso 2: Obteniendo carrito")
            try:
                carrito_resp = await client.get(
                    f"{self.ms3_url}/api/carritos/cliente/{request.cliente_id}"
                )
                carrito_resp.raise_for_status()
                carrito = carrito_resp.json()
                carrito_id = carrito.get("id")
                items = carrito.get("items", [])
                if not items:
                    raise HTTPException(400, "El carrito está vacío")
                logger.info(f"Carrito tiene {len(items)} items")
            except httpx.HTTPError as e:
                raise HTTPException(503, f"Error al leer carrito: {str(e)}")

            # ===== PASO 3: Validar stock y precio (ms1) =====
            logger.info("Paso 3: Validando stock")
            productos_validados = []
            for item in items:
                # ms3 usa camelCase (confirmado por ItemCarrito.java: idProducto, cantidad)
                producto_id = item["idProducto"]
                cantidad = item["cantidad"]

                try:
                    stock_resp = await client.get(
                        f"{self.ms1_url}/ms1/stock/available",
                        params={"product_id": producto_id, "client_id": request.cliente_id}
                    )
                    stock_resp.raise_for_status()
                    stock_data = stock_resp.json()
                    stock_disponible = stock_data.get("available_stock", 0)
                    if stock_disponible < cantidad:
                        raise HTTPException(
                            400,
                            f"Stock insuficiente para producto {producto_id}"
                        )

                    prod_resp = await client.get(
                        f"{self.ms1_url}/ms1/products/{producto_id}"
                    )
                    prod_resp.raise_for_status()
                    prod_data = prod_resp.json()

                    productos_validados.append({
                        "producto_id": producto_id,
                        "cantidad": cantidad,
                        "precio_unitario": float(prod_data.get("price", 0)),
                        "producto_nombre": prod_data.get("name", "Producto")
                    })
                except httpx.HTTPError as e:
                    raise HTTPException(503, f"Error al validar producto {producto_id}: {str(e)}")

            # ===== PASO 4: Reservar stock (ms1) =====
            # Reserva uno por uno y va llevando registro de lo ya reservado (stock_reservado)
            # para poder liberarlo si algo falla mas adelante (pedido, detalle o pago).
            logger.info("Paso 4: Reservando stock")
            stock_reservado: List[Dict[str, Any]] = []
            try:
                for item in productos_validados:
                    reservar_resp = await client.patch(
                        f"{self.ms1_url}/ms1/stock/reservar",
                        json={
                            "product_id": item["producto_id"],
                            "client_id": request.cliente_id,
                            "cantidad": item["cantidad"]
                        }
                    )
                    reservar_resp.raise_for_status()
                    reservar_data = reservar_resp.json()
                    if not reservar_data.get("exito", False):
                        raise HTTPException(
                            400,
                            f"No se pudo reservar stock para producto {item['producto_id']}"
                        )
                    stock_reservado.append(item)
                logger.info("Stock reservado exitosamente")
            except httpx.HTTPError as e:
                await self._liberar_stock(client, request.cliente_id, stock_reservado)
                raise HTTPException(503, f"Error al reservar stock: {str(e)}")
            except HTTPException:
                # Ej: 409 de stock insuficiente durante la reserva -> liberar lo ya reservado
                await self._liberar_stock(client, request.cliente_id, stock_reservado)
                raise

            # A partir de aqui, si CUALQUIER paso falla, hay que liberar stock_reservado.
            try:
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
                        "subtotal": subtotal,
                        "impuestos": impuestos,
                        "total": total,
                        "direccion_envio": request.direccion_envio,
                        "metodo_pago": request.metodo_pago.value
                    }
                    pedido_resp = await client.post(
                        f"{self.ms2_url}/ms2/pedidos",
                        json=pedido_data
                    )
                    pedido_resp.raise_for_status()
                    pedido = pedido_resp.json()
                    pedido_id = pedido.get("id")
                    logger.info(f"Pedido creado: {pedido_id}")
                except httpx.HTTPError as e:
                    raise HTTPException(503, f"Error al crear pedido: {str(e)}")

                # ===== PASO 6.5: Crear detalle de pedido (ms2) =====
                logger.info("Paso 5.5: Creando detalle de pedido")
                try:
                    for item in productos_validados:
                        detalle_resp = await client.post(
                            f"{self.ms2_url}/ms2/detalle-pedido",
                            json={
                                "pedido_id": pedido_id,
                                "producto_id": item["producto_id"],
                                "producto_nombre": item["producto_nombre"],
                                "precio_unitario": item["precio_unitario"],
                                "cantidad": item["cantidad"],
                                "subtotal": item["precio_unitario"] * item["cantidad"]
                            }
                        )
                        detalle_resp.raise_for_status()
                except httpx.HTTPError as e:
                    # El pedido ya existe pero sin detalle completo -> cancelarlo
                    await self._cancelar_pedido(client, pedido_id)
                    raise HTTPException(503, f"Error al crear detalle de pedido: {str(e)}")

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
                        f"{self.ms2_url}/ms2/pagos",
                        json=pago_data
                    )
                    pago_resp.raise_for_status()
                    pago = pago_resp.json()
                    pago_id = pago.get("id")
                    logger.info(f"Pago registrado: {pago_id}")
                except httpx.HTTPError as e:
                    # El pedido quedo creado pero sin pago -> cancelarlo
                    await self._cancelar_pedido(client, pedido_id)
                    raise HTTPException(503, f"Error al registrar pago: {str(e)}")

            except HTTPException:
                # Cualquier fallo desde el Paso 5 en adelante libera el stock reservado
                await self._liberar_stock(client, request.cliente_id, stock_reservado)
                raise

            # ===== PASO 8: Vaciar carrito (ms3) =====
            # Si esto falla no hacemos rollback: el pedido y el pago ya son validos,
            # solo queda un carrito con items ya comprados (inconveniente, no critico).
            logger.info("Paso 7: Vaciando carrito")
            try:
                if carrito_id:
                    await client.delete(
                        f"{self.ms3_url}/api/carritos/{carrito_id}/items"
                    )
                    logger.info("Carrito vaciado exitosamente")
                else:
                    logger.warning("No se pudo vaciar carrito: no se obtuvo el id del carrito")
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
        # Ruta coincide con pedidoController.obtenerPorId (GET /pedidos/:id) asumiendo
        # que /pedidos es la raiz real del router.
        # TODO CONFIRMAR: nombres exactos de columnas del modelo Pedido -> asumo
        # "estado", "fecha_pedido", "total" tal cual, pero no vi ese modelo.
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.get(
                    f"{self.ms2_url}/ms2/pedidos/{pedido_id}"
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
        # TODO CONFIRMAR: pedidoRoutes.js no fue compartido; asumo que la ruta interna
        # bajo /ms2/pedidos es "/cliente/:clienteId" siguiendo el nombre del metodo
        # pedidoController.listarPorCliente.
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.get(
                    f"{self.ms2_url}/ms2/pedidos/cliente/{cliente_id}"
                )
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPError as e:
                raise HTTPException(503, f"Error al obtener historial: {str(e)}")

    # ===== ENDPOINTS PROXY: stock / pedidos / pagos =====
    # A diferencia de procesar(), estos métodos NO orquestan nada ni hacen
    # rollback: son llamadas directas y puntuales a ms1/ms2, pensadas para
    # usarse fuera del flujo completo de checkout.

    async def reservar_stock(self, request: ReservarStockRequest) -> Dict[str, Any]:
        """Reserva stock de un producto para un cliente (proxy a ms1)."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.patch(
                    f"{self.ms1_url}/ms1/stock/reservar",
                    json={
                        "product_id": request.producto_id,
                        "client_id": request.cliente_id,
                        "cantidad": request.cantidad
                    }
                )
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                # ms1 respondió con un error de negocio (ej. 409 stock insuficiente):
                # se lo propagamos al cliente tal cual, no es un error de red.
                raise HTTPException(
                    e.response.status_code,
                    f"No se pudo reservar stock: {e.response.text}"
                )
            except httpx.HTTPError as e:
                raise HTTPException(503, f"Error al reservar stock: {str(e)}")

    async def crear_pedido(self, request: CrearPedidoRequest) -> Dict[str, Any]:
        """Crea un pedido directamente (proxy a ms2)."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(
                    f"{self.ms2_url}/ms2/pedidos",
                    json={
                        "cliente_id": request.cliente_id,
                        "subtotal": request.subtotal,
                        "impuestos": request.impuestos,
                        "total": request.total,
                        "direccion_envio": request.direccion_envio,
                        "metodo_pago": request.metodo_pago.value
                    }
                )
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                # ms2 respondió 400 (ej. validación de Sequelize) -> se propaga tal cual
                raise HTTPException(
                    e.response.status_code,
                    f"No se pudo crear el pedido: {e.response.text}"
                )
            except httpx.HTTPError as e:
                raise HTTPException(503, f"Error al crear pedido: {str(e)}")

    async def registrar_pago(self, request: CrearPagoRequest) -> Dict[str, Any]:
        """Registra un pago directamente (proxy a ms2)."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(
                    f"{self.ms2_url}/ms2/pagos",
                    json={
                        "pedido_id": request.pedido_id,
                        "monto": request.monto,
                        "metodo_pago": request.metodo_pago.value,
                        "estado_pago": request.estado_pago.value
                    }
                )
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                raise HTTPException(
                    e.response.status_code,
                    f"No se pudo registrar el pago: {e.response.text}"
                )
            except httpx.HTTPError as e:
                raise HTTPException(503, f"Error al registrar pago: {str(e)}")
