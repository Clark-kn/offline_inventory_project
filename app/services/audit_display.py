import re


ACTION_LABELS = {
    "login_success": "Logged in",
    "login_failed": "Failed login attempt",
    "user_created": "Created a user account",
    "user_status_changed": "Changed a user account status",
    "user_role_changed": "Changed a user's role",
    "password_changed": "Changed an account password",
    "reference_created": "Added a reference item",
    "reference_renamed": "Renamed a reference item",
    "reference_status_changed": "Changed a reference item's status",
    "supplier_created": "Added a supplier",
    "supplier_updated": "Updated supplier information",
    "supplier_status_changed": "Changed a supplier's status",
    "customer_created": "Added a customer",
    "customer_updated": "Updated customer information",
    "customer_status_changed": "Changed a customer's status",
    "product_created": "Added a product",
    "product_price_set": "Set a product selling price",
    "product_price_changed": "Changed a product selling price",
    "product_updated": "Updated product information",
    "product_status_changed": "Changed a product's status",
    "purchase_created": "Recorded a purchase",
    "sale_created": "Recorded a sale",
    "stock_adjustment": "Adjusted stock",
    "purchase_order_created": "Created a purchase order",
    "purchase_order_line_received": "Received items against a purchase order",
    "purchase_order_receipt_recorded": "Recorded goods received",
    "purchase_order_quantity_closed": "Closed part of a purchase order",
    "purchase_order_outstanding_closed": "Closed outstanding order quantities",
    "damaged_good_deleted": "Deleted a damaged-goods record",
    "auto_backup": "Automatic backup completed",
}


FIELD_LABELS = {
    "id": "Record number",
    "sku": "Product code",
    "name": "Name",
    "username": "Account username",
    "role": "User role",
    "is_active": "Account or item status",
    "user_id": "User record number",
    "purchase_id": "Purchase record number",
    "sale_id": "Sale record number",
    "reference": "Reference",
    "lines": "Number of order lines",
    "quantity": "Quantity",
    "supplier": "Supplier",
    "unit": "Unit",
    "date_brought": "Date brought in",
    "recorded_by_user_id": "Originally recorded by user number",
    "recorded_at": "Original recording time",
    "deleted_by": "Deleted by",
    "old_price": "Previous selling price",
    "new_price": "New selling price",
    "old_name": "Previous name",
    "new_name": "New name",
    "changed_fields": "Information changed",
    "product_id": "Product record number",
    "delta": "Stock change",
    "reason": "Reason",
    "po_id": "Purchase order number",
    "receipt_id": "Receipt number",
    "item_id": "Product record number",
    "closure_id": "Closure record number",
    "closure_item_id": "Closure item number",
    "reason_code": "Closure reason",
    "created_by": "Created by user number",
    "closed_by": "Closed by user number",
    "user_id": "User record number",
}


def parse_audit_details(details):
    """Parse key=value audit details without splitting values containing spaces."""
    if not details:
        return {}

    matches = list(re.finditer(r"(?<!\S)([A-Za-z_][A-Za-z0-9_]*)=", details))
    if not matches:
        return {}

    parsed = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(details)
        parsed[match.group(1)] = details[start:end].strip()

    return parsed


def audit_action_label(action):
    if action in ACTION_LABELS:
        return ACTION_LABELS[action]

    return (action or "other_activity").replace("_", " ").strip().capitalize()


def _display_value(key, value):
    if key == "is_active":
        return "Active" if value.lower() == "true" else "Inactive" if value.lower() == "false" else value

    if key == "role":
        return {
            "admin": "Administrator",
            "manager": "Manager",
            "operator": "Operator",
            "viewer": "Viewer",
        }.get(value.lower(), value)

    if key in {"old_price", "new_price"}:
        return f"{value} RWF"

    if key == "date_brought":
        return value[:10] if len(value) >= 10 else value

    return value


