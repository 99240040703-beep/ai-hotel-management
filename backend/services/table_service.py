"""
Table tokens and table-context resolution.

A printed table QR carries a single value: `qr_token`. It is a random
public identifier generated with `secrets`, so it encodes nothing about
the database, a guest, a password or a JWT. Rotating it invalidates the
old printed code without touching the table number.

The rule that matters for security: once a guest has claimed a table,
their orders are tied to that table by the server. The table number in
the checkout request is only ever consulted when there is no claim.
"""

import secrets

from sqlalchemy.orm import Session

from models import RestaurantTable, User


# Long enough that a token cannot be guessed by enumerating.
TOKEN_BYTES = 24


def generate_table_token() -> str:
    """
    A fresh, URL-safe, unguessable QR identifier.

    `token_urlsafe` uses base64url so it needs no escaping inside a
    query string, and it is not derived from the table id, so a token
    leaks nothing even if two tables are compared.
    """
    return secrets.token_urlsafe(TOKEN_BYTES)


def get_table_by_token(db: Session, token: str):
    """
    Resolve a QR token to a row, or None.

    An empty or absurdly long value is rejected before touching the
    database so a scan of junk cannot become a slow lookup.
    """
    if not token or not isinstance(token, str):
        return None

    token = token.strip()

    if not token or len(token) > 128:
        return None

    return (
        db.query(RestaurantTable)
        .filter(RestaurantTable.qr_token == token)
        .first()
    )


def get_active_table_by_number(db: Session, table_number: int):
    """
    Look up a table number for the no-claim path.

    Returns None when the table does not exist or is inactive, so a
    client cannot order against a table the restaurant has withdrawn.
    """
    if table_number is None:
        return None

    return (
        db.query(RestaurantTable)
        .filter(
            RestaurantTable.table_number == int(table_number),
            RestaurantTable.is_active.is_(True),
        )
        .first()
    )


def get_table_by_id(db: Session, table_id: int):
    if table_id is None:
        return None

    return (
        db.query(RestaurantTable)
        .filter(RestaurantTable.id == int(table_id))
        .first()
    )


def assign_token_if_missing(db: Session, table: RestaurantTable) -> bool:
    """Gives a newly created table a token. Returns True if it did."""
    if table.qr_token:
        return False

    table.qr_token = generate_table_token()

    return True


def claim_table(db: Session, user_id: int, token: str):
    """
    Bind a signed-in guest to the table whose QR they scanned.

    Returns (table, None) on success or (None, reason) when the token
    is unknown or the table is not taking orders. The claim is stored on
    the users row, so it survives a page refresh and is the single
    source of truth for subsequent orders.
    """
    table = get_table_by_token(db, token)

    if not table:
        return None, "This QR code is not recognised. Please ask staff for a new one."

    if not table.is_active:
        return None, (
            f"Table {table.table_number} is not currently accepting orders. "
            "Please choose another table."
        )

    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        return None, "Account not found"

    user.active_table_id = table.id

    db.commit()
    db.refresh(user)

    return table, None


def release_table(db: Session, user_id: int):
    """Clear the guest's table context, used on sign out."""
    user = db.query(User).filter(User.id == user_id).first()

    if user and user.active_table_id:
        user.active_table_id = None
        db.commit()

        return True

    return False


def get_claimed_table(db: Session, user_id: int):
    """
    The table this guest is currently seated at, or None.

    An inactive table is reported as no context, so a withdrawn table
    stops accepting orders immediately rather than at the next scan.
    """
    user = db.query(User).filter(User.id == user_id).first()

    if not user or not user.active_table_id:
        return None

    table = get_table_by_id(db, user.active_table_id)

    if not table or not table.is_active:
        return None

    return table


def public_table_info(table: RestaurantTable, restaurant_name: str = None):
    """
    What a phone is allowed to learn from a QR before signing in.

    Deliberately excludes qr_token, id and is_active so the entry page
    cannot be used to enumerate tokens or internal state.
    """
    if not table:
        return None

    return {
        "table_number": table.table_number,
        "table_name": table.table_name,
        "capacity": table.capacity,
        "section": table.section,
        "restaurant_name": restaurant_name,
    }


def table_qr_payload(table: RestaurantTable, entry_base_url: str):
    """
    The URL encoded into the printed QR.

    Only the table's own token appears. No user id, no JWT, no secret.
    """
    base = (entry_base_url or "").rstrip("/")

    return f"{base}/customer/entry?table={table.qr_token}"
