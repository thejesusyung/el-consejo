"""WebSocket API Lambda — $connect, $disconnect, $default.

Clients connect and then send {"action":"watch","session_id":"..."} once to
subscribe. We store a (SESSION#<id>, WS#<connection_id>) marker in DynamoDB
so the conductor Lambda can look up all live subscribers for a session and
broadcast each new line as it's produced.

We also store the reverse (WS#<connection_id>, META) so disconnect cleanup
knows which session to deregister from.
"""
from __future__ import annotations

import json
import os

import boto3
from botocore.exceptions import ClientError

from backend.shared import config as cfg
from backend.shared import storage


def _table():
    return storage._table()  # noqa: SLF001


def _connect(connection_id: str) -> dict:
    _table().put_item(Item={"pk": f"WS#{connection_id}", "sk": "META"})
    return {"statusCode": 200}


def _disconnect(connection_id: str) -> dict:
    # Read META to find the subscribed session, then clean up both records.
    meta = _table().get_item(Key={"pk": f"WS#{connection_id}", "sk": "META"}).get("Item", {})
    sid = meta.get("session_id")
    if sid:
        try:
            _table().delete_item(
                Key={"pk": f"SESSION#{sid}", "sk": f"WS#{connection_id}"}
            )
        except ClientError:
            pass
    _table().delete_item(Key={"pk": f"WS#{connection_id}", "sk": "META"})
    return {"statusCode": 200}


def _watch(connection_id: str, session_id: str) -> dict:
    _table().put_item(Item={
        "pk": f"SESSION#{session_id}",
        "sk": f"WS#{connection_id}",
    })
    _table().update_item(
        Key={"pk": f"WS#{connection_id}", "sk": "META"},
        UpdateExpression="SET session_id = :s",
        ExpressionAttributeValues={":s": session_id},
    )
    return {"statusCode": 200}


def handler(event: dict, _context) -> dict:
    route = event.get("requestContext", {}).get("routeKey")
    connection_id = event["requestContext"]["connectionId"]

    if route == "$connect":
        return _connect(connection_id)
    if route == "$disconnect":
        return _disconnect(connection_id)

    # $default — client messages
    body = {}
    if event.get("body"):
        try:
            body = json.loads(event["body"])
        except Exception:
            return {"statusCode": 400}
    if body.get("action") == "watch" and body.get("session_id"):
        return _watch(connection_id, body["session_id"])
    return {"statusCode": 200}


# ---------- Called by conductor Lambda to push updates to subscribers ----------

def broadcast(session_id: str, message: dict, endpoint: str | None = None) -> None:
    """Publish `message` to every WebSocket subscribed to this session.

    `endpoint` is the WebSocket management endpoint URL — read from env at
    the conductor's runtime. On stale connections we best-effort-delete the
    subscription so broadcasts stay fast.
    """
    endpoint = endpoint or os.environ.get("ELCONSEJO_WS_ENDPOINT", "")
    if not endpoint:
        return  # WS not wired up — no-op
    mgmt = boto3.client("apigatewaymanagementapi", endpoint_url=endpoint, region_name=cfg.REGION)
    resp = _table().query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key("pk").eq(f"SESSION#{session_id}")
                               & boto3.dynamodb.conditions.Key("sk").begins_with("WS#"),
    )
    payload = json.dumps(message, ensure_ascii=False, default=str).encode("utf-8")
    for item in resp.get("Items", []):
        connection_id = item["sk"][len("WS#"):]
        try:
            mgmt.post_to_connection(ConnectionId=connection_id, Data=payload)
        except mgmt.exceptions.GoneException:
            _table().delete_item(Key={"pk": f"SESSION#{session_id}", "sk": f"WS#{connection_id}"})
        except Exception:
            pass
