"""
Payments
 • Razorpay (India): set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET → real orders + signature verification.
 • Demo mode (no keys): a simulated checkout so the whole subscribe flow can be tested end-to-end.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import urllib.error
import urllib.request

from . import plans, store
from .util import HttpError, iso, now_ms

KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")
MODE = "razorpay" if KEY_ID and KEY_SECRET else "demo"


def create_order(user, plan_id) -> dict:
    plan = plans.get_plan(plan_id)
    if not plan:
        raise HttpError(400, "Unknown plan.")
    receipt = f"cq_{user['userId']}_{now_ms()}"
    if MODE == "razorpay":
        body = json.dumps({"amount": plan["price"] * 100, "currency": plan["currency"], "receipt": receipt,
                           "notes": {"userId": user["userId"], "plan": plan["id"]}}).encode()
        auth = base64.b64encode(f"{KEY_ID}:{KEY_SECRET}".encode()).decode()
        req = urllib.request.Request("https://api.razorpay.com/v1/orders", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Basic {auth}"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                order_id = json.loads(r.read())["id"]
        except urllib.error.HTTPError as e:
            try:
                desc = json.loads(e.read()).get("error", {}).get("description")
            except Exception:  # noqa: BLE001
                desc = None
            raise HttpError(502, desc or "Could not create payment order.")
        except (urllib.error.URLError, TimeoutError):
            raise HttpError(502, "Could not reach the payment service. Please try again.")
    else:
        order_id = "order_demo_" + secrets.token_hex(8)
    store.insert_payment({"orderId": order_id, "userId": user["userId"], "plan": plan["id"], "amount": plan["price"],
                          "currency": plan["currency"], "status": "created", "mode": MODE, "createdAt": iso()})
    return {"mode": MODE, "orderId": order_id, "keyId": KEY_ID or None, "amount": plan["price"] * 100, "currency": plan["currency"],
            "plan": plan, "prefill": {"name": user["fullName"], "email": user["email"]}}


def verify(user, body) -> dict:
    """Returns the paid payment record, or raises HttpError."""
    order_id, payment_id, signature = body.get("orderId"), body.get("paymentId"), body.get("signature")
    pay = store.find_payment(order_id)
    if not pay or pay["userId"] != user["userId"]:
        raise HttpError(404, "Payment order not found.")
    if pay["status"] == "paid":
        raise HttpError(409, "This order has already been processed.")
    if pay["mode"] == "razorpay":
        expected = hmac.new((KEY_SECRET or "").encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
        if not signature or not hmac.compare_digest(expected, str(signature)):
            pay["status"] = "failed"
            store.save_payment(pay)
            raise HttpError(400, "Payment verification failed.")
    else:
        payment_id = "pay_demo_" + secrets.token_hex(7)
    pay.update(status="paid", paymentId=payment_id, paidAt=iso())
    store.save_payment(pay)
    return pay