def _format_quantity_unit(quantity, unit):
    unit = (unit or "unit").strip()
    unit = re.sub(r"\(s\)$", "", unit, flags=re.IGNORECASE).strip().lower()

    try:
        singular = float(quantity) == 1
    except (TypeError, ValueError):
        singular = False

    if singular:
        unit = unit[:-1] if unit.endswith("s") else unit
    elif not unit.endswith("s"):
        unit += "s"

    return f"{quantity} {unit}"


def format_audit_summary(action, details):
    data = parse_audit_details(details)
    label = audit_action_label(action)

    if action == "login_success":
        return f"Account: {data.get('username', 'unknown')}"

    if action == "login_failed":
        return f"Login attempt for account: {data.get('username', 'unknown')}"

    if action == "user_created":
        role = _display_value("role", data.get("role", ""))
        return f"Account: {data.get('username', 'unknown')}" + (f" — Role: {role}" if role else "")

    if action == "user_role_changed":
        return f"User record #{data.get('user_id', '?')} — New role: {_display_value('role', data.get('role', 'unknown'))}"

    if action == "user_status_changed":
        status = _display_value("is_active", data.get("is_active", "unknown"))
        return f"User record #{data.get('user_id', '?')} — {status}"

    if action == "product_created":
        name = data.get("name", "Unnamed product")
        sku = data.get("sku")
        return f"{name}" + (f" (Code: {sku})" if sku else "")

    if action in {"product_price_set", "product_price_changed"}:
        code = data.get("sku", "unknown product")
        old_price = data.get("old_price")
        new_price = data.get("new_price", "unknown")
        if old_price and old_price.lower() != "none":
            return f"{code}: {old_price} RWF → {new_price} RWF"
        return f"{code}: Selling price set to {new_price} RWF"

    if action in {"product_updated", "product_status_changed"}:
        return f"Product code: {data.get('sku', 'not specified')}"

    if action in {"supplier_created", "supplier_updated", "supplier_status_changed",
                  "customer_created", "customer_updated", "customer_status_changed",
                  "reference_created", "reference_renamed", "reference_status_changed"}:
        return data.get("name") or data.get("new_name") or data.get("old_name") or "Reference information changed"

    if action in {"purchase_created", "sale_created"}:
        reference = data.get("reference") or "No reference"
        lines = data.get("lines")
        return f"Reference: {reference}" + (f" — {lines} line(s)" if lines else "")

    if action == "stock_adjustment":
        product = data.get("product_id", "?")
        change = data.get("delta", "?")
        reason = data.get("reason")
        result = f"Product record #{product} — Stock change: {change}"
        return result + (f" — Reason: {reason}" if reason else "")

    if action == "purchase_order_created":
        reference = data.get("reference", "No reference")
        return f"Order: {reference} — {data.get('lines', '?')} line(s)"

    if action in {"purchase_order_line_received", "purchase_order_receipt_recorded"}:
        return f"Purchase order #{data.get('po_id', '?')} — Receipt recorded"

    if action in {"purchase_order_quantity_closed", "purchase_order_outstanding_closed"}:
        return f"Purchase order #{data.get('po_id', '?')} — Quantities closed"

    if action == "damaged_good_deleted":
        quantity = data.get("quantity", "?")
        unit = data.get("unit", "unit")
        supplier = data.get("supplier")
        result = _format_quantity_unit(quantity, unit)
        return result + (f" - Supplier: {supplier}" if supplier else "")

    if action == "auto_backup":
        return details or "Daily automatic backup"

    if details:
        return details

    return label


def format_audit_details(action, details):
    lines = [f"Activity: {audit_action_label(action)}"]
    data = parse_audit_details(details)

    if not data:
        if details:
            lines.append(f"Additional information: {details}")
        return "\n".join(lines)

    for key, value in data.items():
        if key == "unit":
            continue

        label = FIELD_LABELS.get(key, key.replace("_", " ").capitalize())

        if key == "quantity" and data.get("unit"):
            value = _format_quantity_unit(value, data["unit"])

        lines.append(f"{label}: {_display_value(key, value)}")

    return "\n".join(lines)
