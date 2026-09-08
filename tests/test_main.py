"""
Pruebas unitarias para MS4 (Orquestador)
Responsable: Elias Alonso Usaqui Cabezas
"""

import pytest
from fastapi.testclient import TestClient
from httpx import Response
import respx

from src.main import app
from src.models import MetodoPago

# ========== CLIENTE DE PRUEBA ==========
client = TestClient(app)

# ========== DATOS DE PRUEBA ==========

CLIENTE_TEST = {
    "id": 1,
    "nombre": "Juan Perez",
    "email": "juan@email.com"
}

CARRITO_TEST = {
    "id_carrito": "carrito_1",
    "id_cliente": 1,
    "items": [
        {"producto_id": 1, "cantidad": 2},
        {"producto_id": 2, "cantidad": 1}
    ],
    "estado": "activo"
}

PRODUCTO_1 = {
    "id": 1,
    "nombre": "Laptop",
    "price": 1500.00,
    "stock_disponible": 10
}

PRODUCTO_2 = {
    "id": 2,
    "nombre": "Mouse",
    "price": 25.00,
    "stock_disponible": 5
}

INVENTARIO_1 = {"stock_disponible": 10, "stock_reservado": 0}
INVENTARIO_2 = {"stock_disponible": 5, "stock_reservado": 0}

PEDIDO_CREADO = {"pedido_id": 9999, "estado": "pendiente"}
PAGO_CREADO = {"pago_id": 8888, "estado_pago": "aprobado"}


# ========== PRUEBAS ==========

