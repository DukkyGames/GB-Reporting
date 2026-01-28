from __future__ import annotations

import os
import time
from datetime import date, datetime, time as dt_time, timedelta, timezone
from typing import Any, Dict, List

import requests
from requests.auth import HTTPBasicAuth
from zeep import Client, Settings
from zeep.exceptions import Fault
from zeep.helpers import serialize_object
from zeep.transports import Transport


US_BASE = "https://webservices.vin65.com"
AU_BASE = "https://webservices.aus.vin65.com"


class TrackingTransport(Transport):
    def __init__(self, *args, on_response=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._on_response = on_response

    def post(self, address, message, headers):
        response = super().post(address, message, headers)
        if self._on_response is not None:
            self._on_response(response)
        return response

    def get(self, address, params, headers):
        response = super().get(address, params, headers)
        if self._on_response is not None:
            self._on_response(response)
        return response


class WineDirectClient:
    def __init__(self, username: str, password: str, region: str = "us", version: str = "v3") -> None:
        self.username = username
        self.password = password
        self.region = region.lower()
        self.version = version.lower()
        self.rate_limit: Dict[str, str] = {}

        base = US_BASE if self.region in ("us", "usa") else AU_BASE
        if self.version in ("v304",):
            order_version = "V304"
        elif self.version in ("v3", "v301"):
            order_version = "V301"
        else:
            order_version = "V300"
        product_version = "V300"
        inventory_version = "V300"

        self.order_wsdl = f"{base}/{order_version}/OrderService.cfc?wsdl"
        self.product_wsdl = f"{base}/{product_version}/ProductService.cfc?wsdl"
        self.inventory_wsdl = f"{base}/{inventory_version}/InventoryService.cfc?wsdl"

        session = requests.Session()
        session.auth = HTTPBasicAuth(self.username, self.password)
        transport = TrackingTransport(session=session, timeout=60, on_response=self._capture_rate_limit)

        settings = Settings(strict=False, xml_huge_tree=True)
        self.order_client = Client(self.order_wsdl, transport=transport, settings=settings)
        self.product_client = Client(self.product_wsdl, transport=transport, settings=settings)
        self.inventory_client = Client(self.inventory_wsdl, transport=transport, settings=settings)

    def _capture_rate_limit(self, response) -> None:
        headers = getattr(response, "headers", {}) or {}
        limit = headers.get("x-rate-limit-limit")
        remaining = headers.get("x-rate-limit-remaining")
        reset = headers.get("x-rate-limit-reset")
        if limit is not None:
            self.rate_limit["limit"] = str(limit)
        if remaining is not None:
            self.rate_limit["remaining"] = str(remaining)
        if reset is not None:
            self.rate_limit["reset"] = str(reset)

    @classmethod
    def from_env(cls) -> "WineDirectClient":
        username = os.environ.get("WINE_USERNAME", "")
        password = os.environ.get("WINE_PASSWORD", "")
        region = os.environ.get("WINE_REGION", "us")
        version = os.environ.get("WINE_VERSION", "v3")
        if not username or not password:
            raise RuntimeError("Missing WINE_USERNAME or WINE_PASSWORD env vars")
        return cls(username, password, region, version)

    def fetch_orders(
        self,
        start_date: date,
        end_date: date,
        progress_cb=None,
    ) -> List[Dict[str, Any]]:
        orders: List[Dict[str, Any]] = []
        raw_orders: List[Dict[str, Any]] = []
        page = 1
        max_rows = 200
        fetch_detail = os.environ.get("WINE_FETCH_ORDER_DETAIL", "0") == "1"
        detail_budget = os.environ.get("WINE_ORDER_DETAIL_MAX", "").strip()
        max_detail = int(detail_budget) if detail_budget.isdigit() else None
        detail_count = 0
        wait_on_rate_limit = os.environ.get("WINE_RATE_LIMIT_WAIT", "0") == "1"
        rate_check_interval = 5
        detail_queue: List[tuple[int, str, float | None]] = []

        def _ensure_rate_limit() -> None:
            remaining = self.rate_limit.get("remaining")
            if remaining is None:
                return
            try:
                if int(remaining) > 0:
                    return
            except ValueError:
                return
            if wait_on_rate_limit:
                while True:
                    try:
                        self.rate_limit_check()
                    except Exception:
                        pass
                    new_remaining = self.rate_limit.get("remaining")
                    try:
                        if new_remaining is not None and int(new_remaining) > 0:
                            break
                    except ValueError:
                        pass
                    time.sleep(rate_check_interval)
            else:
                raise RuntimeError("Rate limit exhausted before next page request.")
        while True:
            _ensure_rate_limit()
            response = self._search_orders(start_date, end_date, page, max_rows)
            order_rows = response.get("Orders") or response.get("Order") or []
            if isinstance(order_rows, dict):
                order_rows = [order_rows]

            for order in order_rows:
                order_id = str(order.get("OrderID") or order.get("OrderId") or "")
                order_number = order.get("OrderNumber") or order.get("OrderNumberLong")
                if isinstance(order_number, str):
                    try:
                        order_number = float(order_number)
                    except ValueError:
                        order_number = None
                if not order_id:
                    continue
                raw_orders.append(order)
                orders.append(self._normalize_order(order, {}))
                detail_queue.append((len(orders) - 1, order_id, order_number))

            total_candidates = (
                response.get("Total"),
                response.get("TotalRows"),
                response.get("RecordCount"),
                response.get("TotalRecordCount"),
            )
            total = next((int(value) for value in total_candidates if value not in (None, "")), 0)
            if progress_cb is not None:
                try:
                    progress_cb(page, len(orders), total)
                except Exception:
                    pass
            if not order_rows:
                break
            if total > 0 and len(orders) >= total:
                break
            if total == 0 and len(order_rows) < max_rows:
                break
            page += 1

        if fetch_detail:
            for idx, order_id, order_number in detail_queue:
                if max_detail is not None and detail_count >= max_detail:
                    break
                _ensure_rate_limit()
                try:
                    detail = self._get_order_detail(order_id, order_number)
                except Exception as exc:
                    print(f"Order detail fetch failed for {order_id}: {exc}")
                    continue
                orders[idx] = self._normalize_order(raw_orders[idx], detail)
                detail_count += 1
        return orders

    def fetch_orders_chunked(self, start_date: date, end_date: date, chunk_days: int = 30) -> List[Dict[str, Any]]:
        orders: List[Dict[str, Any]] = []
        if end_date < start_date:
            return orders

        stack: List[tuple[date, date]] = []
        if chunk_days and chunk_days > 0:
            cursor = start_date
            while cursor <= end_date:
                chunk_end = min(cursor + timedelta(days=chunk_days - 1), end_date)
                stack.append((cursor, chunk_end))
                cursor = chunk_end + timedelta(days=1)
        else:
            stack.append((start_date, end_date))

        while stack:
            current_start, current_end = stack.pop(0)
            try:
                orders.extend(self.fetch_orders(current_start, current_end))
            except Exception as exc:
                span_days = (current_end - current_start).days
                if span_days <= 0:
                    print(f"Order search failed for {current_start}: {exc}")
                    continue
                mid = current_start + timedelta(days=span_days // 2)
                if mid < current_end:
                    stack.append((current_start, mid))
                    stack.append((mid + timedelta(days=1), current_end))
                else:
                    print(f"Order search failed for {current_start} to {current_end}: {exc}")
        return orders

    def rate_limit_check(self) -> None:
        today = datetime.now(timezone.utc).date()
        # Minimal request to capture rate-limit headers.
        self._search_orders(today, today, page=1, max_rows=1)

    def fetch_products(self) -> List[Dict[str, Any]]:
        products: List[Dict[str, Any]] = []
        page = 1
        max_rows = 500
        while True:
            response = self._search_products(page=page, max_rows=max_rows)
            product_rows = self._extract_products(response)
            products.extend(product_rows)

            total_candidates = (
                response.get("Total"),
                response.get("TotalRows"),
                response.get("RecordCount"),
                response.get("TotalRecordCount"),
            )
            total = next((int(value) for value in total_candidates if value not in (None, "")), 0)
            if not product_rows:
                break
            if total > 0 and len(products) >= total:
                break
            if total == 0 and len(product_rows) < max_rows:
                break
            page += 1

        normalized = []
        for product in products:
            normalized.append(
                {
                    "product_id": str(product.get("ProductID") or product.get("ProductId") or ""),
                    "sku": product.get("SKU") or product.get("Sku") or "",
                    "name": product.get("ProductName") or product.get("Name") or "",
                    "last_updated": product.get("LastModified") or "",
                }
            )
        return normalized

    def fetch_inventory(self) -> List[Dict[str, Any]]:
        inventory: List[Dict[str, Any]] = []
        page = 1
        max_rows = 100
        filter_value = os.environ.get("WINE_INVENTORY_FILTER", "OnlySKUsWithInventoryOn")

        while True:
            response = self._search_inventory(page=page, max_rows=max_rows, filter_value=filter_value)
            rows = self._extract_inventory(response)
            inventory.extend(rows)

            total_candidates = (
                response.get("Total"),
                response.get("TotalRows"),
                response.get("RecordCount"),
                response.get("TotalRecordCount"),
            )
            total = next((int(value) for value in total_candidates if value not in (None, "")), 0)
            if not rows:
                break
            if total > 0 and len(inventory) >= total:
                break
            if total == 0 and len(rows) < max_rows:
                break
            page += 1

        normalized = []
        for row in inventory:
            normalized.append(
                {
                    "sku": row.get("SKU") or row.get("Sku") or "",
                    "inventory_pool": row.get("InventoryPool") or "",
                    "inventory_pool_id": row.get("InventoryPoolID") or row.get("InventoryPoolId") or "",
                    "website_id": row.get("WebsiteID") or row.get("WebsiteId") or "",
                    "current_inventory": self._safe_float(row.get("CurrentInventory") or 0),
                    "raw_json": row,
                }
            )
        return normalized

    def _security(self) -> Dict[str, str]:
        return {"Username": self.username, "Password": self.password}

    def _website_ids(self) -> str | None:
        value = os.environ.get("WINE_WEBSITE_IDS") or os.environ.get("WINE_WEBSITE_ID")
        if not value:
            return None
        return value.strip()

    def _date_payload(self, start_date: date, end_date: date) -> Dict[str, str]:
        start_dt = datetime.combine(start_date, dt_time.min)
        end_dt = datetime.combine(end_date, dt_time.max)
        return {
            "DateCompletedFrom": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "DateCompletedTo": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        }

    def _search_orders(self, start_date: date, end_date: date, page: int, max_rows: int) -> Dict[str, Any]:
        request = {
            "Security": self._security(),
            "OrderStatus": "Completed",
            "Page": page,
            "MaxRows": max_rows,
            **self._date_payload(start_date, end_date),
        }
        website_ids = self._website_ids()
        if website_ids:
            request["WebsiteIDs"] = website_ids
        result = self.order_client.service.SearchOrders(Request=request)
        return serialize_object(result) or {}

    def _get_order_detail(self, order_id: str, order_number: float | None) -> Dict[str, Any]:
        attempts: List[Dict[str, Any]] = []
        if order_number is not None:
            attempts.append({"OrderNumber": order_number})
        if order_id:
            attempts.append({"OrderID": order_id})

        last_exc: Exception | None = None
        for payload in attempts:
            request = {
                "Security": self._security(),
                "ShowKitAsIndividualSKUs": True,
                **payload,
            }
            website_id = self._website_ids()
            if website_id:
                request["WebsiteID"] = website_id
            try:
                result = self.order_client.service.GetOrderDetail(Request=request)
                return serialize_object(result) or {}
            except Fault as exc:
                last_exc = exc
                continue
        if last_exc:
            raise last_exc
        return {}

    def _search_products(self, page: int = 1, max_rows: int = 500) -> Dict[str, Any]:
        today = datetime.now(timezone.utc).date()
        modified_from = (today - timedelta(days=3650)).strftime("%Y-%m-%dT%H:%M:%S")
        modified_to = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

        attempts = [
            {"IsActive": True, "DateModifiedFrom": modified_from, "DateModifiedTo": modified_to},
            {"DateModifiedFrom": modified_from, "DateModifiedTo": modified_to},
            {"IsActive": True},
            {},
        ]
        last_exc: Exception | None = None
        for payload in attempts:
            request = {
                "Security": self._security(),
                "MaxRows": max_rows,
                "Page": page,
                **payload,
            }
            website_ids = self._website_ids()
            if website_ids:
                request["WebsiteIDs"] = website_ids
            try:
                result = self.product_client.service.SearchProducts(Request=request)
                return serialize_object(result) or {}
            except Fault as exc:
                last_exc = exc
                continue
        if last_exc:
            raise last_exc
        return {}

    @staticmethod
    def _extract_products(response: Dict[str, Any]) -> List[Dict[str, Any]]:
        products = response.get("Products") or response.get("Product") or []
        if isinstance(products, dict):
            if "Products" in products:
                products = products["Products"]
        if isinstance(products, dict):
            products = [products]
        return products or []

    def _search_inventory(self, page: int = 1, max_rows: int = 100, filter_value: str = "OnlySKUsWithInventoryOn") -> Dict[str, Any]:
        request = {
            "Security": self._security(),
            "MaxRows": max_rows,
            "Page": page,
            "Filter": filter_value,
        }
        website_ids = self._website_ids()
        if website_ids:
            request["WebsiteIDs"] = website_ids
        result = self.inventory_client.service.SearchInventory(Request=request)
        return serialize_object(result) or {}

    @staticmethod
    def _extract_inventory(response: Dict[str, Any]) -> List[Dict[str, Any]]:
        inventory = response.get("Inventory") or []
        if isinstance(inventory, dict) and "Inventory" in inventory:
            inventory = inventory["Inventory"]
        if isinstance(inventory, dict):
            inventory = [inventory]
        return inventory or []

    def _normalize_order(self, order: Dict[str, Any], detail: Dict[str, Any]) -> Dict[str, Any]:
        order_info = detail.get("Order") or detail.get("OrderDetail") or detail
        bill_contact = order_info.get("BillContact") or {}
        ship_to = order_info.get("ShipToAddress") or {}
        items = self._extract_items(order_info)

        units = sum(item.get("quantity", 0) for item in items)
        net_sales = 0.0

        def _get(key: str, fallback: Any = 0):
            return order_info.get(key, order.get(key, fallback))

        total = self._safe_float(_get("Total") or _get("OrderTotal") or 0)
        taxes = self._safe_float(_get("Tax") or _get("TaxTotal") or _get("OrderTax") or 0)
        shipping = self._safe_float(_get("Shipping") or _get("ShippingTotal") or 0)
        tip = self._safe_float(_get("Tip") or 0)
        net_sales = max(total - taxes - shipping - tip, 0)

        return {
            "order_id": str(_get("OrderID", order.get("OrderID")) or ""),
            "order_number": str(_get("OrderNumber", order.get("OrderNumber")) or ""),
            "completed_date": self._safe_date(_get("DateCompleted") or _get("CompletedDate") or ""),
            "submitted_date": self._safe_date(_get("DateSubmitted") or _get("SubmittedDate") or ""),
            "date_modified": self._safe_date(_get("DateModified") or ""),
            "shipped_date": self._safe_date(_get("DateShipped") or _get("ShippedDate") or ""),
            "order_type": _get("Type") or _get("OrderType") or _get("OrderSource") or "Unknown",
            "order_status": _get("OrderStatus") or "",
            "ship_state": _get("ShipStateCode") or _get("ShippingState") or "Unknown",
            "customer_id": str(_get("ContactID") or _get("CustomerID") or _get("CustomerNumber") or ""),
            "bill_first_name": _get("BillFirstName") or "",
            "bill_last_name": _get("BillLastName") or "",
            "ship_first_name": _get("ShipFirstName") or "",
            "ship_last_name": _get("ShipLastName") or "",
            "bill_address": bill_contact.get("Address") or "",
            "bill_address2": bill_contact.get("Address2") or "",
            "bill_city": bill_contact.get("City") or "",
            "bill_state": bill_contact.get("StateCode") or "",
            "bill_zip": bill_contact.get("ZipCode") or "",
            "bill_country": bill_contact.get("CountryCode") or "",
            "bill_email": bill_contact.get("Email") or "",
            "bill_phone": bill_contact.get("Phone") or "",
            "ship_address": ship_to.get("Address") or "",
            "ship_address2": ship_to.get("Address2") or "",
            "ship_city": ship_to.get("City") or "",
            "ship_state_code": ship_to.get("StateCode") or "",
            "ship_zip": ship_to.get("ZipCode") or "",
            "ship_country": ship_to.get("CountryCode") or "",
            "ship_email": ship_to.get("Email") or "",
            "ship_phone": ship_to.get("Phone") or "",
            "gift_message": _get("GiftMessage") or "",
            "order_notes": _get("OrderNotes") or "",
            "payment_status": _get("PaymentStatus") or "",
            "shipping_status": _get("ShippingStatus") or "",
            "shipping_type": _get("ShippingType") or "",
            "tracking_number": _get("TrackingNumber") or "",
            "website_id": _get("WebsiteID") or "",
            "is_external_order": str(_get("IsExternalOrder") or "").lower() in ("true", "1", "yes"),
            "is_pending_pickup": str(_get("IsPendingPickup") or "").lower() in ("true", "1", "yes"),
            "is_arms_order": str(_get("IsARMSOrder") or "").lower() in ("true", "1", "yes"),
            "pickup": str(_get("IsAPickupOrder") or _get("Pickup") or "").lower() in ("yes", "true", "1"),
            "order_number_long": _get("OrderNumberLong") or "",
            "pickup_date": self._safe_date(_get("PickupDate") or ""),
            "pickup_location_code": _get("PickupLocationCode") or "",
            "payment_terms": _get("PaymentTerms") or "",
            "price_level": _get("PriceLevel") or "",
            "sales_associate": _get("SalesAssociate") or "",
            "sales_attribute": _get("SalesAttribute") or "",
            "transaction_type": _get("TransactionType") or "",
            "source_code": _get("SourceCode") or "",
            "wholesale_number": _get("WholesaleNumber") or "",
            "requested_delivery_date": self._safe_date(_get("RequestedDeliveryDate") or ""),
            "requested_ship_date": self._safe_date(_get("RequestedShipDate") or ""),
            "sent_to_fulfillment_date": self._safe_date(_get("SentToFulfillmentDate") or ""),
            "future_ship_date": self._safe_date(_get("FutureShipDate") or ""),
            "marketplace": _get("Marketplace") or "",
            "order_total": total,
            "taxes": taxes,
            "shipping_paid": self._safe_float(_get("ShippingTotal") or _get("Shipping") or 0),
            "shipping": shipping,
            "sub_total": self._safe_float(_get("SubTotal") or 0),
            "tip": tip,
            "total": total,
            "total_after_tip": self._safe_float(_get("TotalAfterTip") or 0),
            "net_sales": net_sales,
            "units": units,
            "items": items,
            "raw_json": order_info,
        }

    def _extract_items(self, order_info: Dict[str, Any]) -> List[Dict[str, Any]]:
        for key in ("OrderItems", "Items", "OrderItem"):
            if key in order_info:
                items = order_info[key]
                if isinstance(items, dict) and "OrderItem" in items:
                    items = items["OrderItem"]
                if isinstance(items, dict):
                    items = [items]
                return [self._normalize_item(item) for item in items]
        return []

    def _normalize_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "sku": item.get("SKU") or item.get("ProductSKU") or item.get("Sku") or "",
            "name": item.get("ProductName") or item.get("Name") or "",
            "quantity": self._safe_float(item.get("Quantity") or item.get("Qty") or 0),
            "net_sales": self._safe_float(item.get("ExtItemPrice") or item.get("ExtendedPrice") or item.get("Price") or 0),
            "product_id": item.get("ProductID") or "",
            "product_skuid": item.get("ProductSKUID") or "",
            "price": self._safe_float(item.get("Price") or 0),
            "original_price": self._safe_float(item.get("OriginalPrice") or 0),
            "department": item.get("Department") or "",
            "department_code": item.get("DepartmentCode") or "",
            "inventory_pool": item.get("InventoryPool") or "",
            "is_non_taxable": str(item.get("IsNonTaxable") or "").lower() in ("true", "1", "yes"),
            "is_subsku": str(item.get("IsSubSKU") or "").lower() in ("true", "1", "yes"),
            "sales_tax": self._safe_float(item.get("SalesTax") or 0),
            "shipping_sku": item.get("ShippingSKU") or "",
            "shipping_service": item.get("ShippingService") or "",
            "sub_department": item.get("SubDepartment") or "",
            "sub_department_code": item.get("SubDepartmentCode") or "",
            "subtitle": item.get("SubTitle") or "",
            "title": item.get("Title") or "",
            "item_type": item.get("Type") or "",
            "unit_description": item.get("UnitDescription") or "",
            "weight": self._safe_float(item.get("Weight") or 0),
            "cost_of_good": self._safe_float(item.get("CostOfGood") or 0),
            "custom_tax1": self._safe_float(item.get("CustomTax1") or 0),
            "custom_tax2": self._safe_float(item.get("CustomTax2") or 0),
            "custom_tax3": self._safe_float(item.get("CustomTax3") or 0),
            "parent_sku": item.get("ParentSKU") or "",
            "parent_skuid": item.get("ParentSKUID") or "",
            "shipped_date": self._safe_date(item.get("ShippedDate") or ""),
            "tracking_number": item.get("TrackingNumber") or "",
            "raw_json": item,
        }

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _safe_date(value: Any) -> str:
        if not value:
            return ""
        text = str(value).strip()
        # Normalize common ISO-like formats to date-only strings.
        try:
            iso_text = text.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso_text)
            return dt.date().isoformat()
        except ValueError:
            pass

        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y"):
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except ValueError:
                continue

        for sep in ("T", " "):
            if sep in text:
                return text.split(sep)[0]
        return text