class TestCheckout:

    @pytest.mark.asyncio
    async def test_checkout_exitoso(self):
        """
        Prueba: Checkout exitoso con todos los pasos correctos
        """
        # Simular respuestas de los microservicios
        with respx.mock:
            # MS2 - Validar cliente
            ms2_cliente = respx.get("http://localhost:8081/cliente/1").mock(
                return_value=Response(200, json=CLIENTE_TEST)
            )

            # MS3 - Obtener carrito
            ms3_carrito = respx.get("http://localhost:8082/carrito/1").mock(
                return_value=Response(200, json=CARRITO_TEST)
            )

            # MS1 - Validar stock y obtener precio (producto 1)
            ms1_stock_1 = respx.get("http://localhost:8080/inventario/stock/1").mock(
                return_value=Response(200, json=INVENTARIO_1)
            )
            ms1_producto_1 = respx.get("http://localhost:8080/productos/1").mock(
                return_value=Response(200, json=PRODUCTO_1)
            )

            # MS1 - Validar stock y obtener precio (producto 2)
            ms1_stock_2 = respx.get("http://localhost:8080/inventario/stock/2").mock(
                return_value=Response(200, json=INVENTARIO_2)
            )
            ms1_producto_2 = respx.get("http://localhost:8080/productos/2").mock(
                return_value=Response(200, json=PRODUCTO_2)
            )

            # MS1 - Reservar stock (2 productos)
            ms1_reservar_1 = respx.patch("http://localhost:8080/inventario/stock/reservar").mock(
                return_value=Response(200, json={"exito": True})
            )
            ms1_reservar_2 = respx.patch("http://localhost:8080/inventario/stock/reservar").mock(
                return_value=Response(200, json={"exito": True})
            )

            # MS2 - Crear pedido
            ms2_pedido = respx.post("http://localhost:8081/pedidos").mock(
                return_value=Response(200, json=PEDIDO_CREADO)
            )

            # MS2 - Registrar pago
            ms2_pago = respx.post("http://localhost:8081/pagos").mock(
                return_value=Response(200, json=PAGO_CREADO)
            )

            # MS3 - Vaciar carrito
            ms3_delete = respx.delete("http://localhost:8082/carrito/1").mock(
                return_value=Response(200, json={"exito": True})
            )

            # Ejecutar checkout
            response = client.post(
                "/checkout",
                json={
                    "cliente_id": 1,
                    "direccion_envio": "Calle 123",
                    "metodo_pago": MetodoPago.TARJETA_CREDITO.value
                }
            )

            # Validar respuesta
            assert response.status_code == 200
            data = response.json()
            assert data["mensaje"] == "Checkout completado exitosamente"
            assert data["pedido_id"] == 9999
            assert data["pago_id"] == 8888
            assert data["total"] == 3569.5  # 3025 * 1.18 (18% de impuestos)            assert len(data["items"]) == 2

            # Verificar que se llamaron los endpoints correctos
            assert ms2_cliente.called
            assert ms3_carrito.called
            assert ms1_stock_1.called
            assert ms1_producto_1.called
            assert ms1_stock_2.called
            assert ms1_producto_2.called
            assert ms1_reservar_1.called
            assert ms1_reservar_2.called
            assert ms2_pedido.called
            assert ms2_pago.called
            assert ms3_delete.called

    @pytest.mark.asyncio
    async def test_checkout_cliente_no_existe(self):
        """
        Prueba: Cliente no existe (MS2 devuelve 404)
        """
        with respx.mock:
            # MS2 - Cliente no encontrado
            respx.get("http://localhost:8081/cliente/999").mock(
                return_value=Response(404, json={"detail": "Cliente no encontrado"})
            )

            response = client.post(
                "/checkout",
                json={
                    "cliente_id": 999,
                    "direccion_envio": "Calle 123",
                    "metodo_pago": MetodoPago.TARJETA_CREDITO.value
                }
            )

            assert response.status_code == 404
            assert "Cliente no encontrado" in response.text

    @pytest.mark.asyncio
    async def test_checkout_carrito_vacio(self):
        """
        Prueba: Carrito vacío (MS3 devuelve items vacíos)
        """
        with respx.mock:
            # MS2 - Cliente existe
            respx.get("http://localhost:8081/cliente/1").mock(
                return_value=Response(200, json=CLIENTE_TEST)
            )
            # MS3 - Carrito vacío
            respx.get("http://localhost:8082/carrito/1").mock(
                return_value=Response(200, json={"id_cliente": 1, "items": []})
            )

            response = client.post(
                "/checkout",
                json={
                    "cliente_id": 1,
                    "direccion_envio": "Calle 123",
                    "metodo_pago": MetodoPago.TARJETA_CREDITO.value
                }
            )

            assert response.status_code == 400
            assert "El carrito está vacío" in response.text

    @pytest.mark.asyncio
    async def test_checkout_stock_insuficiente(self):
        """
        Prueba: Stock insuficiente para un producto
        """
        with respx.mock:
            # MS2 - Cliente existe
            respx.get("http://localhost:8081/cliente/1").mock(
                return_value=Response(200, json=CLIENTE_TEST)
            )
            # MS3 - Carrito con items
            respx.get("http://localhost:8082/carrito/1").mock(
                return_value=Response(200, json=CARRITO_TEST)
            )
            # MS1 - Stock insuficiente para producto 1
            respx.get("http://localhost:8080/inventario/stock/1").mock(
                return_value=Response(200, json={"stock_disponible": 0})
            )

            response = client.post(
                "/checkout",
                json={
                    "cliente_id": 1,
                    "direccion_envio": "Calle 123",
                    "metodo_pago": MetodoPago.TARJETA_CREDITO.value
                }
            )

            assert response.status_code == 400
            assert "Stock insuficiente" in response.text

    @pytest.mark.asyncio
    async def test_health(self):
        """Prueba: Health check"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "ms-consultas"

    @pytest.mark.asyncio
    async def test_obtener_estado_pedido(self):
        """Prueba: Obtener estado de pedido"""
        with respx.mock:
            respx.get("http://localhost:8081/pedidos/9999").mock(
                return_value=Response(200, json={
                    "pedido_id": 9999,
                    "estado": "pagado",
                    "fecha_pedido": "2026-09-08",
                    "total": 3025.0
                })
            )

            response = client.get("/checkout/9999/estado")
            assert response.status_code == 200
            data = response.json()
            assert data["pedido_id"] == 9999
            assert data["estado"] == "pagado"

    @pytest.mark.asyncio
    async def test_obtener_historial_cliente(self):
        """Prueba: Obtener historial de pedidos de un cliente"""
        with respx.mock:
            respx.get("http://localhost:8081/pedidos/cliente/1").mock(
                return_value=Response(200, json=[
                    {"pedido_id": 9999, "total": 3025.0, "estado": "pagado"},
                    {"pedido_id": 9998, "total": 1500.0, "estado": "enviado"}
                ])
            )

            response = client.get("/checkout/usuario/1/pedidos")
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2
            assert data[0]["pedido_id"] == 9999